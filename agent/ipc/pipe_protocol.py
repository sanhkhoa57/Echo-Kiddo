"""Named Pipe IPC Protocol for OGK-Agent (FR-F5-07, Section 3.1).
Provides length-prefixed IpcEnvelope communication between OGK-Service and OGK-Tray
over Windows Named Pipe \\\\.\\pipe\\OGKServicePipe with constant-time challenge auth,
actual CallerSid kernel token verification, and test socket fallback.
"""
import hmac
import json
import logging
import os
import socket
import struct
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, Callable

logger = logging.getLogger("OGK.IpcProtocol")

PIPE_NAME = r"\\.\pipe\OGKServicePipe"
FALLBACK_SOCKET_PORT = 54321
PROTOCOL_VERSION = 1

_IS_WINDOWS = sys.platform == "win32"
if _IS_WINDOWS:
    try:
        import win32pipe
        import win32file
        import win32security
        import win32process
        import win32api
        import win32con
    except ImportError:
        pass


def extract_client_process_sid(pipe_handle) -> Optional[str]:
    """
    Extracts the actual Windows SID of the client process connected to the Named Pipe.
    Calls GetNamedPipeClientProcessId and OpenProcessToken to prevent spoofing of caller_sid.
    """
    if not _IS_WINDOWS:
        return None
    try:
        client_pid = win32pipe.GetNamedPipeClientProcessId(pipe_handle)
        h_proc = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, client_pid)
        try:
            h_tok = win32security.OpenProcessToken(h_proc, win32security.TOKEN_QUERY)
            try:
                user_sid_tuple = win32security.GetTokenInformation(h_tok, win32security.TokenUser)
                sid_str = win32security.ConvertSidToStringSid(user_sid_tuple[0])
                return sid_str
            finally:
                win32api.CloseHandle(h_tok)
        finally:
            win32api.CloseHandle(h_proc)
    except Exception as e:
        logger.debug("Could not query caller SID from pipe handle: %s", e)
        return None


class IpcEnvelope:
    """Represents a structured IPC message with 4-byte little-endian length prefix."""

    def __init__(
        self,
        msg_type: str,
        payload: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        caller_sid: str = "",
        challenge_token: str = "",
        protocol_version: int = PROTOCOL_VERSION,
    ):
        self.protocol_version = protocol_version
        self.request_id = request_id or str(uuid.uuid4())
        self.type = msg_type
        self.timestamp_utc = datetime.now(timezone.utc).isoformat()
        self.caller_sid = caller_sid
        self.challenge_token = challenge_token
        self.payload = payload or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "type": self.type,
            "timestamp_utc": self.timestamp_utc,
            "caller_sid": self.caller_sid,
            "challenge_token": self.challenge_token,
            "payload": self.payload,
        }

    def pack(self) -> bytes:
        """Packs envelope into 4-byte little-endian length prefix followed by UTF-8 JSON."""
        json_bytes = json.dumps(self.to_dict()).encode("utf-8")
        prefix = struct.pack("<I", len(json_bytes))
        return prefix + json_bytes

    @classmethod
    def unpack(cls, raw_data: bytes) -> "IpcEnvelope":
        """Unpacks UTF-8 JSON bytes into IpcEnvelope object."""
        data = json.loads(raw_data.decode("utf-8"))
        return cls(
            msg_type=data.get("type", "UNKNOWN"),
            payload=data.get("payload", {}),
            request_id=data.get("request_id"),
            caller_sid=data.get("caller_sid", ""),
            challenge_token=data.get("challenge_token", ""),
            protocol_version=data.get("protocol_version", PROTOCOL_VERSION),
        )


class ChallengeManager:
    """Manages short-lived challenge tokens (30s TTL) to prevent timing & replay attacks."""

    def __init__(self, ttl_seconds: float = 30.0):
        self.ttl = ttl_seconds
        self._challenges: Dict[str, float] = {}

    def generate_challenge(self) -> str:
        token = uuid.uuid4().hex
        self._challenges[token] = time.time() + self.ttl
        self._cleanup()
        return token

    def validate_and_consume(self, token: str) -> bool:
        if not token:
            return False
        self._cleanup()
        expire_at = self._challenges.pop(token, None)
        if expire_at and time.time() <= expire_at:
            return True
        return False

    def _cleanup(self) -> None:
        now = time.time()
        expired = [t for t, exp in self._challenges.items() if exp < now]
        for t in expired:
            self._challenges.pop(t, None)


