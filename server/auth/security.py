"""Security, password hashing (Argon2id), AES-256-GCM, JWT & CSRF utilities."""
import os
import secrets
import base64
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any
import jwt
from passlib.context import CryptContext
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 1. Password hashing with Argon2id
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__type="ID",  # Argon2id
    argon2__memory_cost=65536,  # 64 MiB
    argon2__time_cost=3,
    argon2__parallelism=4,
)

# 2. Secret keys from environment or secure defaults
JWT_SECRET = os.getenv("OGK_JWT_SECRET", "ogk-insecure-dev-jwt-secret-replace-in-prod-32bytes!")
JWT_ALGORITHM = "HS256"
DEVICE_TOKEN_EXPIRE_MINUTES = 15
SESSION_COOKIE_EXPIRE_HOURS = 12

# 3. AES-256-GCM Master Key (32 bytes)
_raw_enc_key = os.getenv("OGK_ENCRYPTION_KEY")
if _raw_enc_key:
    if len(_raw_enc_key) == 32:
        AES_KEY = _raw_enc_key.encode("utf-8")
    else:
        # Base64 decode or pad/hash
        try:
            AES_KEY = base64.b64decode(_raw_enc_key)[:32]
        except Exception:
            AES_KEY = _raw_enc_key.ljust(32, "0")[:32].encode("utf-8")
else:
    # No hardcoded key: generate 32 random bytes once and keep them beside the server DB
    _key_file = Path(os.getenv("OGK_ENCRYPTION_KEY_FILE", Path(__file__).resolve().parent.parent / "data" / "aes.key"))
    if _key_file.exists():
        AES_KEY = base64.b64decode(_key_file.read_bytes())
    else:
        AES_KEY = secrets.token_bytes(32)
        _key_file.parent.mkdir(parents=True, exist_ok=True)
        _key_file.write_bytes(base64.b64encode(AES_KEY))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against an Argon2id hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hashes a password with Argon2id."""
    return pwd_context.hash(password)


def encrypt_aes_gcm(plaintext: bytes, key: bytes = AES_KEY) -> bytes:
    """Encrypts bytes using AES-256-GCM.
    
    Returns 12-byte nonce prepended to ciphertext + 16-byte auth tag.
    """
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_aes_gcm(encrypted_data: bytes, key: bytes = AES_KEY) -> bytes:
    """Decrypts AES-256-GCM payload (first 12 bytes are nonce)."""
    if len(encrypted_data) < 28:
        raise ValueError("Invalid encrypted payload size")
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def create_jwt_token(data: dict[str, Any], expires_delta: timedelta) -> str:
    """Creates a signed JWT with UTC expiry."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    # Unique token id so a single session can be revoked server-side (logout)
    to_encode.setdefault("jti", secrets.token_hex(16))
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict[str, Any]:
    """Decodes and validates a JWT token."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def generate_csrf_token(session_id: str) -> str:
    """Generates a CSRF token bound to a session identifier."""
    salt = secrets.token_hex(8)
    msg = f"{session_id}:{salt}".encode("utf-8")
    import hmac
    import hashlib
    sig = hmac.new(JWT_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{salt}:{sig}"


def verify_csrf_token(session_id: str, csrf_token: str) -> bool:
    """Validates CSRF token using constant-time comparison."""
    try:
        parts = csrf_token.split(":")
        if len(parts) != 2:
            return False
        salt, provided_sig = parts
        import hmac
        import hashlib
        msg = f"{session_id}:{salt}".encode("utf-8")
        expected_sig = hmac.new(JWT_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, provided_sig)
    except Exception:
        return False
