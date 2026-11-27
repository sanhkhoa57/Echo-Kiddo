"""Local Async DNS Proxy Server for OGK-Agent (FR-F2-03, FR-F2-05, FR-F2-06, M1, EX-01, EX-02).
Listens on 127.0.0.1:53 (both UDP and TCP) using dnslib + asyncio.
Implements:
1. Port 53 conflict pre-check (EX-01) with process detection
2. DoH Canary & DoH Endpoints blocking (NXDOMAIN)
3. SafeSearch CNAME/A record redirection
4. Blocked domain sinkholing (0.0.0.0)
5. Upstream DNS forwarding (1.1.1.1) with automatic failover to 8.8.8.8 on timeout > 2s (EX-02)
6. In-memory TTL Cache and eTLD+1 event logging
"""
import asyncio
import logging
import socket
import struct
import time
from typing import Optional, Dict, Tuple, Any, List, Callable
import psutil
from dnslib import DNSRecord, DNSHeader, DNSQuestion, QTYPE, RR, A, AAAA, CNAME, RCODE

from agent.dns.domain_engine import (
    DomainPolicyEngine,
    ACTION_ALLOW,
    ACTION_BLOCK,
    ACTION_SAFESEARCH,
    ACTION_DOH_CANARY,
    normalize_etld_plus_one,
)

logger = logging.getLogger("OGK.DnsProxy")

DEFAULT_PRIMARY_UPSTREAM = "1.1.1.1"
DEFAULT_SECONDARY_UPSTREAM = "8.8.8.8"
DEFAULT_UPSTREAM_PORT = 53
UPSTREAM_TIMEOUT_SEC = 2.0
CACHE_MIN_TTL = 5
CACHE_MAX_TTL = 300
NEGATIVE_CACHE_TTL = 30
BLOCK_TTL = 60


def _is_truncated(wire: bytes) -> bool:
    """TC flag of a DNS message (byte 2, bit 0x02)."""
    return len(wire) > 2 and bool(wire[2] & 0x02)


def _cache_ttl(record: DNSRecord) -> Optional[int]:
    """TTL to cache an upstream answer for, or None when it must not be cached."""
    if record.header.rcode in (RCODE.SERVFAIL, RCODE.REFUSED) or record.header.tc:
        return None
    ttls = [rr.ttl for rr in record.rr]
    if not ttls:
        return NEGATIVE_CACHE_TTL
    return max(CACHE_MIN_TTL, min(CACHE_MAX_TTL, min(ttls)))


class DnsTtlCache:
    """In-memory DNS response cache with TTL expiration."""

    def __init__(self, maxsize: int = 2048):
        self.maxsize = maxsize
        self._cache: Dict[Tuple[str, int], Tuple[float, bytes]] = {}

    def get(self, qname: str, qtype: int) -> Optional[bytes]:
        key = (qname.lower().rstrip("."), qtype)
        if key in self._cache:
            expire_at, data = self._cache[key]
            if time.time() < expire_at:
                return data
            else:
                del self._cache[key]
        return None

    def put(self, qname: str, qtype: int, data: bytes, ttl: int = 60) -> None:
        if len(self._cache) >= self.maxsize:
            now = time.time()
            expired = [k for k, (exp, _) in self._cache.items() if exp <= now]
            if expired:
                for k in expired:
                    del self._cache[k]
            else:
                self._cache.pop(next(iter(self._cache)))

        expire_at = time.time() + max(5, ttl)
        self._cache[(qname.lower().rstrip("."), qtype)] = (expire_at, data)

    def clear(self) -> None:
        self._cache.clear()


def check_port_53_conflict(host: str = "127.0.0.1", port: int = 53) -> Optional[Dict[str, Any]]:
    """
    Checks if host:port is already occupied by another service (EX-01).
    Returns conflict info dictionary if occupied, or None if port is free.
    """
    conflict_detected = False

    # 1. Test UDP bind
    try:
        sock_u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_u.bind((host, port))
        sock_u.close()
    except OSError:
        conflict_detected = True

    # 2. Test TCP bind
    if not conflict_detected:
        try:
            sock_t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock_t.bind((host, port))
            sock_t.close()
        except OSError:
            conflict_detected = True

    if not conflict_detected:
        return None

    # Identify process holding port 53 via psutil
    conflict_info = {
        "host": host,
        "port": port,
        "pid": None,
        "process_name": "unknown",
        "details": "Port is already in use by another service."
    }

    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port:
                if host in (conn.laddr.ip, "0.0.0.0", "127.0.0.1"):
                    conflict_info["pid"] = conn.pid
                    if conn.pid:
                        try:
                            proc = psutil.Process(conn.pid)
                            conflict_info["process_name"] = proc.name()
                        except Exception:
                            pass
                    break
    except Exception as e:
        logger.debug("Failed scanning connections for port conflict: %s", e)

    logger.warning(
        "Port conflict detected on %s:%d! Process: %s (PID: %s)",
        host, port, conflict_info["process_name"], conflict_info["pid"]
    )
    return conflict_info


