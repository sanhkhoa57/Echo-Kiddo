"""WebSocket Command Hub for Realtime Urgent Commands (< 5s latency)."""
import asyncio
import hmac
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import WebSocket

from server.services.policy_service import POLICY_SECRET


class CommandHub:
    """Manages WebSocket connections and immediate dispatch of urgent commands."""

    def __init__(self):
        # device_id -> active WebSocket connection
        self.active_connections: dict[str, WebSocket] = {}
        # device_id -> list of unacknowledged command dictionaries
        self.pending_commands: dict[str, list[dict[str, Any]]] = {}
        self._lock: asyncio.Lock | None = None

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self.lock:
            self.active_connections[device_id] = websocket
            if device_id not in self.pending_commands:
                self.pending_commands[device_id] = []

    async def disconnect(self, device_id: str) -> None:
        async with self.lock:
            if device_id in self.active_connections:
                del self.active_connections[device_id]

    def is_connected(self, device_id: str) -> bool:
        return device_id in self.active_connections

    def sign_command(self, cmd_id: str, command: str, issued_at_utc: str, params: dict) -> str:
        """Computes HMAC-SHA256 signature for urgent command."""
        data = f"{cmd_id}:{command}:{issued_at_utc}:{json.dumps(params, sort_keys=True)}"
        # Signed with the device-facing key issued at enrollment (`policy_hmac_secret`),
        # so the agent can verify commands without ever holding the JWT secret.
        return hmac.new(POLICY_SECRET.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()

    async def send_command(
        self,
        device_id: str,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatches an urgent command via WebSocket (latency < 5s) or queues for Heartbeat."""
        cmd_id = f"cmd_{uuid.uuid4().hex[:16]}"
        now_utc = datetime.now(timezone.utc).isoformat()
        params_dict = params or {}
        sig = self.sign_command(cmd_id, command, now_utc, params_dict)

        payload = {
            "msg_type": "URGENT_COMMAND",
            "command_id": cmd_id,
            "command": command,
            "params": params_dict,
            "issued_at_utc": now_utc,
            "signature": sig,
        }

        async with self.lock:
            if device_id not in self.pending_commands:
                self.pending_commands[device_id] = []
            self.pending_commands[device_id].append(payload)

            ws = self.active_connections.get(device_id)
            if ws:
                try:
                    await ws.send_json(payload)
                except Exception:
                    # Connection might have dropped
                    if device_id in self.active_connections:
                        del self.active_connections[device_id]

        return payload

    async def handle_ack(self, device_id: str, ack_payload: dict[str, Any]) -> bool:
        """Removes acknowledged command from pending queue upon COMMAND_ACK."""
        cmd_id = ack_payload.get("command_id")
        if not cmd_id:
            return False

        async with self.lock:
            queue = self.pending_commands.get(device_id, [])
            self.pending_commands[device_id] = [c for c in queue if c["command_id"] != cmd_id]
        return True

    def get_pending_commands(self, device_id: str) -> list[dict[str, Any]]:
        """Returns pending commands for inclusion in 60s Heartbeat response."""
        return list(self.pending_commands.get(device_id, []))


# Global Singleton Command Hub
command_hub = CommandHub()
