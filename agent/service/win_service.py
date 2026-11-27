"""Windows Service Host for OGK-Agent (FR-F5-09, Section 2 & 3.2).
Runs in Session 0 as LocalSystem. Manages lifecycle of DNS Proxy, App Controller,
Screen Time Engine, IPC Pipe Server, Network/Browser Guards, and Session Launcher.
Supports both SCM Windows Service execution and standalone runner mode.

CLI:
    python agent/service/win_service.py enroll --code <PAIRING_CODE> [--server https://127.0.0.1:8000]
    python agent/service/win_service.py run
"""
import argparse
import asyncio
import hashlib
import logging
import os
import re
import socket
import sys
import threading
import time
import uuid
from collections import deque
from typing import Optional, Dict, Any, List

if __package__ in (None, ""):
    # Allow `python agent/service/win_service.py ...` from any working directory
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from branding import APP_NAME

from agent.core.agent_db import AgentDatabase, DEFAULT_AGENT_DB_PATH
from agent.core.event_buffer import EventBuffer
from agent.core.screen_time import ScreenTimeManager, CLOCK_TAMPER_SUBJECT
from agent.core.app_controller import AppController
from agent.core.pin_auth import verify_pin_hash, load_offline_pin_hash
from agent.dns.domain_engine import DomainPolicyEngine
from agent.dns.dns_proxy import DnsProxyServer
from agent.platform.network_guard import NetworkDnsGuard
from agent.platform.browser_policy import BrowserPolicyGuard
from agent.platform.bypass_detector import BypassDetector
from agent.ipc.pipe_protocol import IpcPipeHandler, IpcEnvelope, IpcServer
from agent.service.session_launcher import SessionAgentLauncher
from agent.sync.server_client import AgentServerClient

logger = logging.getLogger("OGK.WinService")

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
DEFAULT_ENROLL_SERVER_URL = "https://127.0.0.1:8000"

QUOTA_WARNINGS = ("warn_10m", "warn_5m", "warn_1m")
RECENT_BLOCKS_MAX = 20
BLOCK_NOTIFY_COOLDOWN_SEC = 30.0      # same subject is announced at most once per window
TRAY_LIVENESS_TIMEOUT_SEC = 15.0      # tray polls every 2s; silence this long = tray gone
PIN_MAX_FAILURES = 5
PIN_LOCKOUT_SEC = 900                 # 15 minutes
OVERRIDE_BONUS_SEC = 900              # +15 minutes
# Events that are not about an app or a domain use this neutral subject
SYSTEM_SUBJECT = "system"

_IS_WINDOWS = sys.platform == "win32"
if _IS_WINDOWS:
    try:
        import win32serviceutil
        import win32service
        import win32event
        import servicemanager
    except ImportError:
        pass


