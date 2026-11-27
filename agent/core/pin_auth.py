"""Offline parent-PIN verification for OGK-Agent.

The agent only ever holds the Argon2id hash issued by the server (`offline_pin_hash`).
There is no built-in or default PIN: with no hash stored, verification always fails.
"""
import logging
from typing import Optional

logger = logging.getLogger("OGK.PinAuth")


def verify_pin_hash(pin: str, pin_hash: Optional[str]) -> bool:
    """Checks `pin` against an Argon2id hash. Returns False when no hash is configured."""
    if not pin or not pin_hash or not isinstance(pin_hash, str):
        return False
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
    except ImportError:
        try:
            from passlib.hash import argon2 as passlib_argon2
            return bool(passlib_argon2.verify(pin, pin_hash))
        except Exception as e:
            logger.error("No Argon2 implementation available to verify the parent PIN: %s", e)
            return False
    try:
        return bool(PasswordHasher().verify(pin_hash, pin))
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False
    except Exception as e:
        logger.debug("PIN verification error: %s", e)
        return False


def load_offline_pin_hash(db) -> Optional[str]:
    """Reads the stored parent-PIN hash from device credentials in agent.db."""
    try:
        creds = db.get_device_credentials() if db else None
    except Exception:
        creds = None
    if creds and creds.get("offline_pin_hash"):
        return creds["offline_pin_hash"]
    return None