class DnsProxyServer:
    """
    Async Dual-Stack (UDP + TCP) DNS Proxy Server.
    Integrates Suffix Trie domain filtering, SafeSearch, DoH Canary,
    TTL caching, and upstream failover (EX-02).
    """

    def __init__(
        self,
        engine: DomainPolicyEngine,
        host: str = "127.0.0.1",
        port: int = 53,
        event_buffer=None,
        policy_id: str = "default_policy",
        primary_upstream: str = DEFAULT_PRIMARY_UPSTREAM,
        secondary_upstream: str = DEFAULT_SECONDARY_UPSTREAM,
        upstream_port: int = DEFAULT_UPSTREAM_PORT,
        on_blocked_callback: Optional[Callable[[str, str], None]] = None,
        extra_upstreams: Optional[List[str]] = None,
        listen_ipv6: bool = False,
    ):
        self.on_blocked_callback = on_blocked_callback
        self.listen_ipv6 = listen_ipv6
        self.ipv6_active: bool = False
        self.udp6_transport: Optional[asyncio.DatagramTransport] = None
        self.tcp6_server: Optional[asyncio.Server] = None
        self.extra_upstreams: List[str] = []
        # Index into upstreams() of the last resolver that answered: tried first next time,
        # so a network that blocks 1.1.1.1 only costs one timeout, not one per query.
        self._preferred_upstream: int = 0
        # Identical queries already on their way upstream (qname, qtype) -> future answer:
        # a page firing the same lookup ten times costs one upstream round trip.
        self._inflight: Dict[Tuple[str, int], "asyncio.Future"] = {}
        self.engine = engine
        self.host = host
        self.port = port
        self.event_buffer = event_buffer
        self.policy_id = policy_id
        self.primary_upstream = primary_upstream
        self.secondary_upstream = secondary_upstream
        self.upstream_port = upstream_port

        self.cache = DnsTtlCache()
        self.set_extra_upstreams(extra_upstreams or [])
        self.udp_transport: Optional[asyncio.DatagramTransport] = None
        self.tcp_server: Optional[asyncio.Server] = None
        self.conflict_info: Optional[Dict[str, Any]] = None
        self.is_running: bool = False

    def set_extra_upstreams(self, servers: List[str]) -> None:
        """Adds the DNS servers of the network the PC was on (from the adapter snapshot) as
        fallbacks, so filtering keeps working where public resolvers are blocked."""
        base = [self.primary_upstream, self.secondary_upstream]
        self.extra_upstreams = [ip for ip in servers if ip and ip not in base
                                and not ip.startswith("127.") and ip != "::1"]

    def upstreams(self) -> List[str]:
        return [self.primary_upstream, self.secondary_upstream] + self.extra_upstreams

    async def start(self) -> bool:
        """
        Starts the DNS Proxy on UDP and TCP.
        Checks for port conflict before binding (EX-01).
        Returns True if successfully started, False if blocked by conflict.
        """
        # Pre-check port conflict (EX-01)
        self.conflict_info = check_port_53_conflict(self.host, self.port)
        if self.conflict_info:
            logger.error(
                "EX-01: Port %d conflict detected! Occupied by '%s' (PID %s). DNS Proxy start aborted.",
                self.port, self.conflict_info["process_name"], self.conflict_info["pid"]
            )
            return False

        loop = asyncio.get_running_loop()

        # 1. Start UDP Datagram Listener
        try:
            self.udp_transport, _ = await loop.create_datagram_endpoint(
                lambda: _DnsDatagramProtocol(self),
                local_addr=(self.host, self.port)
            )
        except Exception as e:
            logger.error("Failed to start UDP DNS Proxy on %s:%d: %s", self.host, self.port, e)
            self.stop()
            return False

        # 2. Start TCP Stream Listener
        try:
            self.tcp_server = await asyncio.start_server(
                self._handle_tcp_connection,
                host=self.host,
                port=self.port
            )
        except Exception as e:
            logger.warning("TCP DNS listener could not start on %s:%d (%s). Operating in UDP-only mode.", self.host, self.port, e)

        # 3. Optional IPv6 loopback listeners ([::1]:53) so the adapters' IPv6 DNS can also
        #    point at the proxy instead of leaking to the router.
        if self.listen_ipv6:
            try:
                self.udp6_transport, _ = await loop.create_datagram_endpoint(
                    lambda: _DnsDatagramProtocol(self), local_addr=("::1", self.port)
                )
                try:
                    self.tcp6_server = await asyncio.start_server(
                        self._handle_tcp_connection, host="::1", port=self.port
                    )
                except Exception as e:
                    logger.debug("TCP [::1]:%d unavailable: %s", self.port, e)
                self.ipv6_active = True
            except Exception as e:
                logger.info("IPv6 loopback DNS listener unavailable (%s); IPv4 only.", e)

        self.is_running = True
        logger.info(
            "OGK DNS Proxy started on %s:%d (UDP & TCP). Upstream: %s (Failover: %s)",
            self.host, self.port, self.primary_upstream, self.secondary_upstream
        )
        return True

    def stop(self) -> None:
        """Stops the DNS proxy listeners cleanly."""
        self.is_running = False
        if self.udp_transport:
            try:
                self.udp_transport.close()
            except Exception:
                pass
            self.udp_transport = None

        if self.tcp_server:
            try:
                self.tcp_server.close()
            except Exception:
                pass
            self.tcp_server = None

        for attr in ("udp6_transport", "tcp6_server"):
            obj = getattr(self, attr, None)
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        self.ipv6_active = False

        logger.info("OGK DNS Proxy stopped.")

    def _record_event(self, event_type: str, subject: str) -> None:
        """Records an event; a logging failure must never break the DNS answer."""
        if not self.event_buffer:
            return
        try:
            self.event_buffer.record_event(
                event_type=event_type,
                subject=subject,
                policy_id=self.policy_id,
                duration_sec=0
            )
        except Exception as e:
            logger.debug("Could not record %s event: %s", event_type, e)

    def _reply_skeleton(self, request: DNSRecord, rcode: int = RCODE.NOERROR, aa: int = 1) -> DNSRecord:
        return DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=aa, ra=1, rd=request.header.rd, rcode=rcode),
                         q=request.q)

    def _from_cache(self, request: DNSRecord, qname: str, qtype: int) -> Optional[bytes]:
        cached = self.cache.get(qname, qtype)
        if not cached:
            return None
        try:
            record = DNSRecord.parse(cached)
            record.header.id = request.header.id
            return record.pack()
        except Exception:
            return None

    async def process_dns_query(self, raw_data: bytes, via_tcp: bool = False) -> Optional[bytes]:
        """
        Core DNS query resolution pipeline.
        Returns DNS response wire bytes.
        """
        try:
            request = DNSRecord.parse(raw_data)
        except Exception as e:
            logger.debug("Failed parsing DNS packet: %s", e)
            return None
        if not request.questions:
            return self._reply_skeleton(request, RCODE.FORMERR, aa=0).pack()

        qname = str(request.q.qname).rstrip(".")
        qtype = request.q.qtype

        # 1. Evaluate query via DomainPolicyEngine
        action, reason, target = self.engine.evaluate(qname)
        etld_subject = normalize_etld_plus_one(qname)

        # 2. Handle DoH Canary (RFC/Mozilla spec) & DoH Endpoints -> NXDOMAIN
        if action == ACTION_DOH_CANARY:
            return self._reply_skeleton(request, RCODE.NXDOMAIN).pack()

        # 3. Handle SafeSearch CNAME Redirection (FR-F2-05). The CNAME alone is not enough:
        #    stub resolvers and Chrome's own resolver expect the addresses of the target in
        #    the same answer (like a real recursive resolver), or google.com fails to load.
        elif action == ACTION_SAFESEARCH and target:
            cached = self._from_cache(request, qname, qtype)
            if cached:
                return cached
            reply = self._reply_skeleton(request)
            reply.add_answer(RR(request.q.qname, QTYPE.CNAME, rdata=CNAME(target), ttl=300))
            target_query = DNSRecord(DNSHeader(rd=1), q=DNSQuestion(target, qtype))
            upstream = await self._forward_upstream_with_failover(target_query.pack(), via_tcp=via_tcp)
            if upstream:
                try:
                    resolved = DNSRecord.parse(upstream)
                    for rr in resolved.rr:
                        reply.add_answer(rr)
                    if resolved.rr:
                        self.cache.put(qname, qtype, reply.pack(), ttl=_cache_ttl(resolved) or CACHE_MIN_TTL)
                except Exception as e:
                    logger.debug("SafeSearch target %s answer unparsable: %s", target, e)

            # Record domain_query event with eTLD+1
            self._record_event("domain_query", etld_subject)
            return reply.pack()

        # 4. Handle Blocked Domain -> Sinkhole: 0.0.0.0 for A, :: for AAAA, empty otherwise
        elif action == ACTION_BLOCK:
            reply = self._reply_skeleton(request)
            if qtype == QTYPE.A:
                reply.add_answer(RR(request.q.qname, QTYPE.A, rdata=A("0.0.0.0"), ttl=BLOCK_TTL))
            elif qtype == QTYPE.AAAA:
                reply.add_answer(RR(request.q.qname, QTYPE.AAAA, rdata=AAAA("::"), ttl=BLOCK_TTL))

            # Record blocked_domain event with eTLD+1
            self._record_event("blocked_domain", etld_subject)
            # Never block silently: let the service tell the child why (FR-F2-02)
            if self.on_blocked_callback:
                try:
                    self.on_blocked_callback(etld_subject, reason)
                except Exception as cb_err:
                    logger.debug("Blocked-domain callback error: %s", cb_err)
            return reply.pack()

        # 5. Handle Allowed Domain: Check TTL Cache
        cached = self._from_cache(request, qname, qtype)
        if cached:
            return cached

        # 6. Cache Miss: Forward upstream with EX-02 failover (coalescing identical queries)
        key = (qname.lower(), qtype)
        pending = self._inflight.get(key)
        if pending is not None and not via_tcp:
            shared = await asyncio.shield(pending)
            if shared:
                return raw_data[:2] + shared[2:]
            return self._reply_skeleton(request, RCODE.SERVFAIL, aa=0).pack()

        fut = asyncio.get_running_loop().create_future()
        if not via_tcp:
            self._inflight[key] = fut
        upstream_resp: Optional[bytes] = None
        try:
            upstream_resp = await self._forward_upstream_with_failover(raw_data, via_tcp=via_tcp)
        finally:
            if not fut.done():
                fut.set_result(upstream_resp)
            if self._inflight.get(key) is fut:
                del self._inflight[key]
        if upstream_resp:
            try:
                ttl = _cache_ttl(DNSRecord.parse(upstream_resp))
            except Exception:
                ttl = None
            if ttl is not None:
                self.cache.put(qname, qtype, upstream_resp, ttl=ttl)
            self._record_event("domain_query", etld_subject)
            return upstream_resp

        # 7. Upstream Timeout: Return SERVFAIL
        return self._reply_skeleton(request, RCODE.SERVFAIL, aa=0).pack()

    async def _forward_upstream_with_failover(self, query_data: bytes, via_tcp: bool = False) -> Optional[bytes]:
        """
        Forwards the query to the upstream resolvers in turn (1.1.1.1, then 8.8.8.8 after a
        2s timeout (EX-02), then the network's own DNS), starting with the one that answered
        last. A truncated UDP answer is re-asked over TCP for TCP clients.
        """
        loop = asyncio.get_running_loop()
        servers = self.upstreams()
        order = list(range(len(servers)))
        if 0 < self._preferred_upstream < len(servers):
            order.remove(self._preferred_upstream)
            order.insert(0, self._preferred_upstream)

        fallback: Optional[bytes] = None
        for attempt, idx in enumerate(order):
            host = servers[idx]
            if attempt > 0:
                logger.warning("EX-02: upstream %s did not answer within %.0fs; trying %s...",
                               servers[order[attempt - 1]], UPSTREAM_TIMEOUT_SEC, host)
            try:
                resp = await self._udp_query(host, self.upstream_port, query_data, UPSTREAM_TIMEOUT_SEC)
                if resp and via_tcp and _is_truncated(resp):
                    tcp_resp = await loop.run_in_executor(
                        None, self._sync_tcp_query, host, self.upstream_port, query_data, UPSTREAM_TIMEOUT_SEC
                    )
                    resp = tcp_resp or resp
                if resp:
                    if len(resp) > 3 and (resp[3] & 0x0F) in (RCODE.SERVFAIL, RCODE.REFUSED):
                        # This resolver is broken for the name: try the next one first
                        fallback = fallback or resp
                        continue
                    if idx != self._preferred_upstream:
                        logger.info("Upstream %s answered; preferring it from now on.", host)
                    self._preferred_upstream = idx
                    return resp
            except Exception as e:
                logger.debug("Upstream %s failed: %s", host, e)

        if fallback:
            return fallback
        logger.error("No upstream DNS answered (%s).", ", ".join(servers))
        return None

    async def _udp_query(self, host: str, port: int, query_data: bytes, timeout: float) -> Optional[bytes]:
        """One upstream UDP round trip without occupying a worker thread, so hundreds of
        parallel lookups (a page load) never queue behind the default thread pool.
        Tests / benchmarks that replace _sync_udp_query on the instance keep working."""
        if "_sync_udp_query" in vars(self):
            return await asyncio.get_running_loop().run_in_executor(
                None, self._sync_udp_query, host, port, query_data, timeout)
        loop = asyncio.get_running_loop()
        answer = loop.create_future()
        txid = query_data[:2]

        class _Upstream(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                if data[:2] == txid and not answer.done():
                    answer.set_result(data)

            def error_received(self, exc):
                pass  # ICMP unreachable etc.: let the timeout decide

        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        transport, _ = await loop.create_datagram_endpoint(
            _Upstream, remote_addr=(host, port), family=family)
        try:
            transport.sendto(query_data)
            return await asyncio.wait_for(answer, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            transport.close()

    def _sync_udp_query(self, host: str, port: int, query_data: bytes, timeout: float) -> Optional[bytes]:
        """Synchronous UDP query helper. Ignores datagrams whose transaction ID does not
        match the query (late answers, spoofing attempts)."""
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(query_data, (host, port))
            while True:
                data, _ = sock.recvfrom(65535)
                if len(data) >= 2 and data[:2] == query_data[:2]:
                    return data
        except socket.timeout:
            return None
        finally:
            sock.close()

    def _sync_tcp_query(self, host: str, port: int, query_data: bytes, timeout: float) -> Optional[bytes]:
        """Synchronous DNS-over-TCP query (2-byte length prefix), for truncated answers."""
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.sendall(struct.pack("!H", len(query_data)) + query_data)

            def _read(n: int) -> bytes:
                buf = b""
                while len(buf) < n:
                    chunk = sock.recv(n - len(buf))
                    if not chunk:
                        raise ConnectionError("upstream closed TCP connection")
                    buf += chunk
                return buf

            length = struct.unpack("!H", _read(2))[0]
            return _read(length)

    async def _handle_tcp_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handles DNS over TCP queries (RFC 1035: 2-byte big-endian length prefix)."""
        try:
            while True:
                prefix = await reader.readexactly(2)
                if not prefix:
                    break
                msg_len = struct.unpack("!H", prefix)[0]
                if msg_len > 65535:
                    break
                raw_query = await reader.readexactly(msg_len)

                resp_bytes = await self.process_dns_query(raw_query, via_tcp=True)
                if resp_bytes:
                    writer.write(struct.pack("!H", len(resp_bytes)) + resp_bytes)
                    await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            logger.debug("TCP client handling error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


_PENDING_TASKS: set = set()


class _DnsDatagramProtocol(asyncio.DatagramProtocol):
    """Internal Datagram Protocol for DNS Proxy."""

    def __init__(self, server: DnsProxyServer):
        self.server = server
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        # Keep a reference: the event loop only holds weak references to tasks
        task = asyncio.create_task(self._handle_datagram(data, addr))
        _PENDING_TASKS.add(task)
        task.add_done_callback(_PENDING_TASKS.discard)

    def error_received(self, exc: Exception) -> None:
        # Windows reports ICMP "port unreachable" from a client that already left as
        # ConnectionResetError on the listening socket; it must not stop the proxy.
        logger.debug("UDP listener error ignored: %s", exc)

    async def _handle_datagram(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            resp = await self.server.process_dns_query(data)
            if resp and self.transport:
                self.transport.sendto(resp, addr)
        except Exception as e:
            logger.debug("Error responding to %s: %s", addr, e)
