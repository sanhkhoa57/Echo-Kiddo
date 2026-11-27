"""Server Sync Client for OGK-Agent (FR-LC-01, FR-LC-02, FR-LC-03, FR-LC-04, Section 5).
Manages Enrollment, 60s Heartbeat, Event Batch Upload, Policy Sync, and WebSocket Urgent Command Hub.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable
import httpx
import websockets

from agent.core.policy_verifier import (
    verify_policy,
    decode_policy,
    default_policy_secret,
    is_server_format,
)

logger = logging.getLogger("OGK.ServerClient")


class CertificatePinError(RuntimeError):
    """The server presented a certificate other than the pinned one."""


class AgentServerClient:
    """Manages all communications between OGK-Agent and OGK-Server."""

    def __init__(
        self,
        server_url: str,
        device_id: str = "",
        child_id: str = "",
        access_token: str = "",
        refresh_token: str = "",
        device_secret: Optional[str] = None,
        pinned_cert_fingerprint: Optional[str] = None,
        event_buffer=None,
        screen_time_mgr=None,
        app_controller=None,
        domain_engine=None,
        db=None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id
        self.child_id = child_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.device_secret = device_secret
        # SHA-256 of the server certificate (DER), as printed by scripts/setup_lab.py
        self.pinned_cert_fingerprint = pinned_cert_fingerprint or os.getenv("OGK_PINNED_CERT_FINGERPRINT") or None

        self.event_buffer = event_buffer
        self.screen_time_mgr = screen_time_mgr
        self.app_controller = app_controller
        self.domain_engine = domain_engine
        self.db = db

        self._http_client = http_client
        self.current_policy_version: int = 1
        self.active_policy: Dict[str, Any] = {}
        self.ws_connected: bool = False
        self._running: bool = False
        # Command ids already executed (pending commands are re-delivered by heartbeat)
        self._executed_command_ids: deque = deque(maxlen=512)

        # Pairing identity survives restarts: fill anything not passed in from agent.db
        self.load_saved_credentials()
        self._sync_identity()

    # ------------------------------------------------------------------ credentials
    def policy_secret(self) -> str:
        """Key for verifying policy / command HMACs: issued at enrollment, else env / lab default."""
        return self.device_secret or default_policy_secret()

    def _sync_identity(self) -> None:
        """Propagates device_id / child_id to the event buffer so events can be recorded."""
        if self.event_buffer is not None and self.device_id and self.child_id:
            try:
                self.event_buffer.device_id = self.device_id
                self.event_buffer.child_id = self.child_id
            except Exception:
                pass

    def load_saved_credentials(self) -> bool:
        """Fills device_id / child_id / tokens / policy secret that were not passed to the
        constructor from agent.db. Returns True when a paired identity is available."""
        if not self.db or not hasattr(self.db, "get_device_credentials"):
            return bool(self.device_id and self.access_token)
        try:
            creds = self.db.get_device_credentials()
        except Exception as e:
            logger.debug("Could not read device credentials: %s", e)
            creds = None
        if isinstance(creds, dict):
            self.device_id = self.device_id or creds.get("device_id") or ""
            self.child_id = self.child_id or creds.get("child_id") or ""
            self.access_token = self.access_token or creds.get("access_token") or ""
            self.refresh_token = self.refresh_token or creds.get("refresh_token") or ""
            self.device_secret = self.device_secret or creds.get("policy_hmac_secret") or None
        self._sync_identity()
        return bool(self.device_id and self.access_token)

    def _persist_credentials(self, **extra: Any) -> None:
        """Saves the current pairing identity to agent.db."""
        if not self.db or not hasattr(self.db, "save_device_credentials"):
            return
        try:
            self.db.save_device_credentials(
                device_id=self.device_id,
                child_id=self.child_id,
                access_token=self.access_token,
                refresh_token=self.refresh_token,
                server_url=self.server_url,
                **extra,
            )
        except Exception as e:
            logger.error("Could not persist device credentials: %s", e)

    def verify_cert_fingerprint(self, cert_der: bytes) -> bool:
        """Verifies server certificate SHA-256 fingerprint against pinned value."""
        if not self.pinned_cert_fingerprint:
            return True
        import hashlib
        computed = hashlib.sha256(cert_der).hexdigest().lower()
        expected = self.pinned_cert_fingerprint.lower().replace(":", "").replace(" ", "")
        return computed == expected

    def _fetch_peer_cert_der(self, host: str, port: int) -> bytes:
        """Opens a TLS connection and returns the server's leaf certificate (DER).
        Chain validation is not needed here: the pin itself is the trust decision."""
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=5.0) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                return tls.getpeercert(binary_form=True) or b""

    async def enforce_certificate_pin(self) -> Optional[bytes]:
        """Certificate Pinning (F5): refuses to talk to an HTTPS/WSS server whose certificate
        does not match the pinned SHA-256 fingerprint. No-op for http:// or when no pin is set."""
        if not self.pinned_cert_fingerprint:
            return None
        from urllib.parse import urlsplit
        parts = urlsplit(self.server_url)
        if parts.scheme not in ("https", "wss"):
            return None
        der = await asyncio.get_running_loop().run_in_executor(
            None, self._fetch_peer_cert_der, parts.hostname, parts.port or 443
        )
        if not der or not self.verify_cert_fingerprint(der):
            raise CertificatePinError(
                f"Server certificate for {parts.hostname} does not match the pinned fingerprint."
            )
        return der

    def _pinned_ssl_context(self, der: bytes):
        """TLS context that trusts exactly the pinned certificate and nothing else, so the
        connection that carries data is held to the same certificate the pin check saw."""
        import ssl
        return ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(der))

    def _ca_bundle(self) -> Optional[str]:
        """OGK_CA_CERT if it exists, else certs/server.crt in the project (lab CA)."""
        from pathlib import Path
        for candidate in (os.getenv("OGK_CA_CERT"), "certs/server.crt",
                          str(Path(__file__).resolve().parents[2] / "certs" / "server.crt")):
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Returns shared or new async httpx client supporting custom CA/cert pinning."""
        if self._http_client is not None and not self._http_client.is_closed:
            return self._http_client
        # A new connection pool is only created after the pinned certificate is confirmed
        pinned_der = await self.enforce_certificate_pin()
        ca_cert = self._ca_bundle()
        if pinned_der:
            verify: Any = self._pinned_ssl_context(pinned_der)
        elif ca_cert:
            verify = ca_cert
        elif os.getenv("OGK_INSECURE_TLS") == "1":
            verify = False
        else:
            verify = True
        self._http_client = httpx.AsyncClient(timeout=10.0, verify=verify)
        return self._http_client

    async def enroll(
        self,
        pairing_code: str,
        device_fingerprint: str,
        windows_user_sid: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes device enrollment using pairing code (FR-LC-01).
        Stores credentials and signed initial policy.
        """
        client = await self.get_http_client()
        url = f"{self.server_url}/api/v1/enroll"
        # Must match server DeviceEnrollRequest exactly (extra fields are forbidden)
        payload: Dict[str, Any] = {
            "pairing_code": pairing_code,
            "device_name": (device_name or socket.gethostname() or "OGK-Device")[:100],
            "device_fingerprint": device_fingerprint,
        }
        if windows_user_sid:
            payload["windows_user_sid"] = windows_user_sid

        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Enrollment failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        self.device_id = data["device_id"]
        self.child_id = data["child_id"]
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        if data.get("policy_hmac_secret"):
            self.device_secret = data["policy_hmac_secret"]

        self._sync_identity()
        self._persist_credentials(
            offline_pin_hash=data.get("offline_pin_hash"),
            policy_hmac_secret=self.device_secret,
        )

        # Process initial signed policy
        policy = data.get("policy", {})
        if policy and not self._apply_policy(policy):
            logger.error("Enrollment succeeded but the initial policy failed verification.")

        logger.info("Device successfully enrolled! Device ID: %s, Child ID: %s", self.device_id, self.child_id)
        return data

    async def refresh_access_token(self) -> bool:
        """Refreshes expired access_token using refresh_token."""
        if not self.refresh_token:
            return False

        client = await self.get_http_client()
        url = f"{self.server_url}/api/v1/auth/device/refresh"
        try:
            # Server DeviceRefreshRequest accepts only `refresh_token`
            resp = await client.post(url, json={"refresh_token": self.refresh_token})
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data["access_token"]
                self._persist_credentials()
                logger.debug("Access token refreshed successfully.")
                return True
            else:
                logger.warning("Token refresh rejected: %s", resp.text)
                return False
        except Exception as e:
            logger.error("Token refresh network error: %s", e)
            return False

    async def send_heartbeat(self) -> Dict[str, Any]:
        """
        Sends 60s heartbeat to server (FR-LC-02).
        Computes clock drift and processes pending commands.
        """
        client = await self.get_http_client()
        url = f"{self.server_url}/api/v1/heartbeat"

        used_sec = self.screen_time_mgr.used_total_sec if self.screen_time_mgr else 0
        mono_sec = self.screen_time_mgr.last_monotonic if self.screen_time_mgr else 0.0

        # Must match server HeartbeatRequest exactly (extra="forbid"); the device identity
        # comes from the Bearer token, not from the body.
        payload = {
            "used_sec": max(0, int(used_sec)),
            "local_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_sec": max(0.0, float(mono_sec)),
            "policy_version": max(0, int(self.current_policy_version)),
        }
        headers = {"Authorization": f"Bearer {self.access_token}"}

        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 401:
            # Token expired, try refreshing
            if await self.refresh_access_token():
                headers = {"Authorization": f"Bearer {self.access_token}"}
                resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"Heartbeat failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        server_utc = data.get("server_utc")
        if server_utc and self.screen_time_mgr:
            self.screen_time_mgr.verify_clock_drift(server_utc)

        # Check policy version mismatch
        latest_ver = data.get("latest_policy_version", self.current_policy_version)
        if latest_ver > self.current_policy_version:
            logger.info("Newer policy version detected (%d > %d). Syncing policy.", latest_ver, self.current_policy_version)
            await self.fetch_and_apply_policy()

        # Execute any pending commands
        pending_cmds = data.get("pending_commands", [])
        for cmd in pending_cmds:
            await self.handle_command_envelope(cmd)

        return data

    async def upload_event_batch(self) -> int:
        """
        Uploads pending events from event_buffer to server (FR-LC-04, FR-F3-01).
        Uses idempotency_key to prevent duplicate ingestion.
        Returns count of successfully synced events.
        """
        if not self.event_buffer:
            return 0

        batch = self.event_buffer.get_pending_batch(limit=200)
        if not batch:
            return 0

        client = await self.get_http_client()
        url = f"{self.server_url}/api/v1/events/batch"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        # Filter fields strictly
        clean_events = []
        for item in batch:
            clean_events.append({
                "idempotency_key": item["idempotency_key"],
                "ts": item["ts"],
                "device_id": item["device_id"],
                "child_id": item["child_id"],
                "type": item["type"],
                "subject": item["subject"],
                "duration_sec": item.get("duration_sec", 0),
                "policy_id": item.get("policy_id", "default_policy"),
            })

        resp = await client.post(url, json={"events": clean_events}, headers=headers)
        if resp.status_code == 401:
            if await self.refresh_access_token():
                headers = {"Authorization": f"Bearer {self.access_token}"}
                resp = await client.post(url, json={"events": clean_events}, headers=headers)

        if resp.status_code == 200:
            # Mark uploaded events as synced
            keys = [e["idempotency_key"] for e in clean_events]
            self.event_buffer.mark_synced(keys)
            logger.info("Successfully synced %d events to server.", len(keys))
            return len(keys)
        else:
            logger.warning("Event batch upload failed (%d): %s", resp.status_code, resp.text)
            return 0

    async def fetch_and_apply_policy(self) -> bool:
        """Fetches signed policy from GET /api/v1/policy and verifies HMAC signature."""
        client = await self.get_http_client()
        url = f"{self.server_url}/api/v1/policy"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        resp = await client.get(url, headers=headers)
        if resp.status_code == 401:
            if await self.refresh_access_token():
                headers = {"Authorization": f"Bearer {self.access_token}"}
                resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.error("Failed to fetch policy (%d): %s", resp.status_code, resp.text)
            return False

        policy = resp.json()
        applied = self._apply_policy(policy)
        # Unsigned metadata: refresh the parent-PIN hash only alongside a verified policy
        if applied and isinstance(policy, dict) and policy.get("offline_pin_hash") and self.device_id:
            self._persist_credentials(offline_pin_hash=policy["offline_pin_hash"])
        return applied

    def _apply_policy(self, policy: Dict[str, Any]) -> bool:
        """Verifies policy signature and applies rules to runtime engines."""
        # 1. Verify signature
        is_valid, reason = verify_policy(policy, self.policy_secret())
        if not is_valid:
            logger.error("Policy rejected! Reason: %s", reason)
            return False

        # The signing key is shared by all devices of a server: bind the policy to this child
        if is_server_format(policy) and self.child_id and policy.get("child_id") != self.child_id:
            logger.error("Policy rejected! Reason: issued for a different child profile")
            return False

        # Runtime copy with decoded helper keys (app_rules, domain_rules, category_quotas,
        # category_budgets, schedule_matrix, ...) derived from the signed fields only
        self.active_policy = decode_policy(policy)
        self.current_policy_version = policy.get("version", self.current_policy_version)

        # 2. Persist the original signed payload in local DB cache (re-verified on restart)
        if self.db:
            sig = policy.get("signature", "")
            policy_json_str = json.dumps(policy)
            self.db.save_cached_policy(self.current_policy_version, policy_json_str, sig)

        # 3. Apply domain rules to DomainPolicyEngine
        if self.domain_engine:
            self.domain_engine.load_policy(self.active_policy.get("domain_rules") or [])

        logger.info("Successfully applied policy v%d", self.current_policy_version)
        return True

    def verify_command_signature(self, cmd_envelope: Dict[str, Any]) -> bool:
        """Verifies the HMAC-SHA256 of an urgent command (same formula as server CommandHub)."""
        if not isinstance(cmd_envelope, dict):
            return False
        signature = cmd_envelope.get("signature")
        cmd_id = cmd_envelope.get("command_id")
        command = cmd_envelope.get("command")
        issued_at = cmd_envelope.get("issued_at_utc")
        params = cmd_envelope.get("params") or {}
        if not all(isinstance(v, str) and v for v in (signature, cmd_id, command, issued_at)):
            return False
        data = f"{cmd_id}:{command}:{issued_at}:{json.dumps(params, sort_keys=True)}"
        expected = hmac.new(self.policy_secret().encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def handle_command_envelope(self, cmd_envelope: Dict[str, Any]) -> bool:
        """Entry point for commands received from the network (WebSocket / heartbeat).
        Executes only correctly signed commands, and each command_id at most once."""
        if not self.verify_command_signature(cmd_envelope):
            logger.warning("Rejected urgent command with missing or invalid signature.")
            return False
        cmd_id = cmd_envelope["command_id"]
        if cmd_id in self._executed_command_ids:
            return False
        self._executed_command_ids.append(cmd_id)
        await self._execute_command(cmd_envelope)
        return True

    async def _execute_command(self, cmd_envelope: Dict[str, Any]) -> None:
        """Executes an urgent command envelope (FR-LC-03, Section 5.2)."""
        cmd_type = cmd_envelope.get("command")
        params = cmd_envelope.get("params", {})
        cmd_id = cmd_envelope.get("command_id", "")
        logger.info("Executing urgent command: %s (ID: %s)", cmd_type, cmd_id)

        if cmd_type == "LOCK_NOW":
            if self.screen_time_mgr:
                self.screen_time_mgr.set_manual_lock(True)
            if self.app_controller:
                self.app_controller.scan_and_enforce(
                    app_rules=[],
                    is_locked=True,
                    policy_id=str(self.current_policy_version)
                )

        elif cmd_type == "UNLOCK":
            if self.screen_time_mgr:
                self.screen_time_mgr.set_manual_lock(False)

        elif cmd_type == "ADD_TIME_15M":
            bonus_sec = params.get("bonus_seconds", 900)
            if self.screen_time_mgr:
                self.screen_time_mgr.add_bonus_time(bonus_sec)

        elif cmd_type == "PARENT_PAUSE_2H":
            duration = params.get("duration_seconds", 7200)
            if self.screen_time_mgr:
                self.screen_time_mgr.activate_parent_pause(duration)

        elif cmd_type == "PURGE_DATA":
            if self.event_buffer:
                self.event_buffer.purge_local_events()
            if self.screen_time_mgr:
                self.screen_time_mgr.used_total_sec = 0
                self.screen_time_mgr.category_used_sec = {}
                self.screen_time_mgr._persist_state_to_db()

        elif cmd_type == "POLICY_UPDATED":
            await self.fetch_and_apply_policy()

    async def run_websocket_loop(self) -> None:
        """Maintains persistent WebSocket connection for real-time urgent commands (< 5s) with Exponential Backoff + Jitter."""
        ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        endpoint = f"{ws_url}/ws/agent/{self.device_id}"
        retry_count = 0
        base_delay = 1.0
        max_delay = 60.0

        while self._running:
            try:
                headers = {"Authorization": f"Bearer {self.access_token}"}
                ssl_context = None
                if endpoint.startswith("wss://"):
                    import ssl
                    ca_cert = self._ca_bundle()
                    if ca_cert:
                        ssl_context = ssl.create_default_context(cafile=ca_cert)
                    elif os.getenv("OGK_INSECURE_TLS") == "1":
                        ssl_context = ssl.create_default_context()
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE

                if endpoint.startswith("wss://"):
                    pinned_der = await self.enforce_certificate_pin()
                    if pinned_der:
                        ssl_context = self._pinned_ssl_context(pinned_der)
                async with websockets.connect(endpoint, additional_headers=headers, ssl=ssl_context) as ws:
                    self.ws_connected = True
                    retry_count = 0  # Reset backoff upon successful connection
                    logger.info("Connected to WebSocket Command Hub: %s", endpoint)

                    async for msg_str in ws:
                        try:
                            msg = json.loads(msg_str)
                            if msg.get("msg_type") == "URGENT_COMMAND":
                                if not self.verify_command_signature(msg):
                                    logger.warning("Rejected unsigned / forged urgent command.")
                                    continue
                                # Duplicates are not re-executed but still ACKed so the
                                # server can drop them from its pending queue
                                await self.handle_command_envelope(msg)
                                ack = {
                                    "msg_type": "COMMAND_ACK",
                                    "command_id": msg.get("command_id"),
                                    "status": "EXECUTED",
                                    "executed_at_utc": datetime.now(timezone.utc).isoformat(),
                                }
                                await ws.send(json.dumps(ack))
                        except Exception as parse_err:
                            logger.error("Error processing WebSocket message: %s", parse_err)

            except Exception as e:
                self.ws_connected = False
                retry_count += 1
                import random
                # Exponential backoff: min(60, base * 2^retries) + random jitter [0.1, 1.0]
                delay = min(max_delay, base_delay * (2 ** min(retry_count, 6)))
                jitter = random.uniform(0.1, 1.0)
                total_sleep = delay + jitter
                logger.debug(
                    "WebSocket connection lost: %s. Reconnecting in %.2fs (attempt %d)...",
                    e, total_sleep, retry_count
                )
                await asyncio.sleep(total_sleep)

    async def start(self) -> None:
        """Starts background loops for heartbeat, event sync, and WebSocket."""
        self._running = True
        # Pairing identity persisted by a previous enroll() / token refresh
        self.load_saved_credentials()
        # Try loading cached policy from SQLite
        if self.db:
            cached = self.db.get_cached_policy()
            if cached and cached.get("policy"):
                self._apply_policy(cached["policy"])

        # Start WebSocket task
        asyncio.create_task(self.run_websocket_loop())

        # Start Heartbeat & Event Sync loop
        asyncio.create_task(self._sync_worker_loop())

    async def _sync_worker_loop(self) -> None:
        """Background loop running heartbeat and event sync every 60s."""
        while self._running:
            try:
                if self.device_id and self.access_token:
                    await self.send_heartbeat()
                    await self.upload_event_batch()
            except Exception as e:
                logger.debug("Periodic sync error: %s", e)
            await asyncio.sleep(60.0)

    def stop(self) -> None:
        """Stops client tasks."""
        self._running = False
