"""Tests for Agent IPC Protocol, Service Lifecycle, Tray UI, and Cleanup Rollback (FR-F4-05, FR-F5-07, FR-F5-09)."""
import os
import tempfile
import pytest
from unittest.mock import MagicMock

from agent.core.agent_db import AgentDatabase
from agent.ipc.pipe_protocol import IpcEnvelope, ChallengeManager, IpcPipeHandler, IpcServer, IpcClient
from agent.service.session_launcher import SessionAgentLauncher
from agent.ui.tray_app import create_tray_icon_image, TrayApplication
from agent.cleanup.ogk_cleanup import perform_clean_rollback


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AgentDatabase(path)
    # Save dummy snapshots
    db.save_snapshot("NETWORK_DNS", '[{"name": "Wi-Fi", "dhcp": true, "dns": []}]')
    db.save_snapshot("BROWSER_REGISTRY", '{"chrome": {"exists": false}}')
    yield db, path
    if os.path.exists(path):
        os.remove(path)


# 1. Named Pipe IPC Protocol Tests
def test_ipc_envelope_pack_unpack():
    env = IpcEnvelope(
        msg_type="GET_SESSION_STATUS",
        payload={"query": "test"},
        caller_sid="S-1-5-21-1234",
    )
    packed_bytes = env.pack()

    # Verify 4-byte prefix length
    assert len(packed_bytes) > 4
    import struct
    payload_len = struct.unpack("<I", packed_bytes[:4])[0]
    assert payload_len == len(packed_bytes) - 4

    # Unpack
    unpacked = IpcEnvelope.unpack(packed_bytes[4:])
    assert unpacked.type == "GET_SESSION_STATUS"
    assert unpacked.caller_sid == "S-1-5-21-1234"
    assert unpacked.payload == {"query": "test"}


def test_challenge_manager_ttl():
    mgr = ChallengeManager(ttl_seconds=0.2)
    token = mgr.generate_challenge()
    assert token is not None

    # Immediate consumption should succeed
    assert mgr.validate_and_consume(token) is True
    # Replay consumption should fail
    assert mgr.validate_and_consume(token) is False

    # Expired token test
    token2 = mgr.generate_challenge()
    import time
    time.sleep(0.3)
    assert mgr.validate_and_consume(token2) is False


def test_ipc_pipe_handler_flow():
    handler = IpcPipeHandler(
        get_status_fn=lambda: {"remaining_sec": 1200},
        verify_pin_fn=lambda pin: pin == "9999",
    )

    # 1. Status request
    req_status = IpcEnvelope(msg_type="GET_SESSION_STATUS")
    resp_status = handler.handle_envelope(req_status)
    assert resp_status.type == "SESSION_STATUS_RESPONSE"
    assert resp_status.payload["remaining_sec"] == 1200

    # 2. Challenge issue
    req_chal = IpcEnvelope(msg_type="GET_CHALLENGE")
    resp_chal = handler.handle_envelope(req_chal)
    assert resp_chal.type == "CHALLENGE_ISSUED"
    token = resp_chal.payload["challenge_token"]

    # 3. Verify PIN with valid challenge
    req_pin = IpcEnvelope(
        msg_type="VERIFY_PARENT_PIN",
        challenge_token=token,
        payload={"pin": "9999"}
    )
    resp_pin = handler.handle_envelope(req_pin)
    assert resp_pin.type == "VERIFY_PARENT_PIN_RESPONSE"
    assert resp_pin.payload["valid"] is True

    # 4. Attempt PIN verify without challenge -> error
    req_pin_no_chal = IpcEnvelope(
        msg_type="VERIFY_PARENT_PIN",
        payload={"pin": "9999"}
    )
    resp_err = handler.handle_envelope(req_pin_no_chal)
    assert resp_err.type == "AUTH_ERROR"

    # 5. UNINSTALL_AUTH with valid challenge
    token2 = handler.challenge_mgr.generate_challenge()
    handler.verify_uninstall_fn = lambda s: s == "secret123"
    req_un = IpcEnvelope(
        msg_type="UNINSTALL_AUTH",
        challenge_token=token2,
        payload={"password_or_pin": "secret123"}
    )
    resp_un = handler.handle_envelope(req_un)
    assert resp_un.type == "UNINSTALL_AUTH_RESPONSE"
    assert resp_un.payload["authorized"] is True


