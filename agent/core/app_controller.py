"""App Controller and PE Inspector for OGK-Agent (FR-F2-01, FR-F2-02, Section 8.1).
Scans running processes, verifies SHA-256 with LRU cache, inspects PE Header OriginalFileName,
matches against Blocklist/Allowlist and category quotas, and terminates violating processes.
"""
import os
import hashlib
import logging
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Set, Tuple, Callable
import psutil

logger = logging.getLogger("OGK.AppController")

# System-critical processes that must NEVER be terminated
WHITELISTED_SYSTEM_EXES = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "svchost.exe", "fontdrvhost.exe",
    "dwm.exe", "explorer.exe", "taskhostw.exe", "sihost.exe", "ctfmon.exe",
    "conhost.exe", "cmd.exe", "powershell.exe", "python.exe", "py.exe",
    "pythonw.exe", "winlogon.exe", "logonui.exe", "lockapp.exe", "userinit.exe",
    "runtimebroker.exe", "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe",
    "securityhealthsystray.exe", "securityhealthservice.exe", "audiodg.exe",
    "dllhost.exe", "wudfhost.exe", "spoolsv.exe", "msmpeng.exe", "smartscreen.exe",
    "ogk_service.exe", "ogk_tray.exe"
}


def get_process_session_id(pid: int) -> Optional[int]:
    """Windows session of a process (0 = services, >=1 = interactive user), or None."""
    try:
        import ctypes
        from ctypes import wintypes
        sid = wintypes.DWORD()
        if ctypes.windll.kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(sid)):
            return int(sid.value)
    except Exception:
        pass
    return None


def budget_exhausted(category: str, cat_quotas: Dict[str, Any], cat_used: Dict[str, int]) -> Tuple[bool, int]:
    """(over_budget, limit_min). A negative budget (-1) means unlimited."""
    try:
        limit_min = int(cat_quotas[category])
    except (KeyError, TypeError, ValueError):
        return False, -1
    if limit_min < 0:
        return False, limit_min
    return cat_used.get(category, 0) >= limit_min * 60, limit_min

_HAS_WIN32 = False
try:
    import win32api
    _HAS_WIN32 = True
except ImportError:
    pass


def extract_pe_original_filename(exe_path: str) -> Optional[str]:
    """
    Extracts the OriginalFileName from Windows PE version resource info.
    Returns None if absent or running on non-Windows/test environment.
    """
    if not _HAS_WIN32 or not os.path.exists(exe_path):
        return None

    try:
        info = win32api.GetFileVersionInfo(exe_path, "\\")
        # Try language/codepage translations first
        try:
            translations = win32api.VerQueryValue(info, "\\VarFileInfo\\Translation")
            if translations:
                lang, codepage = translations[0]
                str_path = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\OriginalFilename"
                orig = win32api.VerQueryValue(info, str_path)
                if orig:
                    return str(orig).strip()
        except Exception:
            pass

        # Fallback to standard language blocks
        for sub in ("040904b0", "040904e4", "000004b0", "04090000"):
            try:
                orig = win32api.VerQueryValue(info, f"\\StringFileInfo\\{sub}\\OriginalFilename")
                if orig:
                    return str(orig).strip()
            except Exception:
                pass
    except Exception:
        pass
    return None


