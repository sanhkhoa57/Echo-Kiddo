"""Unit Tests for OGK-Agent Core Components (FR-F1, FR-F2, FR-F3, M1, M3, M6)."""
import os
import time
import tempfile
from datetime import datetime, timezone, date
import pytest

from agent.core.agent_db import AgentDatabase
from agent.core.policy_verifier import verify_policy, calculate_policy_signature, canonical_policy_bytes
from agent.core.event_buffer import EventBuffer, normalize_subject
from agent.core.screen_time import ScreenTimeManager
from agent.core.app_controller import AppController, Sha256LruCache, WHITELISTED_SYSTEM_EXES
from agent.platform.network_guard import NetworkDnsGuard
from agent.platform.browser_policy import BrowserPolicyGuard
from agent.platform.bypass_detector import BypassDetector


@pytest.fixture
def temp_agent_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AgentDatabase(path)
    yield db
    if os.path.exists(path):
        os.remove(path)


# 1. Policy Verifier Tests
def test_policy_verifier_valid_and_tampered():
    secret = "test-secret-key-12345"
    policy_data = {
        "version": 1,
        "daily_limit_minutes_weekday": 90,
        "daily_limit_minutes_weekend": 120,
        "schedule_matrix": "1" * 336,
        "app_rules_json": "[]",
        "domain_rules_json": "[]",
    }
    # Calculate valid signature
    sig = calculate_policy_signature(policy_data, secret)
    policy_data["signature"] = sig

    is_valid, reason = verify_policy(policy_data, secret)
    assert is_valid is True
    assert reason == "OK"

    # Tampering test: change limit from 90 to 180 without updating signature
    tampered_data = dict(policy_data)
    tampered_data["daily_limit_minutes_weekday"] = 180

    is_valid, reason = verify_policy(tampered_data, secret)
    assert is_valid is False
    assert "tampering detected" in reason.lower()

    # Invalid matrix test
    invalid_matrix = dict(policy_data)
    invalid_matrix["schedule_matrix"] = "1" * 300  # only 300 chars instead of 336
    invalid_matrix["signature"] = calculate_policy_signature(invalid_matrix, secret)
    is_valid, reason = verify_policy(invalid_matrix, secret)
    assert is_valid is False
    assert "schedule_matrix" in reason


# 2. Event Buffer Tests
def test_event_buffer_strict_schema(temp_agent_db):
    buffer = EventBuffer(db=temp_agent_db, device_id="dev_001", child_id="child_001")

    # Valid event
    key = buffer.record_event(
        event_type="app_start",
        subject="notepad.exe",
        policy_id="pol_001",
        duration_sec=15
    )
    assert key is not None

    # Verify event stored in queue
    pending = buffer.get_pending_batch()
    assert len(pending) == 1
    assert pending[0]["subject"] == "notepad.exe"
    assert pending[0]["type"] == "app_start"

    # Test rejection of URL path and query
    with pytest.raises(ValueError, match="Strict schema violation"):
        buffer.record_event(
            event_type="domain_query",
            subject="youtube.com/watch?v=123",
            policy_id="pol_001"
        )

    with pytest.raises(ValueError, match="Strict schema violation"):
        buffer.record_event(
            event_type="domain_query",
            subject="example.com?query=test",
            policy_id="pol_001"
        )

    # Test normalization of domain to eTLD+1
    assert normalize_subject("m.youtube.com", "domain_query") == "youtube.com"
    assert normalize_subject("portal.uit.edu.vn", "domain_query") == "uit.edu.vn"

    # Mark synced
    buffer.mark_synced([key])
    assert len(buffer.get_pending_batch()) == 0

    # Purge
    buffer.record_event("locked", "system", "pol_001")
    assert len(buffer.get_pending_batch()) == 1
    buffer.purge_local_events()
    assert len(buffer.get_pending_batch()) == 0


# 3. Screen Time Manager Tests
def test_screen_time_monotonic_and_idle(temp_agent_db):
    # Mock idle function returning 0 seconds (active user)
    mgr = ScreenTimeManager(db=temp_agent_db, mock_idle_fn=lambda: 0.0)

    # Simulate ticking
    time.sleep(0.05)
    mgr.tick(active_category="gaming")
    assert mgr.used_total_sec >= 0
    assert "gaming" in mgr.category_used_sec or mgr.used_total_sec == 0

    # Test idle pause (> 300 seconds)
    mgr.mock_idle_fn = lambda: 350.0  # 350s idle (> 300s threshold)
    initial_used = mgr.used_total_sec
    time.sleep(0.05)
    mgr.tick()
    # Should not have increased because user is idle
    assert mgr.used_total_sec == initial_used