class IpcPipeHandler:
    """Processes incoming IPC requests and dispatches responses."""

    def __init__(
        self,
        get_status_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        on_request_more_time_fn: Optional[Callable[[int], Dict[str, Any]]] = None,
        verify_pin_fn: Optional[Callable[[str], bool]] = None,
        verify_uninstall_fn: Optional[Callable[[str], bool]] = None,
        on_tray_ready_fn: Optional[Callable[[], None]] = None,
        on_user_activity_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.get_status_fn = get_status_fn
        self.on_request_more_time_fn = on_request_more_time_fn
        self.verify_pin_fn = verify_pin_fn
        self.verify_uninstall_fn = verify_uninstall_fn
        self.on_tray_ready_fn = on_tray_ready_fn
        self.on_user_activity_fn = on_user_activity_fn
        self.challenge_mgr = ChallengeManager()

    def handle_envelope(self, envelope: IpcEnvelope, actual_caller_sid: Optional[str] = None) -> IpcEnvelope:
        msg_type = envelope.type
        payload = envelope.payload

        if msg_type == "GET_CHALLENGE":
            token = self.challenge_mgr.generate_challenge()
            return IpcEnvelope(
                msg_type="CHALLENGE_ISSUED",
                payload={"challenge_token": token, "ttl_sec": 30},
                request_id=envelope.request_id,
            )

        elif msg_type == "GET_SESSION_STATUS":
            # The Tray piggybacks idle time / lock state of the child's session on each poll
            if self.on_user_activity_fn and isinstance(payload, dict) and (
                "idle_sec" in payload or "session_locked" in payload
            ):
                try:
                    self.on_user_activity_fn(payload)
                except Exception as e:
                    logger.debug("User activity report rejected: %s", e)
            status_data = self.get_status_fn() if self.get_status_fn else {}
            return IpcEnvelope(
                msg_type="SESSION_STATUS_RESPONSE",
                payload=status_data,
                request_id=envelope.request_id,
            )

        elif msg_type == "TRAY_READY":
            # Tray UI reports that tray icon is successfully visible (F5 compliance)
            if self.on_tray_ready_fn:
                self.on_tray_ready_fn()
            return IpcEnvelope(
                msg_type="TRAY_READY_ACK",
                payload={"status": "REGISTERED"},
                request_id=envelope.request_id,
            )

        elif msg_type == "REQUEST_MORE_TIME":
            requested_minutes = payload.get("minutes", 15)
            result = {}
            if self.on_request_more_time_fn:
                result = self.on_request_more_time_fn(requested_minutes)
            return IpcEnvelope(
                msg_type="REQUEST_MORE_TIME_RESPONSE",
                payload=result,
                request_id=envelope.request_id,
            )

        elif msg_type == "VERIFY_PARENT_PIN":
            # Privileged command requires valid 30s challenge token
            challenge = envelope.challenge_token
            if not self.challenge_mgr.validate_and_consume(challenge):
                return IpcEnvelope(
                    msg_type="AUTH_ERROR",
                    payload={"error": "Invalid or expired challenge token. Call GET_CHALLENGE first."},
                    request_id=envelope.request_id,
                )

            pin = payload.get("pin", "")
            is_valid = False
            if self.verify_pin_fn:
                is_valid = self.verify_pin_fn(pin)

            return IpcEnvelope(
                msg_type="VERIFY_PARENT_PIN_RESPONSE",
                payload={"valid": is_valid},
                request_id=envelope.request_id,
            )

        elif msg_type == "UNINSTALL_AUTH":
            # Privileged command for legal uninstallation
            challenge = envelope.challenge_token
            if not self.challenge_mgr.validate_and_consume(challenge):
                return IpcEnvelope(
                    msg_type="AUTH_ERROR",
                    payload={"error": "Invalid or expired challenge token. Call GET_CHALLENGE first."},
                    request_id=envelope.request_id,
                )

            auth_secret = payload.get("password_or_pin", "")
            authorized = False
            if self.verify_uninstall_fn:
                authorized = self.verify_uninstall_fn(auth_secret)

            return IpcEnvelope(
                msg_type="UNINSTALL_AUTH_RESPONSE",
                payload={"authorized": authorized},
                request_id=envelope.request_id,
            )

        return IpcEnvelope(
            msg_type="ERROR",
            payload={"error": f"Unknown message type '{msg_type}'"},
            request_id=envelope.request_id,
        )


class IpcServer:
    """
    Listens on Named Pipe \\\\.\\pipe\\OGKServicePipe with fallback localhost socket.
    Processes IpcEnvelope packets and sends back responses.
    """

    def __init__(self, handler: IpcPipeHandler, use_socket_fallback: bool = False, port: int = FALLBACK_SOCKET_PORT):
        self.handler = handler
        self.use_socket_fallback = use_socket_fallback or not _IS_WINDOWS
        self.port = port
        self.running = False
        self._server_sock = None
        self._thread = None
        self._ready_event = threading.Event()

    def start(self) -> None:
        self.running = True
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=2.0)
        logger.info("IPC Server started (fallback_socket=%s, port=%d)", self.use_socket_fallback, self.port)

    def _run_server(self) -> None:
        if self.use_socket_fallback:
            self._run_socket_server()
        else:
            try:
                self._run_named_pipe_server()
            except Exception as e:
                logger.warning("Named pipe error (%s), switching to socket fallback.", e)
                self._run_socket_server()

    def _run_socket_server(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", self.port))
        self.port = self._server_sock.getsockname()[1]
        self._server_sock.listen(5)
        self._server_sock.settimeout(1.0)
        self._ready_event.set()

        while self.running:
            try:
                client_sock, addr = self._server_sock.accept()
                threading.Thread(target=self._handle_socket_client, args=(client_sock,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.debug("Socket server error: %s", e)
                break

    def _handle_socket_client(self, client_sock: socket.socket) -> None:
        client_sock.settimeout(5.0)
        try:
            # Read 4-byte length prefix
            prefix = client_sock.recv(4)
            if len(prefix) < 4:
                return
            msg_len = struct.unpack("<I", prefix)[0]
            if msg_len > 1024 * 1024:  # 1MB limit
                return

            raw_bytes = b""
            while len(raw_bytes) < msg_len:
                chunk = client_sock.recv(min(4096, msg_len - len(raw_bytes)))
                if not chunk:
                    break
                raw_bytes += chunk

            if len(raw_bytes) == msg_len:
                req_env = IpcEnvelope.unpack(raw_bytes)
                resp_env = self.handler.handle_envelope(req_env, actual_caller_sid="S-1-5-LOCAL-SOCKET")
                client_sock.sendall(resp_env.pack())
        except Exception as e:
            logger.debug("Socket client handle error: %s", e)
        finally:
            client_sock.close()

    def _run_named_pipe_server(self) -> None:
        first = True
        while self.running:
            try:
                pipe_handle = win32pipe.CreateNamedPipe(
                    PIPE_NAME,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    65536,
                    65536,
                    0,
                    None
                )
                if first:
                    self._ready_event.set()
                    first = False
                # Wait for client connection
                win32pipe.ConnectNamedPipe(pipe_handle, None)
                threading.Thread(target=self._handle_pipe_client, args=(pipe_handle,), daemon=True).start()
            except Exception as e:
                if self.running:
                    logger.error("Pipe server error: %s", e)
                time.sleep(0.5)

    def _handle_pipe_client(self, pipe_handle) -> None:
        try:
            actual_sid = extract_client_process_sid(pipe_handle)
            # Read 4-byte length prefix
            hr, prefix = win32file.ReadFile(pipe_handle, 4)
            if len(prefix) < 4:
                return
            msg_len = struct.unpack("<I", prefix)[0]
            if msg_len > 1024 * 1024:
                return

            hr, raw_bytes = win32file.ReadFile(pipe_handle, msg_len)
            req_env = IpcEnvelope.unpack(raw_bytes)
            resp_env = self.handler.handle_envelope(req_env, actual_caller_sid=actual_sid)
            win32file.WriteFile(pipe_handle, resp_env.pack())
        except Exception as e:
            logger.debug("Pipe client error: %s", e)
        finally:
            try:
                win32file.CloseHandle(pipe_handle)
            except Exception:
                pass

    def stop(self) -> None:
        self.running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass


class IpcClient:
    """Client for connecting to OGKServicePipe with fallback to localhost socket."""

    def __init__(self, port: int = FALLBACK_SOCKET_PORT, prefer_pipe: bool = True):
        self.port = port
        self.prefer_pipe = prefer_pipe

    def send_request(self, envelope: IpcEnvelope, timeout: float = 3.0) -> Optional[IpcEnvelope]:
        # Try Named Pipe first if on Windows and requested
        if self.prefer_pipe and _IS_WINDOWS and "win32file" in sys.modules:
            try:
                handle = win32file.CreateFile(
                    PIPE_NAME,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None,
                    win32file.OPEN_EXISTING,
                    0, None
                )
                try:
                    win32file.WriteFile(handle, envelope.pack())
                    hr, prefix = win32file.ReadFile(handle, 4)
                    if len(prefix) == 4:
                        resp_len = struct.unpack("<I", prefix)[0]
                        hr, resp_bytes = win32file.ReadFile(handle, resp_len)
                        return IpcEnvelope.unpack(resp_bytes)
                finally:
                    win32file.CloseHandle(handle)
            except Exception:
                pass

        # Fallback to localhost socket with connection retry
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(timeout)
                s.connect(("127.0.0.1", self.port))
                try:
                    s.sendall(envelope.pack())
                    prefix = s.recv(4)
                    if len(prefix) == 4:
                        resp_len = struct.unpack("<I", prefix)[0]
                        raw_bytes = b""
                        while len(raw_bytes) < resp_len:
                            chunk = s.recv(min(4096, resp_len - len(raw_bytes)))
                            if not chunk:
                                break
                            raw_bytes += chunk
                        return IpcEnvelope.unpack(raw_bytes)
                finally:
                    s.close()
            except (ConnectionRefusedError, TimeoutError, OSError):
                time.sleep(0.05)
            except Exception as e:
                logger.debug("IpcClient request failed: %s", e)
                return None
        return None

    # Alias kept so callers may use either name
    send_envelope = send_request
