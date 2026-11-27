"""Session 0 Breakout and Tray Process Launcher (FR-F5-09, Section 3.2).
Launches OGK-Tray into active interactive user sessions (Session 1+) using WTS APIs.
Enforces the strict No-Stealth-Mode anti-abuse guardrail:
If Tray UI fails to display after 3 attempts, switches service to UNPROTECTED_HALT.
"""
import logging
import os
import sys
import time
from typing import Optional, Callable

logger = logging.getLogger("OGK.SessionLauncher")

_IS_WINDOWS = sys.platform == "win32"
if _IS_WINDOWS:
    try:
        import win32ts
        import win32security
        import win32process
        import win32con
        import win32profile
    except ImportError:
        pass


class SessionAgentLauncher:
    """Manages spawning OGK-Tray into active user desktop sessions from Session 0."""

    def __init__(
        self,
        tray_script_or_exe_path: Optional[str] = None,
        on_unprotected_halt_callback: Optional[Callable[[], None]] = None,
        max_launch_attempts: int = 3,
        ready_timeout_sec: float = 20.0,
    ):
        self.tray_path = tray_script_or_exe_path or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "ui", "tray_app.py"
        )
        self.on_unprotected_halt_callback = on_unprotected_halt_callback
        self.max_launch_attempts = max_launch_attempts
        # How long a spawned tray may take to confirm its icon (TRAY_READY) before the
        # launch counts as a failed attempt.
        self.ready_timeout_sec = ready_timeout_sec
        # time.monotonic() of the last real spawn still waiting for TRAY_READY
        self.awaiting_ready_since: Optional[float] = None

        # Health tracking
        self.consecutive_failed_attempts: int = 0
        self.is_tray_registered: bool = False
        self.is_unprotected_halt: bool = False
        self.last_launch_time: float = 0.0

    def mark_tray_ready(self) -> None:
        """Called when OGK-Tray confirms it is running and tray icon is visible."""
        self.is_tray_registered = True
        self.consecutive_failed_attempts = 0
        self.awaiting_ready_since = None
        if self.is_unprotected_halt:
            logger.info("Tray UI reconnected! Clearing UNPROTECTED_HALT.")
            self.is_unprotected_halt = False
        logger.info("Tray UI confirmed visible and healthy.")

    def mark_tray_disconnected(self) -> None:
        """Called when Tray UI disconnects or crashes."""
        self.is_tray_registered = False

    def trigger_launch_if_needed(self) -> bool:
        """
        Periodically invoked (e.g. every 3s).
        Finds active user session and spawns Tray UI if not already registered.
        """
        if self.is_tray_registered:
            return True

        if self.is_unprotected_halt:
            # Already in halt state to respect No-Stealth-Mode
            return False

        # A tray process was spawned but has not confirmed its icon yet
        if self.awaiting_ready_since is not None:
            if time.monotonic() - self.awaiting_ready_since < self.ready_timeout_sec:
                return False  # still within the deadline; do not spawn duplicates
            # Spawned but never became visible: that is a failed attempt too
            self.awaiting_ready_since = None
            logger.warning("Tray UI was launched but sent no TRAY_READY within %.0fs", self.ready_timeout_sec)
            if self._register_failed_attempt():
                return False

        # Throttle launch attempts to every 3 seconds
        now = time.time()
        if now - self.last_launch_time < 3.0:
            return False
        self.last_launch_time = now

        success = self._launch_into_active_session()
        if not success:
            self._register_failed_attempt()
            return False

        return success

    def _register_failed_attempt(self) -> bool:
        """Counts one failed attempt. Returns True when UNPROTECTED_HALT was entered."""
        self.consecutive_failed_attempts += 1
        logger.warning(
            "Failed to launch Tray UI (Attempt %d/%d)",
            self.consecutive_failed_attempts,
            self.max_launch_attempts,
        )

        # Strict guardrail: If tray fails 3 times, switch to UNPROTECTED_HALT
        if self.consecutive_failed_attempts >= self.max_launch_attempts:
            logger.critical(
                "OGK-Tray failed to display after %d attempts! "
                "Enforcing UNPROTECTED_HALT: Halting protection to prevent stealth monitoring.",
                self.max_launch_attempts,
            )
            self.is_unprotected_halt = True
            if self.on_unprotected_halt_callback:
                try:
                    self.on_unprotected_halt_callback()
                except Exception as e:
                    logger.error("Error in UNPROTECTED_HALT callback: %s", e)
            return True
        return False

    def _launch_into_active_session(self) -> bool:
        """Spawns Tray UI into interactive desktop session using CreateProcessAsUser."""
        if not _IS_WINDOWS:
            logger.debug("Non-windows environment: mock launching Tray UI")
            return True

        try:
            # 1. Enumerate sessions to find active console / interactive session
            sessions = win32ts.WTSEnumerateSessions()
            active_session_id = None
            for s in sessions:
                state = s.get("State")
                # WTSActive = 0
                if state == 0 and s.get("SessionId") != 0:
                    active_session_id = s.get("SessionId")
                    break

            if active_session_id is None:
                # No active user logged in
                return True

            # 2. Get user token for active session
            user_token = win32ts.WTSQueryUserToken(active_session_id)

            # 3. Duplicate token to Primary token
            primary_token = win32security.DuplicateTokenEx(
                user_token,
                win32security.SecurityIdentification,
                win32security.TokenPrimary,
                win32con.MAXIMUM_ALLOWED
            )

            # 4. Prepare environment block
            env = win32profile.CreateEnvironmentBlock(primary_token, False)

            # 5. Build startup info with lpDesktop = "winsta0\\default"
            startup = win32process.STARTUPINFO()
            startup.lpDesktop = r"winsta0\default"

            # 6. Command line
            python_exe = sys.executable
            cmd_line = f'"{python_exe}" "{self.tray_path}"'

            # 7. CreateProcessAsUser
            proc_handle, thread_handle, pid, tid = win32process.CreateProcessAsUser(
                primary_token,
                None,
                cmd_line,
                None,
                None,
                False,
                win32con.CREATE_NEW_CONSOLE | win32con.CREATE_UNICODE_ENVIRONMENT,
                env,
                None,
                startup
            )
            logger.info("Launched OGK-Tray into Session %d with PID %d", active_session_id, pid)
            # The launch only counts once the tray confirms its icon with TRAY_READY
            self.awaiting_ready_since = time.monotonic()
            return True

        except Exception as e:
            logger.error("CreateProcessAsUser error: %s", e)
            return False
