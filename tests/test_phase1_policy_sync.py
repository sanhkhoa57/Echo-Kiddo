"""Phase 1: policy schema / HMAC / pairing between OGK-Server and OGK-Agent.

Everything runs in-process: the agent's httpx client talks to the FastAPI app through
httpx.ASGITransport (or MockTransport), all databases live in temp files, and nothing
touches adapter DNS, the registry or Windows services.
"""
import os
os.environ["OGK_TESTING"] = "1"

import hashlib
import hmac
import json
import tempfile
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import httpx
import pytest
from argon2 import PasswordHasher
from dnslib import DNSRecord
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from agent.cleanup import ogk_cleanup
from agent.core.agent_db import AgentDatabase
from agent.core.event_buffer import EventBuffer, normalize_subject
from agent.core.pin_auth import verify_pin_hash
from agent.core import policy_verifier
from agent.core.policy_verifier import (
    SIGNED_POLICY_KEYS as AGENT_SIGNED_KEYS,
    calculate_policy_signature,
    decode_policy,
    verify_policy,
)
from agent.core.screen_time import ScreenTimeManager
from agent.dns.dns_proxy import DnsProxyServer
from agent.dns.domain_engine import DomainPolicyEngine
from agent.platform.browser_policy import BrowserPolicyGuard
from agent.platform.network_guard import NetworkDnsGuard
from agent.service import win_service
from agent.service.session_launcher import SessionAgentLauncher
from agent.sync.server_client import AgentServerClient
from server.auth.security import JWT_SECRET
from server.main import app
from server.models.base import Base
from server.models.child import Child
from server.models.database import create_ogk_engine, get_db
from server.models.policy import Policy
from server.services import policy_service
from server.services.command_hub import command_hub

SERVER_URL = "http://testserver"
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
FINGERPRINT = "f" * 64


