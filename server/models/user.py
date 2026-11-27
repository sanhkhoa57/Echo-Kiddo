"""User model (Parent & Admin accounts)."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="parent")  # 'parent' | 'admin'
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until_utc: Mapped[str | None] = mapped_column(String(30), nullable=True)  # Lock for 15m after 5 failed
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # AES-256-GCM optional
    created_at_utc: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Relationships
    children: Mapped[list["Child"]] = relationship("Child", back_populates="parent", cascade="all, delete-orphan")
    pairing_codes: Mapped[list["PairingCode"]] = relationship("PairingCode", back_populates="parent", cascade="all, delete-orphan")
    profile: Mapped["AccountProfile | None"] = relationship("AccountProfile", cascade="all, delete-orphan")
    profile_details: Mapped["AccountProfileDetails | None"] = relationship("AccountProfileDetails", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
