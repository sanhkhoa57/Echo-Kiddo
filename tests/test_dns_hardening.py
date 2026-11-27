"""Regression tests for DNS problems found in the live check on Windows:
SafeSearch answers without addresses, A-only sinkhole for AAAA, thread-pool starvation
under bursts, upstream failover / network resolvers, adapter DNS read from the registry,
anti-tamper on single static servers, test mode never touching the real adapters, and
the service only locking DNS once the proxy really runs."""
import asyncio
import json

import pytest
from dnslib import DNSRecord, DNSHeader, RR, A, AAAA, QTYPE, RCODE

from agent.core.agent_db import AgentDatabase
from agent.dns.dns_proxy import DnsProxyServer
from agent.dns.domain_engine import DomainPolicyEngine
from agent.platform import network_guard as ng
from agent.platform.network_guard import NetworkDnsGuard


def _answer(query: bytes, ip: str = "203.0.113.7") -> bytes:
    req = DNSRecord.parse(query)
    resp = DNSRecord(DNSHeader(id=req.header.id, qr=1, ra=1), q=req.q)
    if req.q.qtype == QTYPE.AAAA:
        resp.add_answer(RR(req.q.qname, QTYPE.AAAA, rdata=AAAA("2001:db8::7"), ttl=120))
    else:
        resp.add_answer(RR(req.q.qname, QTYPE.A, rdata=A(ip), ttl=120))
    return resp.pack()


def _proxy(rules=None, **kw):
    engine = DomainPolicyEngine()
    engine.load_policy(rules or [{"domain": "facebook.com", "category": "social", "action": "block"}])
    server = DnsProxyServer(engine=engine, port=0, **kw)
    return server


@pytest.mark.asyncio
async def test_safesearch_answer_contains_target_addresses():
    server = _proxy()
    asked = []
    server._sync_udp_query = lambda h, p, q, t: asked.append(str(DNSRecord.parse(q).q.qname)) or _answer(q)
    resp = DNSRecord.parse(await server.process_dns_query(DNSRecord.question("www.google.com", "A").pack()))
    types = [rr.rtype for rr in resp.rr]
    assert types[0] == QTYPE.CNAME and QTYPE.A in types
    assert asked == ["forcesafesearch.google.com."]
    # Second lookup is served from cache
    await server.process_dns_query(DNSRecord.question("www.google.com", "A").pack())
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_sinkhole_matches_query_type():
    server = _proxy()
    a = DNSRecord.parse(await server.process_dns_query(DNSRecord.question("m.facebook.com", "A").pack()))
    aaaa = DNSRecord.parse(await server.process_dns_query(DNSRecord.question("facebook.com", "AAAA").pack()))
    https = DNSRecord.parse(await server.process_dns_query(DNSRecord.question("facebook.com", "HTTPS").pack()))
    assert [(r.rtype, str(r.rdata)) for r in a.rr] == [(QTYPE.A, "0.0.0.0")]
    assert [(r.rtype, str(r.rdata)) for r in aaaa.rr] == [(QTYPE.AAAA, "::")]
    assert https.rr == [] and https.header.rcode == RCODE.NOERROR


@pytest.mark.asyncio
async def test_identical_parallel_queries_share_one_upstream_trip():
    server = _proxy()
    calls = []

    async def slow_udp(host, port, data, timeout):
        calls.append(host)
        await asyncio.sleep(0.05)
        return _answer(data)

    server._udp_query = slow_udp
    queries = [DNSRecord.question("example.org", "A") for _ in range(30)]
    results = await asyncio.gather(*[server.process_dns_query(q.pack()) for q in queries])
    assert len(calls) == 1
    for q, raw in zip(queries, results):
        resp = DNSRecord.parse(raw)
        assert resp.header.id == q.header.id and str(resp.rr[0].rdata) == "203.0.113.7"


@pytest.mark.asyncio
async def test_failover_reaches_network_resolver_and_sticks():
    server = _proxy(extra_upstreams=["192.168.6.1", "127.0.0.1"])
    assert server.upstreams() == ["1.1.1.1", "8.8.8.8", "192.168.6.1"]   # loopback dropped
    calls = []

    async def only_router(host, port, data, timeout):
        calls.append(host)
        return _answer(data) if host == "192.168.6.1" else None

    server._udp_query = only_router
    await server.process_dns_query(DNSRecord.question("a.example", "A").pack())
    assert calls == ["1.1.1.1", "8.8.8.8", "192.168.6.1"]
    calls.clear()
    await server.process_dns_query(DNSRecord.question("b.example", "A").pack())
    assert calls == ["192.168.6.1"]                                     # no repeated timeouts


