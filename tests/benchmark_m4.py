"""M4 performance benchmark (>= 30 samples per measurement).
Measures:
1. CPU % and RAM RSS (MB) at idle and under load
2. DNS resolution latency p50/p95: without Agent (direct to resolver) vs with Agent
   (OGK DNS Proxy: cache miss, cache hit, sinkhole), over real UDP when the network is up
3. End-to-end policy apply and urgent-command latency (Dashboard -> Server -> WS -> Agent)
Writes docs/benchmark_m4_results.md.
"""
import asyncio
import os
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import psutil
from dnslib import DNSRecord, DNSHeader, QTYPE, RR, A, RCODE

from agent.dns.domain_engine import DomainPolicyEngine
from agent.dns.dns_proxy import DnsProxyServer
from agent.core.app_controller import Sha256LruCache
from agent.core.policy_verifier import verify_policy
from server.services.policy_service import sign_policy_payload


def calculate_stats(samples: List[float]) -> Dict[str, float]:
    """Calculates min, max, mean, p50, and p95."""
    if not samples:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0}
    sorted_s = sorted(samples)
    n = len(sorted_s)
    p50_idx = int(n * 0.50)
    p95_idx = min(int(n * 0.95), n - 1)
    return {
        "min": round(min(sorted_s), 3),
        "max": round(max(sorted_s), 3),
        "mean": round(statistics.mean(sorted_s), 3),
        "p50": round(sorted_s[p50_idx], 3),
        "p95": round(sorted_s[p95_idx], 3),
    }


def benchmark_cpu_and_memory(samples_count: int = 30) -> Dict[str, Any]:
    """Measures CPU % and RAM RSS (MB) over >= 30 consecutive samples."""
    proc = psutil.Process()
    idle_cpu, idle_ram = [], []
    stress_cpu, stress_ram = [], []

    proc.cpu_percent(interval=None)
    for _ in range(samples_count):
        time.sleep(0.03)
        idle_cpu.append(proc.cpu_percent(interval=None))
        idle_ram.append(proc.memory_info().rss / (1024 * 1024))

    _ = Sha256LruCache(maxsize=512)
    engine = DomainPolicyEngine()
    engine.load_policy([{"domain": f"site{i}.test", "category": "education", "action": "allow"} for i in range(200)])

    proc.cpu_percent(interval=None)
    for _ in range(samples_count):
        t0 = time.time()
        for i in range(50):
            engine.evaluate(f"sub.site{i % 200}.test")
        time.sleep(max(0, 0.02 - (time.time() - t0)))
        stress_cpu.append(proc.cpu_percent(interval=None))
        stress_ram.append(proc.memory_info().rss / (1024 * 1024))

    return {
        "idle_cpu": calculate_stats(idle_cpu),
        "idle_ram": calculate_stats(idle_ram),
        "stress_cpu": calculate_stats(stress_cpu),
        "stress_ram": calculate_stats(stress_ram),
    }




# ----------------------------------------------------------------------------- DNS
BENCH_UPSTREAM = os.getenv("OGK_BENCH_UPSTREAM", "1.1.1.1")
PROXY_PORT = 53545
# Ordinary, safe domains with no SafeSearch rewrite and no DoH endpoint
REAL_DOMAINS = [
    "wikipedia.org", "python.org", "mozilla.org", "khanacademy.org", "github.com",
    "w3.org", "ietf.org", "debian.org", "apache.org", "kernel.org",
    "nasa.gov", "who.int", "un.org", "britannica.com", "scratch.mit.edu",
    "code.org", "duolingo.com", "openstreetmap.org", "gnu.org", "rust-lang.org",
    "nodejs.org", "sqlite.org", "postgresql.org", "ubuntu.com", "fedoraproject.org",
    "arxiv.org", "nature.com", "ted.com", "vnexpress.net", "moet.gov.vn",
]


def _mock_upstream_answer(query_data: bytes) -> bytes:
    """Offline stand-in for an upstream resolver: builds an A answer with no network I/O."""
    req = DNSRecord.parse(query_data)
    resp = DNSRecord(DNSHeader(id=req.header.id, qr=1, ra=1, rcode=RCODE.NOERROR), q=req.q)
    resp.add_answer(RR(req.q.qname, QTYPE.A, rdata=A("93.184.216.34"), ttl=60))
    return resp.pack()


