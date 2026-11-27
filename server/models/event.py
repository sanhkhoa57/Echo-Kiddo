"""Event model - STRICT 7-field schema compliant with Section F3 & BR-07."""
from sqlalchemy import String, Integer, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base

VALID_EVENT_TYPES = (
    "app_start",
    "app_stop",
    "domain_query",
    "blocked_app",
    "blocked_domain",
    "quota_warning",
    "locked",
    "unlock_request",
    "override_granted",
)


class Event(Base):
    __tablename__ = "events"

    # Primary key for idempotency deduplication across batch syncs
    idempotency_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # STRICT 7 BUSINESS FIELDS (F3 & BR-07)
    # 1. ts (ISO-8601 UTC timestamp)
    ts: Mapped[str] = mapped_column(String(30), nullable=False)

    # 2. device_id (FK -> devices.id)
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False
    )

    # 3. child_id (FK -> children.id)
    child_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("children.id", ondelete="CASCADE"),
        nullable=False
    )

    # 4. type (1 of 9 valid event types)
    type: Mapped[str] = mapped_column(String(30), nullable=False)

    # 5. subject (Application filename OR eTLD+1 domain; NEVER full URL)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    # 6. duration_sec (integer >= 0)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 7. policy_id (version tracking)
    policy_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="events")
    child: Mapped["Child"] = relationship("Child", back_populates="events")

    __table_args__ = (
        CheckConstraint(
            f"type IN {VALID_EVENT_TYPES}",
            name="chk_event_type_valid"
        ),
        Index("idx_events_child_ts", "child_id", "ts"),
        Index("idx_events_ts", "ts"),
    )

    def __repr__(self) -> str:
        return f"<Event(idempotency_key={self.idempotency_key}, type={self.type}, subject={self.subject})>"
