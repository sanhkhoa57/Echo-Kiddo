"""Browser DoH Policy Guard for OGK-Agent (FR-F2-06, M3).
Snapshots and enforces Registry Group Policies on Chrome, Edge, Brave, and CocCoc
to disable DNS-over-HTTPS (DnsOverHttpsMode = "off"), and provides clean rollback.
"""
import json
import logging
import sys
from typing import Dict, Any, Optional

from agent.platform.network_guard import system_changes_allowed

logger = logging.getLogger("OGK.BrowserPolicy")

_IS_WINDOWS = sys.platform == "win32"
if _IS_WINDOWS:
    import winreg
else:
    winreg = None

BROWSER_POLICY_KEYS = {
    "chrome": r"SOFTWARE\Policies\Google\Chrome",
    "edge": r"SOFTWARE\Policies\Microsoft\Edge",
    "brave": r"SOFTWARE\Policies\BraveSoftware\Brave",
    "coccoc": r"SOFTWARE\Policies\CocCoc\Browser",
}


class BrowserPolicyGuard:
    """Manages browser DoH group policies via HKLM registry with snapshot and restore."""

    def __init__(self, db=None):
        self.db = db

    def capture_and_save_snapshot(self) -> Dict[str, Any]:
        """
        Reads existing Registry values for all targeted browsers and saves to agent.db.
        """
        # Keep an un-restored snapshot (service crashed while DoH was forced off): the
        # registry currently holds OGK's values, not the user's original ones.
        if self.db and self.db.has_active_snapshot("BROWSER_REGISTRY"):
            try:
                existing = json.loads(self.db.get_snapshot("BROWSER_REGISTRY")["data_json"])
                logger.info("Keeping existing un-restored BROWSER_REGISTRY snapshot")
                return existing
            except Exception:
                pass
        snapshot = {}
        if not _IS_WINDOWS or winreg is None:
            snapshot = {b: {"exists": False, "mode": None} for b in BROWSER_POLICY_KEYS}
            if self.db:
                self.db.save_snapshot("BROWSER_REGISTRY", json.dumps(snapshot))
            return snapshot

        for browser, subkey in BROWSER_POLICY_KEYS.items():
            entry = {"exists": False, "mode": None, "templates": None}
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_READ) as key:
                    entry["exists"] = True
                    try:
                        mode_val, _ = winreg.QueryValueEx(key, "DnsOverHttpsMode")
                        entry["mode"] = mode_val
                    except FileNotFoundError:
                        pass
                    try:
                        tmpl_val, _ = winreg.QueryValueEx(key, "DnsOverHttpsTemplates")
                        entry["templates"] = tmpl_val
                    except FileNotFoundError:
                        pass
            except FileNotFoundError:
                entry["exists"] = False
            except Exception as e:
                logger.debug("Failed reading registry for %s: %s", browser, e)

            snapshot[browser] = entry

        if self.db:
            self.db.save_snapshot("BROWSER_REGISTRY", json.dumps(snapshot))
            logger.info("Saved BROWSER_REGISTRY snapshot for %d browsers", len(snapshot))

        return snapshot

    def enforce_disable_doh(self) -> None:
        """Sets DnsOverHttpsMode = 'off' across all targeted browsers in HKLM."""
        if not _IS_WINDOWS or winreg is None:
            logger.debug("Non-windows environment: skipping browser registry write.")
            return
        if not system_changes_allowed():
            logger.debug("Test mode: skipping browser registry write.")
            return

        for browser, subkey in BROWSER_POLICY_KEYS.items():
            try:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, "DnsOverHttpsMode", 0, winreg.REG_SZ, "off")
                    # Clear any templates
                    try:
                        winreg.DeleteValue(key, "DnsOverHttpsTemplates")
                    except FileNotFoundError:
                        pass
                logger.info("Enforced DnsOverHttpsMode='off' for %s", browser)
            except PermissionError:
                logger.warning("Permission denied writing HKLM registry for %s (requires Administrator)", browser)
            except Exception as e:
                logger.error("Failed setting browser policy for %s: %s", browser, e)

    def restore_browser_policies(self) -> bool:
        """Restores original Registry state from the snapshot."""
        if not self.db:
            logger.error("No database reference to restore BROWSER_REGISTRY snapshot")
            return False

        row = self.db.get_snapshot("BROWSER_REGISTRY")
        if not row or not row.get("data_json"):
            logger.warning("No BROWSER_REGISTRY snapshot found in agent.db")
            return False

        try:
            snapshot = json.loads(row["data_json"])
        except Exception:
            snapshot = {}

        if not _IS_WINDOWS or winreg is None or not system_changes_allowed():
            logger.info("Non-windows / test environment: mock restoring browser policies")
            self.db.mark_snapshot_restored("BROWSER_REGISTRY")
            return True

        success = True
        for browser, subkey in BROWSER_POLICY_KEYS.items():
            entry = snapshot.get(browser, {})
            key_existed_before = entry.get("exists", False)
            old_mode = entry.get("mode")
            old_templates = entry.get("templates")

            try:
                if not key_existed_before:
                    # Remove the created policy value or subkey
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_SET_VALUE) as key:
                            try:
                                winreg.DeleteValue(key, "DnsOverHttpsMode")
                            except FileNotFoundError:
                                pass
                    except FileNotFoundError:
                        pass
                else:
                    # Restore previous values
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_SET_VALUE) as key:
                        if old_mode is not None:
                            winreg.SetValueEx(key, "DnsOverHttpsMode", 0, winreg.REG_SZ, str(old_mode))
                        else:
                            try:
                                winreg.DeleteValue(key, "DnsOverHttpsMode")
                            except FileNotFoundError:
                                pass

                        if old_templates is not None:
                            winreg.SetValueEx(key, "DnsOverHttpsTemplates", 0, winreg.REG_SZ, str(old_templates))
                logger.info("Restored browser policy for %s", browser)
            except Exception as e:
                logger.error("Failed restoring browser policy for %s: %s", browser, e)
                success = False

        if success and self.db:
            self.db.mark_snapshot_restored("BROWSER_REGISTRY")
        return success
