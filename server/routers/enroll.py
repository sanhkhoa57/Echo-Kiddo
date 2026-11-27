"""Enrollment Router (/api/v1/enroll)."""
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.user import User
from server.schemas.pairing import PairingCodeCreate, PairingCodeResponse
from server.schemas.device import DeviceEnrollRequest
from server.auth.dependencies import (
    require_parent,
    get_child_for_parent,
    limiter,
)
from server.services.enrollment import (
    generate_pairing_code,
    enroll_device,
)

router = APIRouter(prefix="/api/v1/enroll", tags=["Enrollment"])


@router.post("/code", response_model=PairingCodeResponse)
def create_pairing_code(
    request: Request,
    payload: PairingCodeCreate,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Parent generates an 8-character pairing code (TTL 10m) after confirming consent (Decree 13/2023)."""
    # Anti-IDOR: ensures child belongs to parent
    child = get_child_for_parent(payload.child_id, db, current_user)
    client_ip = request.client.host if request.client else "127.0.0.1"

    pairing = generate_pairing_code(
        parent_id=current_user.id,
        child_id=child.id,
        consent_confirmed=payload.consent_confirmed,
        ip_address=client_ip,
        db=db,
    )

    return PairingCodeResponse(
        code=pairing.code,
        child_id=pairing.child_id,
        expires_at_utc=pairing.expires_at_utc,
    )


@router.post("")
@limiter.limit("20/minute")
def enroll_agent(
    request: Request,
    payload: DeviceEnrollRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """OGK-Agent exchanges pairing code for Device credentials & signed policy."""
    client_ip = request.client.host if request.client else "127.0.0.1"

    result = enroll_device(
        code_str=payload.pairing_code,
        device_name=payload.device_name,
        device_fingerprint=payload.device_fingerprint,
        windows_user_sid=payload.windows_user_sid,
        ip_address=client_ip,
        db=db,
    )

    return result
