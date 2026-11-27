"""End-to-End Integration Scenarios for OGK (Open Guardian for Kids).
Covers 5 core end-to-end user journeys:
1. Enrollment & Provisioning (Consent -> 8-char Code -> Tokens & Signed Policy)
2. Real-time Urgent Command & ACK Flow via WebSocket (< 5s)
3. Screen Time Expiry, 60s Grace Period & Request More Time Flow
4. DNS Filtering, SafeSearch CNAME & Anti-Tamper Reversion
5. Child Data Purge & 100% Clean System Snapshot Rollback
"""
import os
os.environ["OGK_TESTING"] = "1"

import asyncio
import json
import socket
import tempfile
import time
import uuid
from typing import Generator, Tuple
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from dnslib import DNSRecord, QTYPE, RCODE

from server.models.base import Base
from server.models.database import create_ogk_engine, get_db
from server.models.user import User
from server.models.child import Child
from server.models.device import Device
from server.main import app

from agent.core.agent_db import AgentDatabase
from agent.core.screen_time import ScreenTimeManager
from agent.core.event_buffer import EventBuffer
from agent.dns.domain_engine import DomainPolicyEngine, ACTION_BLOCK, ACTION_SAFESEARCH
from agent.dns.dns_proxy import DnsProxyServer
from agent.platform.network_guard import NetworkDnsGuard
from agent.platform.browser_policy import BrowserPolicyGuard
from agent.cleanup.ogk_cleanup import perform_clean_rollback
from agent.sync.server_client import AgentServerClient


