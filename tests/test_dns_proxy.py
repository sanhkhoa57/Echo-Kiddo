"""Tests for Domain Policy Engine & Local DNS Proxy (FR-F2-03, FR-F2-04, FR-F2-05, FR-F2-06, M1, EX-01, EX-02).
Includes:
- Suffix Trie & HashSet O(1) matching
- Allowlist > Blocklist precedence
- SafeSearch CNAME enforcement across major search engines
- DoH Canary and DoH endpoint blocking (NXDOMAIN)
- Dual-stack UDP & TCP resolution
- 50 safe test domains with >= 95% block rate
- 20 educational domains with 0% false positives
- Port 53 conflict pre-check (EX-01)
- Upstream failover on timeout (EX-02)
- eTLD+1 normalization in recorded events
"""
import asyncio
import socket
import struct
from unittest.mock import MagicMock
import pytest
from dnslib import DNSRecord, DNSHeader, QTYPE, RCODE, RR, A, CNAME

from agent.dns.domain_engine import (
    DomainPolicyEngine,
    SuffixTrie,
    ACTION_ALLOW,
    ACTION_BLOCK,
    ACTION_SAFESEARCH,
    ACTION_DOH_CANARY,
    CANARY_DOH_DOMAIN,
    normalize_etld_plus_one,
)
from agent.dns.dns_proxy import (
    DnsProxyServer,
    DnsTtlCache,
    check_port_53_conflict,
)


def test_suffix_trie_subdomain_matching():
    trie = SuffixTrie()
    trie.insert("bad.example.test", {"action": "block", "category": "inappropriate"})

    # Exact match
    rule = trie.find_rule("bad.example.test")
    assert rule is not None
    assert rule["action"] == "block"

    # Subdomain match (*.bad.example.test)
    sub_rule = trie.find_rule("sub.bad.example.test")
    assert sub_rule is not None
    assert sub_rule["action"] == "block"

    deep_rule = trie.find_rule("deep.nested.sub.bad.example.test")
    assert deep_rule is not None
    assert deep_rule["action"] == "block"

    # Sibling domain should NOT match
    sibling = trie.find_rule("good.example.test")
    assert sibling is None

    # Parent domain should NOT match
    parent = trie.find_rule("example.test")
    assert parent is None


def test_domain_policy_engine_allowlist_over_blocklist():
    engine = DomainPolicyEngine()
    engine.load_policy(
        domain_rules=[
            {"domain": "study.social-network.test", "category": "social", "action": "allow"},
            {"domain": "social-network.test", "category": "social", "action": "block"},
            {"domain": "explicit-allow.test", "category": "inappropriate", "action": "allow"},
        ],
        category_rules={
            "social": "block",
            "inappropriate": "block",
        }
    )

    # 1. Broad category is blocked
    action, _, _ = engine.evaluate("social-network.test")
    assert action == ACTION_BLOCK

    # 2. Specific subdomain has explicit allow -> Must BE ALLOWED (Allowlist > Blocklist)
    action, _, _ = engine.evaluate("study.social-network.test")
    assert action == ACTION_ALLOW

    # 3. Explicit exact allow inside blocked category -> Must BE ALLOWED
    action, _, _ = engine.evaluate("explicit-allow.test")
    assert action == ACTION_ALLOW


def test_domain_policy_engine_safesearch_and_doh():
    engine = DomainPolicyEngine(safesearch_enabled=True)
    engine.load_policy(
        domain_rules=[
            {"domain": "gambling.test", "category": "inappropriate", "action": "block"},
            {"domain": "safe-school.edu.vn", "category": "education", "action": "allow"},
        ],
        category_rules={
            "inappropriate": "block",
            "social": "block",
            "education": "allow",
            "entertainment": "allow",
        }
    )

    # 1. Blocked domain
    action, _, _ = engine.evaluate("gambling.test")
    assert action == ACTION_BLOCK

    action, _, _ = engine.evaluate("sub.gambling.test")
    assert action == ACTION_BLOCK

    # 2. Allowed domain
    action, _, _ = engine.evaluate("safe-school.edu.vn")
    assert action == ACTION_ALLOW

    # 3. SafeSearch enforcement (Google, Bing, YouTube, DuckDuckGo)
    for domain, expected_cname in [
        ("google.com", "forcesafesearch.google.com"),
        ("www.google.com", "forcesafesearch.google.com"),
        ("bing.com", "strict.bing.com"),
        ("www.bing.com", "strict.bing.com"),
        ("duckduckgo.com", "safe.duckduckgo.com"),
        ("youtube.com", "restrict.youtube.com"),
        ("www.youtube.com", "restrict.youtube.com"),
    ]:
        action, _, target = engine.evaluate(domain)
        assert action == ACTION_SAFESEARCH
        assert target == expected_cname

    # 4. DoH Canary blocking -> Must return NXDOMAIN
    action, _, _ = engine.evaluate(CANARY_DOH_DOMAIN)
    assert action == ACTION_DOH_CANARY

    # 5. DoH Endpoint blocking -> Must return NXDOMAIN
    for ep in ["dns.google", "cloudflare-dns.com", "dns.quad9.net"]:
        action, _, _ = engine.evaluate(ep)
        assert action == ACTION_DOH_CANARY