class OGKServiceCore:
    """Core daemon managing all agent subcomponents and life-cycle."""

    def __init__(self, db_path: str = DEFAULT_AGENT_DB_PATH, server_url: Optional[str] = None):
        self.db = AgentDatabase(db_path)
        saved = self.db.get_device_credentials() or {}
        self.server_url = (
            server_url
            or saved.get("server_url")
            or os.getenv("OGK_SERVER_URL")
            or DEFAULT_SERVER_URL
        )
        self.running = False

        # Child-facing notification state shared between worker threads and IPC
        self._state_lock = threading.Lock()
        self._recent_blocks: deque = deque(maxlen=RECENT_BLOCKS_MAX)
        self._last_block_notified: Dict[str, float] = {}
        self._pending_warning: Optional[str] = None
        self._last_tray_poll_monotonic: float = time.monotonic()
        self._pin_failures: int = 0
        self._pin_locked_until_monotonic: float = 0.0

        # Core subsystems
        self.event_buffer = EventBuffer(db=self.db)
        self.screen_time_mgr = ScreenTimeManager(db=self.db)
        self.app_controller = AppController(
            event_buffer=self.event_buffer,
            on_blocked_callback=self._note_block,
        )
        self.domain_engine = DomainPolicyEngine()
        self.dns_proxy = DnsProxyServer(
            engine=self.domain_engine, host="127.0.0.1", port=53,
            event_buffer=self.event_buffer,
            on_blocked_callback=self._note_block,
            listen_ipv6=True,
        )
        self.net_guard = NetworkDnsGuard(db=self.db)
        self.browser_guard = BrowserPolicyGuard(db=self.db)
        self.bypass_detector = BypassDetector(event_buffer=self.event_buffer)

        # Server sync client (loads device_id / child_id / tokens from agent.db if paired)
        self.server_client = AgentServerClient(
            server_url=self.server_url,
            event_buffer=self.event_buffer,
            screen_time_mgr=self.screen_time_mgr,
            app_controller=self.app_controller,
            domain_engine=self.domain_engine,
            db=self.db,
        )

        # Session launcher (enforcing No-Stealth-Mode)
        self.session_launcher = SessionAgentLauncher(
            on_unprotected_halt_callback=self._handle_unprotected_halt
        )

        # IPC Handler & Server
        self.ipc_handler = IpcPipeHandler(
            get_status_fn=self._get_session_status,
            on_request_more_time_fn=self._handle_request_more_time,
            verify_pin_fn=self._verify_parent_pin,
            on_tray_ready_fn=self._on_tray_ready,
            on_user_activity_fn=self._on_user_activity,
        )
        self.ipc_server = IpcServer(self.ipc_handler)

        self._dns_task: Optional[asyncio.Task] = None
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------ helpers
    def _record_event_safe(self, event_type: str, subject: str, duration_sec: int = 0) -> bool:
        """Records a 7-field event; never raises (e.g. device not enrolled yet)."""
        try:
            self.event_buffer.record_event(
                event_type=event_type,
                subject=subject,
                policy_id=str(self.server_client.current_policy_version),
                duration_sec=max(0, int(duration_sec)),
            )
            return True
        except Exception as e:
            logger.debug("Could not record %s event: %s", event_type, e)
            return False

    def _note_block(self, subject: str, reason: str) -> None:
        """Queues a block notice (exe name or eTLD+1 + reason) for the Tray UI so that
        nothing is ever blocked silently (FR-F2-02)."""
        if not subject:
            return
        now = time.monotonic()
        with self._state_lock:
            last = self._last_block_notified.get(subject)
            if last is not None and now - last < BLOCK_NOTIFY_COOLDOWN_SEC:
                return
            if len(self._last_block_notified) > 256:
                self._last_block_notified.clear()
            self._last_block_notified[subject] = now
            self._recent_blocks.append({
                "subject": subject,
                "reason": reason or "",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

    def _evaluate_lock(self, policy: dict):
        """evaluate_lock_status() hands out each 10/5/1-minute warning only once, so latch
        it here for the Tray UI and log the quota_warning event exactly once."""
        is_locked, reason, warning = self.screen_time_mgr.evaluate_lock_status(policy)
        if warning in QUOTA_WARNINGS:
            with self._state_lock:
                self._pending_warning = warning
            remaining = self.screen_time_mgr.get_remaining_seconds(policy)
            self._record_event_safe("quota_warning", SYSTEM_SUBJECT, duration_sec=max(0, remaining))
        return is_locked, reason, warning

    def _get_session_status(self) -> dict:
        """Returns session status for OGK-Tray display (polled every ~2s)."""
        self._last_tray_poll_monotonic = time.monotonic()
        policy = self.server_client.active_policy
        halted = self.session_launcher.is_unprotected_halt

        remaining_sec = self.screen_time_mgr.get_remaining_seconds(policy)
        is_locked, reason, warning = self._evaluate_lock(policy)

        with self._state_lock:
            pending = self._pending_warning
            self._pending_warning = None
            # Delivered once: the queue is emptied as soon as the Tray has fetched it
            recent_blocks: List[Dict[str, Any]] = list(self._recent_blocks)
            self._recent_blocks.clear()
        if warning is None:
            warning = pending

        if halted:
            # Nothing is enforced while halted; say so honestly
            is_locked, reason, warning = False, "UNPROTECTED_HALT", None

        try:
            summary = self.db.get_today_usage_summary(limit=5)
        except Exception as e:
            logger.debug("Could not build usage summary: %s", e)
            summary = {"top_apps": [], "top_domains": []}

        return {
            "used_total_sec": self.screen_time_mgr.used_total_sec,
            "remaining_sec": max(0, remaining_sec),
            "is_locked": is_locked,
            "lock_reason": reason,
            "warning": warning,
            "is_parent_paused": self.screen_time_mgr.is_parent_paused(),
            "unprotected_halt": halted,
            "tray_registered": self.session_launcher.is_tray_registered,
            "enrolled": bool(self.server_client.device_id),
            "recent_blocks": recent_blocks,
            "top_apps": summary.get("top_apps", []),
            "top_domains": summary.get("top_domains", []),
        }

    def _handle_request_more_time(self, minutes: int) -> dict:
        """Records unlock_request event to send to parent dashboard."""
        try:
            minutes = max(1, min(int(minutes), 120))
        except (TypeError, ValueError):
            minutes = 15
        recorded = self._record_event_safe(
            "unlock_request", f"request_{minutes}m", duration_sec=minutes * 60
        )
        return {"status": "REQUESTED" if recorded else "NOT_ENROLLED", "minutes": minutes}

    def _verify_parent_pin(self, pin: str) -> bool:
        """Verifies the parent offline PIN against the stored Argon2id hash.
        No default PIN exists. On success grants a temporary override (override_granted)."""
        now = time.monotonic()
        if now < self._pin_locked_until_monotonic:
            logger.warning("Parent PIN entry is temporarily locked after repeated failures.")
            return False

        pin_hash = load_offline_pin_hash(self.db)
        if not pin_hash:
            logger.warning("No parent PIN is configured for this device; offline unlock unavailable.")
            return False

        if verify_pin_hash(pin, pin_hash):
            self._pin_failures = 0
            self._grant_parent_override()
            return True

        self._pin_failures += 1
        if self._pin_failures >= PIN_MAX_FAILURES:
            self._pin_failures = 0
            self._pin_locked_until_monotonic = now + PIN_LOCKOUT_SEC
        return False

    def _grant_parent_override(self, seconds: int = OVERRIDE_BONUS_SEC) -> None:
        """Parent authorised locally: unlock temporarily / add 15 minutes, and log it."""
        policy = self.server_client.active_policy
        _, reason, _ = self.screen_time_mgr.evaluate_lock_status(policy)
        self.screen_time_mgr.set_manual_lock(False)
        if reason in ("OUTSIDE_ALLOWED_SCHEDULE", "MANUAL_LOCK"):
            # Extra quota would not lift these locks: open a temporary window instead
            self.screen_time_mgr.activate_parent_pause(seconds)
        else:
            self.screen_time_mgr.add_bonus_time(seconds)
        self._record_event_safe("override_granted", SYSTEM_SUBJECT, duration_sec=seconds)

    def _on_user_activity(self, payload: Dict[str, Any]) -> None:
        """Idle seconds and lock state of the child's session, reported by OGK-Tray."""
        self.screen_time_mgr.report_user_activity(
            payload.get("idle_sec"), payload.get("session_locked")
        )

    # ------------------------------------------------------------------ no-stealth guardrail
    def _on_tray_ready(self) -> None:
        """Tray confirmed its icon is visible. Resumes protection if we were halted."""
        was_halted = self.session_launcher.is_unprotected_halt
        self._last_tray_poll_monotonic = time.monotonic()
        self.session_launcher.mark_tray_ready()
        if was_halted and self.running:
            logger.info("Tray UI is visible again: resuming protection.")
            self._apply_protection()

    def _check_tray_liveness(self) -> bool:
        """A registered tray that stopped polling is gone (killed / crashed): un-register it
        so the launcher retries and, failing that, falls back to UNPROTECTED_HALT."""
        if not self.session_launcher.is_tray_registered:
            return False
        if time.monotonic() - self._last_tray_poll_monotonic <= TRAY_LIVENESS_TIMEOUT_SEC:
            return True
        logger.warning("Tray UI stopped responding; marking it disconnected.")
        self.session_launcher.mark_tray_disconnected()
        return False

    def _handle_unprotected_halt(self) -> None:
        """Invoked when Tray UI cannot be displayed after 3 attempts (FR-F5-09)."""
        logger.critical("UNPROTECTED_HALT active: Halting blocking and locking to prevent stealth monitoring.")
        # Release everything OGK changed on the system: adapter DNS and browser DoH policy
        try:
            self.net_guard.restore_original_dns()
        except Exception as e:
            logger.error("Failed restoring DNS during UNPROTECTED_HALT: %s", e)
        try:
            self.browser_guard.restore_browser_policies()
        except Exception as e:
            logger.error("Failed restoring browser policies during UNPROTECTED_HALT: %s", e)
        # Clear manual locks
        self.screen_time_mgr.set_manual_lock(False)

    def _apply_protection(self) -> None:
        """Snapshots the system state, then applies DoH-off and the DNS lock."""
        # 1. System Snapshots (an existing un-restored snapshot is never overwritten)
        self.net_guard.capture_and_save_snapshot()
        self.browser_guard.capture_and_save_snapshot()

        # 2. Enforce Browser DoH disable
        self.browser_guard.enforce_disable_doh()

        # 3. Point the adapters at 127.0.0.1 ONLY once our proxy really answers on port 53.
        #    Locking first and starting the proxy later meant a proxy that failed to start
        #    (port taken, no permission) left the whole PC without DNS.
        if getattr(self.dns_proxy, "is_running", False):
            self._lock_dns_to_proxy()
        else:
            logger.info("DNS proxy not running yet: adapter DNS stays unchanged for now.")

    def _lock_dns_to_proxy(self) -> None:
        """Proxy is up: give it the network's own resolvers as fallback, then lock DNS."""
        self.dns_proxy.set_extra_upstreams(self.net_guard.original_upstreams())
        self.net_guard.lock_ipv6 = bool(getattr(self.dns_proxy, "ipv6_active", False))
        self.net_guard.lock_dns_to_loopback()

    def start(self) -> None:
        """Initializes subsystems and starts loops."""
        logger.info("Starting OGK Service Core...")
        self.running = True
        self._last_tray_poll_monotonic = time.monotonic()

        # 1-3. Snapshot, DoH-off, DNS lock
        self._apply_protection()

        # 4. Start IPC Pipe Server
        self.ipc_server.start()

        # 5. Start background async loop for DNS Proxy & Sync Client
        threading.Thread(target=self._run_async_worker, daemon=True).start()

        # 6. Start synchronous monitoring loop (Process scanner, Screen time tick, Session check)
        threading.Thread(target=self._run_monitoring_loop, daemon=True).start()

    def _run_async_worker(self) -> None:
        """Runs the asyncio loop for DNS Proxy, Heartbeat, and WebSocket."""
        self._async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._async_loop)

        async def _main_async():
            # Start DNS Proxy; only a running proxy may take over the adapters' DNS
            if await self.dns_proxy.start():
                if self.running and not self.session_launcher.is_unprotected_halt:
                    await asyncio.get_running_loop().run_in_executor(None, self._lock_dns_to_proxy)
            else:
                conflict = self.dns_proxy.conflict_info or {}
                logger.error(
                    "EX-01: DNS proxy could not start (port 53 held by '%s', PID %s). "
                    "Adapter DNS left untouched so the PC keeps Internet access; website "
                    "filtering is unavailable until this is fixed.",
                    conflict.get("process_name", "unknown"), conflict.get("pid"))
            # Start Server Client
            await self.server_client.start()
            # Keep loop active
            while self.running:
                await asyncio.sleep(1.0)
            self.dns_proxy.stop()
            self.server_client.stop()

        self._async_loop.run_until_complete(_main_async())

    def _run_monitoring_loop(self) -> None:
        """Runs periodic checks: 1s screen time tick, 2s process scan, 3s session launcher."""
        last_scan_time = 0.0
        last_launcher_time = 0.0
        last_tamper_check_time = 0.0

        while self.running:
            try:
                now = time.time()

                # If UNPROTECTED_HALT is active, do not enforce limits
                if self.session_launcher.is_unprotected_halt:
                    time.sleep(1.0)
                    continue

                # 0. A tray that stopped polling no longer counts as visible
                self._check_tray_liveness()

                # 1. Tick screen time (every ~1s); each running app category has its own counter
                self.screen_time_mgr.tick(
                    active_categories=self.app_controller.last_running_categories
                )
                if self.screen_time_mgr.pop_tamper_event():
                    # Clock changed by hand: quota is unaffected (monotonic), but it is logged
                    self._record_event_safe("quota_warning", CLOCK_TAMPER_SUBJECT)

                # 2. Check lock status
                policy = self.server_client.active_policy
                is_locked, reason, warning = self._evaluate_lock(policy)

                # 3. Process scan & enforcement (every 2s)
                if now - last_scan_time >= 2.0:
                    last_scan_time = now
                    app_rules = policy.get("app_rules", [])
                    cat_quotas = policy.get("category_quotas", {})
                    self.app_controller.scan_and_enforce(
                        app_rules=app_rules,
                        category_quotas=cat_quotas,
                        category_used=self.screen_time_mgr.category_used_sec,
                        is_locked=is_locked,
                        policy_id=str(self.server_client.current_policy_version)
                    )

                # 4. Session launcher check (every 3s)
                if now - last_launcher_time >= 3.0:
                    last_launcher_time = now
                    self.session_launcher.trigger_launch_if_needed()

                # 5. Anti-tamper DNS check (every 10s), only while our proxy is answering
                if now - last_tamper_check_time >= 10.0 and self.dns_proxy.is_running:
                    last_tamper_check_time = now
                    self.net_guard.check_and_enforce_anti_tamper()

                time.sleep(1.0)
            except Exception as e:
                logger.error("Error in service monitoring loop: %s", e)
                time.sleep(1.0)

    def stop(self) -> None:
        """Clean shutdown and rollback."""
        logger.info("Stopping OGK Service Core...")
        self.running = False

        # Stop IPC server
        if hasattr(self, "ipc_server") and self.ipc_server:
            self.ipc_server.stop()

        # Clean rollback: restore original DNS and browser policies
        self.net_guard.restore_original_dns()
        self.browser_guard.restore_browser_policies()
        logger.info("OGK Service Core safely stopped and system restored.")


if _IS_WINDOWS and "win32serviceutil" in sys.modules:
    class OGKWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = "OGKService"
        _svc_display_name_ = f"{APP_NAME} Service"
        _svc_description_ = f"{APP_NAME} Service (Screen Time & Policy Engine)"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.core = OGKServiceCore()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            self.core.stop()

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, "")
            )
            self.core.start()
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)