def test_screen_time_matrix_and_lock_evaluation(temp_agent_db):
    mgr = ScreenTimeManager(db=temp_agent_db, mock_idle_fn=lambda: 0.0)

    # Create policy with 60 minutes limit and allowed matrix
    policy = {
        "daily_limit_minutes_weekday": 60,
        "daily_limit_minutes_weekend": 60,
        "schedule_matrix": "1" * 336,
    }

    # Under limit
    mgr.used_total_sec = 1800  # 30 minutes used
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    assert is_locked is False
    assert reason == "ALLOWED"

    # Warning trigger at 10m remaining (3000s used of 3600s -> 600s remaining)
    mgr.used_total_sec = 3050  # 550s remaining (< 600s)
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    assert warning == "warn_10m"

    # Over quota: enters 60s grace period
    mgr.used_total_sec = 3600  # 0 remaining
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    assert is_locked is False
    assert reason == "GRACE_PERIOD"
    assert warning == "GRACE_PERIOD_60S"

    # Expire grace period
    mgr.grace_period_start_monotonic = time.monotonic() - 70.0  # 70s ago
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    assert is_locked is True
    assert reason == "DAILY_LIMIT_REACHED"

    # Bonus time adds 15 minutes (900s)
    mgr.add_bonus_time(900)
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    assert is_locked is False  # unlocked!

    # Outside schedule test
    all_zero_matrix_policy = dict(policy)
    all_zero_matrix_policy["schedule_matrix"] = "0" * 336
    is_locked, reason, warning = mgr.evaluate_lock_status(all_zero_matrix_policy)
    assert is_locked is True
    assert reason == "OUTSIDE_ALLOWED_SCHEDULE"

    # Parent pause overrides lock
    mgr.activate_parent_pause(duration_sec=7200)
    is_locked, reason, warning = mgr.evaluate_lock_status(all_zero_matrix_policy)
    assert is_locked is False
    assert reason == "PARENT_PAUSED"


def test_screen_time_adr01_graded_fail_open(temp_agent_db):
    from datetime import timedelta
    mgr = ScreenTimeManager(db=temp_agent_db)

    policy = {
        "daily_limit_minutes_weekday": 60,
        "daily_limit_minutes_weekend": 60,
        "schedule_matrix": "0" * 336,  # Normally locked schedule
    }

    # Case 1: Offline for 2 days (< 7 days) -> Normal lock is enforced
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    mgr.record_server_sync(two_days_ago)
    assert mgr.is_graded_fail_open() is False
    is_locked, reason, _ = mgr.evaluate_lock_status(policy)
    assert is_locked is True
    assert reason == "OUTSIDE_ALLOWED_SCHEDULE"

    # Case 2: Offline for 8 days (> 7 days) -> ADR-01 Graded Fail-Open activated!
    eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    mgr.record_server_sync(eight_days_ago)
    assert mgr.is_graded_fail_open() is True
    is_locked, reason, warning = mgr.evaluate_lock_status(policy)
    # Does NOT hard lock machine for learning tools
    assert is_locked is False
    assert reason == "GRADED_FAIL_OPEN"
    assert warning == "OFFLINE_OVER_7_DAYS"


def test_screen_time_3layer_clock_tampering(temp_agent_db):
    from datetime import timedelta
    mgr = ScreenTimeManager(db=temp_agent_db)

    # Layer 1: Monotonic ticking works reliably
    t0 = mgr.last_monotonic
    time.sleep(0.01)
    mgr.tick()
    assert mgr.last_monotonic >= t0

    # Layer 2: Wall clock rollback check (kid changes clock backwards by 3 hours)
    future_time = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    mgr.last_wall_clock_utc = future_time
    mgr.tick()
    # Detected tampering because current UTC is earlier than last_wall_clock_utc
    assert mgr.clock_tampered_flag is True

    # Layer 3: Server drift verification
    # When server clock differs by > 120s, flag is raised
    server_time_drifted = "2020-01-01T00:00:00Z"
    drift, is_tampered = mgr.verify_clock_drift(server_time_drifted)
    assert drift > 120.0
    assert is_tampered is True
    assert mgr.clock_tampered_flag is True


def test_screen_time_category_budgets(temp_agent_db):
    mgr = ScreenTimeManager(db=temp_agent_db)
    policy = {
        "category_budgets": {"gaming": 30, "education": 120}  # 30m gaming
    }
    # Gaming used 20m -> not over budget
    mgr.category_used_sec = {"gaming": 1200}
    is_over, used, limit = mgr.is_category_over_budget("gaming", policy)
    assert is_over is False
    assert used == 1200
    assert limit == 1800

    # Gaming used 35m -> over budget!
    mgr.category_used_sec = {"gaming": 2100}
    is_over, used, limit = mgr.is_category_over_budget("gaming", policy)
    assert is_over is True
    assert used == 2100