class Sha256LruCache:
    """LRU Cache for file hashes and PE original file names (Section 8.1, maxsize=512)."""

    def __init__(self, maxsize: int = 512):
        self.maxsize = maxsize
        self._cache: OrderedDict[Tuple[str, int, int], Tuple[str, Optional[str]]] = OrderedDict()

    def get_or_compute(self, exe_path: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Returns (sha256_hex, original_filename).
        Cache key is (normalized_path, mtime_ns, size_bytes).
        """
        if not exe_path or not os.path.exists(exe_path):
            return None, None

        try:
            st = os.stat(exe_path)
            cache_key = (os.path.normcase(os.path.abspath(exe_path)), st.st_mtime_ns, st.st_size)
        except Exception:
            return None, None

        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # Cache miss: compute SHA-256
        sha256_hex = None
        try:
            h = hashlib.sha256()
            with open(exe_path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            sha256_hex = h.hexdigest().lower()
        except Exception as e:
            logger.debug("Failed to hash file %s: %s", exe_path, e)

        # Extract OriginalFileName
        orig_name = extract_pe_original_filename(exe_path)

        result = (sha256_hex, orig_name)

        if len(self._cache) >= self.maxsize:
            self._cache.popitem(last=False)
        self._cache[cache_key] = result
        return result


class AppController:
    """Monitors running processes, detects violations, and enforces app blocking."""

    def __init__(self, event_buffer=None, on_blocked_callback: Optional[Callable[[str, str], None]] = None):
        self.event_buffer = event_buffer
        self.on_blocked_callback = on_blocked_callback
        self.cache = Sha256LruCache(maxsize=512)
        # Categories (from matched app rules) that had a running program in the last scan;
        # the service feeds them to ScreenTimeManager so each category has its own counter.
        self.last_running_categories: Set[str] = set()

    def scan_and_enforce(
        self,
        app_rules: List[Dict[str, Any]],
        category_quotas: Optional[Dict[str, int]] = None,
        category_used: Optional[Dict[str, int]] = None,
        is_locked: bool = False,
        policy_id: str = "default_policy",
        dry_run: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Scans running processes and terminates any blocked or overtime apps.
        Returns a list of violation records.
        """
        violations = []
        running_categories: Set[str] = set()
        cat_quotas = category_quotas or {}
        cat_used = category_used or {}

        # Index app rules for fast lookup
        rule_by_exe: Dict[str, Dict[str, Any]] = {}
        rule_by_sha256: Dict[str, Dict[str, Any]] = {}
        rule_by_orig_name: Dict[str, Dict[str, Any]] = {}

        for rule in app_rules:
            if rule.get("exe_name"):
                rule_by_exe[rule["exe_name"].lower()] = rule
            if rule.get("sha256"):
                rule_by_sha256[rule["sha256"].lower()] = rule
            if rule.get("original_filename"):
                rule_by_orig_name[rule["original_filename"].lower()] = rule

        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                proc_name = (proc.info.get('name') or "").lower()
                exe_path = proc.info.get('exe') or ""

                if not proc_name or proc_name in WHITELISTED_SYSTEM_EXES:
                    continue

                # Only compute SHA-256 / PE OriginalFileName if we have rules requiring them
                # or if the process name already matches a rule
                needs_deep_inspect = bool(rule_by_sha256 or rule_by_orig_name) or (proc_name in rule_by_exe)
                sha256_hex, orig_name = (None, None)
                if exe_path and needs_deep_inspect:
                    sha256_hex, orig_name = self.cache.get_or_compute(exe_path)
                orig_name_clean = orig_name.lower() if orig_name else None

                # 1. Match specific rule (Priority: SHA-256 > OriginalFileName > Exe Name)
                matched_rule = None
                if sha256_hex and sha256_hex in rule_by_sha256:
                    matched_rule = rule_by_sha256[sha256_hex]
                elif orig_name_clean and orig_name_clean in rule_by_orig_name:
                    matched_rule = rule_by_orig_name[orig_name_clean]
                elif proc_name in rule_by_exe:
                    matched_rule = rule_by_exe[proc_name]

                is_blocked = False
                reason = ""
                category = matched_rule.get("category", "unclassified") if matched_rule else "unclassified"

                # Check action in rule
                if matched_rule:
                    if matched_rule.get("action") == "block":
                        is_blocked = True
                        reason = f"Application is on the blocklist ({matched_rule.get('reason', 'Policy block')})"

                # Check category quota (e.g. gaming limit reached). Only programs the parent
                # classified (matched rule) count; unknown processes are never budget-killed.
                if not is_blocked and matched_rule and category in cat_quotas:
                    over, limit_min = budget_exhausted(category, cat_quotas, cat_used)
                    if over:
                        is_blocked = True
                        reason = f"Category '{category}' daily limit ({limit_min} min) reached"

                # Check global lock: only the child's own programs in the interactive session,
                # never services running in session 0.
                if not is_blocked and is_locked:
                    session_id = get_process_session_id(proc.info['pid'])
                    if session_id is not None and session_id != 0:
                        is_blocked = True
                        reason = "Screen time lock active (outside allowed schedule or daily quota reached)"

                if matched_rule and not is_blocked:
                    running_categories.add(category)

                if is_blocked:
                    # Terminate the process if not in dry_run
                    if not dry_run:
                        self._terminate_process(proc, proc_name, reason)

                    violation = {
                        "pid": proc.info['pid'],
                        "name": proc_name,
                        "sha256": sha256_hex,
                        "original_filename": orig_name,
                        "reason": reason,
                        "category": category,
                    }
                    violations.append(violation)

                    # Emit blocked_app event to buffer
                    if self.event_buffer:
                        try:
                            self.event_buffer.record_event(
                                event_type="blocked_app",
                                subject=proc_name,
                                policy_id=policy_id,
                                duration_sec=0
                            )
                        except Exception as ev_err:
                            # Logging must never suppress the child-facing notification below
                            logger.debug("Could not record blocked_app event: %s", ev_err)

                    # Notify UI callback
                    if self.on_blocked_callback:
                        try:
                            self.on_blocked_callback(proc_name, reason)
                        except Exception as cb_err:
                            logger.error("Callback error: %s", cb_err)

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as e:
                logger.debug("Error inspecting process %s: %s", proc.info.get('pid'), e)

        if not dry_run:
            self.last_running_categories = running_categories
        return violations

    def _terminate_process(self, proc: psutil.Process, name: str, reason: str) -> None:
        """Terminates process safely and logs action."""
        try:
            logger.info("Terminating blocked process '%s' (PID %d): %s", name, proc.pid, reason)
            proc.terminate()
            # Wait up to 1 second before hard kill
            try:
                proc.wait(timeout=1.0)
            except psutil.TimeoutExpired:
                proc.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            logger.warning("Access denied when trying to terminate '%s' (PID %d)", name, proc.pid)
        except Exception as e:
            logger.error("Failed to terminate process '%s' (PID %d): %s", name, proc.pid, e)
