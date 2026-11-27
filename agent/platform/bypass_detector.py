"""Bypass Detector for OGK-Agent (FR-F2-08, M3).
Scans for VPN virtual adapters (TAP/TUN/WireGuard/WARP), Windows System Proxy,
and DNS-over-TLS (port 853) traffic.
"""
import logging
import sys
from typing import List, Dict, Any, Optional
import psutil

logger = logging.getLogger("OGK.BypassDetector")

_IS_WINDOWS = sys.platform == "win32"
if _IS_WINDOWS:
    import winreg
else:
    winreg = None

VPN_ADAPTER_KEYWORDS = [
    "tap", "tun", "wireguard", "warp", "openvpn",
    "nord", "proton", "expressvpn", "tailscale",
    "zerotier", "wintun", "surfshark", "fortinet"
]


class BypassDetector:
    """Detects active circumvention vectors on Windows."""

    def __init__(self, event_buffer=None):
        self.event_buffer = event_buffer

    def detect_vpn_adapters(self) -> List[str]:
        """Scans network interfaces for known VPN adapter signatures."""
        detected = []
        try:
            adapters = psutil.net_if_addrs()
            stats = psutil.net_if_stats()

            for name in adapters.keys():
                name_lower = name.lower()
                # Check if interface is up and matches any VPN keywords
                is_up = stats.get(name).isup if name in stats else True
                if is_up and any(kw in name_lower for kw in VPN_ADAPTER_KEYWORDS):
                    detected.append(name)
        except Exception as e:
            logger.debug("Error scanning network interfaces for VPN: %s", e)

        return detected

    def detect_system_proxy(self) -> Dict[str, Any]:
        """Checks if Windows Internet Settings has System Proxy enabled."""
        result = {"enabled": False, "server": None, "pac_url": None}
        if not _IS_WINDOWS or winreg is None:
            return result

        try:
            reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ) as key:
                try:
                    proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    if proxy_enable == 1:
                        result["enabled"] = True
                        try:
                            server, _ = winreg.QueryValueEx(key, "ProxyServer")
                            result["server"] = str(server)
                        except FileNotFoundError:
                            pass
                except FileNotFoundError:
                    pass

                try:
                    pac, _ = winreg.QueryValueEx(key, "AutoConfigURL")
                    if pac:
                        result["pac_url"] = str(pac)
                except FileNotFoundError:
                    pass
        except Exception as e:
            logger.debug("Error querying system proxy registry: %s", e)

        return result

    def detect_dot_connections(self) -> List[Dict[str, Any]]:
        """Scans active network connections for outbound connections to port 853 (DoT)."""
        detected = []
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr:
                    if conn.raddr.port == 853:
                        detected.append({
                            "pid": conn.pid,
                            "remote_ip": conn.raddr.ip,
                            "port": conn.raddr.port,
                        })
        except Exception as e:
            logger.debug("Error scanning network connections for DoT: %s", e)

        return detected

    def scan_all_bypass_vectors(self) -> Dict[str, Any]:
        """Runs a complete bypass check across VPN, Proxy, and DoT."""
        vpn = self.detect_vpn_adapters()
        proxy = self.detect_system_proxy()
        dot = self.detect_dot_connections()

        has_bypass = bool(vpn or proxy.get("enabled") or dot)

        if has_bypass:
            logger.warning("Bypass vectors detected! VPN: %s, Proxy: %s, DoT: %d", vpn, proxy, len(dot))

        return {
            "has_bypass": has_bypass,
            "vpn_adapters": vpn,
            "system_proxy": proxy,
            "dot_connections": dot,
        }
