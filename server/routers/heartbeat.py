"""Heartbeat Router (/api/v1/heartbeat)."""
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.device import Device
from server.models.policy import Policy
from server.schemas.device import HeartbeatRequest, HeartbeatResponse
from server.auth.dependencies import get_current_device
from server.services.command_hub import command_hub

router = APIRouter(prefix="/api/v1/heartbeat", tags=["Heartbeat"])

# device_id -> {"used_sec": int, "at_utc": str}
LIVE_USAGE: dict[str, dict] = {}


@router.post("", response_model=HeartbeatResponse)
def handle_heartbeat(
    payload: HeartbeatRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
    db: Annotated[Session, Depends(get_db)],
):
    """60s Heartbeat: measures clock drift, checks policy version, and returns pending commands."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Calculate clock drift |agent_wall_clock_utc - server_utc|
    clock_drift_sec = 0
    try:
        agent_dt = datetime.fromisoformat(payload.local_utc.replace("Z", "+00:00"))
        clock_drift_sec = int(abs((agent_dt - now).total_seconds()))
    except Exception:
        pass

    # Keep the agent's own screen-time counter (the authoritative F1 figure) for the dashboard.
    # In memory only: it is refreshed by the next heartbeat within 60s after a restart.
    LIVE_USAGE[current_device.id] = {"used_sec": payload.used_sec, "at_utc": now_iso}

    # Update device heartbeat & drift
    current_device.last_heartbeat_utc = now_iso
    current_device.last_clock_drift_sec = clock_drift_sec
    db.commit()

    # Latest policy version
    policy = db.query(Policy).filter(Policy.child_id == current_device.child_id).first()
    latest_version = policy.version if policy else 1

    # Pending commands in queue
    pending = command_hub.get_pending_commands(current_device.id)

    return HeartbeatResponse(
        server_utc=now_iso,
        latest_policy_version=latest_version,
        pending_commands=pending,
        clock_drift_sec=clock_drift_sec,
    )