def _install_console_close_handler(core: "OGKServiceCore") -> None:
    """Dev `run` mode: closing the console window, logging off or shutting down must
    still restore the adapters' DNS, or the PC is left pointing at a dead 127.0.0.1."""
    if not _IS_WINDOWS:
        return
    try:
        import win32api
        import win32con

        def _handler(ctrl_type):
            if ctrl_type in (win32con.CTRL_C_EVENT, win32con.CTRL_BREAK_EVENT,
                             win32con.CTRL_CLOSE_EVENT, win32con.CTRL_LOGOFF_EVENT,
                             win32con.CTRL_SHUTDOWN_EVENT):
                try:
                    core.stop()
                finally:
                    if ctrl_type in (win32con.CTRL_C_EVENT, win32con.CTRL_BREAK_EVENT):
                        os._exit(0)
                return True
            return False

        win32api.SetConsoleCtrlHandler(_handler, True)
    except Exception as e:
        logger.debug("Console close handler unavailable: %s", e)


def configure_scm_recovery(service_name: str = "OGKService") -> bool:
    """Configures Windows SCM recovery actions (restart service after 1 minute on crash)."""
    if not _IS_WINDOWS:
        return False
    try:
        import subprocess
        cmd = ["sc.exe", "failure", service_name, "reset=", "86400", "actions=", "restart/60000/restart/60000/restart/60000"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        logger.info("SCM recovery configuration for %s: %s", service_name, res.stdout.strip())
        return res.returncode == 0
    except Exception as e:
        logger.warning("Could not configure SCM recovery: %s", e)
        return False


# ---------------------------------------------------------------------- enrollment CLI
def compute_device_fingerprint() -> str:
    """Stable, non-reversible device fingerprint (SHA-256 hex, 64 chars)."""
    raw = f"{socket.gethostname()}|{uuid.getnode()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _say(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"))