@pytest.mark.asyncio
async def test_servfail_is_not_cached():
    server = _proxy()
    state = {"n": 0}

    async def flaky(host, port, data, timeout):
        state["n"] += 1
        req = DNSRecord.parse(data)
        if state["n"] <= 2:
            return DNSRecord(DNSHeader(id=req.header.id, qr=1, rcode=RCODE.SERVFAIL), q=req.q).pack()
        return _answer(data)

    server._udp_query = flaky
    q = DNSRecord.question("flaky.example", "A").pack()
    first = DNSRecord.parse(await server.process_dns_query(q))
    second = DNSRecord.parse(await server.process_dns_query(q))
    assert first.header.rcode == RCODE.SERVFAIL
    assert str(second.rr[0].rdata) == "203.0.113.7"


# ---------------------------------------------------------------- adapters
def test_registry_server_lists_are_parsed():
    assert ng._split_servers("192.168.6.1") == ["192.168.6.1"]
    assert ng._split_servers("8.8.8.8 8.8.4.4") == ["8.8.8.8", "8.8.4.4"]
    assert ng._split_servers("1.1.1.1,9.9.9.9") == ["1.1.1.1", "9.9.9.9"]
    assert ng._split_servers("fec0:0:0:ffff::1%1 junk") == ["fec0:0:0:ffff::1"]
    assert ng._split_servers("") == []


def test_anti_tamper_detects_single_static_server_and_dhcp(monkeypatch, tmp_path):
    monkeypatch.setattr(ng, "_IS_WINDOWS", True)
    commands = []
    monkeypatch.setattr(ng, "_netsh", lambda args: commands.append(args) or True)
    monkeypatch.setattr(ng, "flush_dns_cache", lambda: True)
    guard = NetworkDnsGuard(db=AgentDatabase(tmp_path / "a.db"))

    guard._get_current_adapters_config = lambda: [
        {"name": "Wi-Fi", "dhcp": False, "dns": ["127.0.0.1"], "dns6_static": []}]
    assert guard.check_and_enforce_anti_tamper() is False

    guard._get_current_adapters_config = lambda: [
        {"name": "Wi-Fi", "dhcp": False, "dns": ["8.8.8.8"], "dns6_static": []},
        {"name": "Ethernet 2", "dhcp": True, "dns": ["192.168.6.1"], "dns6_static": []}]
    assert guard.check_and_enforce_anti_tamper() is True
    assert any('name="Wi-Fi"' in c and "address=127.0.0.1" in c for c in commands)
    assert any('name="Ethernet 2"' in c and "validate=no" in c for c in commands)


def test_original_upstreams_come_from_snapshot(tmp_path):
    db = AgentDatabase(tmp_path / "a.db")
    db.save_snapshot("NETWORK_DNS", json.dumps([
        {"name": "Wi-Fi", "dhcp": True, "dns": ["8.8.8.8", "192.168.1.1"]},
        {"name": "Ethernet", "dhcp": False, "dns": ["127.0.0.1", "192.168.1.1"]}]))
    assert NetworkDnsGuard(db=db).original_upstreams() == ["8.8.8.8", "192.168.1.1"]


def test_test_mode_never_runs_netsh(monkeypatch):
    ran = []
    monkeypatch.setattr(ng.subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setenv("OGK_TESTING", "1")
    monkeypatch.delenv("OGK_ALLOW_SYSTEM_CHANGES", raising=False)
    assert ng._netsh('interface ipv4 set dnsservers name="Wi-Fi" source=dhcp') is True
    assert ran == []


# ---------------------------------------------------------------- service ordering
def test_service_does_not_lock_dns_before_proxy_runs(tmp_path, monkeypatch):
    from agent.service.win_service import OGKServiceCore
    core = OGKServiceCore(db_path=str(tmp_path / "agent.db"))
    locked = []
    monkeypatch.setattr(core.net_guard, "lock_dns_to_loopback", lambda *a, **k: locked.append(1) or True)
    core.dns_proxy.is_running = False
    core._apply_protection()
    assert locked == []                      # proxy not up yet: adapters untouched

    core.dns_proxy.is_running = True
    core.dns_proxy.ipv6_active = True
    core._apply_protection()
    assert locked == [1] and core.net_guard.lock_ipv6 is True
