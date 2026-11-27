"""Child model (1 Parent : n Children)."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base


class Child(Base):
    __tablename__ = "children"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_group: Mapped[str] = mapped_column(String(20), nullable=False, default="6-11")
    avatar_code: Mapped[str | None] = mapped_column(String(50), nullable=True, default="kid_default")
    created_at_utc: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Relationships
    parent: Mapped["User"] = relationship("User", back_populates="children")
    devices: Mapped[list["Device"]] = relationship("Device", back_populates="child", cascade="all, delete-orphan")
    policy: Mapped["Policy | None"] = relationship("Policy", back_populates="child", uselist=False, cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="child", cascade="all, delete-orphan")
    pairing_codes: Mapped[list["PairingCode"]] = relationship("PairingCode", back_populates="child", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="child", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_children_parent", "parent_id"),
    )

    def __repr__(self) -> str:
        return f"<Child(id={self.id}, display_name={self.display_name}, parent_id={self.parent_id})>"
