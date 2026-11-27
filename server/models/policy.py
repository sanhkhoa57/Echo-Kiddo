"""Policy model (Versioned & Signed Policy)."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("children.id", ondelete="CASCADE"), unique=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    daily_limit_weekday_min: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    daily_limit_weekend_min: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    schedule_matrix_7x48: Mapped[str] = mapped_column(String(336), nullable=False)  # 336 chars of '0'/'1'
    category_budgets_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    app_rules_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    domain_rules_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    offline_pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Argon2id hash
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat()
    )
    signature: Mapped[str] = mapped_column(Text, nullable=False)  # HMAC-SHA256 / RSA-PSS signature

    # Relationships
    child: Mapped["Child"] = relationship("Child", back_populates="policy")

    def __repr__(self) -> str:
        return f"<Policy(id={self.id}, child_id={self.child_id}, version={self.version})>"