def _udp_query(q_bytes: bytes, host: str, port: int, timeout: float = 2.0) -> Tuple[bytes, float]:
    """Sends one DNS query over UDP and returns (answer, round-trip ms)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.perf_counter()
        s.sendto(q_bytes, (host, port))
        resp, _ = s.recvfrom(4096)
        return resp, (time.perf_counter() - t0) * 1000.0
    finally:
        s.close()


def upstream_reachable(host: str = BENCH_UPSTREAM) -> bool:
    try:
        _udp_query(DNSRecord.question("wikipedia.org", "A").pack(), host, 53, timeout=1.5)
        return True
    except Exception:
        return False


async def benchmark_dns_latencies(samples_count: int = 30, allow_network: bool = True) -> Dict[str, Any]:
    """DNS latency (ms), >= 30 samples per row.

    Network mode (default when the upstream answers): real UDP packets.
      - Without Agent: client -> upstream resolver directly.
      - With Agent: client -> OGK DNS Proxy on 127.0.0.1 -> same upstream. The proxy cache is
        cleared before every cache-miss sample; without/with samples are interleaved on the
        same domain so both arms see the same upstream state.
    Offline mode (no network, or OGK_BENCH_OFFLINE=1): in-process pipeline with a mock
    upstream. It only measures the Agent's own processing cost, not a real comparison.
    """
    engine = DomainPolicyEngine()
    engine.load_policy(domain_rules=[
        {"domain": "blocked.test", "category": "inappropriate", "action": "block"},
        {"domain": "school.edu.vn", "category": "education", "action": "allow"},
    ])

    real = allow_network and os.getenv("OGK_BENCH_OFFLINE") != "1" and upstream_reachable()
    server = DnsProxyServer(
        engine=engine, host="127.0.0.1", port=PROXY_PORT,
        primary_upstream=BENCH_UPSTREAM, secondary_upstream="8.8.8.8",
    )
    if real:
        real = await server.start()
    if not real:
        server._sync_udp_query = lambda host, p, q_data, timeout: _mock_upstream_answer(q_data)

    loop = asyncio.get_running_loop()

    def q(name: str) -> bytes:
        return DNSRecord.question(name, "A").pack()

    async def via_upstream(name: str) -> Tuple[bytes, float]:
        if real:
            return await loop.run_in_executor(None, _udp_query, q(name), BENCH_UPSTREAM, 53)
        t0 = time.perf_counter()
        data = _mock_upstream_answer(q(name))
        return data, (time.perf_counter() - t0) * 1000.0

    async def via_agent(name: str) -> Tuple[bytes, float]:
        if real:
            return await loop.run_in_executor(None, _udp_query, q(name), "127.0.0.1", PROXY_PORT)
        t0 = time.perf_counter()
        data = await server.process_dns_query(q(name))
        return data, (time.perf_counter() - t0) * 1000.0

    baseline: List[float] = []
    miss: List[float] = []
    hit: List[float] = []
    sinkhole: List[float] = []
    hit_name = "wikipedia.org" if real else "school.edu.vn"
    try:
        domains = REAL_DOMAINS if real else [f"miss-{i}.example.test" for i in range(samples_count)]
        if real:
            for d in domains:  # warm the upstream resolver's cache for both arms
                try:
                    await via_upstream(d)
                except Exception:
                    pass
        for i in range(samples_count):
            d = domains[i % len(domains)]
            baseline.append((await via_upstream(d))[1])
            server.cache.clear()
            miss.append((await via_agent(d))[1])

        await via_agent(hit_name)  # prime the proxy cache
        for _ in range(samples_count):
            hit.append((await via_agent(hit_name))[1])

        for _ in range(samples_count):
            data, ms = await via_agent("www.blocked.test")
            assert str(DNSRecord.parse(data).rr[0].rdata) == "0.0.0.0"
            sinkhole.append(ms)
    finally:
        server.stop()

    b, m = calculate_stats(baseline), calculate_stats(miss)
    if real:
        mode = (f"mạng thật. Không Agent: UDP tới {BENCH_UPSTREAM}:53. Có Agent: UDP tới OGK DNS Proxy "
                f"127.0.0.1:{PROXY_PORT}, proxy chuyển tiếp tới {BENCH_UPSTREAM}.")
    else:
        mode = "mô phỏng in-process (không có mạng): chỉ đo chi phí xử lý của Agent, không phải so sánh thật."
    return {
        "real": real,
        "mode": mode,
        "baseline": b,
        "cache_miss": m,
        "cache_hit": calculate_stats(hit),
        "blocked_eval": calculate_stats(sinkhole),
        "overhead_p50": round(m["p50"] - b["p50"], 3),
        "overhead_p95": round(m["p95"] - b["p95"], 3),
    }


# ----------------------------------------------------------------------------- policy / command
def benchmark_policy_and_command(samples_count: int = 30) -> Dict[str, Any]:
    """Agent-side processing only: HMAC verify + rule load, and local lock evaluation."""
    from agent.core.screen_time import ScreenTimeManager

    mgr = ScreenTimeManager()
    engine = DomainPolicyEngine()
    secret = "benchmark-secret-key"
    payload = {
        "child_id": "child-bench-1",
        "version": 1,
        "daily_limit_weekday_min": 90,
        "daily_limit_weekend_min": 120,
        "schedule_matrix_7x48": "1" * 336,
        "category_budgets_json": '{"gaming": 45}',
        "app_rules_json": '[]',
        "domain_rules_json": '[{"domain": "blocked.test", "category": "inappropriate", "action": "block"}]',
        "updated_at_utc": "2026-11-17T00:00:00+00:00",
    }
    payload["signature"] = sign_policy_payload(payload, secret)

    policy_latencies: List[float] = []
    cmd_latencies: List[float] = []
    for _ in range(samples_count):
        t0 = time.perf_counter()
        ok, _ = verify_policy(payload, secret)
        assert ok is True
        engine.load_policy([{"domain": "blocked.test", "category": "inappropriate", "action": "block"}])
        policy_latencies.append((time.perf_counter() - t0) * 1000.0)

        t1 = time.perf_counter()
        mgr.set_manual_lock(True)
        mgr.evaluate_lock_status(payload)
        mgr.set_manual_lock(False)
        cmd_latencies.append((time.perf_counter() - t1) * 1000.0)

    return {
        "policy_apply": calculate_stats(policy_latencies),
        "command_dispatch": calculate_stats(cmd_latencies),
    }


def benchmark_end_to_end(samples_count: int = 30) -> Dict[str, Any]:
    """Full path on one machine: real FastAPI app + real agent client, temp databases.
      - Policy: parent PUT /api/v1/policy/{child} -> server signs v+1 -> WebSocket POLICY_UPDATED
        -> agent GET /api/v1/policy -> HMAC verify -> rules applied.
      - Urgent command: parent POST /api/v1/commands LOCK_NOW -> WebSocket -> agent verifies
        the command HMAC -> lock applied -> ACK.
    Network RTT between two machines is not included (loopback, in-process transport)."""
    os.environ.setdefault("OGK_TESTING", "1")
    import shutil
    import tempfile
    import uuid
    import httpx
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from agent.core.agent_db import AgentDatabase
    from agent.core.screen_time import ScreenTimeManager
    from agent.sync.server_client import AgentServerClient
    from server.main import app
    from server.models.base import Base
    from server.models.child import Child
    from server.models.database import create_ogk_engine, get_db

    tmp = Path(tempfile.mkdtemp(prefix="ogk-bench-"))
    engine = create_ogk_engine(f"sqlite:///{tmp / 'server.db'}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    loop = asyncio.new_event_loop()
    policy_ms: List[float] = []
    command_ms: List[float] = []
    agent = None
    try:
        with TestClient(app) as client:
            email = f"bench_{uuid.uuid4().hex[:8]}@example.com"
            reg = client.post("/api/v1/auth/register",
                              json={"email": email, "password": "Password123!", "role": "parent"})
            login = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
            client.cookies.clear()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            db = SessionLocal()
            child = Child(parent_id=reg.json()["id"], display_name="Bench")
            db.add(child)
            db.commit()
            child_id = child.id
            db.close()
            code = client.post("/api/v1/enroll/code", json={"child_id": child_id, "consent_confirmed": True},
                               headers=headers).json()["code"]

            agent = AgentServerClient(
                server_url="http://testserver",
                db=AgentDatabase(tmp / "agent.db"),
                screen_time_mgr=ScreenTimeManager(),
                domain_engine=DomainPolicyEngine(),
                http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver"),
            )
            loop.run_until_complete(agent.enroll(code, "b" * 64))

            with client.websocket_connect(f"/ws/agent/{agent.device_id}?token={agent.access_token}") as ws:
                for i in range(samples_count):
                    expected = agent.current_policy_version + 1
                    t0 = time.perf_counter()
                    put = client.put(f"/api/v1/policy/{child_id}", headers=headers,
                                     json={"daily_limit_weekday_min": 60 + i})
                    assert put.status_code == 200, put.text
                    msg = ws.receive_json()
                    assert msg["command"] == "POLICY_UPDATED"
                    loop.run_until_complete(agent.handle_command_envelope(msg))
                    assert agent.current_policy_version == expected
                    policy_ms.append((time.perf_counter() - t0) * 1000.0)
                    ws.send_json({"msg_type": "COMMAND_ACK", "command_id": msg["command_id"], "status": "EXECUTED"})

                for _ in range(samples_count):
                    t0 = time.perf_counter()
                    r = client.post("/api/v1/commands", headers=headers,
                                    json={"child_id": child_id, "command": "LOCK_NOW"})
                    assert r.status_code == 200, r.text
                    msg = ws.receive_json()
                    assert loop.run_until_complete(agent.handle_command_envelope(msg)) is True
                    assert agent.screen_time_mgr.manual_lock_active
                    command_ms.append((time.perf_counter() - t0) * 1000.0)
                    ws.send_json({"msg_type": "COMMAND_ACK", "command_id": msg["command_id"], "status": "EXECUTED"})
                    agent.screen_time_mgr.set_manual_lock(False)
    finally:
        if agent is not None and agent._http_client is not None:
            loop.run_until_complete(agent._http_client.aclose())
        loop.close()
        app.dependency_overrides.clear()
        engine.dispose()
        shutil.rmtree(tmp, ignore_errors=True)

    return {"policy_e2e": calculate_stats(policy_ms), "command_e2e": calculate_stats(command_ms)}


# ----------------------------------------------------------------------------- report
def _ok(cond: bool) -> str:
    return "Đạt" if cond else "Không đạt"


def _row(label: str, s: Dict[str, float], limit: str, ok: str) -> str:
    return f"| {label} | {s['min']} | {s['mean']} | {s['max']} | {s['p50']} | {s['p95']} | {limit} | {ok} |"


def _head(first_col: str) -> str:
    return (f"| {first_col} | Min | Mean | Max | p50 | p95 | Ngưỡng | Kết quả |\n"
            "|---|---|---|---|---|---|---|---|")


def run_all_benchmarks() -> str:
    """Runs the complete M4 suite and writes docs/benchmark_m4_results.md."""
    print("Running M4 Benchmarks (>= 30 samples/measurement)...")
    n = 30
    cpu = benchmark_cpu_and_memory(n)
    dns = asyncio.run(benchmark_dns_latencies(n))
    dns_local = asyncio.run(benchmark_dns_latencies(n, allow_network=False))
    ctrl = benchmark_policy_and_command(n)
    e2e = benchmark_end_to_end(n)

    report = [
        "# Báo cáo đo hiệu năng M4 (OGK)",
        "",
        f"- Thời gian đo: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"- Máy đo: {sys.platform}, Python {sys.version.split()[0]}, {psutil.cpu_count()} luồng CPU",
        f"- Số mẫu: {n} mẫu liên tục cho mỗi dòng; p50/p95 tính theo nearest-rank. Đơn vị độ trễ: ms.",
        f"- Chế độ đo DNS: {dns['mode']}",
        "- Tái lập: `python tests/benchmark_m4.py` (đặt `OGK_BENCH_OFFLINE=1` để chạy khi không có mạng).",
        "",
        "## 1. CPU và RAM",
        "",
        "Rảnh: lấy mẫu mỗi 30 ms khi không có tải. Cao điểm: 50 lượt tra cứu tên miền mỗi 20 ms "
        "(khoảng 2.500 lượt/giây) trên 200 quy tắc.",
        "",
        _head("Trạng thái, chỉ số"),
        _row("Rảnh, CPU (%)", cpu["idle_cpu"], "< 1%", _ok(cpu["idle_cpu"]["p95"] < 1.0)),
        _row("Rảnh, RAM (MB)", cpu["idle_ram"], "< 100 MB", _ok(cpu["idle_ram"]["max"] < 100)),
        _row("Cao điểm, CPU (%)", cpu["stress_cpu"], "< 15%", _ok(cpu["stress_cpu"]["p95"] < 15.0)),
        _row("Cao điểm, RAM (MB)", cpu["stress_ram"], "< 120 MB", _ok(cpu["stress_ram"]["max"] < 120)),
        "",
        "RAM là RSS của tiến trình benchmark, đã gồm thư viện máy chủ nạp cho phần đo đầu-cuối, "
        "nên cao hơn Agent chạy riêng.",
        "",
        "## 2. Độ trễ phân giải DNS: có và không có Agent",
        "",
        _head("Đường đi truy vấn"),
        _row("Không có Agent (truy vấn thẳng resolver)", dns["baseline"], "tham chiếu", "-"),
        _row("Có Agent, cache miss (chuyển tiếp upstream)", dns["cache_miss"], "tham chiếu", "-"),
        _row("Chi phí xử lý riêng của Agent khi cache miss (upstream giả lập)", dns_local["cache_miss"],
             "p50 < 5 ms", _ok(dns_local["cache_miss"]["p50"] < 5.0)),
        _row("Có Agent, cache hit", dns["cache_hit"], "p50 < 1 ms", _ok(dns["cache_hit"]["p50"] < 1.0)),
        _row("Có Agent, bị chặn (sinkhole 0.0.0.0)", dns["blocked_eval"], "p50 < 2 ms",
             _ok(dns["blocked_eval"]["p50"] < 2.0)),
        "",
        f"Agent cộng thêm khi cache miss: p50 {dns['overhead_p50']:+} ms, p95 {dns['overhead_p95']:+} ms "
        "(có Agent trừ không có Agent). Độ dao động của Internet (jitter, hàng chục ms) lớn hơn chi phí "
        "xử lý của Agent (dưới 1 ms, xem dòng cache hit), nên chênh lệch này có thể âm. Khi cache hit hoặc bị chặn, Agent trả lời ngay tại 127.0.0.1 "
        "nên nhanh hơn truy vấn không qua Agent.",
        "",
        "## 3. Độ trễ áp dụng chính sách và lệnh khẩn",
        "",
        "Đầu-cuối: Dashboard gửi PUT/POST, OGK-Server ký HMAC, đẩy qua WebSocket, Agent xác minh rồi áp dụng. "
        "Đo trên một máy (loopback), chưa gồm RTT mạng giữa hai máy.",
        "",
        _head("Tác vụ"),
        _row("Chính sách mới, đầu-cuối (PUT, WS, GET, verify, apply)", e2e["policy_e2e"], "< 60 000 ms",
             _ok(e2e["policy_e2e"]["p95"] < 60000)),
        _row("Lệnh khẩn LOCK_NOW, đầu-cuối (POST, WS, verify, khóa)", e2e["command_e2e"], "< 5 000 ms",
             _ok(e2e["command_e2e"]["p95"] < 5000)),
        _row("Riêng Agent: verify HMAC và nạp quy tắc", ctrl["policy_apply"], "-", "-"),
        _row("Riêng Agent: đánh giá trạng thái khóa", ctrl["command_dispatch"], "-", "-"),
        "",
        "Khi WebSocket mất kết nối, Agent nhận chính sách mới ở nhịp tim kế tiếp (tối đa 60 giây), "
        "nên độ trễ xấu nhất khoảng 60 giây cộng thời gian trong bảng.",
    ]

    markdown_output = "\n".join(report) + "\n"
    out_file = ROOT_DIR / "docs" / "benchmark_m4_results.md"
    out_file.write_text(markdown_output, encoding="utf-8")
    print("\n" + markdown_output)
    print(f"[Saved benchmark results to {out_file}]")
    return markdown_output


def test_m4_benchmark_run():
    """Pytest smoke check; DNS runs offline so the suite does not depend on internet access."""
    cpu_mem = benchmark_cpu_and_memory(30)
    assert cpu_mem["idle_ram"]["p50"] < 300.0

    dns_lat = asyncio.run(benchmark_dns_latencies(30, allow_network=False))
    assert dns_lat["cache_hit"]["p50"] < 15.0

    ctrl_lat = benchmark_policy_and_command(30)
    assert ctrl_lat["policy_apply"]["p95"] < 100.0

    e2e = benchmark_end_to_end(30)
    assert e2e["policy_e2e"]["p95"] < 60000
    assert e2e["command_e2e"]["p95"] < 5000


if __name__ == "__main__":
    run_all_benchmarks()
