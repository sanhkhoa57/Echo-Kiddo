"""Events and Privacy Purge Router (/api/v1/events and /api/v1/privacy)."""
from datetime import datetime, timezone, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.device import Device
from server.models.user import User
from server.models.event import Event
from server.models.audit_log import AuditLog
from server.schemas.event import EventBatchRequest, EventBatchResponse
from server.auth.dependencies import (
    get_current_device,
    require_parent,
    get_child_for_parent,
)
from server.services.command_hub import command_hub

router = APIRouter(tags=["Events & Privacy"])


@router.post("/api/v1/events/batch", response_model=EventBatchResponse)
def ingest_events_batch(
    payload: EventBatchRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
    db: Annotated[Session, Depends(get_db)],
):
    """Batch event ingestion adhering strictly to 7-field schema with idempotent deduplication."""
    incoming_keys = [e.idempotency_key for e in payload.events]

    # Find existing keys in DB to prevent duplicates
    existing_keys_stmt = select(Event.idempotency_key).where(Event.idempotency_key.in_(incoming_keys))
    existing_keys = set(db.scalars(existing_keys_stmt).all())

    new_events = []
    acked_keys = []
    duplicate_count = 0

    for item in payload.events:
        acked_keys.append(item.idempotency_key)
        if item.idempotency_key in existing_keys:
            duplicate_count += 1
            continue

        # Force device_id and child_id to match authenticated device context (prevent spoofing)
        event_model = Event(
            idempotency_key=item.idempotency_key,
            ts=item.ts,
            device_id=current_device.id,
            child_id=current_device.child_id,
            type=item.type.value if hasattr(item.type, "value") else str(item.type),
            subject=item.subject,
            duration_sec=item.duration_sec,
            policy_id=item.policy_id,
        )
        new_events.append(event_model)

    if new_events:
        db.add_all(new_events)
        db.commit()

    return EventBatchResponse(
        accepted_count=len(new_events),
        duplicate_count=duplicate_count,
        acked_keys=acked_keys,
    )


@router.delete("/api/v1/privacy/children/{child_id}/events")
async def purge_child_events(
    child_id: str,
    request: Request,
    current_user: Annotated[User, Depends(require_parent)],
    db: Annotated[Session, Depends(get_db)],
):
    """Enforces 'Delete all my child's data' button (Section F3, FR-F3-04):
    Deletes all events for the child on Server and dispatches PURGE_DATA to all child devices.
    """
    child = get_child_for_parent(child_id, db, current_user)
    client_ip = request.client.host if request.client else "127.0.0.1"

    # 1. Delete all events from server DB
    deleted_count = db.query(Event).filter(Event.child_id == child.id).delete()

    # 2. Record AuditLog
    audit = AuditLog(
        actor_id=current_user.id,
        actor_role=current_user.role,
        child_id=child.id,
        ip_address=client_ip,
        action="PURGE_CHILD_DATA",
        old_value_json=f'{{"deleted_events_count": {deleted_count}}}',
    )
    db.add(audit)
    db.commit()

    # 3. Push PURGE_DATA command to all devices registered for this child
    devices = db.query(Device).filter(Device.child_id == child.id, Device.token_revoked == 0).all()
    for dev in devices:
        await command_hub.send_command(
            device_id=dev.id,
            command="PURGE_DATA",
            params={"deleted_at_utc": datetime.now(timezone.utc).isoformat()},
        )

    return {
        "message": f"Đã xóa toàn bộ {deleted_count} sự kiện của trẻ trên máy chủ và đẩy lệnh xóa xuống thiết bị.",
        "deleted_count": deleted_count,
    }


def purge_events_older_than_90_days(db: Session) -> int:
    """Retention background worker: deletes events older than 90 days (FR-F3-04)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    deleted = db.query(Event).filter(Event.ts < cutoff).delete()
    if deleted > 0:
        db.commit()
    return deleted