def test_ipc_server_client_roundtrip():
    handler = IpcPipeHandler(
        get_status_fn=lambda: {"used_total_sec": 300},
        verify_uninstall_fn=lambda secret: secret == "ParentAdminPass!",
    )
    server = IpcServer(handler=handler, use_socket_fallback=True, port=0)
    server.start()
    client = IpcClient(port=server.port, prefer_pipe=False)

    try:
        # Request status
        req = IpcEnvelope(msg_type="GET_SESSION_STATUS")
        resp = client.send_request(req)
        assert resp is not None
        assert resp.type == "SESSION_STATUS_RESPONSE"
        assert resp.payload["used_total_sec"] == 300

        # Request challenge
        req_c = IpcEnvelope(msg_type="GET_CHALLENGE")
        resp_c = client.send_request(req_c)
        assert resp_c is not None
        token = resp_c.payload["challenge_token"]

        # Request UNINSTALL_AUTH with valid challenge
        req_un = IpcEnvelope(
            msg_type="UNINSTALL_AUTH",
            challenge_token=token,
            payload={"password_or_pin": "ParentAdminPass!"}
        )
        resp_un = client.send_request(req_un)
        assert resp_un is not None
        assert resp_un.type == "UNINSTALL_AUTH_RESPONSE"
        assert resp_un.payload["authorized"] is True
    finally:
        server.stop()


# 2. Session Launcher & No-Stealth-Mode Guardrail Tests
def test_session_launcher_unprotected_halt_guardrail():
    halt_called = [False]

    def on_halt():
        halt_called[0] = True

    launcher = SessionAgentLauncher(
        on_unprotected_halt_callback=on_halt,
        max_launch_attempts=3
    )

    # Mock _launch_into_active_session to simulate 3 consecutive failures
    launcher._launch_into_active_session = MagicMock(return_value=False)

    # Attempt 1
    assert launcher.trigger_launch_if_needed() is False
    assert launcher.consecutive_failed_attempts == 1
    assert launcher.is_unprotected_halt is False

    launcher.last_launch_time = 0.0  # bypass 3s throttle for test
    # Attempt 2
    assert launcher.trigger_launch_if_needed() is False
    assert launcher.consecutive_failed_attempts == 2
    assert launcher.is_unprotected_halt is False

    launcher.last_launch_time = 0.0
    # Attempt 3 -> triggers UNPROTECTED_HALT!
    assert launcher.trigger_launch_if_needed() is False
    assert launcher.consecutive_failed_attempts == 3
    assert launcher.is_unprotected_halt is True
    assert halt_called[0] is True

    # When Tray reconnects, halt is cleared
    launcher.mark_tray_ready()
    assert launcher.is_unprotected_halt is False
    assert launcher.consecutive_failed_attempts == 0


# 3. Tray App UI & Icon Generation Tests
def test_tray_app_icon_generation():
    for state in ("active", "warning", "locked", "paused"):
        img = create_tray_icon_image(state)
        assert img is not None
        assert img.size == (64, 64)
        assert img.mode == "RGBA"


def test_tray_app_headless_dialogs():
    app = TrayApplication(headless=True)
    # Headless calls should not raise or block
    app.show_warning_dialog("Nhắc nhở", "Còn 10 phút nhé!")
    app.show_grace_countdown_dialog()
    app.show_transparency_screen()
    app.show_block_explanation("game.exe", "Đang trong giờ học")
    app.show_eye_break_reminder()


# 4. Clean Rollback Tests
def test_clean_rollback_with_force(temp_db):
    db, path = temp_db
    success = perform_clean_rollback(
        db_path=path,
        remove_service=False,
        delete_data_dir=False,
        force=True
    )
    assert success is True
    # Snapshot restored_at should be recorded
    row = db.get_snapshot("NETWORK_DNS")
    assert row is not None
    assert row["restored_at_utc"] is not None