def run_enroll_cli(
    code: str,
    server_url: Optional[str] = None,
    db_path=None,
    http_client=None,
    device_name: Optional[str] = None,
) -> int:
    """Pairs this device with the 8-character code shown on the parent dashboard and saves
    the credentials to agent.db. Touches neither DNS, registry nor the Windows service.
    Returns a process exit code (0 = paired)."""
    code = (code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{8}", code):
        _say("Ma ghep doi khong hop le: can dung 8 ky tu chu hoa / so.")
        return 2

    url = (server_url or os.getenv("OGK_SERVER_URL") or DEFAULT_ENROLL_SERVER_URL).rstrip("/")
    db = AgentDatabase(db_path if db_path is not None else DEFAULT_AGENT_DB_PATH)
    client = AgentServerClient(server_url=url, db=db, http_client=http_client)

    async def _go():
        try:
            return await client.enroll(
                pairing_code=code,
                device_fingerprint=compute_device_fingerprint(),
                device_name=device_name,
            )
        finally:
            if http_client is None and client._http_client is not None:
                await client._http_client.aclose()

    try:
        asyncio.run(_go())
    except Exception as e:
        _say(f"Ghep doi that bai: {e}")
        return 1

    # Never print tokens or secrets
    _say(f"Ghep doi thanh cong. device_id={client.device_id} child_id={client.child_id}")
    if client.active_policy:
        _say(f"Da xac minh chu ky va ap dung chinh sach phien ban {client.current_policy_version}.")
    else:
        _say("Canh bao: chinh sach ban dau khong qua duoc buoc xac minh chu ky HMAC.")
    return 0


def _build_enroll_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="win_service.py enroll",
        description=f"Pair this device with {APP_NAME} using the 8-character pairing code.",
    )
    parser.add_argument("--code", required=True, help="8-character pairing code (valid for 10 minutes)")
    parser.add_argument("--server", default=None, help=f"Server URL (default: {DEFAULT_ENROLL_SERVER_URL})")
    parser.add_argument("--db", default=None, help="Path to agent.db (default: %%PROGRAMDATA%%\\OGK\\agent.db)")
    parser.add_argument("--name", default=None, help="Device name shown to the parent (default: hostname)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "enroll":
        ns = _build_enroll_parser().parse_args(args[1:])
        return run_enroll_cli(code=ns.code, server_url=ns.server, db_path=ns.db, device_name=ns.name)

    if args and args[0] == "run":
        # Standalone runner for testing or dev mode
        core = OGKServiceCore()
        _install_console_close_handler(core)
        core.start()
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            core.stop()
    elif _IS_WINDOWS and "win32serviceutil" in sys.modules:
        win32serviceutil.HandleCommandLine(OGKWindowsService)
        if args and args[0] == "install":
            configure_scm_recovery("OGKService")
    else:
        print("Usage: python win_service.py run | enroll --code <PAIRING_CODE> [--server URL]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
