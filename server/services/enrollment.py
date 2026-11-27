"""Enrollment and Device Provisioning Service (Section 4.3, FR-LC-01)."""
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from server.models.pairing_code import PairingCode
from server.models.device import Device
from server.models.audit_log import AuditLog
from server.auth.security import create_jwt_token, DEVICE_TOKEN_EXPIRE_MINUTES
from server.services.policy_service import (
    create_default_policy_for_child,
    ensure_policy_signature,
    policy_wire_dict,
    Policy,
    POLICY_SECRET,
)

# Alphanumeric set without confusing chars 0, O, 1, I
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_pairing_code(
    parent_id: str,
    child_id: str,
    consent_confirmed: bool,
    ip_address: str,
    db: Session,
) -> PairingCode:
    """Generates an 8-character pairing code with 10-minute TTL and records Decree 13 consent."""
    if not consent_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bắt buộc xác nhận đồng ý của phụ huynh theo Nghị định 13/2023.",
        )

    # Clean old unused codes for this child
    db.query(PairingCode).filter(PairingCode.child_id == child_id, PairingCode.used_at_utc.is_(None)).delete()

    code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=10)

    pairing_entry = PairingCode(
        code=code,
        parent_id=parent_id,
        child_id=child_id,
        consent_confirmed=1,
        expires_at_utc=expires_at.isoformat(),
        used_at_utc=None,
    )
    db.add(pairing_entry)

    # Record AuditLog
    audit = AuditLog(
        actor_id=parent_id,
        actor_role="parent",
        child_id=child_id,
        ip_address=ip_address,
        action="CREATE_PAIRING_CODE",
        new_value_json=f'{{"code": "{code}", "expires_at": "{expires_at.isoformat()}"}}',
    )
    db.add(audit)

    db.commit()
    db.refresh(pairing_entry)
    return pairing_entry


def enroll_device(
    code_str: str,
    device_name: str,
    device_fingerprint: str,
    windows_user_sid: str | None,
    ip_address: str,
    db: Session,
) -> dict:
    """Enrolls an OGK-Agent, validates 10-min code, and issues device credentials + signed policy."""
    pairing = db.query(PairingCode).filter(PairingCode.code == code_str).first()
    if not pairing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mã ghép đôi không tồn tại.",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    if pairing.used_at_utc is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã ghép đôi này đã được sử dụng.",
        )

    if pairing.expires_at_utc < now_iso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã ghép đôi đã hết hạn (quá 10 phút). Vui lòng tạo mã mới.",
        )

    # Mark pairing code as used
    pairing.used_at_utc = now_iso

    # Create Device
    device = Device(
        child_id=pairing.child_id,
        device_name=device_name,
        fingerprint_hash=device_fingerprint,
        windows_user_sid=windows_user_sid,
        applied_policy_version=1,
        last_heartbeat_utc=now_iso,
    )
    db.add(device)
    db.flush()  # Populates device.id

    # Generate tokens
    access_token = create_jwt_token(
        data={"sub": device.id, "child_id": device.child_id, "type": "device_access"},
        expires_delta=timedelta(minutes=DEVICE_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_jwt_token(
        data={"sub": device.id, "child_id": device.child_id, "type": "device_refresh"},
        expires_delta=timedelta(days=90),
    )

    # Save SHA-256 hash of refresh token
    device.refresh_token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()

    # Ensure signed policy exists
    policy = db.query(Policy).filter(Policy.child_id == pairing.child_id).first()
    if not policy:
        policy = create_default_policy_for_child(pairing.child_id, db)
    policy = ensure_policy_signature(policy, db)

    # Record AuditLog
    audit = AuditLog(
        actor_id=device.id,
        actor_role="device-agent",
        child_id=pairing.child_id,
        ip_address=ip_address,
        action="ENROLL_DEVICE",
        new_value_json=f'{{"device_id": "{device.id}", "device_name": "{device_name}"}}',
    )
    db.add(audit)

    db.commit()
    db.refresh(device)

    return {
        "device_id": device.id,
        "child_id": pairing.child_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        # Key the agent uses to verify the policy HMAC (never the JWT secret itself)
        "policy_hmac_secret": POLICY_SECRET,
        # Argon2id hash for offline parent-PIN verification on the agent (may be null)
        "offline_pin_hash": policy.offline_pin_hash,
        # Exactly SIGNED_POLICY_KEYS + signature
        "policy": policy_wire_dict(policy),
    }