# --------------------------------------------------------------------------- fixtures
@pytest.fixture
def server():
    """FastAPI app on a temp SQLite DB. Yields (parent TestClient, SessionLocal)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_ogk_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, SessionLocal
    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def agent_db(tmp_path):
    return AgentDatabase(tmp_path / "agent.db")


def make_parent_and_child(client, SessionLocal, name="Bé Na"):
    email = f"p_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "role": "parent"})
    assert reg.status_code in (200, 201), reg.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    assert login.status_code == 200, login.text
    client.cookies.clear()  # act as a pure Bearer client
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    db = SessionLocal()
    child = Child(parent_id=reg.json()["id"], display_name=name)
    db.add(child)
    db.commit()
    db.refresh(child)
    child_id = child.id
    db.close()
    return headers, child_id


def new_pairing_code(client, headers, child_id) -> str:
    resp = client.post("/api/v1/enroll/code", json={"child_id": child_id, "consent_confirmed": True}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["code"]


def asgi_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=SERVER_URL)


def make_agent(db=None, **kwargs) -> AgentServerClient:
    return AgentServerClient(server_url=SERVER_URL, db=db, http_client=asgi_http_client(), **kwargs)


def make_core(tmp_path) -> "win_service.OGKServiceCore":
    """Service core on a temp DB with the system-touching guards replaced by mocks."""
    core = win_service.OGKServiceCore(db_path=tmp_path / "agent.db", server_url=SERVER_URL)
    core.net_guard = MagicMock()
    core.browser_guard = MagicMock()
    return core


# --------------------------------------------------------------------------- HMAC contract
def test_signed_key_list_is_identical_on_server_and_agent():
    assert tuple(policy_service.SIGNED_POLICY_KEYS) == tuple(AGENT_SIGNED_KEYS)
    assert "id" not in AGENT_SIGNED_KEYS and "signature" not in AGENT_SIGNED_KEYS
    # Agent lab default derives the same key the server signs with
    assert policy_verifier.derive_policy_secret(JWT_SECRET) == policy_service.derive_policy_secret(JWT_SECRET)
    # The device-facing key is never the JWT secret itself
    assert policy_service.POLICY_SECRET != JWT_SECRET


@pytest.mark.asyncio
async def test_enroll_policy_passes_agent_hmac_verification(server, agent_db):
    client, SessionLocal = server
    headers, child_id = make_parent_and_child(client, SessionLocal)
    code = new_pairing_code(client, headers, child_id)

    agent = make_agent(db=agent_db)
    data = await agent.enroll(code, FINGERPRINT, "S-1-5-21-1-2-3-1001")

    policy = data["policy"]
    assert set(policy) == set(AGENT_SIGNED_KEYS) | {"signature"}
    assert policy["child_id"] == child_id
    assert data["policy_hmac_secret"] != JWT_SECRET
    assert verify_policy(policy, data["policy_hmac_secret"]) == (True, "OK")

    # The agent applied it and decoded the JSON fields for the enforcement engines
    assert agent.device_id == data["device_id"] and agent.child_id == child_id
    assert agent.current_policy_version == 1
    assert isinstance(agent.active_policy["app_rules"], list) and agent.active_policy["app_rules"]
    assert isinstance(agent.active_policy["domain_rules"], list)
    assert isinstance(agent.active_policy["category_quotas"], dict)
    assert agent.active_policy["category_budgets"] == agent.active_policy["category_quotas"]
    assert len(agent.active_policy["schedule_matrix"]) == 336


@pytest.mark.asyncio
async def test_get_policy_then_put_then_get_still_verifies(server, agent_db):
    client, SessionLocal = server
    headers, child_id = make_parent_and_child(client, SessionLocal)
    agent = make_agent(db=agent_db)
    await agent.enroll(new_pairing_code(client, headers, child_id), FINGERPRINT)
    secret = agent.policy_secret()
    dev_headers = {"Authorization": f"Bearer {agent.access_token}"}

    # GET /api/v1/policy carries the unsigned `id`, yet verifies
    got = client.get("/api/v1/policy", headers=dev_headers)
    assert got.status_code == 200
    assert "id" in got.json()
    assert verify_policy(got.json(), secret) == (True, "OK")
    assert await agent.fetch_and_apply_policy() is True

    # Parent updates with the canonical PolicyUpdate field names
    matrix = "1" * 300 + "0" * 36
    put = client.put(f"/api/v1/policy/{child_id}", headers=headers, json={
        "daily_limit_weekday_min": 45,
        "daily_limit_weekend_min": 75,
        "schedule_matrix_7x48": matrix,
        "category_budgets": {"gaming": 30},
        "app_rules": [{"exe_name": "game.exe", "category": "gaming", "action": "block"}],
        "domain_rules": [{"domain": "blocked-site.test", "category": "inappropriate", "action": "block"}],
    })
    assert put.status_code == 200, put.text
    assert verify_policy(put.json(), secret) == (True, "OK")

    got2 = client.get("/api/v1/policy", headers=dev_headers)
    assert got2.json()["version"] == 2
    assert verify_policy(got2.json(), secret) == (True, "OK")

    engine = DomainPolicyEngine()
    agent.domain_engine = engine
    assert await agent.fetch_and_apply_policy() is True
    assert agent.current_policy_version == 2
    assert agent.active_policy["app_rules"] == [
        {"exe_name": "game.exe", "sha256": None, "original_filename": None, "category": "gaming", "action": "block"}
    ]
    assert agent.active_policy["category_quotas"] == {"gaming": 30}
    assert agent.active_policy["schedule_matrix"] == matrix
    assert engine.evaluate("www.blocked-site.test")[0] == "BLOCK"

    # Tampering with a signed field, or with the signature, is rejected
    tampered = dict(got2.json(), daily_limit_weekday_min=600)
    assert verify_policy(tampered, secret)[0] is False
    assert agent._apply_policy(tampered) is False
    assert agent.active_policy["daily_limit_weekday_min"] == 45


@pytest.mark.asyncio
async def test_unsigned_extra_fields_cannot_influence_enforcement(server, agent_db):
    client, SessionLocal = server
    headers, child_id = make_parent_and_child(client, SessionLocal)
    agent = make_agent(db=agent_db)
    data = await agent.enroll(new_pairing_code(client, headers, child_id), FINGERPRINT)

    # Valid signature, but legacy alias fields injected next to the signed ones
    injected = dict(data["policy"], daily_limit_minutes_weekday=9999, schedule_matrix="1" * 336,
                    app_rules=[], category_quotas={"gaming": 9999})
    assert agent._apply_policy(injected) is True
    active = agent.active_policy
    assert active["daily_limit_minutes_weekday"] == data["policy"]["daily_limit_weekday_min"]
    assert active["schedule_matrix"] == data["policy"]["schedule_matrix_7x48"]
    assert active["app_rules"] == json.loads(data["policy"]["app_rules_json"])
    assert active["category_quotas"] == json.loads(data["policy"]["category_budgets_json"])


@pytest.mark.asyncio
async def test_policy_of_another_child_is_rejected(server, agent_db):
    client, SessionLocal = server
    headers, child_a = make_parent_and_child(client, SessionLocal)
    headers_b, child_b = make_parent_and_child(client, SessionLocal, name="Bé Bo")
    agent = make_agent(db=agent_db)
    await agent.enroll(new_pairing_code(client, headers, child_a), FINGERPRINT)

    other = client.get(f"/api/v1/policy/{child_b}", headers=headers_b).json()
    assert verify_policy(other, agent.policy_secret())[0] is True  # same signing key...
    assert agent._apply_policy(other) is False                     # ...but bound to child A
    assert agent.active_policy["child_id"] == child_a


@pytest.mark.asyncio
async def test_policy_row_signed_with_old_key_is_resigned_for_agent(server, agent_db):
    client, SessionLocal = server
    headers, child_id = make_parent_and_child(client, SessionLocal)
    agent = make_agent(db=agent_db)
    await agent.enroll(new_pairing_code(client, headers, child_id), FINGERPRINT)

    # Simulate a row written by the old code (signed directly with the JWT secret)
    db = SessionLocal()
    row = db.query(Policy).filter(Policy.child_id == child_id).first()
    payload = {k: getattr(row, k) for k in AGENT_SIGNED_KEYS}
    row.signature = policy_service.sign_policy_payload(payload, JWT_SECRET)
    db.commit()
    db.close()

    assert await agent.fetch_and_apply_policy() is True


@pytest.mark.asyncio
async def test_heartbeat_refresh_and_event_upload_match_server_schemas(server, agent_db):
    client, SessionLocal = server
    headers, child_id = make_parent_and_child(client, SessionLocal)
    buffer = EventBuffer(db=agent_db)
    agent = make_agent(db=agent_db, event_buffer=buffer, screen_time_mgr=ScreenTimeManager())
    await agent.enroll(new_pairing_code(client, headers, child_id), FINGERPRINT)

    # Enrollment gave the event buffer its identity
    assert buffer.device_id == agent.device_id and buffer.child_id == child_id
    buffer.record_event("blocked_domain", "www.blocked-site.test", policy_id="1")

    # Parent changes the policy; the next heartbeat (60s cadence) picks it up
    put = client.put(f"/api/v1/policy/{child_id}", headers=headers, json={"daily_limit_weekday_min": 30})
    assert put.status_code == 200
    hb = await agent.send_heartbeat()
    assert hb["latest_policy_version"] == 2
    assert agent.current_policy_version == 2
    assert agent.active_policy["daily_limit_minutes_weekday"] == 30

    assert await agent.upload_event_batch() == 1
    assert await agent.refresh_access_token() is True


# --------------------------------------------------------------------------- field names
def _weekday(hour=10):
    return datetime(2026, 11, 16, hour, 15)   # Monday


def _weekend(hour=10):
    return datetime(2026, 11, 21, hour, 15)   # Saturday


@pytest.mark.parametrize("policy", [
    # canonical server names
    {"daily_limit_weekday_min": 50, "daily_limit_weekend_min": 80,
     "schedule_matrix_7x48": "0" * 48 + "1" * 288, "category_budgets_json": '{"gaming": 20}'},
    # legacy aliases used by the original unit tests
    {"daily_limit_minutes_weekday": 50, "daily_limit_minutes_weekend": 80,
     "schedule_matrix": "0" * 48 + "1" * 288, "category_budgets": {"gaming": 20}},
    # win_service-style alias for budgets
    {"daily_limit_minutes_weekday": 50, "daily_limit_minutes_weekend": 80,
     "schedule_matrix": "0" * 48 + "1" * 288, "category_quotas": {"gaming": 20}},
])
def test_screen_time_reads_canonical_and_legacy_field_names(policy):
    mgr = ScreenTimeManager()
    assert mgr.get_daily_limit_seconds(policy, _weekday()) == 50 * 60
    assert mgr.get_daily_limit_seconds(policy, _weekend()) == 80 * 60

    # Monday is fully locked by the matrix, Saturday is open
    assert mgr.evaluate_lock_status(policy, _weekday())[:2] == (True, "OUTSIDE_ALLOWED_SCHEDULE")
    assert mgr.evaluate_lock_status(policy, _weekend())[0] is False

    mgr.category_used_sec = {"gaming": 21 * 60}
    assert mgr.is_category_over_budget("gaming", policy) == (True, 21 * 60, 20 * 60)
    assert mgr.is_category_over_budget("education", policy)[0] is False


def test_verify_policy_validates_canonical_field_names():
    secret = "k"
    base = {k: None for k in AGENT_SIGNED_KEYS}
    base.update(child_id="c1", version=3, daily_limit_weekday_min=60, daily_limit_weekend_min=90,
                schedule_matrix_7x48="1" * 336, category_budgets_json="{}", app_rules_json="[]",
                domain_rules_json="[]", updated_at_utc="2026-11-17T00:00:00+00:00")
    good = dict(base, signature=calculate_policy_signature(base, secret))
    assert verify_policy(good, secret) == (True, "OK")
    assert verify_policy(dict(good, id="metadata-is-not-signed"), secret) == (True, "OK")

    bad = dict(base, schedule_matrix_7x48="1" * 10)
    bad["signature"] = calculate_policy_signature(bad, secret)
    ok, reason = verify_policy(bad, secret)
    assert ok is False and "schedule_matrix" in reason

    decoded = decode_policy(dict(good, app_rules_json='[{"exe_name": "a.exe", "action": "block"}]'))
    assert decoded["app_rules"] == [{"exe_name": "a.exe", "action": "block"}]


# --------------------------------------------------------------------------- credentials
@pytest.mark.asyncio
async def test_credentials_survive_restart(server, tmp_path):
    client, SessionLocal = server
    headers, child_id = make_parent_and_child(client, SessionLocal)
    db_path = tmp_path / "agent.db"

    first = make_agent(db=AgentDatabase(db_path))
    await first.enroll(new_pairing_code(client, headers, child_id), FINGERPRINT)

    saved = AgentDatabase(db_path).get_device_credentials()
    assert saved["device_id"] == first.device_id
    assert saved["child_id"] == child_id
    assert saved["access_token"] == first.access_token
    assert saved["refresh_token"] == first.refresh_token
    assert saved["server_url"] == SERVER_URL
    assert saved["policy_hmac_secret"] == first.policy_secret()

    # "Restart": brand-new objects on the same agent.db, nothing passed to the constructor
    buffer = EventBuffer(db=AgentDatabase(db_path))
    second = AgentServerClient(server_url=SERVER_URL, db=AgentDatabase(db_path),
                               event_buffer=buffer, http_client=asgi_http_client())
    assert second.device_id == first.device_id
    assert second.child_id == child_id
    assert second.access_token == first.access_token
    assert second.refresh_token == first.refresh_token
    assert buffer.device_id == first.device_id and buffer.child_id == child_id

    # start() restores the cached signed policy as well (background loops stubbed out)
    async def _noop():
        return None
    second.run_websocket_loop = _noop
    second._sync_worker_loop = _noop
    await second.start()
    second.stop()
    assert second.current_policy_version == 1
    assert second.active_policy["child_id"] == child_id
    assert second.active_policy["app_rules"]

    # The restored identity really works against the server
    assert (await second.send_heartbeat())["latest_policy_version"] == 1

    # Explicit constructor arguments still win over the stored values
    third = AgentServerClient(server_url=SERVER_URL, db=AgentDatabase(db_path),
                              device_id="explicit-dev", access_token="explicit-token")
    assert third.device_id == "explicit-dev" and third.access_token == "explicit-token"


@pytest.mark.asyncio
async def test_token_refresh_is_persisted(agent_db):
    agent_db.save_device_credentials(device_id="d1", child_id="c1", access_token="old",
                                     refresh_token="r1", server_url=SERVER_URL)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"access_token": "new-token", "token_type": "bearer", "expires_in_sec": 900})

    agent = AgentServerClient(server_url=SERVER_URL, db=agent_db,
                              http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await agent.refresh_access_token() is True
    assert seen["body"] == {"refresh_token": "r1"}
    assert agent_db.get_device_credentials()["access_token"] == "new-token"
    assert agent_db.get_device_credentials()["refresh_token"] == "r1"


def test_agent_db_credentials_roundtrip_and_partial_update(agent_db):
    assert agent_db.get_device_credentials() is None
    agent_db.save_device_credentials(device_id="d", child_id="c", access_token="a", refresh_token="r",
                                     server_url="https://127.0.0.1:8000", offline_pin_hash="h")
    agent_db.save_device_credentials(access_token="a2")
    creds = agent_db.get_device_credentials()
    assert (creds["device_id"], creds["access_token"], creds["offline_pin_hash"]) == ("d", "a2", "h")
    with pytest.raises(ValueError):
        agent_db.save_device_credentials(password="nope")
    agent_db.clear_device_credentials()
    assert agent_db.get_device_credentials() is None


# --------------------------------------------------------------------------- enroll CLI
def _signed_policy(child_id: str, secret: str) -> dict:
    policy = {
        "child_id": child_id, "version": 4,
        "daily_limit_weekday_min": 90, "daily_limit_weekend_min": 120,
        "schedule_matrix_7x48": "1" * 336,
        "category_budgets_json": json.dumps({"gaming": 45}),
        "app_rules_json": json.dumps([{"exe_name": "notepad.exe", "category": "education", "action": "allow"}]),
        "domain_rules_json": json.dumps([{"domain": "blocked-site.test", "category": "inappropriate", "action": "block"}]),
        "updated_at_utc": "2026-11-17T00:00:00+00:00",
    }
    policy["signature"] = calculate_policy_signature(policy, secret)
    return policy


def test_cli_enroll_with_mocked_http(tmp_path, capsys):
    secret = "cli-test-policy-secret"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "device_id": "dev-cli-1", "child_id": "child-cli-1",
            "access_token": "ACCESS-SECRET", "refresh_token": "REFRESH-SECRET",
            "policy_hmac_secret": secret, "offline_pin_hash": None,
            "policy": _signed_policy("child-cli-1", secret),
        })

    db_path = tmp_path / "ogk" / "agent.db"
    rc = win_service.run_enroll_cli(
        code="abcd2345", server_url="https://127.0.0.1:8000", db_path=db_path,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert rc == 0
    assert seen["url"] == "https://127.0.0.1:8000/api/v1/enroll"
    # Exactly the fields of server DeviceEnrollRequest (extra="forbid")
    assert set(seen["body"]) == {"pairing_code", "device_name", "device_fingerprint"}
    assert seen["body"]["pairing_code"] == "ABCD2345"
    assert 1 <= len(seen["body"]["device_name"]) <= 100
    assert 10 <= len(seen["body"]["device_fingerprint"]) <= 64

    db = AgentDatabase(db_path)
    creds = db.get_device_credentials()
    assert creds["device_id"] == "dev-cli-1" and creds["child_id"] == "child-cli-1"
    assert creds["server_url"] == "https://127.0.0.1:8000"
    assert db.get_cached_policy()["version"] == 4

    out = capsys.readouterr().out
    assert "dev-cli-1" in out
    assert "ACCESS-SECRET" not in out and "REFRESH-SECRET" not in out and secret not in out


def test_cli_enroll_failure_and_argument_parsing(tmp_path, monkeypatch):
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "expired"})

    db_path = tmp_path / "agent.db"
    rc = win_service.run_enroll_cli(code="ABCD2345", server_url=SERVER_URL, db_path=db_path,
                                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(reject)))
    assert rc == 1
    assert AgentDatabase(db_path).get_device_credentials() is None

    # Malformed code never reaches the network
    assert win_service.run_enroll_cli(code="short", server_url=SERVER_URL, db_path=db_path) == 2

    # `win_service.py enroll --code X --server URL` is routed to run_enroll_cli
    calls = {}
    monkeypatch.setattr(win_service, "run_enroll_cli", lambda **kw: calls.update(kw) or 0)
    assert win_service.main(["enroll", "--code", "ABCD2345", "--server", "https://127.0.0.1:8000"]) == 0
    assert calls["code"] == "ABCD2345" and calls["server_url"] == "https://127.0.0.1:8000"


# --------------------------------------------------------------------------- urgent command HMAC
@pytest.mark.asyncio
async def test_agent_verifies_urgent_command_signature():
    mgr = ScreenTimeManager()
    agent = AgentServerClient(server_url=SERVER_URL, device_id="d1", child_id="c1",
                              device_secret=policy_service.POLICY_SECRET, screen_time_mgr=mgr)

    signed = await command_hub.send_command("dev-not-connected", "ADD_TIME_15M", {"bonus_seconds": 900})
    assert agent.verify_command_signature(signed) is True
    assert await agent.handle_command_envelope(signed) is True
    assert mgr.bonus_sec == 900
    # Heartbeat re-delivers pending commands: the same command_id runs only once
    assert await agent.handle_command_envelope(signed) is False
    assert mgr.bonus_sec == 900

    forged = dict(signed, command_id="cmd_forged", params={"bonus_seconds": 36000})
    assert await agent.handle_command_envelope(forged) is False
    unsigned = {"msg_type": "URGENT_COMMAND", "command_id": "cmd_x", "command": "UNLOCK", "params": {}}
    mgr.set_manual_lock(True)
    assert await agent.handle_command_envelope(unsigned) is False
    assert mgr.manual_lock_active is True and mgr.bonus_sec == 900

    # A device holding a different key rejects the server's command
    stranger = AgentServerClient(server_url=SERVER_URL, device_secret="some-other-key", screen_time_mgr=ScreenTimeManager())
    fresh = await command_hub.send_command("dev-not-connected", "LOCK_NOW", {})
    assert await stranger.handle_command_envelope(fresh) is False
    command_hub.pending_commands.pop("dev-not-connected", None)


# --------------------------------------------------------------------------- event subject
@pytest.mark.parametrize("bad", [
    "example.com/path", "example.com?q=1", "a.com&b=1", "C:\\Games\\game.exe", "site.test#frag",
])
def test_event_subject_rejects_url_and_path_characters(bad, agent_db):
    with pytest.raises(ValueError):
        normalize_subject(bad, "domain_query")
    buffer = EventBuffer(db=agent_db, device_id="d", child_id="c")
    with pytest.raises(ValueError):
        buffer.record_event("blocked_app", bad, policy_id="1")
    assert agent_db.get_unsynced_events() == []


@pytest.mark.asyncio
async def test_dns_block_answers_even_when_event_logging_fails(agent_db):
    engine = DomainPolicyEngine()
    engine.load_policy([{"domain": "blocked-site.test", "category": "inappropriate", "action": "block"}])
    notices = []
    # Not enrolled: record_event raises ValueError (no device_id / child_id)
    proxy = DnsProxyServer(engine=engine, event_buffer=EventBuffer(db=agent_db),
                           on_blocked_callback=lambda subject, reason: notices.append(subject))

    raw = await proxy.process_dns_query(DNSRecord.question("www.blocked-site.test").pack())
    assert raw is not None
    reply = DNSRecord.parse(raw)
    assert str(reply.rr[0].rdata) == "0.0.0.0"
    assert notices == ["blocked-site.test"]


# --------------------------------------------------------------------------- offline PIN
def test_no_hardcoded_parent_pin(tmp_path):
    core = make_core(tmp_path)
    assert core._verify_parent_pin("1234") is False     # nothing configured -> nothing unlocks
    assert core.screen_time_mgr.bonus_sec == 0
    assert verify_pin_hash("1234", None) is False
    assert verify_pin_hash("1234", "not-a-hash") is False


def test_parent_pin_checked_against_stored_hash_with_lockout(tmp_path):
    core = make_core(tmp_path)
    core.db.save_device_credentials(device_id="d1", child_id="c1", access_token="a", refresh_token="r",
                                    server_url=SERVER_URL, offline_pin_hash=FAST_HASHER.hash("4821"))
    core.server_client.load_saved_credentials()

    assert core._verify_parent_pin("1234") is False
    assert core._verify_parent_pin("4821") is True
    assert core.screen_time_mgr.bonus_sec == 900
    events = core.db.get_unsynced_events()
    assert [(e["type"], e["subject"], e["duration_sec"]) for e in events] == [("override_granted", "system", 900)]

    for _ in range(win_service.PIN_MAX_FAILURES):
        assert core._verify_parent_pin("0000") is False
    # Locked for 15 minutes: even the right PIN is refused now
    assert core._verify_parent_pin("4821") is False
    assert core.screen_time_mgr.bonus_sec == 900


def test_server_hashes_offline_pin_and_agent_receives_hash(server, tmp_path):
    client, SessionLocal = server
    headers, child_id = make_parent_and_child(client, SessionLocal)
    put = client.put(f"/api/v1/policy/{child_id}", headers=headers, json={"offline_pin": "4821"})
    assert put.status_code == 200, put.text
    pin_hash = put.json()["offline_pin_hash"]
    assert pin_hash.startswith("$argon2id$") and "4821" not in pin_hash
    assert verify_pin_hash("4821", pin_hash) is True
    assert verify_pin_hash("1234", pin_hash) is False

    code = new_pairing_code(client, headers, child_id)
    enrolled = client.post("/api/v1/enroll", json={
        "pairing_code": code, "device_name": "PC", "device_fingerprint": FINGERPRINT})
    assert enrolled.json()["offline_pin_hash"] == pin_hash
    assert client.put(f"/api/v1/policy/{child_id}", headers=headers, json={"offline_pin": "12"}).status_code == 422


def test_cleanup_rejects_default_and_wrong_pin(tmp_path, monkeypatch):
    # Safety net: this test must never reach the real restore code paths
    monkeypatch.setattr(ogk_cleanup.NetworkDnsGuard, "restore_original_dns", lambda self: True)
    monkeypatch.setattr(ogk_cleanup.BrowserPolicyGuard, "restore_browser_policies", lambda self: True)
    monkeypatch.setattr(ogk_cleanup, "flush_dns_cache", lambda: True)

    db_path = str(tmp_path / "agent.db")
    db = AgentDatabase(db_path)
    kwargs = dict(db_path=db_path, remove_service=False, delete_data_dir=False, force=False)

    # No PIN configured: the old built-in "1234" no longer works
    assert ogk_cleanup.perform_clean_rollback(parent_pin="1234", **kwargs) is False

    db.save_device_credentials(device_id="d", child_id="c", access_token="a", refresh_token="r",
                               server_url=SERVER_URL, offline_pin_hash=FAST_HASHER.hash("4821"))
    assert ogk_cleanup.perform_clean_rollback(parent_pin="1234", **kwargs) is False
    assert ogk_cleanup.perform_clean_rollback(parent_pin="4821", **kwargs) is True


# --------------------------------------------------------------------------- snapshots
def test_crash_restart_does_not_overwrite_original_snapshots(agent_db):
    original = [{"name": "Wi-Fi", "dhcp": False, "dns": ["192.168.1.1"]}]
    locked = [{"name": "Wi-Fi", "dhcp": False, "dns": ["127.0.0.1"]}]

    guard = NetworkDnsGuard(db=agent_db)
    guard._get_current_adapters_config = lambda: original
    assert guard.capture_and_save_snapshot() == original

    # Service crashed while DNS was locked; on restart the adapters show 127.0.0.1
    guard._get_current_adapters_config = lambda: locked
    assert guard.capture_and_save_snapshot() == original
    assert json.loads(agent_db.get_snapshot("NETWORK_DNS")["data_json"]) == original

    # After a clean restore a fresh snapshot is taken again
    agent_db.mark_snapshot_restored("NETWORK_DNS")
    changed = [{"name": "Wi-Fi", "dhcp": True, "dns": []}]
    guard._get_current_adapters_config = lambda: changed
    assert guard.capture_and_save_snapshot() == changed

    # Browser registry snapshot: an un-restored one is returned without re-reading anything
    original_reg = {"chrome": {"exists": True, "mode": "automatic", "templates": None}}
    agent_db.save_snapshot("BROWSER_REGISTRY", json.dumps(original_reg))
    assert BrowserPolicyGuard(db=agent_db).capture_and_save_snapshot() == original_reg
    assert json.loads(agent_db.get_snapshot("BROWSER_REGISTRY")["data_json"]) == original_reg


# --------------------------------------------------------------------------- no stealth mode
def test_tray_spawned_but_never_ready_leads_to_unprotected_halt(tmp_path):
    core = make_core(tmp_path)
    core.screen_time_mgr.set_manual_lock(True)
    launcher = SessionAgentLauncher(on_unprotected_halt_callback=core._handle_unprotected_halt,
                                    max_launch_attempts=3, ready_timeout_sec=0.0)
    core.session_launcher = launcher
    spawns = []

    def fake_spawn():
        # CreateProcessAsUser "succeeds", but the tray never sends TRAY_READY
        import time as _t
        spawns.append(1)
        launcher.awaiting_ready_since = _t.monotonic() - 1.0
        return True

    launcher._launch_into_active_session = fake_spawn

    for _ in range(3):
        launcher.last_launch_time = 0.0
        launcher.trigger_launch_if_needed()
        assert launcher.is_unprotected_halt is False
    launcher.last_launch_time = 0.0
    assert launcher.trigger_launch_if_needed() is False

    assert len(spawns) == 3
    assert launcher.is_unprotected_halt is True
    # Halt releases the DNS lock AND the browser DoH policy, and lifts locks
    core.net_guard.restore_original_dns.assert_called_once()
    core.browser_guard.restore_browser_policies.assert_called_once()
    assert core.screen_time_mgr.manual_lock_active is False
    status = core._get_session_status()
    assert status["unprotected_halt"] is True and status["is_locked"] is False

    # No further tray launches while halted
    launcher.last_launch_time = 0.0
    assert launcher.trigger_launch_if_needed() is False
    assert len(spawns) == 3


def test_waiting_for_tray_ready_does_not_spawn_duplicates_or_count_failures():
    launcher = SessionAgentLauncher(max_launch_attempts=3, ready_timeout_sec=60.0)
    spawns = []

    def fake_spawn():
        import time as _t
        spawns.append(1)
        launcher.awaiting_ready_since = _t.monotonic()
        return True

    launcher._launch_into_active_session = fake_spawn
    launcher.trigger_launch_if_needed()
    for _ in range(5):
        launcher.last_launch_time = 0.0
        assert launcher.trigger_launch_if_needed() is False
    assert len(spawns) == 1 and launcher.consecutive_failed_attempts == 0

    launcher.mark_tray_ready()
    assert launcher.awaiting_ready_since is None
    assert launcher.trigger_launch_if_needed() is True


# --------------------------------------------------------------------------- certificate pinning (F5)
@pytest.mark.asyncio
async def test_certificate_pin_accepts_matching_and_rejects_other_certificates():
    from agent.sync.server_client import CertificatePinError

    good_der, bad_der = b"pinned-server-cert-der", b"attacker-cert-der"
    pin = ":".join(f"{b:02X}" for b in hashlib.sha256(good_der).digest())   # setup_lab.py format
    client = AgentServerClient(server_url="https://ogk.lab:8443", pinned_cert_fingerprint=pin)

    client._fetch_peer_cert_der = lambda host, port: good_der
    await client.enforce_certificate_pin()          # matches: no error

    client._fetch_peer_cert_der = lambda host, port: bad_der
    with pytest.raises(CertificatePinError):
        await client.enforce_certificate_pin()
    with pytest.raises(CertificatePinError):
        await client.get_http_client()              # no connection pool is created either
    assert client._http_client is None


@pytest.mark.asyncio
async def test_certificate_pin_reads_env_and_skips_plain_http(monkeypatch):
    monkeypatch.setenv("OGK_PINNED_CERT_FINGERPRINT", "ab" * 32)
    client = AgentServerClient(server_url="http://127.0.0.1:8000")
    assert client.pinned_cert_fingerprint == "ab" * 32
    client._fetch_peer_cert_der = lambda host, port: pytest.fail("must not dial TLS for http://")
    await client.enforce_certificate_pin()
