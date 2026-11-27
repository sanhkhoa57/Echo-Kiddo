"""Screen Time Monitor and Anti-Clock Tampering Engine (FR-F1, M6, ADR-01).
Implements:
1. Real screen-time counting via time.monotonic()
2. Idle pause (> 300s) via ctypes/win32 GetLastInputInfo and session lock (WTS_SESSION_LOCK)
3. Weekday/weekend limits, 7x48 matrix schedule (336 chars), and category budgets
4. 10m/5m/1m warnings and 60-second grace period (GRACE_PERIOD_60S)
5. 3-layer anti-clock tampering (monotonic, local wall clock SQLite, server_utc drift)
6. ADR-01 Graded Fail-Open after N=7 days of offline disconnection
"""
import ctypes
from ctypes import wintypes
import time
import json
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional, Dict, Any, Tuple, Iterable

from agent.core.policy_verifier import policy_field

logger = logging.getLogger("OGK.ScreenTime")

_IS_WINDOWS = ctypes.sizeof(ctypes.c_void_p) is not None and hasattr(ctypes, "windll")


# A wall-clock jump larger than this (compared with the elapsed-time clock) is treated
# as the clock being changed by hand rather than NTP slewing.
CLOCK_JUMP_THRESHOLD_SEC = 60.0
# Subject used for the event logged when the system clock is changed by hand
CLOCK_TAMPER_SUBJECT = "clock_tamper"


def elapsed_clock_sec() -> float:
    """Seconds since boot that keep running while the machine sleeps and are immune to
    changes of the wall clock. GetTickCount64 includes sleep/hibernate time, so a laptop
    waking up next morning is not mistaken for a manual clock change."""
    if _IS_WINDOWS:
        try:
            fn = ctypes.windll.kernel32.GetTickCount64
            fn.restype = ctypes.c_ulonglong
            return fn() / 1000.0
        except Exception:
            pass
    return time.monotonic()


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def get_system_idle_seconds() -> float:
    """Returns number of seconds since last user input on Windows via ctypes GetLastInputInfo."""
    if _IS_WINDOWS and hasattr(ctypes.windll, "user32"):
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if user32.GetLastInputInfo(ctypes.byref(lii)):
                current_tick = kernel32.GetTickCount()
                last_input_tick = lii.dwTime
                if current_tick < last_input_tick:
                    diff = (0xFFFFFFFF - last_input_tick) + current_tick
                else:
                    diff = current_tick - last_input_tick
                return max(0.0, diff / 1000.0)
        except Exception as e:
            logger.debug("GetLastInputInfo failed: %s", e)
    return 0.0