# 4. App Controller LRU Cache & Whitelist
def test_sha256_lru_cache():
    cache = Sha256LruCache(maxsize=3)

    # Create temporary files
    with tempfile.NamedTemporaryFile(delete=False) as f1, tempfile.NamedTemporaryFile(delete=False) as f2:
        f1.write(b"content 1")
        f2.write(b"content 2")
        f1_path = f1.name
        f2_path = f2.name

    try:
        h1, orig1 = cache.get_or_compute(f1_path)
        assert h1 is not None
        # Cache hit
        h1_again, _ = cache.get_or_compute(f1_path)
        assert h1 == h1_again

        h2, _ = cache.get_or_compute(f2_path)
        assert h2 is not None
        assert h1 != h2
    finally:
        os.remove(f1_path)
        os.remove(f2_path)


def test_app_controller_system_whitelist():
    controller = AppController()
    assert "explorer.exe" in WHITELISTED_SYSTEM_EXES
    assert "ogk_service.exe" in WHITELISTED_SYSTEM_EXES
    # System processes are never in scan violations even when locked
    violations = controller.scan_and_enforce(app_rules=[], is_locked=True, dry_run=True)
    violation_names = [v["name"] for v in violations]
    assert "explorer.exe" not in violation_names
    assert "ogk_service.exe" not in violation_names


def test_app_controller_renamed_file_detection_by_sha256():
    """FR-F2-01: Verifies process identification by SHA-256 even when executable is renamed."""
    controller = AppController()

    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        f.write(b"MOCK_GAME_BINARY_PAYLOAD_BYTES_XYZ_98765")
        mock_exe_path = f.name

    try:
        sha256_hex, _ = controller.cache.get_or_compute(mock_exe_path)
        assert sha256_hex is not None

        # Scenario A: Kid renamed game.exe to innocent_calc.exe
        app_rules = [
            {
                "exe_name": "game.exe",
                "sha256": sha256_hex,
                "action": "block",
                "category": "gaming",
                "reason": "Restricted Game"
            }
        ]

        class MockProc:
            def __init__(self, pid, name, exe):
                self.pid = pid
                self.info = {'pid': pid, 'name': name, 'exe': exe}
            def terminate(self): pass
            def wait(self, timeout=None): pass
            def kill(self): pass

        mock_process = MockProc(pid=9999, name="innocent_calc.exe", exe=mock_exe_path)

        import psutil
        orig_iter = psutil.process_iter
        try:
            psutil.process_iter = lambda attrs: [mock_process]
            violations = controller.scan_and_enforce(app_rules=app_rules, dry_run=True)
            assert len(violations) == 1
            # Detected as blocked via SHA-256 despite being named innocent_calc.exe!
            assert violations[0]["sha256"] == sha256_hex
            assert "Restricted Game" in violations[0]["reason"]
        finally:
            psutil.process_iter = orig_iter

        # Scenario B: Suspicious name "bad_hack.exe" but SHA-256 matches an allowed educational tool
        allow_rules = [
            {
                "exe_name": "calculator.exe",
                "sha256": sha256_hex,
                "action": "allow",
                "category": "education"
            }
        ]
        mock_process_b = MockProc(pid=9998, name="bad_hack.exe", exe=mock_exe_path)
        try:
            psutil.process_iter = lambda attrs: [mock_process_b]
            violations_b = controller.scan_and_enforce(app_rules=allow_rules, dry_run=True)
            # Allowed because SHA-256 matches allow rule
            assert len(violations_b) == 0
        finally:
            psutil.process_iter = orig_iter

    finally:
        if os.path.exists(mock_exe_path):
            os.remove(mock_exe_path)


# 5. Platform Guards & Sensors
def test_network_and_browser_guards(temp_agent_db):
    net_guard = NetworkDnsGuard(db=temp_agent_db)
    snapshot = net_guard.capture_and_save_snapshot()
    assert isinstance(snapshot, list)
    assert temp_agent_db.get_snapshot("NETWORK_DNS") is not None

    browser_guard = BrowserPolicyGuard(db=temp_agent_db)
    b_snapshot = browser_guard.capture_and_save_snapshot()
    assert isinstance(b_snapshot, dict)
    assert "chrome" in b_snapshot

    # Restore calls should not raise
    assert net_guard.restore_original_dns() is True
    assert browser_guard.restore_browser_policies() is True


def test_bypass_detector():
    detector = BypassDetector()
    results = detector.scan_all_bypass_vectors()
    assert "has_bypass" in results
    assert isinstance(results["vpn_adapters"], list)
    assert isinstance(results["system_proxy"], dict)
    assert isinstance(results["dot_connections"], list)
