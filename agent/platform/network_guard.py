"""Network DNS Guard for OGK-Agent (FR-F2-07, M3).
Snapshots adapter DNS configuration into agent.db before locking to the local proxy.
Monitors tampering, flushes Windows resolver cache, and restores original DNS cleanly.

Adapter DNS is read from the registry (Tcpip / Tcpip6 Interfaces), not by parsing netsh
text: netsh output is localised (Vietnamese Windows prints different labels) and its
layout put the first server on the label line, which the old parser dropped.
"""
import ctypes
import ipaddress
import json
import logging
import os
import subprocess
import sys
from typing import List, Dict, Any, Optional

logger = logging.getLogger("OGK.NetworkGuard")

_IS_WINDOWS = sys.platform == "win32"
try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - non-Windows
    winreg = None

LOOPBACK_V4 = "127.0.0.1"
LOOPBACK_V6 = "::1"

_NET_CLASS = r"SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}"
_TCPIP4 = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
_TCPIP6 = r"SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters\Interfaces"


def system_changes_allowed() -> bool:
    """The automated test suite (OGK_TESTING=1) must never rewrite the real adapters or
    registry of the machine it runs on, even when pytest happens to run as admin."""
    if os.getenv("OGK_ALLOW_SYSTEM_CHANGES") == "1":
        return True
    return os.getenv("OGK_TESTING") != "1"


def flush_dns_cache() -> bool:
    """Calls Windows dnsapi.dll DnsFlushResolverCache to immediately invalidate DNS cache."""
    if _IS_WINDOWS:
        try:
            dnsapi = ctypes.windll.dnsapi
            result = dnsapi.DnsFlushResolverCache()
            logger.debug("DnsFlushResolverCache returned: %d", result)
            return result == 1
        except Exception as e:
            logger.debug("Failed to call DnsFlushResolverCache via ctypes: %s", e)

    # Fallback to ipconfig /flushdns
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, check=False)
        return True
    except Exception:
        return False


def _split_servers(raw: Any) -> List[str]:
    """Registry NameServer values use commas or spaces; keep valid IP literals only."""
    if not raw or not isinstance(raw, str):
        return []
    out = []
    for token in raw.replace(",", " ").split():
        token = token.split("%")[0].strip()
        try:
            ipaddress.ip_address(token)
        except ValueError:
            continue
        if token not in out:
            out.append(token)
    return out


