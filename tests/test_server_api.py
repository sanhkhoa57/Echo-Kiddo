"""Integration and API tests for OGK-Server (Auth, Lockout, Anti-IDOR, Enrollment, Policy, Events, WebSocket)."""
import os
os.environ["OGK_TESTING"] = "1"

import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.models.base import Base
from server.models.database import create_ogk_engine, get_db
from server.models.user import User
from server.models.child import Child
from server.models.device import Device
from server.models.event import Event
from server.main import app
from server.services.policy_service import verify_policy_signature


@pytest.fixture
def test_app_and_db():
    """Sets up a clean test database and FastAPI TestClient."""
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


def test_parent_registration_and_login(test_app_and_db):
    """Verify parent registration with >= 10 chars password and login with cookie/tokens."""
    client, _ = test_app_and_db

    # 1. Reject password < 10 chars
    res_short = client.post("/api/v1/auth/register", json={
        "email": "parent@example.com",
        "password": "short",
        "role": "parent"
    })
    assert res_short.status_code == 422 or res_short.status_code == 400

    # 2. Register valid parent
    res_reg = client.post("/api/v1/auth/register", json={
        "email": "parent@example.com",
        "password": "SecurePassword123!",
        "role": "parent"
    })
    assert res_reg.status_code == 201
    assert res_reg.json()["email"] == "parent@example.com"

    # 3. Login success
    res_login = client.post("/api/v1/auth/login", json={
        "email": "parent@example.com",
        "password": "SecurePassword123!"
    })
    assert res_login.status_code == 200
    data = res_login.json()
    assert "access_token" in data
    assert "csrf_token" in data
    assert "ogk_session" in res_login.cookies


def test_lockout_after_5_failed_attempts(test_app_and_db):
    """Verify 15-minute account lockout after 5 consecutive failed logins."""
    client, _ = test_app_and_db

    # Register parent
    client.post("/api/v1/auth/register", json={
        "email": "victim@example.com",
        "password": "CorrectPassword123!",
        "role": "parent"
    })

    # Fail 4 times (returns 401)
    for i in range(4):
        res = client.post("/api/v1/auth/login", json={
            "email": "victim@example.com",
            "password": "WrongPassword!"
        })
        assert res.status_code == 401
        assert "lần thử" in res.json()["detail"]

    # 5th failure -> returns 423 Locked
    res_5th = client.post("/api/v1/auth/login", json={
        "email": "victim@example.com",
        "password": "WrongPassword!"
    })
    assert res_5th.status_code == 423
    assert "tạm khóa 15 phút" in res_5th.json()["detail"]

    # 6th attempt even with correct password is still locked (423)
    res_locked = client.post("/api/v1/auth/login", json={
        "email": "victim@example.com",
        "password": "CorrectPassword123!"
    })
    assert res_locked.status_code == 423


def test_anti_idor_protection(test_app_and_db):
    """Verify that Parent B cannot access or modify Child A (returns 404)."""
    client, SessionLocal = test_app_and_db

    # Parent A & Child A
    res_a = client.post("/api/v1/auth/register", json={
        "email": "parentA@example.com",
        "password": "Password123A!",
        "role": "parent"
    })
    parent_a_id = res_a.json()["id"]

    db = SessionLocal()
    child_a = Child(parent_id=parent_a_id, display_name="Child A")
    db.add(child_a)
    db.commit()
    db.refresh(child_a)
    child_a_id = child_a.id
    db.close()

    # Parent B login
    client.post("/api/v1/auth/register", json={
        "email": "parentB@example.com",
        "password": "Password123B!",
        "role": "parent"
    })
    login_b = client.post("/api/v1/auth/login", json={
        "email": "parentB@example.com",
        "password": "Password123B!"
    })
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Parent B attempts to access Child A's policy -> MUST BE REJECTED 404 (Anti-IDOR)
    res_policy = client.get(f"/api/v1/policy/{child_a_id}", headers=headers_b)
    assert res_policy.status_code == 404

    # Parent B attempts to update Child A's policy -> MUST BE REJECTED 404
    res_update = client.put(f"/api/v1/policy/{child_a_id}", json={"daily_limit_weekday_min": 30}, headers=headers_b)
    assert res_update.status_code == 404

    # Parent B attempts to send command to Child A -> MUST BE REJECTED 404
    res_cmd = client.post("/api/v1/commands", json={"child_id": child_a_id, "command": "LOCK_NOW"}, headers=headers_b)
    assert res_cmd.status_code == 404

    # Parent B attempts to purge Child A's data -> MUST BE REJECTED 404
    res_purge = client.delete(f"/api/v1/privacy/children/{child_a_id}/events", headers=headers_b)
    assert res_purge.status_code == 404


