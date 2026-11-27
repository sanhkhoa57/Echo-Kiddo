"""Optional display preferences for a parent account."""
from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class AccountProfile(Base):
    __tablename__ = "account_profiles"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    avatar_color: Mapped[str] = mapped_column(String(12), nullable=False, default="forest")

    @property
    def initials(self) -> str:
        return "".join(word[0] for word in self.display_name.split()[:2]).upper()


class AccountProfileDetails(Base):
    __tablename__ = "account_profile_details"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    avatar_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avatar_image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
