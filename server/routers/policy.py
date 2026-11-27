"""Policy Router (/api/v1/policy)."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.user import User
from server.models.device import Device
from server.models.policy import Policy
from server.schemas.policy import PolicyUpdate, PolicyResponse
from server.auth.dependencies import (
    get_current_device,
    require_parent,
    get_child_for_parent,
)
from server.services.policy_service import (
    create_default_policy_for_child,
    ensure_policy_signature,
    update_policy_for_child,
)
from server.services.command_hub import command_hub

router = APIRouter(prefix="/api/v1/policy", tags=["Policy"])


@router.get("", response_model=PolicyResponse)
def get_device_policy(
    current_device: Annotated[Device, Depends(get_current_device)],
    db: Annotated[Session, Depends(get_db)],
):
    """OGK-Agent fetches the latest versioned & cryptographically signed policy."""
    policy = db.query(Policy).filter(Policy.child_id == current_device.child_id).first()
    if not policy:
        policy = create_default_policy_for_child(current_device.child_id, db)
    # Guarantee the agent can verify the HMAC even for rows signed before key unification
    return ensure_policy_signature(policy, db)


@router.get("/{child_id}", response_model=PolicyResponse)
def get_child_policy(
    child_id: str,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Parent fetches policy for child (enforcing Anti-IDOR)."""
    child = get_child_for_parent(child_id, db, current_user)
    policy = db.query(Policy).filter(Policy.child_id == child.id).first()
    if not policy:
        policy = create_default_policy_for_child(child.id, db)
    return policy


@router.put("/{child_id}", response_model=PolicyResponse)
async def update_child_policy(
    child_id: str,
    payload: PolicyUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Parent updates child policy, increments version, signs with HMAC, and triggers WS update."""
    child = get_child_for_parent(child_id, db, current_user)
    client_ip = request.client.host if request.client else "127.0.0.1"

    updated = update_policy_for_child(
        child_id=child.id,
        # Only the top-level fields the parent sent; nested rules keep their full shape
        update_data={k: getattr(payload, k) for k in payload.model_fields_set},
        actor_id=current_user.id,
        actor_role=current_user.role,
        ip_address=client_ip,
        db=db,
    )

    # Push POLICY_UPDATED to all online devices of this child
    devices = db.query(Device).filter(Device.child_id == child.id, Device.token_revoked == 0).all()
    for dev in devices:
        await command_hub.send_command(
            device_id=dev.id,
            command="POLICY_UPDATED",
            params={"new_version": updated.version},
        )

    return updated
