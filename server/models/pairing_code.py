"""PairingCode model (8 chars [A-Z0-9], TTL 10 minutes, Consent Decree 13/2023)."""
from sqlalchemy import String, Integer, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    child_id: Mapped[str] = mapped_column(String(36), ForeignKey("children.id", ondelete="CASCADE"), nullable=False)
    consent_confirmed: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    used_at_utc: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Relationships
    parent: Mapped["User"] = relationship("User", back_populates="pairing_codes")
    child: Mapped["Child"] = relationship("Child", back_populates="pairing_codes")

    __table_args__ = (
        CheckConstraint("consent_confirmed = 1", name="chk_pairing_consent_confirmed"),
    )

    def __repr__(self) -> str:
        return f"<PairingCode(code={self.code}, child_id={self.child_id}, expires_at_utc={self.expires_at_utc})>"
