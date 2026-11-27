"""Audit Log Router (/api/v1/audit/{child_id}) - Transparency principle NT5."""
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.user import User
from server.models.audit_log import AuditLog
from server.schemas.audit import AuditLogResponse
from server.auth.dependencies import (
    get_current_user,
    get_child_for_parent,
)

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


@router.get("/{child_id}", response_model=list[AuditLogResponse])
def get_child_audit_logs(
    child_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
):
    """Returns Audit Log entries for child (accessible by both Parent and Child-View)."""
    child = get_child_for_parent(child_id, db, current_user)

    stmt = (
        select(AuditLog)
        .where(AuditLog.child_id == child.id)
        .order_by(AuditLog.ts_utc.desc())
        .limit(limit)
    )
    logs = db.scalars(stmt).all()
    return logs
