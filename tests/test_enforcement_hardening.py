"""Regression tests for enforcement fixes found while auditing against DoAn01.docx:
category budgets (-1 = unlimited), independent category counters, clock changes that
cross midnight, session-0 safety when locking, Tray -> Service activity reports,
real session lock, agent data ACL and the legal-uninstall event."""
import time
from datetime import datetime, timezone

import psutil
import pytest

from agent.core import app_controller as ac
from agent.core.agent_db import AgentDatabase, build_acl_command
from agent.core.app_controller import AppController
from agent.core.screen_time import ScreenTimeManager
from agent.ipc.pipe_protocol import IpcEnvelope, IpcPipeHandler
from agent.cleanup import ogk_cleanup
from agent.ui import tray_app


class _Proc:
    def __init__(self, pid, name, exe=""):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "exe": exe}

    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass

    def kill(self):
        pass


@pytest.fixture
def db(tmp_path):
    return AgentDatabase(tmp_path / "agent.db")


def _scan(monkeypatch, procs, **kwargs):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: procs)
    controller = AppController()
    return controller, controller.scan_and_enforce(dry_run=True, **kwargs)


# ---------------------------------------------------------------- F1 category budgets
def test_default_policy_budgets_never_kill_unlimited_or_unknown_apps(monkeypatch):
    """Seed policy uses -1 (= unlimited) for education/unclassified. Nothing may be killed."""
    budgets = {"education": -1, "unclassified": -1, "entertainment": 60, "gaming": 45, "social": 0}
    rules = [{"exe_name": "notepad.exe", "category": "education", "action": "allow"}]
    procs = [_Proc(101, "notepad.exe"), _Proc(102, "winword.exe"), _Proc(103, "someservice.exe")]
    _, violations = _scan(monkeypatch, procs, app_rules=rules, category_quotas=budgets, category_used={})
    assert violations == []


def test_category_budget_applies_only_to_classified_apps(monkeypatch):
    budgets = {"gaming": 45, "unclassified": 10}
    rules = [{"exe_name": "robloxplayerbeta.exe", "category": "gaming", "action": "allow"}]
    used = {"gaming": 46 * 60, "unclassified": 99 * 60}
    procs = [_Proc(201, "robloxplayerbeta.exe"), _Proc(202, "unknown_tool.exe")]
    _, violations = _scan(monkeypatch, procs, app_rules=rules, category_quotas=budgets, category_used=used)
    assert [v["name"] for v in violations] == ["robloxplayerbeta.exe"]
    assert "45 min" in violations[0]["reason"]


def test_screen_time_negative_budget_is_unlimited(db):
    mgr = ScreenTimeManager(db=db)
    mgr.category_used_sec = {"education": 10 * 3600}
    over, used, limit = mgr.is_category_over_budget("education", {"category_budgets": {"education": -1}})
    assert over is False and used == 36000 and limit == -1


def test_two_independent_counters_total_and_gaming(db, monkeypatch):
    """NÊN CÓ F1: the gaming budget counts only while a gaming app runs; the total always."""
    mgr = ScreenTimeManager(db=db, mock_idle_fn=lambda: 0.0)
    mgr.last_monotonic = time.monotonic() - 2.0
    mgr.tick(active_categories={"gaming"})
    mgr.last_monotonic = time.monotonic() - 3.0
    mgr.tick(active_categories=set())
    assert mgr.category_used_sec.get("gaming", 0) == 2
    assert mgr.used_total_sec == 5


def test_running_categories_reported_by_scan(monkeypatch):
    rules = [{"exe_name": "robloxplayerbeta.exe", "category": "gaming", "action": "allow"}]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [_Proc(301, "robloxplayerbeta.exe")])
    controller = AppController()
    controller.scan_and_enforce(app_rules=rules, category_quotas={"gaming": 45}, category_used={})
    assert controller.last_running_categories == {"gaming"}


# ---------------------------------------------------------------- lock safety
def test_global_lock_never_kills_session0_services(monkeypatch):
    monkeypatch.setattr(ac, "get_process_session_id", lambda pid: 0 if pid == 401 else 1)
    procs = [_Proc(401, "vendorservice.exe"), _Proc(402, "game_launcher.exe")]
    _, violations = _scan(monkeypatch, procs, app_rules=[], is_locked=True)
    assert [v["name"] for v in violations] == ["game_launcher.exe"]


# ---------------------------------------------------------------- F1 anti clock change
def test_clock_moved_across_midnight_does_not_reset_quota(db):
    """Moving the wall clock by a day (no matching elapsed time) never re-opens the quota."""
    mgr = ScreenTimeManager(db=db, mock_idle_fn=lambda: 0.0)
    mgr.used_total_sec = 3000
    mgr._last_wall_ts -= 26 * 3600      # wall clock and elapsed clock now disagree by 26 h
    mgr.tick()
    assert mgr.used_total_sec >= 3000
    assert mgr.clock_tampered_flag is True
    assert abs(mgr.wall_offset_sec) >= 26 * 3600 - 5
    assert mgr.pop_tamper_event() is True
    assert mgr.pop_tamper_event() is False


