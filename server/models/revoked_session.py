"""Server-side session revocation list (F5: logout destroys the session on the server)."""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from server.models.base import Base


class RevokedSession(Base):
    __tablename__ = "revoked_sessions"

    # `jti` claim of a parent / child-view session JWT that must no longer be accepted
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Original token expiry; rows past this time can be purged (token is dead anyway)
    expires_at_utc: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