def test_50_safe_domains_block_rate_and_20_edu_zero_false_positive():
    """
    FR-F2-03 Acceptance Test:
    - >= 95% block rate on 50 safe test domains across blocked categories (.test / .example)
    - 0% false positives on 20 educational / news domains
    """
    engine = DomainPolicyEngine()

    # 50 simulated safe test domains
    test_50_blocked = [f"simulated-adult-site-{i}.test" for i in range(1, 26)] + \
                      [f"simulated-gambling-{i}.test" for i in range(1, 26)]

    # 20 educational / public domains
    test_20_edu = [
        "uit.edu.vn", "hcmut.edu.vn", "vnu.edu.vn", "hust.edu.vn",
        "khanacademy.org", "coursera.org", "edx.org", "wikipedia.org",
        "tuoitre.vn", "thanhnien.vn", "vnexpress.net", "moet.gov.vn",
        "scratch.mit.edu", "code.org", "duolingo.com", "nationalgeographic.com",
        "nasa.gov", "britannica.com", "ted.com", "sciencedaily.com"
    ]

    rules = [{"domain": d, "category": "inappropriate", "action": "block"} for d in test_50_blocked]
    rules += [{"domain": d, "category": "education", "action": "allow"} for d in test_20_edu]

    engine.load_policy(
        domain_rules=rules,
        category_rules={"inappropriate": "block", "education": "allow"}
    )

    # 1. Verify >= 95% block rate on 50 test domains
    blocked_count = sum(1 for d in test_50_blocked if engine.evaluate(d)[0] == ACTION_BLOCK)
    block_rate = (blocked_count / len(test_50_blocked)) * 100.0
    assert block_rate >= 95.0, f"Block rate {block_rate}% is below 95% threshold"

    # 2. Verify 0% false positives on 20 educational domains
    fp_count = sum(1 for d in test_20_edu if engine.evaluate(d)[0] == ACTION_BLOCK)
    fp_rate = (fp_count / len(test_20_edu)) * 100.0
    assert fp_rate == 0.0, f"False positive rate {fp_rate}% must be exactly 0%"


def test_dns_ttl_cache():
    cache = DnsTtlCache(maxsize=10)
    cache.put("example.com", QTYPE.A, b"response_data", ttl=10)

    cached = cache.get("example.com", QTYPE.A)
    assert cached == b"response_data"

    # Cache miss
    miss = cache.get("notfound.com", QTYPE.A)
    assert miss is None


def test_etld_plus_one_normalization():
    assert normalize_etld_plus_one("sub.school.edu.vn") == "school.edu.vn"
    assert normalize_etld_plus_one("m.youtube.com") == "youtube.com"
    assert normalize_etld_plus_one("chat.openai.com") == "openai.com"
    assert normalize_etld_plus_one("portal.uit.edu.vn") == "uit.edu.vn"
    assert normalize_etld_plus_one("localhost") == "localhost"


def test_port_53_conflict_check_ex01():
    # Bind a mock socket on ephemeral port
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    test_sock.bind(("127.0.0.1", 0))
    bound_port = test_sock.getsockname()[1]

    try:
        conflict = check_port_53_conflict(host="127.0.0.1", port=bound_port)
        assert conflict is not None
        assert conflict["port"] == bound_port
    finally:
        test_sock.close()

    # Free port check should return None
    free_conflict = check_port_53_conflict(host="127.0.0.1", port=bound_port)
    assert free_conflict is None


def _send_udp_query(query_bytes: bytes, port: int) -> bytes:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)
    try:
        sock.sendto(query_bytes, ("127.0.0.1", port))
        data, _ = sock.recvfrom(4096)
        return data
    finally:
        sock.close()