def test_schedule_uses_trusted_time_after_clock_change(db):
    """Setting the clock back 3 h into an allowed slot does not escape the 7x48 schedule."""
    mgr = ScreenTimeManager(db=db)
    mgr.wall_offset_sec = -3 * 3600     # local clock is 3 h behind the trusted time
    trusted = mgr.trusted_now()
    blocked_idx = trusted.weekday() * 48 + trusted.hour * 2 + (1 if trusted.minute >= 30 else 0)
    matrix = "1" * blocked_idx + "0" + "1" * (335 - blocked_idx)
    policy = {"daily_limit_minutes_weekday": 600, "daily_limit_minutes_weekend": 600, "schedule_matrix": matrix}
    locked, reason, _ = mgr.evaluate_lock_status(policy)
    assert locked is True and reason == "OUTSIDE_ALLOWED_SCHEDULE"


def test_server_time_resets_trusted_offset(db):
    mgr = ScreenTimeManager(db=db)
    mgr.wall_offset_sec = 5000
    drift, tampered = mgr.verify_clock_drift(datetime.now(timezone.utc).isoformat())
    assert tampered is False and mgr.wall_offset_sec == 0.0


# ---------------------------------------------------------------- Tray -> Service activity
def test_tray_activity_report_drives_idle_and_session_lock(db):
    mgr = ScreenTimeManager(db=db)
    handler = IpcPipeHandler(
        get_status_fn=lambda: {"ok": True},
        on_user_activity_fn=lambda p: mgr.report_user_activity(p.get("idle_sec"), p.get("session_locked")),
    )
    resp = handler.handle_envelope(IpcEnvelope(msg_type="GET_SESSION_STATUS",
                                               payload={"idle_sec": 400, "session_locked": False}))
    assert resp.payload == {"ok": True}
    assert mgr.get_idle_seconds() >= 400          # > 300 s idle: not counted

    mgr.used_total_sec = 0
    mgr.last_monotonic = time.monotonic() - 2.0
    mgr.tick()
    assert mgr.used_total_sec == 0

    handler.handle_envelope(IpcEnvelope(msg_type="GET_SESSION_STATUS",
                                        payload={"idle_sec": 1, "session_locked": True}))
    mgr.last_monotonic = time.monotonic() - 2.0
    mgr.tick()
    assert mgr.is_session_locked is True and mgr.used_total_sec == 0

    handler.handle_envelope(IpcEnvelope(msg_type="GET_SESSION_STATUS",
                                        payload={"idle_sec": 1, "session_locked": False}))
    mgr.last_monotonic = time.monotonic() - 2.0
    mgr.tick()
    assert mgr.used_total_sec == 2


def test_tray_locks_windows_on_hard_lock_but_not_in_grace(monkeypatch):
    calls = []
    monkeypatch.setattr(tray_app, "lock_workstation", lambda: calls.append(1) or True)
    monkeypatch.setattr(tray_app, "is_workstation_locked", lambda: False)
    app = tray_app.TrayApplication(ipc_client=object(), headless=False)
    app.show_grace_countdown_dialog = lambda: None
    app.show_block_explanation = lambda s, r: None

    app.apply_session_status({"is_locked": False, "lock_reason": "GRACE_PERIOD",
                              "warning": "GRACE_PERIOD_60S", "remaining_sec": 0})
    assert calls == []
    app.apply_session_status({"is_locked": True, "lock_reason": "DAILY_LIMIT_REACHED", "remaining_sec": 0})
    assert calls == [1]
    app.apply_session_status({"is_locked": True, "lock_reason": "OUTSIDE_ALLOWED_SCHEDULE", "remaining_sec": 0})
    assert calls == [1, 1]


# ---------------------------------------------------------------- F5 local privileges
def test_agent_data_acl_grants_only_system_and_administrators(tmp_path):
    cmd = build_acl_command(tmp_path)
    assert cmd[:3] == ["icacls", str(tmp_path), "/inheritance:r"]
    grants = [cmd[i + 1] for i, part in enumerate(cmd) if part == "/grant:r"]
    assert grants == ["*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]


# ---------------------------------------------------------------- F4 legal uninstall
def test_uninstall_event_uses_real_identity(db):
    db.save_device_credentials(device_id="dev-123", child_id="chd-456", access_token="a",
                               refresh_token="r", server_url="https://127.0.0.1:8000")
    ogk_cleanup.record_uninstall_event(db, upload=False)
    from agent.core.event_buffer import EventBuffer
    queued = EventBuffer(db=db).get_pending_batch()
    assert len(queued) == 1
    ev = queued[0]
    assert (ev["device_id"], ev["child_id"], ev["type"], ev["subject"]) == (
        "dev-123", "chd-456", "app_stop", ogk_cleanup.UNINSTALL_SUBJECT)


def test_force_uninstall_refused_for_standard_user(monkeypatch, tmp_path):
    monkeypatch.delenv("OGK_TESTING", raising=False)
    monkeypatch.setattr(ogk_cleanup, "_IS_WINDOWS", False)
    assert ogk_cleanup.perform_clean_rollback(db_path=str(tmp_path / "a.db"), force=True,
                                              remove_service=False) is False