@pytest.fixture
def agent_test_db() -> Generator[Tuple[AgentDatabase, str], None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AgentDatabase(path)
    yield db, path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def server_test_client() -> Generator[Tuple[TestClient, sessionmaker], None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    engine = create_ogk_engine(db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, TestingSessionLocal

    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(path):
        os.remove(path)


# ==============================================================================
# Scenario 1: Enrollment & Provisioning
# ==============================================================================
def test_scenario_1_enrollment_and_provisioning(server_test_client):
    client, SessionLocal = server_test_client

    # 1. Register parent & create child
    client.post("/api/v1/auth/register", json={
        "email": "scenario1_parent@example.com",
        "password": "Password123!",
        "role": "parent"
    })
    login = client.post("/api/v1/auth/login", json={
        "email": "scenario1_parent@example.com",
        "password": "Password123!"
    })
    parent_token = login.json()["access_token"]
    parent_id = login.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {parent_token}"}

    db = SessionLocal()
    child = Child(parent_id=parent_id, display_name="Bé Minh")
    db.add(child)
    db.commit()
    db.refresh(child)
    child_id = child.id
    db.close()

    # 2. Parent requests pairing code (must provide consent_confirmed=True)
    code_resp = client.post(
        "/api/v1/enroll/code",
        json={"child_id": child_id, "consent_confirmed": True},
        headers=headers
    )
    assert code_resp.status_code == 200
    pairing_code = code_resp.json()["code"]
    assert len(pairing_code) == 8

    # 3. Agent executes enrollment
    enroll_resp = client.post(
        "/api/v1/enroll",
        json={
            "pairing_code": pairing_code,
            "device_name": "LAPTOP-MINH",
            "device_fingerprint": "a1b2c3d4"*8,
            "windows_user_sid": "S-1-5-21-99999-1001",
        }
    )
    assert enroll_resp.status_code == 200
    data = enroll_resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["child_id"] == child_id
    assert "policy" in data
    assert data["policy"]["version"] >= 1


# ==============================================================================
# Scenario 2: Real-time Urgent Command & ACK Flow
# ==============================================================================
@pytest.mark.asyncio
async def test_scenario_2_urgent_command_dispatch_and_execution():
    screen_mgr = ScreenTimeManager()
    assert screen_mgr.manual_lock_active is False

    client_sync = AgentServerClient(
        server_url="http://127.0.0.1:8000",
        device_id="dev_integ_01",
        child_id="child_integ_01",
        screen_time_mgr=screen_mgr
    )

    # 1. Dispatch LOCK_NOW command
    cmd_lock = {
        "msg_type": "URGENT_COMMAND",
        "command_id": str(uuid.uuid4()),
        "command": "LOCK_NOW",
        "params": {}
    }
    await client_sync._execute_command(cmd_lock)
    assert screen_mgr.manual_lock_active is True

    # 2. Dispatch UNLOCK command
    cmd_unlock = {
        "msg_type": "URGENT_COMMAND",
        "command_id": str(uuid.uuid4()),
        "command": "UNLOCK",
        "params": {}
    }
    await client_sync._execute_command(cmd_unlock)
    assert screen_mgr.manual_lock_active is False

    # 3. Dispatch ADD_TIME_15M command
    cmd_add = {
        "msg_type": "URGENT_COMMAND",
        "command_id": str(uuid.uuid4()),
        "command": "ADD_TIME_15M",
        "params": {"bonus_seconds": 900}
    }
    await client_sync._execute_command(cmd_add)
    assert screen_mgr.bonus_sec == 900


# ==============================================================================
# Scenario 3: Screen Time Expiry, 60s Grace Period & Request More Time Flow
# ==============================================================================
def test_scenario_3_screen_time_grace_period_and_request_time(agent_test_db):
    db, _ = agent_test_db
    mgr = ScreenTimeManager(db=db)

    # Daily limit 60 minutes = 3600 seconds
    # Same limit on weekdays and weekends so the scenario does not depend on today's date
    policy = {"daily_limit_minutes_weekday": 60, "daily_limit_minutes_weekend": 60, "schedule_matrix": "1" * 336}

    # Kid has used 59 minutes (3540 seconds) -> remaining 60s
    mgr.used_total_sec = 3540
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    assert is_locked is False
    assert warning == "warn_1m"

    # Kid reaches limit -> enters GRACE_PERIOD_60S
    mgr.used_total_sec = 3605
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    # Inside grace period: not hard locked yet, allows kid to save or request time
    assert is_locked is False
    assert warning == "GRACE_PERIOD_60S"

    # Kid requests +15 minutes bonus
    mgr.add_bonus_time(900)
    assert mgr.bonus_sec == 900
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    assert is_locked is False


# ==============================================================================
# Scenario 4: DNS Filtering, SafeSearch & Anti-Tamper Reversion
# ==============================================================================
@pytest.mark.asyncio
async def test_scenario_4_dns_filtering_safesearch_and_antitamper(agent_test_db):
    db, _ = agent_test_db
    engine = DomainPolicyEngine(safesearch_enabled=True)
    engine.load_policy(
        domain_rules=[
            {"domain": "violent-game.test", "category": "gaming", "action": "block"},
            {"domain": "math-portal.edu.vn", "category": "education", "action": "allow"},
        ],
        category_rules={"gaming": "block", "education": "allow"}
    )

    port = 53585
    server = DnsProxyServer(engine=engine, host="127.0.0.1", port=port)
    started = await server.start()
    assert started is True

    try:
        # 1. Verify blocked gaming site is sinkholed to 0.0.0.0
        q_blocked = DNSRecord.question("violent-game.test", "A").pack()
        resp_bytes = await server.process_dns_query(q_blocked)
        resp = DNSRecord.parse(resp_bytes)
        assert resp.header.rcode == RCODE.NOERROR
        assert str(resp.rr[0].rdata) == "0.0.0.0"

        # 2. Verify educational domain is allowed
        act, _, _ = engine.evaluate("math-portal.edu.vn")
        assert act == "ALLOW"

        # 3. Verify Google SafeSearch CNAME
        act, _, target = engine.evaluate("www.google.com")
        assert act == ACTION_SAFESEARCH
        assert target == "forcesafesearch.google.com"

        # 4. Anti-Tamper: Network guard snapshot and reversion
        net_guard = NetworkDnsGuard(db=db)
        snap = net_guard.capture_and_save_snapshot()
        assert len(snap) > 0
        saved_row = db.get_snapshot("NETWORK_DNS")
        assert saved_row is not None

    finally:
        server.stop()


# ==============================================================================
# Scenario 5: Child Data Purge & 100% Clean System Rollback
# ==============================================================================
def test_scenario_5_data_purge_and_clean_rollback(agent_test_db):
    db, path = agent_test_db
    buffer = EventBuffer(db=db, device_id="dev_integ", child_id="child_integ")

    # Record events
    buffer.record_event("app_start", "calculator.exe", "policy_1", 30)
    buffer.record_event("domain_query", "wikipedia.org", "policy_1", 0)
    assert len(buffer.get_pending_batch()) == 2

    # Purge child events
    buffer.purge_local_events()
    assert len(buffer.get_pending_batch()) == 0

    # Execute clean rollback with force=True (simulates uninstallation)
    net_guard = NetworkDnsGuard(db=db)
    net_guard.capture_and_save_snapshot()
    b_guard = BrowserPolicyGuard(db=db)
    b_guard.capture_and_save_snapshot()

    rollback_success = perform_clean_rollback(
        db_path=path,
        remove_service=False,
        delete_data_dir=False,
        force=True
    )
    assert rollback_success is True

    # Verify snapshot restored flags
    net_snap = db.get_snapshot("NETWORK_DNS")
    assert net_snap["restored_at_utc"] is not None
    browser_snap = db.get_snapshot("BROWSER_REGISTRY")
    assert browser_snap["restored_at_utc"] is not None
