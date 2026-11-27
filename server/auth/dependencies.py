"""Authentication, RBAC, Anti-IDOR, CSRF, and Rate Limiting dependencies."""
import os
from datetime import datetime, timezone
from typing import Annotated
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from server.models.database import get_db
from server.models.user import User
from server.models.child import Child
from server.models.device import Device
from server.models.revoked_session import RevokedSession
from server.auth.security import (
    decode_jwt_token,
    verify_csrf_token,
)

# Rate limiter by client IP address (disabled in test suite when OGK_TESTING=1)
limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("OGK_TESTING") != "1",
)


def get_token_from_request(
    request: Request,
    ogk_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Extracts JWT token from either ogk_session cookie or Authorization Bearer header."""
    if ogk_session:
        return ogk_session
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1]
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Chưa xác thực danh tính. Vui lòng đăng nhập.",
        headers={"WWW-Authenticate": "Bearer"},
    )


SESSION_ROLES = ("parent", "admin", "child-view")


def is_session_revoked(db: Session, payload: dict) -> bool:
    """True if the session token was revoked server-side (logout / switch to child-view)."""
    jti = payload.get("jti")
    if not jti:
        return False
    return db.get(RevokedSession, jti) is not None


def revoke_session_token(db: Session, token: str | None) -> None:
    """Puts the token's jti on the server-side revocation list (idempotent)."""
    if not token:
        return
    try:
        payload = decode_jwt_token(token)
    except Exception:
        return  # expired / invalid tokens are already unusable
    jti = payload.get("jti")
    if not jti or db.get(RevokedSession, jti) is not None:
        return
    exp = payload.get("exp")
    expires = (
        datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
        if isinstance(exp, (int, float)) else datetime.now(timezone.utc).isoformat()
    )
    db.add(RevokedSession(jti=jti, expires_at_utc=expires))
    db.commit()


def attach_session_scope(user: User, payload: dict) -> User:
    """Marks the user object with the role of THIS session. A child-view session belongs
    to the parent account but may only read the one child it was opened for."""
    role = payload.get("role")
    if role == "child-view":
        user.session_role = "child-view"
        user.child_scope = payload.get("child_id")
    else:
        user.session_role = user.role
        user.child_scope = None
    return user


def session_role(user: User) -> str:
    return getattr(user, "session_role", None) or user.role


def get_current_user(
    token: Annotated[str, Depends(get_token_from_request)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Decodes user session token, checks revocation and lockout, and returns User record."""
    try:
        payload = decode_jwt_token(token)
        user_id = payload.get("sub")
        role = payload.get("role")
        if not user_id or role not in SESSION_ROLES:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token không hợp lệ hoặc thiếu thông tin định danh.",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên làm việc đã hết hạn hoặc không hợp lệ. Vui lòng đăng nhập lại.",
        )

    if is_session_revoked(db, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên làm việc đã đăng xuất. Vui lòng đăng nhập lại.",
        )

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản người dùng không tồn tại.",
        )
    attach_session_scope(user, payload)

    # Check 15-minute lockout if applicable
    if user.locked_until_utc:
        now_utc = datetime.now(timezone.utc).isoformat()
        if user.locked_until_utc > now_utc:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Tài khoản bị tạm khóa đến {user.locked_until_utc} do nhập sai mật khẩu quá 5 lần.",
            )
        else:
            # Lockout expired, reset counters
            user.locked_until_utc = None
            user.failed_login_count = 0
            db.commit()

    return user


def get_current_user_optional(
    db: Annotated[Session, Depends(get_db)],
    ogk_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """Returns User if valid session cookie/token present, or None."""
    token = None
    if ogk_session:
        token = ogk_session
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
    if not token:
        return None
    try:
        payload = decode_jwt_token(token)
        user_id = payload.get("sub")
        if not user_id or payload.get("role") not in SESSION_ROLES:
            return None
        if is_session_revoked(db, payload):
            return None
        user = db.get(User, user_id)
        return attach_session_scope(user, payload) if user else None
    except Exception:
        return None


def require_role(allowed_roles: list[str]):
    """RBAC dependency to enforce specific roles."""
    def role_checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        # The role of this session counts, so a child-view session never gets parent rights
        if session_role(current_user) not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền thực hiện thao tác này.",
            )
        return current_user
    return role_checker


require_parent = require_role(["parent", "admin"])
require_admin = require_role(["admin"])


def verify_csrf_header(
    request: Request,
    x_csrf_token: Annotated[str | None, Header()] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """Verifies CSRF token for state-changing requests (POST, PUT, DELETE, PATCH)."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # For pure API bearer token requests from devices/scripts, CSRF can be bypassed if explicitly Bearer header
        auth_hdr = request.headers.get("Authorization", "")
        cookie_session = request.cookies.get("ogk_session")
        if cookie_session:
            # If request relies on Cookie authentication, CSRF token is mandatory!
            if not x_csrf_token or not verify_csrf_token(current_user.id, x_csrf_token):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF token không hợp lệ hoặc bị thiếu.",
                )


def get_child_for_parent(
    child_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_parent)],
) -> Child:
    """STRICT ANTI-IDOR ENFORCEMENT:
    Ensures that a parent can ONLY access a child belonging to their own parent_id.
    Queries with WHERE parent_id = current_user.id.
    """
    if session_role(current_user) == "child-view":
        # Child-view: read-only and limited to the one child the session was opened for
        if child_id != getattr(current_user, "child_scope", None):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hồ sơ trẻ không tồn tại hoặc không thuộc quyền quản lý của bạn.",
            )
        child = db.scalar(
            select(Child).where(Child.id == child_id, Child.parent_id == current_user.id)
        )
    elif current_user.role == "admin":
        child = db.get(Child, child_id)
    else:
        child = db.scalar(
            select(Child).where(Child.id == child_id, Child.parent_id == current_user.id)
        )

    if not child:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hồ sơ trẻ không tồn tại hoặc không thuộc quyền quản lý của bạn.",
        )
    return child


def get_current_device(
    authorization: Annotated[str, Header()],
    db: Annotated[Session, Depends(get_db)],
) -> Device:
    """Authenticates OGK-Agent via Device Access Token (Bearer JWT)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu Header Authorization Bearer <access_token>",
        )

    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt_token(token)
        device_id = payload.get("sub")
        token_type = payload.get("type")
        if not device_id or token_type != "device_access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token thiết bị không hợp lệ.",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token thiết bị đã hết hạn (15 phút). Vui lòng refresh token.",
        )

    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiết bị không tồn tại trong hệ thống.",
        )

    if device.token_revoked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Thiết bị này đã bị thu hồi quyền truy cập bởi phụ huynh.",
        )

    return device