def _send_tcp_query(query_bytes: bytes, port: int) -> bytes:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    try:
        sock.connect(("127.0.0.1", port))
        # RFC 1035: 2-byte length prefix
        prefix = struct.pack("!H", len(query_bytes))
        sock.sendall(prefix + query_bytes)
        resp_prefix = sock.recv(2)
        resp_len = struct.unpack("!H", resp_prefix)[0]
        data = b""
        while len(data) < resp_len:
            chunk = sock.recv(min(4096, resp_len - len(data)))
            if not chunk:
                break
            data += chunk
        return data
    finally:
        sock.close()


@pytest.mark.asyncio
async def test_dns_proxy_server_udp_and_tcp_resolution():
    engine = DomainPolicyEngine()
    engine.load_policy(
        domain_rules=[
            {"domain": "blocked.test", "category": "inappropriate", "action": "block"},
        ],
        category_rules={"inappropriate": "block"}
    )

    mock_event_buffer = MagicMock()
    port = 53580
    server = DnsProxyServer(
        engine=engine,
        host="127.0.0.1",
        port=port,
        event_buffer=mock_event_buffer,
    )
    started = await server.start()
    assert started is True
    loop = asyncio.get_running_loop()

    try:
        # 1. UDP Query for blocked domain -> Sinkhole 0.0.0.0
        q_blocked = DNSRecord.question("blocked.test", "A")
        data = await loop.run_in_executor(None, _send_udp_query, q_blocked.pack(), port)
        resp_blocked = DNSRecord.parse(data)
        assert resp_blocked.header.rcode == RCODE.NOERROR
        assert len(resp_blocked.rr) >= 1
        assert str(resp_blocked.rr[0].rdata) == "0.0.0.0"

        # Check event buffer recorded blocked_domain with eTLD+1
        mock_event_buffer.record_event.assert_called_with(
            event_type="blocked_domain",
            subject="blocked.test",
            policy_id="default_policy",
            duration_sec=0
        )

        # 2. UDP Query for DoH Canary -> NXDOMAIN
        q_canary = DNSRecord.question(CANARY_DOH_DOMAIN, "A")
        data = await loop.run_in_executor(None, _send_udp_query, q_canary.pack(), port)
        resp_canary = DNSRecord.parse(data)
        assert resp_canary.header.rcode == RCODE.NXDOMAIN

        # 3. TCP Query for SafeSearch (google.com) -> CNAME forcesafesearch.google.com
        q_google = DNSRecord.question("google.com", "A")
        data_tcp = await loop.run_in_executor(None, _send_tcp_query, q_google.pack(), port)
        resp_google = DNSRecord.parse(data_tcp)
        assert resp_google.header.rcode == RCODE.NOERROR
        assert any(rr.rtype == QTYPE.CNAME for rr in resp_google.rr)
        assert any(str(rr.rdata).rstrip(".") == "forcesafesearch.google.com" for rr in resp_google.rr)

    finally:
        server.stop()


@pytest.mark.asyncio
async def test_dns_proxy_upstream_failover_ex02():
    engine = DomainPolicyEngine()
    engine.load_policy(domain_rules=[])

    # Port 53581 for test
    port = 53581
    # Configure primary to non-responsive loopback port, secondary to mock responder
    server = DnsProxyServer(
        engine=engine,
        host="127.0.0.1",
        port=port,
        primary_upstream="127.0.0.1",
        secondary_upstream="127.0.0.1",
        upstream_port=53599,
    )

    # Mock _sync_udp_query to simulate Primary failure and Secondary success
    call_log = []

    def mock_sync_query(host, p, q_data, timeout):
        call_log.append((host, p))
        if len(call_log) == 1:
            # Primary fails (timeout)
            return None
        # Secondary succeeds: build valid DNS response
        req = DNSRecord.parse(q_data)
        resp = DNSRecord(
            DNSHeader(id=req.header.id, qr=1, ra=1, rcode=RCODE.NOERROR),
            q=req.q
        )
        resp.add_answer(RR(req.q.qname, QTYPE.A, rdata=A("93.184.216.34"), ttl=60))
        return resp.pack()

    server._sync_udp_query = mock_sync_query
    started = await server.start()
    assert started is True
    loop = asyncio.get_running_loop()

    try:
        q_example = DNSRecord.question("example.com", "A")
        data = await loop.run_in_executor(None, _send_udp_query, q_example.pack(), port)
        resp = DNSRecord.parse(data)
        assert resp.header.rcode == RCODE.NOERROR
        assert len(resp.rr) >= 1
        assert str(resp.rr[0].rdata) == "93.184.216.34"

        # Verify failover sequence occurred: primary called, then secondary called
        assert len(call_log) == 2
    finally:
        server.stop()