def _reg_value(root_path: str, guid: str, name: str) -> Optional[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{root_path}\\{guid}") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value if isinstance(value, str) else None
    except OSError:
        return None


def _adapter_name(guid: str) -> Optional[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{_NET_CLASS}\\{guid}\\Connection") as key:
            value, _ = winreg.QueryValueEx(key, "Name")
            return str(value) if value else None
    except OSError:
        return None


def _skip_adapter(name: str) -> bool:
    low = (name or "").lower()
    return not low or "loopback" in low or "pseudo" in low


def _netsh(args: str) -> bool:
    """Runs one netsh command line (a string, so adapter names with spaces stay quoted).
    netsh keywords are never localised, only its output is."""
    if not system_changes_allowed():
        logger.debug("Test mode: skipped netsh %s", args)
        return True
    try:
        res = subprocess.run(f"netsh {args}", capture_output=True, text=True, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if res.returncode != 0:
            logger.warning("netsh %s failed: %s", args, (res.stdout or res.stderr).strip())
        return res.returncode == 0
    except Exception as e:
        logger.warning("netsh %s failed: %s", args, e)
        return False


def _q(name: str) -> str:
    return '"' + name.replace('"', "") + '"'


class NetworkDnsGuard:
    """Safely manages DNS lock on active network interfaces with snapshot rollback."""

    def __init__(self, db=None):
        self.db = db
        # Set by the service once the proxy also listens on [::1]:53
        self.lock_ipv6: bool = False

    def capture_and_save_snapshot(self) -> List[Dict[str, Any]]:
        """
        Captures current DNS configuration of all adapters and saves to agent.db.
        Returns the snapshot list.
        """
        # After a crash the adapters still point at 127.0.0.1: re-capturing now would
        # overwrite the genuine original configuration. Keep the un-restored snapshot.
        if self.db and self.db.has_active_snapshot("NETWORK_DNS"):
            try:
                existing = json.loads(self.db.get_snapshot("NETWORK_DNS")["data_json"])
                logger.info("Keeping existing un-restored NETWORK_DNS snapshot")
                return existing
            except Exception:
                pass
        snapshot = self._get_current_adapters_config()
        if self.db:
            self.db.save_snapshot("NETWORK_DNS", json.dumps(snapshot))
            logger.info("Saved NETWORK_DNS snapshot with %d interfaces", len(snapshot))
        return snapshot

    def _get_current_adapters_config(self) -> List[Dict[str, Any]]:
        """Per adapter: name, guid, dhcp (no static IPv4 DNS), dns (effective IPv4 servers),
        dns6_static (static IPv6 servers). Read from the registry: language independent."""
        if not _IS_WINDOWS or winreg is None:
            return [{"name": "Mock-Adapter", "dhcp": True, "dns": [], "dns6_static": []}]

        adapters: List[Dict[str, Any]] = []
        try:
            import psutil
            present = set(psutil.net_if_stats().keys())
        except Exception:
            present = set()
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _TCPIP4) as root:
                index = 0
                while True:
                    try:
                        guid = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    name = _adapter_name(guid)
                    if not name or (present and name not in present):
                        continue  # stale registry entry, not an adapter Windows has now
                    static4 = _split_servers(_reg_value(_TCPIP4, guid, "NameServer"))
                    dhcp4 = _split_servers(_reg_value(_TCPIP4, guid, "DhcpNameServer"))
                    static6 = _split_servers(_reg_value(_TCPIP6, guid, "NameServer"))
                    adapters.append({
                        "name": name,
                        "guid": guid,
                        "dhcp": not static4,
                        "dns": static4 or dhcp4,
                        "dns6_static": static6,
                    })
        except OSError as e:
            logger.debug("Failed to read adapter DNS from registry: %s", e)
        return adapters

    def original_upstreams(self) -> List[str]:
        """IPv4 DNS servers the network gave this PC before OGK (from the snapshot), so the
        proxy keeps working on networks that block 1.1.1.1 / 8.8.8.8 (schools, offices)."""
        if not self.db:
            return []
        try:
            row = self.db.get_snapshot("NETWORK_DNS")
            snapshot = json.loads(row["data_json"]) if row and row.get("data_json") else []
        except Exception:
            return []
        out: List[str] = []
        for adapter in snapshot if isinstance(snapshot, list) else []:
            for ip in adapter.get("dns", []) or []:
                try:
                    addr = ipaddress.ip_address(ip)
                except ValueError:
                    continue
                if addr.version == 4 and not addr.is_loopback and ip not in out:
                    out.append(ip)
        return out

    def _lock_adapter(self, name: str) -> bool:
        ok = _netsh(f"interface ipv4 set dnsservers name={_q(name)} source=static "
                    f"address={LOOPBACK_V4} register=primary validate=no")
        if self.lock_ipv6:
            # Otherwise Windows may ask the router's IPv6 DNS directly and skip the filter
            _netsh(f"interface ipv6 set dnsservers name={_q(name)} source=static "
                   f"address={LOOPBACK_V6} register=primary validate=no")
        return ok

    def lock_dns_to_loopback(self, port_conflict: bool = False) -> bool:
        """
        Sets DNS server on all interfaces to the local proxy and flushes cache.
        Adheres to EX-01: Does NOT lock if port 53 is in conflict to avoid internet outage.
        """
        if port_conflict:
            logger.warning("EX-01: Port 53 conflict detected. Aborting DNS lock to 127.0.0.1 to prevent network outage.")
            return False

        if not _IS_WINDOWS:
            logger.debug("Non-windows environment: skipping netsh DNS lock.")
            return True

        for adapter in self._get_current_adapters_config():
            name = adapter.get("name", "")
            if _skip_adapter(name):
                continue
            if self._lock_adapter(name):
                logger.info("Locked adapter '%s' DNS to %s", name, LOOPBACK_V4)

        flush_dns_cache()
        return True

    def check_and_enforce_anti_tamper(self) -> bool:
        """
        Detects if DNS was altered (e.g. to 8.8.8.8 or back to DHCP) and reapplies the lock.
        Returns True if tampering was detected and corrected.
        """
        if not _IS_WINDOWS:
            return False

        tampered = False
        for adapter in self._get_current_adapters_config():
            name = adapter.get("name", "")
            if _skip_adapter(name):
                continue
            dns_list = adapter.get("dns", [])
            v4_bad = adapter.get("dhcp", True) or not dns_list or dns_list[0] != LOOPBACK_V4
            v6_static = adapter.get("dns6_static", [])
            v6_bad = self.lock_ipv6 and (not v6_static or v6_static[0] != LOOPBACK_V6)
            if v4_bad or v6_bad:
                logger.warning("DNS tampering detected on '%s'! Current: %s / %s. Re-locking.",
                               name, dns_list, v6_static)
                self._lock_adapter(name)
                tampered = True

        if tampered:
            flush_dns_cache()

        return tampered

    def restore_original_dns(self) -> bool:
        """Restores network adapters to their initial state from the snapshot."""
        if not self.db:
            logger.error("No database reference to restore NETWORK_DNS snapshot")
            return False

        row = self.db.get_snapshot("NETWORK_DNS")
        if not row or not row.get("data_json"):
            logger.warning("No NETWORK_DNS snapshot found in agent.db")
            return False

        try:
            snapshot = json.loads(row["data_json"])
        except Exception:
            snapshot = []

        if not _IS_WINDOWS:
            logger.info("Non-windows environment: mock restoring DNS snapshot")
            self.db.mark_snapshot_restored("NETWORK_DNS")
            return True

        success = True
        for adapter in snapshot:
            name = adapter.get("name")
            if not name:
                continue
            is_dhcp = adapter.get("dhcp", True)
            dns_servers = [ip for ip in adapter.get("dns", []) if ip != LOOPBACK_V4]
            n = _q(name)

            if is_dhcp or not dns_servers:
                ok = _netsh(f"interface ipv4 set dnsservers name={n} source=dhcp")
                logger.info("Restored '%s' to DHCP DNS", name)
            else:
                ok = _netsh(f"interface ipv4 set dnsservers name={n} source=static "
                            f"address={dns_servers[0]} register=primary validate=no")
                for i, sec in enumerate(dns_servers[1:], start=2):
                    _netsh(f"interface ipv4 add dnsservers name={n} address={sec} index={i} validate=no")
                logger.info("Restored '%s' to static DNS: %s", name, dns_servers)

            v6 = [ip for ip in adapter.get("dns6_static", []) or [] if ip != LOOPBACK_V6]
            if v6:
                _netsh(f"interface ipv6 set dnsservers name={n} source=static "
                       f"address={v6[0]} register=primary validate=no")
                for i, sec in enumerate(v6[1:], start=2):
                    _netsh(f"interface ipv6 add dnsservers name={n} address={sec} index={i} validate=no")
            else:
                _netsh(f"interface ipv6 set dnsservers name={n} source=dhcp")
            success = success and ok

        flush_dns_cache()
        if success and self.db:
            self.db.mark_snapshot_restored("NETWORK_DNS")
        return success
