"""AES-256-GCM encryption for sensitive agent.db fields (F5: "Dữ liệu lưu trữ").

Encrypted fields: access_token, refresh_token, policy_hmac_secret in device_credentials.
Stored form: "enc:v1:" + base64(nonce[12] | ciphertext | tag[16]).

The key is never hardcoded. It comes from, in order:
  1. OGK_AGENT_DATA_KEY: base64 of 32 random bytes (lab / CI override);
  2. a key file next to agent.db, created on first use with 32 random bytes and, on
     Windows, wrapped with DPAPI (CryptProtectData, machine scope) so the file is useless
     when copied to another machine. The folder's ACL (SYSTEM + Administrators only)
     is set by the installer; see docs/THREATMODEL.md.
Values written before encryption existed (plain text) are still read as-is and are
re-encrypted on the next save.
"""
import base64
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("OGK.FieldCrypto")

PREFIX = "enc:v1:"
KEY_FILE_NAME = "agent.key"
_AAD = b"ogk-agent-db-v1"


def _dpapi_protect(data: bytes) -> bytes:
    import win32crypt  # pywin32
    CRYPTPROTECT_LOCAL_MACHINE = 0x4
    return win32crypt.CryptProtectData(data, "OGK agent.db key", None, None, None, CRYPTPROTECT_LOCAL_MACHINE)


def _dpapi_unprotect(blob: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]


def _use_dpapi() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32crypt  # noqa: F401
        return True
    except ImportError:
        return False


def load_or_create_key(key_dir: Path) -> bytes:
    """Returns the 32-byte data key (env override, else DPAPI-wrapped key file)."""
    env = os.getenv("OGK_AGENT_DATA_KEY")
    if env:
        key = base64.b64decode(env)
        if len(key) != 32:
            raise ValueError("OGK_AGENT_DATA_KEY must be base64 of exactly 32 bytes")
        return key

    path = Path(key_dir) / KEY_FILE_NAME
    dpapi = _use_dpapi()
    if path.exists():
        raw = path.read_bytes()
        if raw.startswith(b"DPAPI:"):
            return _dpapi_unprotect(raw[6:])
        if raw.startswith(b"RAW:"):
            return base64.b64decode(raw[4:])
        raise ValueError(f"Unrecognised key file format: {path}")

    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"DPAPI:" + _dpapi_protect(key) if dpapi else b"RAW:" + base64.b64encode(key)
    path.write_bytes(payload)
    if not dpapi:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return key


class FieldCipher:
    def __init__(self, key: bytes):
        self._aes = AESGCM(key)

    def encrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None or value == "" or value.startswith(PREFIX):
            return value
        nonce = secrets.token_bytes(12)
        blob = nonce + self._aes.encrypt(nonce, value.encode("utf-8"), _AAD)
        return PREFIX + base64.b64encode(blob).decode("ascii")

    def decrypt(self, value: Optional[str]) -> Optional[str]:
        if not value or not value.startswith(PREFIX):
            return value  # empty, or legacy plain text
        blob = base64.b64decode(value[len(PREFIX):])
        return self._aes.decrypt(blob[:12], blob[12:], _AAD).decode("utf-8")