class ScreenTimeManager:
    """Manages active screen time, schedule matrix evaluation, and anti-tampering logic."""

    def __init__(self, db=None, mock_idle_fn=None):
        self.db = db
        self.mock_idle_fn = mock_idle_fn

        # Runtime state
        self.current_date_str = date.today().isoformat()
        self.used_total_sec: int = 0
        self.category_used_sec: Dict[str, int] = {}
        self.bonus_sec: int = 0
        self.parent_pause_until_monotonic: float = 0.0

        # Monotonic and wall clock tracking (Layer 1 & Layer 2)
        self.last_monotonic: float = time.monotonic()
        self.last_wall_clock_utc: str = datetime.now(timezone.utc).isoformat()
        self.clock_tampered_flag: bool = False
        # Layer 1b: wall clock vs elapsed clock. wall_offset_sec = local wall - trusted time.
        # Every manual jump is folded into the offset so day rollover, weekday/weekend and
        # the 7x48 schedule keep using the real time even after the clock was moved.
        self.wall_offset_sec: float = 0.0
        self._last_wall_ts: float = time.time()
        self._last_elapsed: float = elapsed_clock_sec()
        self.tamper_events_pending: int = 0

        # Server sync tracking for ADR-01 (N = 7 days)
        self.last_server_sync_utc: Optional[str] = datetime.now(timezone.utc).isoformat()

        # Session lock state
        self.is_session_locked: bool = False
        # Idle seconds reported by OGK-Tray from the child's session: a service in session 0
        # cannot read the user's last input itself. (idle_sec, elapsed_clock at report)
        self._reported_idle: Optional[Tuple[float, float]] = None
        self.manual_lock_active: bool = False

        # Warning trigger flags (per day)
        self.warned_10m: bool = False
        self.warned_5m: bool = False
        self.warned_1m: bool = False

        # Grace period (60 seconds)
        self.grace_period_start_monotonic: Optional[float] = None
        self.grace_period_duration_sec: int = 60

        # Load persisted state for today if db provided
        if self.db:
            self._load_state_from_db()

    # ------------------------------------------------------------------ trusted time
    def trusted_now(self) -> datetime:
        """Local time corrected for any manual clock change detected so far."""
        return datetime.now() - timedelta(seconds=self.wall_offset_sec)

    def _flag_tamper(self) -> None:
        """Raises the tamper flag and queues one tamper event for the service to log."""
        self.clock_tampered_flag = True
        self.tamper_events_pending += 1

    def pop_tamper_event(self) -> bool:
        """True once per batch of detected clock changes, so the service logs one event."""
        if self.tamper_events_pending > 0:
            self.tamper_events_pending = 0
            return True
        return False

    def _detect_wall_clock_jump(self) -> None:
        """Compares how far the wall clock moved with how far the elapsed clock moved.
        A difference above the threshold (forwards OR backwards) is a manual change."""
        now_wall = time.time()
        now_el = elapsed_clock_sec()
        jump = (now_wall - self._last_wall_ts) - (now_el - self._last_elapsed)
        self._last_wall_ts = now_wall
        self._last_elapsed = now_el
        if abs(jump) > CLOCK_JUMP_THRESHOLD_SEC:
            self.wall_offset_sec += jump
            self._flag_tamper()
            logger.warning(
                "System clock changed by %+.0fs without matching elapsed time: ignoring it "
                "(trusted offset now %+.0fs).", jump, self.wall_offset_sec)

    def _load_state_from_db(self) -> None:
        """Loads today's accumulated usage from agent.db."""
        today = date.today().isoformat()
        self.current_date_str = today
        row = self.db.get_daily_usage(today)
        if row:
            self.used_total_sec = row.get("used_total_sec", 0)
            cat_json = row.get("category_used_json", "{}")
            try:
                self.category_used_sec = json.loads(cat_json) if isinstance(cat_json, str) else cat_json
            except Exception:
                self.category_used_sec = {}
            self.last_wall_clock_utc = row.get("last_wall_clock_utc", datetime.now(timezone.utc).isoformat())

    def _persist_state_to_db(self) -> None:
        """Saves current state to agent.db."""
        if self.db:
            self.db.save_daily_usage(
                date_local=self.current_date_str,
                used_total_sec=self.used_total_sec,
                category_used_json=json.dumps(self.category_used_sec),
                last_monotonic_sec=self.last_monotonic,
                last_wall_clock_utc=self.last_wall_clock_utc,
            )

    def _check_day_rollover(self) -> None:
        """Resets counters when the (trusted) local calendar day changes at midnight.
        Moving the clock forwards to tomorrow or backwards never resets the quota: the
        jump is detected and folded into wall_offset_sec first, and the day only moves on."""
        self._detect_wall_clock_jump()
        today = self.trusted_now().date().isoformat()
        if today == self.current_date_str:
            return
        if today < self.current_date_str:
            # Calendar went backwards (e.g. clock set back while powered off): never re-open a day
            if not self.clock_tampered_flag:
                logger.warning("Clock wound backwards! Day %s -> %s. Rejecting rollover.", self.current_date_str, today)
                self._flag_tamper()
            return

        # Layer 2 check across reboots: did wall clock go backwards versus the last saved value?
        now_dt = datetime.now(timezone.utc)
        try:
            last_dt = datetime.fromisoformat(self.last_wall_clock_utc.replace("Z", "+00:00"))
            if now_dt < last_dt - timedelta(seconds=CLOCK_JUMP_THRESHOLD_SEC):
                logger.warning("Clock wound backwards! Last: %s, Current: %s. Rejecting rollover.", self.last_wall_clock_utc, now_dt.isoformat())
                self._flag_tamper()
                return
        except Exception:
            pass

        logger.info("Day rollover detected: %s -> %s. Resetting counters.", self.current_date_str, today)
        self.current_date_str = today
        self.used_total_sec = 0
        self.category_used_sec = {}
        self.bonus_sec = 0
        self.warned_10m = False
        self.warned_5m = False
        self.warned_1m = False
        self.grace_period_start_monotonic = None
        self._persist_state_to_db()

    def report_user_activity(self, idle_sec: Optional[float], session_locked: Optional[bool]) -> None:
        """Called with what OGK-Tray observed in the interactive session (every ~2s)."""
        if idle_sec is not None:
            try:
                self._reported_idle = (max(0.0, float(idle_sec)), elapsed_clock_sec())
            except (TypeError, ValueError):
                pass
        if session_locked is not None:
            self.set_session_lock(bool(session_locked))

    def get_idle_seconds(self) -> float:
        """Idle seconds: mock (tests) > fresh report from the Tray > local system API."""
        if self.mock_idle_fn:
            return self.mock_idle_fn()
        if self._reported_idle is not None:
            idle, at = self._reported_idle
            age = elapsed_clock_sec() - at
            if 0 <= age <= 15.0:
                return idle + age
        return get_system_idle_seconds()

    def record_server_sync(self, server_utc_iso: Optional[str] = None) -> None:
        """Records timestamp of successful server synchronization (heartbeat/policy)."""
        self.last_server_sync_utc = server_utc_iso or datetime.now(timezone.utc).isoformat()

    def is_graded_fail_open(self) -> bool:
        """
        Evaluates ADR-01: Graded Fail-Open after N = 7 days of lost connection.
        If offline for > 7 days (604,800s), does not lock machine completely,
        allowing educational tools while maintaining DNS & app blocklist.
        """
        if not self.last_server_sync_utc:
            return False
        try:
            last_sync_dt = datetime.fromisoformat(self.last_server_sync_utc.replace("Z", "+00:00"))
            offline_duration = (datetime.now(timezone.utc) - last_sync_dt).total_seconds()
            return offline_duration >= 7 * 86400  # 7 days
        except Exception:
            return False

    def tick(self, active_category: Optional[str] = None,
             active_categories: Optional[Iterable[str]] = None) -> None:
        """
        Advances the screen-time engine by the delta since last tick (M6, FR-F1-03).
        Enforces 3-layer anti-tampering:
        1. time.monotonic() delta
        2. SQLite last_wall_clock_utc rollback check
        3. Idle > 300s pause and Session Lock pause

        `active_categories` are the app categories with a running program in this tick;
        each one gets its own counter (e.g. the gaming budget runs beside the daily total).
        """
        self._check_day_rollover()

        now_mono = time.monotonic()
        delta_t = now_mono - self.last_monotonic
        self.last_monotonic = now_mono

        now_utc = datetime.now(timezone.utc).isoformat()

        # Layer 2 check: detect backwards wall clock change
        try:
            last_dt = datetime.fromisoformat(self.last_wall_clock_utc.replace("Z", "+00:00"))
            curr_dt = datetime.now(timezone.utc)
            if curr_dt < last_dt - timedelta(seconds=CLOCK_JUMP_THRESHOLD_SEC):
                self._flag_tamper()
                logger.warning("Wall clock backwards jump detected! Last: %s, Current: %s", self.last_wall_clock_utc, now_utc)
        except Exception:
            pass

        self.last_wall_clock_utc = now_utc

        # If parent pause is active, do not accumulate quota
        if self.is_parent_paused():
            return

        # If locked manually or via session lock, do not accumulate
        if self.is_session_locked or self.manual_lock_active:
            return

        idle_sec = self.get_idle_seconds()
        # Count only if active interaction within 5 minutes and reasonable step
        if 0 < delta_t <= 10.0 and idle_sec <= 300.0:
            add_sec = int(round(delta_t))
            if add_sec > 0:
                self.used_total_sec += add_sec
                cats = set(active_categories or ())
                if active_category:
                    cats.add(active_category)
                for cat in cats:
                    self.category_used_sec[cat] = self.category_used_sec.get(cat, 0) + add_sec

        self._persist_state_to_db()

    def is_parent_paused(self) -> bool:
        """Returns True if parent pause (2h) is active."""
        return time.monotonic() < self.parent_pause_until_monotonic

    def activate_parent_pause(self, duration_sec: int = 7200) -> None:
        """Activates parent pause mode (FR-F4-06, default 2 hours)."""
        self.parent_pause_until_monotonic = time.monotonic() + duration_sec
        logger.info("Parent pause activated for %d seconds", duration_sec)

    def cancel_parent_pause(self) -> None:
        """Cancels parent pause immediately."""
        self.parent_pause_until_monotonic = 0.0

    def add_bonus_time(self, seconds: int) -> None:
        """Adds bonus screen time for tasks or parental reward."""
        self.bonus_sec += max(0, seconds)
        logger.info("Added %d seconds bonus time. Total bonus: %d", seconds, self.bonus_sec)

    def set_session_lock(self, locked: bool) -> None:
        """Called when WTS_SESSION_LOCK or WTS_SESSION_UNLOCK is received."""
        self.is_session_locked = locked

    def set_manual_lock(self, locked: bool) -> None:
        """Called on LOCK_NOW / UNLOCK commands."""
        self.manual_lock_active = locked

    @staticmethod
    def is_slot_allowed_by_matrix(schedule_matrix: str, check_dt: Optional[datetime] = None) -> bool:
        """
        Evaluates the 7x48 binary schedule matrix (FR-F1-02).
        Monday=0 ... Sunday=6.
        Each day has 48 half-hour slots (336 slots in total).
        """
        if not schedule_matrix or len(schedule_matrix) != 336:
            return True

        dt = check_dt or datetime.now()
        day_idx = dt.weekday()  # 0=Monday, 6=Sunday
        slot_idx = dt.hour * 2 + (1 if dt.minute >= 30 else 0)
        matrix_idx = day_idx * 48 + slot_idx

        if 0 <= matrix_idx < 336:
            return schedule_matrix[matrix_idx] == "1"
        return True

    def is_category_over_budget(self, category: str, policy: Dict[str, Any]) -> Tuple[bool, int, int]:
        """
        Checks if an application category has exceeded its daily budget (FR-F1-06).
        Returns (is_over_budget, used_seconds, limit_seconds).
        """
        # Canonical server field first, then legacy aliases
        budgets = policy_field(policy, "category_budgets_json", "category_budgets", "category_quotas", default={})
        if isinstance(budgets, str):
            try:
                budgets = json.loads(budgets)
            except Exception:
                budgets = {}
        if not isinstance(budgets, dict):
            budgets = {}

        if category not in budgets:
            return False, self.category_used_sec.get(category, 0), 0

        used_sec = self.category_used_sec.get(category, 0)
        try:
            limit_min = int(budgets[category])
        except (TypeError, ValueError):
            return False, used_sec, 0
        if limit_min < 0:
            # Negative budget (-1) means "no limit" for this category (e.g. education)
            return False, used_sec, -1
        limit_sec = limit_min * 60
        return used_sec >= limit_sec, used_sec, limit_sec

    def get_daily_limit_seconds(self, policy: Dict[str, Any], check_dt: Optional[datetime] = None) -> int:
        """Calculates total allowed seconds for today (weekday vs weekend + bonus)."""
        dt = check_dt or self.trusted_now()
        is_weekend = dt.weekday() in (5, 6)  # Saturday, Sunday

        if is_weekend:
            limit_min = policy_field(policy, "daily_limit_weekend_min", "daily_limit_minutes_weekend", default=120)
        else:
            limit_min = policy_field(policy, "daily_limit_weekday_min", "daily_limit_minutes_weekday", default=120)
        return (limit_min * 60) + self.bonus_sec

    def get_remaining_seconds(self, policy: Dict[str, Any], check_dt: Optional[datetime] = None) -> int:
        """Returns remaining screen time in seconds. Can be negative if overtime."""
        if self.is_parent_paused():
            return 999999  # Unlimited while parent paused

        total_allowed = self.get_daily_limit_seconds(policy, check_dt)
        remaining = total_allowed - self.used_total_sec
        return remaining

    def evaluate_lock_status(self, policy: Dict[str, Any], check_dt: Optional[datetime] = None) -> Tuple[bool, str, Optional[str]]:
        """
        Evaluates current lock status and pending warnings (FR-F1-01, FR-F1-02, FR-F1-04, ADR-01).
        Returns:
            (is_locked: bool, reason: str, warning_type: Optional[str])
            where warning_type can be 'warn_10m', 'warn_5m', 'warn_1m', 'GRACE_PERIOD_60S', or None.
        """
        # 1. Check parent pause override
        if self.is_parent_paused():
            return False, "PARENT_PAUSED", None

        # 2. Check manual lock command
        if self.manual_lock_active:
            return True, "MANUAL_LOCK", None

        # 3. Check ADR-01: Graded Fail-Open after 7 days offline
        if self.is_graded_fail_open():
            logger.info("ADR-01 Active: Over 7 days offline, Graded Fail-Open mode enabled.")
            # Do NOT hard lock machine, allow educational tools
            return False, "GRADED_FAIL_OPEN", "OFFLINE_OVER_7_DAYS"

        # 4. Check weekly 7x48 matrix schedule
        matrix = policy_field(policy, "schedule_matrix_7x48", "schedule_matrix", default="")
        if not self.is_slot_allowed_by_matrix(matrix, check_dt or self.trusted_now()):
            return True, "OUTSIDE_ALLOWED_SCHEDULE", None

        # 5. Check daily total screen time quota
        remaining = self.get_remaining_seconds(policy, check_dt)

        # Warning triggers
        warning = None
        if 540 < remaining <= 600 and not self.warned_10m:
            self.warned_10m = True
            warning = "warn_10m"
        elif 240 < remaining <= 300 and not self.warned_5m:
            self.warned_5m = True
            warning = "warn_5m"
        elif 0 < remaining <= 60 and not self.warned_1m:
            self.warned_1m = True
            warning = "warn_1m"

        # Quota reached: 60-second grace period handling (GRACE_PERIOD_60S)
        if remaining <= 0:
            now_mono = time.monotonic()
            if self.grace_period_start_monotonic is None:
                self.grace_period_start_monotonic = now_mono
                return False, "GRACE_PERIOD", "GRACE_PERIOD_60S"

            elapsed_grace = now_mono - self.grace_period_start_monotonic
            if elapsed_grace < self.grace_period_duration_sec:
                # Still within 60s grace
                return False, "GRACE_PERIOD", "GRACE_PERIOD_60S"
            else:
                # Grace period expired -> hard lock
                return True, "DAILY_LIMIT_REACHED", None

        # Quota available again (e.g. bonus time granted): a later expiry gets a fresh 60s grace
        self.grace_period_start_monotonic = None
        return False, "ALLOWED", warning

    def verify_clock_drift(self, server_utc_iso: str) -> Tuple[float, bool]:
        """
        Layer 3: Verifies clock drift between agent local wall clock and server_utc (M6).
        Returns (drift_sec, is_tampered_or_drifted_exceeding_120s).
        """
        try:
            server_dt = datetime.fromisoformat(server_utc_iso.replace("Z", "+00:00"))
            local_dt = datetime.now(timezone.utc)
            signed_drift = (local_dt - server_dt).total_seconds()
            drift_sec = abs(signed_drift)
            is_tampered = drift_sec > 120.0
            if is_tampered:
                self._flag_tamper()
                logger.warning("Layer 3: Clock drift exceeded 120s! Drift: %.2fs", drift_sec)
            # The server is authoritative: trusted time follows it from now on
            self.wall_offset_sec = signed_drift if is_tampered else 0.0
            self.record_server_sync(server_utc_iso)
            return drift_sec, is_tampered
        except Exception as e:
            logger.error("Error verifying clock drift: %s", e)
            return 0.0, False
