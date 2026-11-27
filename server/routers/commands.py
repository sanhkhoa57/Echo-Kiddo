"""Commands Router (/api/v1/commands)."""
import json
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.user import User
from server.models.device import Device
from server.models.audit_log import AuditLog
from server.auth.dependencies import (
    require_parent,
    get_child_for_parent,
)
from server.services.command_hub import command_hub

router = APIRouter(prefix="/api/v1/commands", tags=["Commands"])

VALID_COMMANDS = {
    "LOCK_NOW",
    "UNLOCK",
    "ADD_TIME_15M",
    "PARENT_PAUSE_2H",
    "PURGE_DATA",
    "POLICY_UPDATED",
}


class UrgentCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: str
    command: str
    device_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("")
async def send_urgent_command(
    payload: UrgentCommandRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Parent sends urgent command (< 5s latency): LOCK_NOW, UNLOCK, ADD_TIME_15M, etc."""
    if payload.command not in VALID_COMMANDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lệnh không hợp lệ. Chỉ chấp nhận: {', '.join(sorted(VALID_COMMANDS))}",
        )

    # Anti-IDOR: ensures child belongs to parent
    child = get_child_for_parent(payload.child_id, db, current_user)
    client_ip = request.client.host if request.client else "127.0.0.1"

    # Determine target devices
    if payload.device_id:
        devices = db.query(Device).filter(Device.id == payload.device_id, Device.child_id == child.id, Device.token_revoked == 0).all()
        if not devices:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thiết bị mục tiêu không tồn tại hoặc đã bị thu hồi.",
            )
    else:
        devices = db.query(Device).filter(Device.child_id == child.id, Device.token_revoked == 0).all()

    if not devices:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy thiết bị nào đang hoạt động của trẻ này.",
        )

    dispatched = []
    for dev in devices:
        res = await command_hub.send_command(
            device_id=dev.id,
            command=payload.command,
            params=payload.params,
        )
        dispatched.append({"device_id": dev.id, "command_id": res["command_id"]})

    # Record AuditLog
    audit = AuditLog(
        actor_id=current_user.id,
        actor_role=current_user.role,
        child_id=child.id,
        ip_address=client_ip,
        action=f"COMMAND_{payload.command}",
        new_value_json=json.dumps({"command": payload.command, "params": payload.params}, ensure_ascii=False),
    )
    db.add(audit)
    db.commit()

    return {
        "status": "DISPATCHED",
        "command": payload.command,
        "targets": dispatched,
    }