def test_enrollment_and_token_refresh(test_app_and_db):
    """Verify pairing code generation, agent enrollment, token issuance, and refresh."""
    client, SessionLocal = test_app_and_db

    # Register parent & child
    client.post("/api/v1/auth/register", json={
        "email": "parent_enroll@example.com",
        "password": "SecurePassword123!",
        "role": "parent"
    })
    login = client.post("/api/v1/auth/login", json={
        "email": "parent_enroll@example.com",
        "password": "SecurePassword123!"
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    db = SessionLocal()
    parent_id = login.json()["user"]["id"]
    child = Child(parent_id=parent_id, display_name="Baby An")
    db.add(child)
    db.commit()
    db.refresh(child)
    child_id = child.id
    db.close()

    # 1. Generate pairing code (requires consent_confirmed = True)
    res_code = client.post("/api/v1/enroll/code", json={
        "child_id": child_id,
        "consent_confirmed": True
    }, headers=headers)
    assert res_code.status_code == 200
    pairing_code = res_code.json()["code"]
    assert len(pairing_code) == 8

    # 2. Agent enrolls
    res_enroll = client.post("/api/v1/enroll", json={
        "pairing_code": pairing_code,
        "device_name": "LAPTOP-CHILD",
        "device_fingerprint": "f"*64,
        "windows_user_sid": "S-1-5-21-12345-1001"
    })
    assert res_enroll.status_code == 200
    enroll_data = res_enroll.json()
    device_id = enroll_data["device_id"]
    access_token = enroll_data["access_token"]
    refresh_token = enroll_data["refresh_token"]
    assert "policy" in enroll_data
    assert "signature" in enroll_data["policy"]

    # 3. Re-using pairing code must fail (400)
    res_reuse = client.post("/api/v1/enroll", json={
        "pairing_code": pairing_code,
        "device_name": "LAPTOP-CHILD-2",
        "device_fingerprint": "f"*64,
    })
    assert res_reuse.status_code == 400

    # 4. Agent refreshes access token
    res_refresh = client.post("/api/v1/auth/device/refresh", json={
        "refresh_token": refresh_token
    })
    assert res_refresh.status_code == 200
    new_access_token = res_refresh.json()["access_token"]
    assert new_access_token is not None

    # 5. Revoke device token -> refresh must return 403
    db = SessionLocal()
    dev = db.get(Device, device_id)
    dev.token_revoked = 1
    db.commit()
    db.close()

    res_revoked = client.post("/api/v1/auth/device/refresh", json={
        "refresh_token": refresh_token
    })
    assert res_revoked.status_code == 403


def test_policy_signing_and_verification(test_app_and_db):
    """Verify policy updates increment version, sign payload, and tamper-resistance."""
    client, SessionLocal = test_app_and_db

    # Register parent & child
    login = client.post("/api/v1/auth/register", json={
        "email": "parent_pol@example.com",
        "password": "Password123!",
        "role": "parent"
    })
    parent_id = login.json()["id"]
    login_res = client.post("/api/v1/auth/login", json={
        "email": "parent_pol@example.com",
        "password": "Password123!"
    })
    headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    db = SessionLocal()
    child = Child(parent_id=parent_id, display_name="Kid Policy")
    db.add(child)
    db.commit()
    db.refresh(child)
    child_id = child.id
    db.close()

    # Initial policy
    res_init = client.get(f"/api/v1/policy/{child_id}", headers=headers)
    assert res_init.status_code == 200
    init_data = res_init.json()
    assert init_data["version"] == 1
    assert init_data["signature"] is not None

    # Update policy (change weekday limit to 60)
    res_upd = client.put(f"/api/v1/policy/{child_id}", json={
        "daily_limit_weekday_min": 60
    }, headers=headers)
    assert res_upd.status_code == 200
    upd_data = res_upd.json()
    assert upd_data["version"] == 2
    assert upd_data["daily_limit_weekday_min"] == 60

    # Verify cryptographic signature
    payload_to_verify = {
        "child_id": child_id,
        "version": upd_data["version"],
        "daily_limit_weekday_min": upd_data["daily_limit_weekday_min"],
        "daily_limit_weekend_min": upd_data["daily_limit_weekend_min"],
        "schedule_matrix_7x48": upd_data["schedule_matrix_7x48"],
        "category_budgets_json": upd_data["category_budgets_json"],
        "app_rules_json": upd_data["app_rules_json"],
        "domain_rules_json": upd_data["domain_rules_json"],
        "updated_at_utc": upd_data["updated_at_utc"],
    }
    assert verify_policy_signature(payload_to_verify, upd_data["signature"]) is True

    # Tampering a single parameter must fail verification
    tampered_payload = payload_to_verify.copy()
    tampered_payload["daily_limit_weekday_min"] = 120  # Tampered!
    assert verify_policy_signature(tampered_payload, upd_data["signature"]) is False


def test_batch_events_idempotency_and_url_rejection(test_app_and_db):
    """Verify batch event ingestion deduplicates idempotency keys and rejects URL paths."""
    client, SessionLocal = test_app_and_db

    # Setup parent, child, device
    db = SessionLocal()
    user = User(email="parent_evt@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    child = Child(parent_id=user.id, display_name="Kid Evt")
    db.add(child)
    db.commit()
    device = Device(child_id=child.id, device_name="PC", fingerprint_hash="a"*64)
    db.add(device)
    db.commit()
    device_id = device.id
    child_id = child.id
    db.close()

    from server.auth.security import create_jwt_token
    from datetime import timedelta
    device_token = create_jwt_token(
        data={"sub": device_id, "child_id": child_id, "type": "device_access"},
        expires_delta=timedelta(minutes=15)
    )
    headers = {"Authorization": f"Bearer {device_token}"}

    # 1. Valid batch of 2 events
    batch_payload = {
        "events": [
            {
                "idempotency_key": "idemp_101",
                "ts": "2026-11-10T16:00:00Z",
                "device_id": device_id,
                "child_id": child_id,
                "type": "domain_query",
                "subject": "wikipedia.org",
                "duration_sec": 10,
                "policy_id": "pol_1"
            },
            {
                "idempotency_key": "idemp_102",
                "ts": "2026-11-10T16:01:00Z",
                "device_id": device_id,
                "child_id": child_id,
                "type": "app_start",
                "subject": "notepad.exe",
                "duration_sec": 0,
                "policy_id": "pol_1"
            }
        ]
    }
    res_batch = client.post("/api/v1/events/batch", json=batch_payload, headers=headers)
    assert res_batch.status_code == 200
    assert res_batch.json()["accepted_count"] == 2
    assert res_batch.json()["duplicate_count"] == 0

    # 2. Resending same batch -> must deduplicate (accepted: 0, duplicate: 2)
    res_resend = client.post("/api/v1/events/batch", json=batch_payload, headers=headers)
    assert res_resend.status_code == 200
    assert res_resend.json()["accepted_count"] == 0
    assert res_resend.json()["duplicate_count"] == 2

    # 3. Reject full URL path in subject (HTTP 422)
    bad_batch = {
        "events": [
            {
                "idempotency_key": "idemp_bad",
                "ts": "2026-11-10T16:02:00Z",
                "device_id": device_id,
                "child_id": child_id,
                "type": "domain_query",
                "subject": "youtube.com/watch?v=123",  # REJECTED!
                "duration_sec": 15,
                "policy_id": "pol_1"
            }
        ]
    }
    res_bad = client.post("/api/v1/events/batch", json=bad_batch, headers=headers)
    assert res_bad.status_code == 422


def test_websocket_command_dispatch_and_ack(test_app_and_db):
    """Verify WebSocket realtime command dispatch and COMMAND_ACK handling."""
    client, SessionLocal = test_app_and_db

    # Setup parent, child, device
    db = SessionLocal()
    user = User(email="parent_ws@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    child = Child(parent_id=user.id, display_name="Kid WS")
    db.add(child)
    db.commit()
    device = Device(child_id=child.id, device_name="PC-WS", fingerprint_hash="b"*64)
    db.add(device)
    db.commit()
    device_id = device.id
    child_id = child.id
    user_id = user.id
    db.close()

    from server.auth.security import create_jwt_token
    from datetime import timedelta
    parent_token = create_jwt_token(
        data={"sub": user_id, "email": "parent_ws@example.com", "role": "parent"},
        expires_delta=timedelta(hours=1)
    )
    device_token = create_jwt_token(
        data={"sub": device_id, "child_id": child_id, "type": "device_access"},
        expires_delta=timedelta(minutes=15)
    )

    # Connect WebSocket client (Agent)
    with client.websocket_connect(f"/ws/agent/{device_id}?token={device_token}") as ws:
        # Parent dispatches LOCK_NOW via REST API
        parent_headers = {"Authorization": f"Bearer {parent_token}"}
        res_cmd = client.post("/api/v1/commands", json={
            "child_id": child_id,
            "command": "LOCK_NOW"
        }, headers=parent_headers)
        assert res_cmd.status_code == 200

        # Agent receives URGENT_COMMAND via WebSocket
        received_msg = ws.receive_json()
        assert received_msg["msg_type"] == "URGENT_COMMAND"
        assert received_msg["command"] == "LOCK_NOW"
        assert "signature" in received_msg
        command_id = received_msg["command_id"]

        # Agent sends back COMMAND_ACK
        ws.send_json({
            "msg_type": "COMMAND_ACK",
            "command_id": command_id,
            "status": "EXECUTED",
            "executed_at_utc": "2026-11-10T16:05:00Z"
        })

        # Check pending queue in Heartbeat is now empty (since ACK was processed)
        dev_headers = {"Authorization": f"Bearer {device_token}"}
        hb_res = client.post("/api/v1/heartbeat", json={
            "used_sec": 120,
            "local_utc": "2026-11-10T16:05:00Z",
            "monotonic_sec": 300.0,
            "policy_version": 1
        }, headers=dev_headers)
        assert hb_res.status_code == 200
        assert len(hb_res.json()["pending_commands"]) == 0
