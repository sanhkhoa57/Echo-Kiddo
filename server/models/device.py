"""Device model (1 Child : m Devices)."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("children.id", ondelete="CASCADE"), nullable=False)
    device_name: Mapped[str] = mapped_column(String(100), nullable=False)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    windows_user_sid: Mapped[str | None] = mapped_column(String(128), nullable=True)  # Standard User SID
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256 of Refresh Token
    token_revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_utc: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_clock_drift_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at_utc: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Relationships
    child: Mapped["Child"] = relationship("Child", back_populates="devices")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="device", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_devices_child", "child_id"),
    )

    def __repr__(self) -> str:
        return f"<Device(id={self.id}, device_name={self.device_name}, child_id={self.child_id})>"
