"""Family management for the parent dashboard: child profiles, devices, and the child's
"more time" requests (unlock_request -> override_granted)."""
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from server.auth.dependencies import get_child_for_parent, require_parent
from server.models.audit_log import AuditLog
from server.models.child import Child
from server.models.database import get_db
from server.models.device import Device
from server.models.event import Event
from server.models.user import User
from server.routers.reports import (
    REQUEST_DENIED_ACTION,
    override_key_for,
    pending_unlock_requests,
)
from server.schemas.child import ChildCreate, ChildResponse
from server.services.command_hub import command_hub
from server.services.policy_service import create_default_policy_for_child

router = APIRouter(prefix="/api/v1", tags=["Family"])

BONUS_SECONDS = 900  # the only grant size the agent supports: ADD_TIME_15M


class RequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=64)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"


def _pending_request_or_404(child_id: str, request_key: str, db: Session) -> Event:
    pending_keys = {r["request_key"] for r in pending_unlock_requests(child_id, db)}
    if request_key not in pending_keys:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Yêu cầu không tồn tại, đã quá 24 giờ hoặc đã được xử lý.",
        )
    return db.get(Event, request_key)


@router.post("/children", response_model=ChildResponse, status_code=status.HTTP_201_CREATED)
def create_child(
    payload: ChildCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """One parent : n children. A new profile starts with the default 6-11 policy."""
    child = Child(
        parent_id=current_user.id,
        display_name=payload.display_name.strip(),
        birth_year=payload.birth_year,
        age_group=payload.age_group,
        avatar_code=payload.avatar_code,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    create_default_policy_for_child(child.id, db)

    db.add(AuditLog(
        actor_id=current_user.id,
        actor_role=current_user.role,
        child_id=child.id,
        ip_address=_client_ip(request),
        action="CHILD_PROFILE_CREATED",
        new_value_json=json.dumps({"display_name": child.display_name, "age_group": child.age_group}),
    ))
    db.commit()
    return child


@router.post("/devices/{device_id}/revoke")
async def revoke_device(
    device_id: str,
    request: Request,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Removes a device: its tokens stop working immediately (revocation list, F5)."""
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thiết bị không tồn tại.")
    child = get_child_for_parent(device.child_id, db, current_user)  # anti-IDOR

    device.token_revoked = 1
    device.refresh_token_hash = None
    db.add(AuditLog(
        actor_id=current_user.id,
        actor_role=current_user.role,
        child_id=child.id,
        ip_address=_client_ip(request),
        action="DEVICE_REVOKED",
        old_value_json=json.dumps({"device_id": device.id, "device_name": device.device_name}),
    ))
    db.commit()
    await command_hub.disconnect(device.id)
    return {"status": "REVOKED", "device_id": device.id}


@router.get("/requests/{child_id}")
def list_pending_requests(
    child_id: str,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    child = get_child_for_parent(child_id, db, current_user)
    return {"pending_requests": pending_unlock_requests(child.id, db)}


@router.post("/requests/{child_id}/approve")
async def approve_request(
    child_id: str,
    payload: RequestDecision,
    request: Request,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Grants +15 minutes: pushes ADD_TIME_15M, records override_granted and an audit entry."""
    child = get_child_for_parent(child_id, db, current_user)
    req = _pending_request_or_404(child.id, payload.request_key, db)

    devices = db.query(Device).filter(Device.child_id == child.id, Device.token_revoked == 0).all()
    targets = [d for d in devices if d.id == req.device_id] or devices
    dispatched = []
    for dev in targets:
        res = await command_hub.send_command(
            device_id=dev.id,
            command="ADD_TIME_15M",
            params={"bonus_seconds": BONUS_SECONDS},
        )
        dispatched.append({"device_id": dev.id, "command_id": res["command_id"]})

    db.add(Event(
        idempotency_key=override_key_for(req.idempotency_key),
        ts=datetime.now(timezone.utc).isoformat(),
        device_id=req.device_id,
        child_id=child.id,
        type="override_granted",
        subject=req.subject,
        duration_sec=BONUS_SECONDS,
        policy_id=req.policy_id,
    ))
    db.add(AuditLog(
        actor_id=current_user.id,
        actor_role=current_user.role,
        child_id=child.id,
        ip_address=_client_ip(request),
        action="UNLOCK_REQUEST_APPROVED",
        old_value_json=json.dumps({"request_key": req.idempotency_key, "requested_at": req.ts}),
        new_value_json=json.dumps({"command": "ADD_TIME_15M", "bonus_seconds": BONUS_SECONDS}),
    ))
    db.commit()
    return {"status": "APPROVED", "bonus_seconds": BONUS_SECONDS, "targets": dispatched}


@router.post("/requests/{child_id}/deny")
def deny_request(
    child_id: str,
    payload: RequestDecision,
    request: Request,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Declines the request. Recorded in the audit log, which the child can read."""
    child = get_child_for_parent(child_id, db, current_user)
    req = _pending_request_or_404(child.id, payload.request_key, db)

    db.add(AuditLog(
        actor_id=current_user.id,
        actor_role=current_user.role,
        child_id=child.id,
        ip_address=_client_ip(request),
        action=REQUEST_DENIED_ACTION,
        new_value_json=json.dumps({"request_key": req.idempotency_key, "requested_at": req.ts}),
    ))
    db.commit()
    return {"status": "DENIED"}
