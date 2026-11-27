"""AuditLog model (Transparency principle NT5, Section F4)."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ts_utc: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat()
    )
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'parent' | 'admin' | 'system'
    child_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("children.id", ondelete="CASCADE"), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    child: Mapped["Child | None"] = relationship("Child", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_child_ts", "child_id", "ts_utc"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, actor_id={self.actor_id}, action={self.action})>"
