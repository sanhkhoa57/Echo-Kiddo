"""Authentication Router (/api/v1/auth)."""
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.user import User
from server.models.device import Device
from server.schemas.user import UserCreate, UserLogin, UserResponse
from server.auth.security import (
    verify_password,
    create_jwt_token,
    decode_jwt_token,
    generate_csrf_token,
    SESSION_COOKIE_EXPIRE_HOURS,
    DEVICE_TOKEN_EXPIRE_MINUTES,
)
from server.auth.dependencies import limiter, get_current_user, revoke_session_token
from server.services.accounts import EmailInUse, create_parent_account, find_account

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


class LoginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "bearer"
    csrf_token: str
    user: UserResponse


class DeviceRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class DeviceRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_sec: int


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_parent(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
):
    """Registers a new parent account with Argon2id password hashing."""
    if payload.role.value != "parent":
        raise HTTPException(status_code=403, detail="Chỉ có thể đăng ký tài khoản phụ huynh.")
    try:
        return create_parent_account(db, payload.email, payload.password)
    except EmailInUse:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email này đã được sử dụng trong hệ thống.",
        ) from None


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
def login_parent(
    request: Request,
    response: Response,
    payload: UserLogin,
    db: Annotated[Session, Depends(get_db)],
):
    """Parent login with 15-minute lockout after 5 consecutive failures and safe cookies."""
    user = find_account(db, payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không chính xác.",
        )

    now_utc = datetime.now(timezone.utc)

    # 1. Check if currently locked
    if user.locked_until_utc:
        if user.locked_until_utc > now_utc.isoformat():
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Tài khoản bị tạm khóa 15 phút đến {user.locked_until_utc} do nhập sai quá 5 lần.",
            )
        else:
            # Lockout expired, reset
            user.locked_until_utc = None
            user.failed_login_count = 0
            db.commit()

    # 2. Verify password with Argon2id
    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            lockout_until = now_utc + timedelta(minutes=15)
            user.locked_until_utc = lockout_until.isoformat()
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Bạn đã nhập sai 5 lần liên tiếp. Tài khoản bị tạm khóa 15 phút.",
            )
        db.commit()
        remaining = 5 - user.failed_login_count
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Email hoặc mật khẩu không chính xác. Bạn còn {remaining} lần thử trước khi bị khóa 15 phút.",
        )

    # 3. Success: reset counters
    user.failed_login_count = 0
    user.locked_until_utc = None
    db.commit()

    # 4. Generate 12-hour session JWT
    token_delta = timedelta(hours=SESSION_COOKIE_EXPIRE_HOURS)
    session_token = create_jwt_token(
        data={"sub": user.id, "email": user.email, "role": user.role},
        expires_delta=token_delta,
    )
    csrf_token = generate_csrf_token(user.id)

    # 5. Set Cookie HttpOnly, Secure, SameSite=Lax
    response.set_cookie(
        key="ogk_session",
        value=session_token,
        max_age=SESSION_COOKIE_EXPIRE_HOURS * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
    )

    return LoginResponse(
        access_token=session_token,
        token_type="bearer",
        csrf_token=csrf_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Revokes the session server-side (jti on the revocation list) and clears the cookie."""
    token = request.cookies.get("ogk_session")
    auth_hdr = request.headers.get("Authorization", "")
    if not token and auth_hdr.startswith("Bearer "):
        token = auth_hdr.split(" ", 1)[1]
    revoke_session_token(db, token)
    response.delete_cookie(key="ogk_session")
    return {"message": "Đăng xuất thành công."}


@router.post("/device/refresh", response_model=DeviceRefreshResponse)
def refresh_device_token(
    payload: DeviceRefreshRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """Refreshes a 15-minute Device Access Token using Refresh Token."""
    try:
        decoded = decode_jwt_token(payload.refresh_token)
        device_id = decoded.get("sub")
        token_type = decoded.get("type")
        if not device_id or token_type != "device_refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token không hợp lệ.",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token không hợp lệ hoặc đã hết hạn.",
        )

    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiết bị không tồn tại.",
        )

    if device.token_revoked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Thiết bị đã bị thu hồi bởi phụ huynh.",
        )

    # Verify SHA-256 hash of refresh token
    provided_hash = hashlib.sha256(payload.refresh_token.encode("utf-8")).hexdigest()
    if device.refresh_token_hash != provided_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token đã bị hủy hoặc thay thế.",
        )

    # Issue new 15-minute access token
    new_access_token = create_jwt_token(
        data={"sub": device.id, "child_id": device.child_id, "type": "device_access"},
        expires_delta=timedelta(minutes=DEVICE_TOKEN_EXPIRE_MINUTES),
    )

    return DeviceRefreshResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in_sec=DEVICE_TOKEN_EXPIRE_MINUTES * 60,
    )
