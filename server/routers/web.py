"""Web Dashboard and View Routers (Jinja2 Templates)."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.user import User
from server.models.child import Child
from server.models.device import Device
from server.models.audit_log import AuditLog
from server.models.policy import Policy
from server.auth.security import (
    verify_password,
    create_jwt_token,
    generate_csrf_token,
    verify_csrf_token,
    SESSION_COOKIE_EXPIRE_HOURS,
)
from server.auth.dependencies import (
    get_current_user_optional,
    get_current_user,
    limiter,
    revoke_session_token,
    session_role,
)
from server.routers.heartbeat import LIVE_USAGE
from server.routers.reports import build_child_report, local_tz
from server.services.command_hub import command_hub
from server.services.policy_service import create_default_policy_for_child

SESSION_COOKIE_NAME = "ogk_session"
CSRF_COOKIE_NAME = "ogk_csrf"
DEVICE_ONLINE_WINDOW_SEC = 150  # two missed 60s heartbeats, with margin
CLOCK_DRIFT_WARN_SEC = 120

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "dashboard" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

web_router = APIRouter(include_in_schema=False)

WEEKDAY_NAMES = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
WEEKDAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
CATEGORY_LABELS = {
    "education": "Học tập",
    "entertainment": "Giải trí",
    "social": "Mạng xã hội",
    "gaming": "Trò chơi",
    "inappropriate": "Không phù hợp",
    "unclassified": "Chưa phân loại",
}
AUDIT_ACTION_LABELS = {
    "POLICY_UPDATE": "Sửa quy định dùng máy",
    "UPDATE_POLICY": "Sửa quy định dùng máy",
    "CREATE_PAIRING_CODE": "Tạo mã ghép đôi thiết bị",
    "ENROLL_DEVICE": "Ghép đôi thiết bị mới",
    "POLICY_UPDATED": "Sửa quy định dùng máy",
    "ENROLL_CODE_GENERATED": "Tạo mã ghép đôi thiết bị",
    "PAIRING_CODE_GENERATED": "Tạo mã ghép đôi thiết bị",
    "DEVICE_ENROLLED": "Ghép đôi thiết bị mới",
    "DEVICE_REVOKED": "Gỡ thiết bị",
    "CHILD_PROFILE_CREATED": "Tạo hồ sơ trẻ",
    "PURGE_CHILD_DATA": "Xóa toàn bộ dữ liệu hoạt động",
    "UNLOCK_REQUEST_APPROVED": "Đồng ý cho thêm 15 phút",
    "UNLOCK_REQUEST_DENIED": "Từ chối yêu cầu thêm giờ",
    "COMMAND_LOCK_NOW": "Khóa máy ngay",
    "COMMAND_UNLOCK": "Mở khóa máy",
    "COMMAND_ADD_TIME_15M": "Cộng thêm 15 phút",
    "COMMAND_PARENT_PAUSE_2H": "Tạm nghỉ kiểm soát 2 giờ",
    "COMMAND_PURGE_DATA": "Xóa dữ liệu trên máy trẻ",
    "COMMAND_DISPATCH": "Gửi lệnh tới máy trẻ",
    "CHILD_VIEW_SESSION_STARTED": "Mở chế độ xem dành cho con",
}
SECRET_AUDIT_KEYS = {"code", "pairing_code", "offline_pin", "offline_pin_hash", "signature"}


def _load_json(raw, fallback):
    try:
        value = json.loads(raw) if raw else fallback
    except (TypeError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _parse_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fmt_minutes(minutes: float) -> str:
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours} giờ {mins} phút"
    if hours:
        return f"{hours} giờ"
    return f"{mins} phút"


def _ago(delta_sec: float) -> str:
    if delta_sec < 90:
        return "vừa xong"
    if delta_sec < 3600:
        return f"{int(delta_sec // 60)} phút trước"
    if delta_sec < 86400:
        return f"{int(delta_sec // 3600)} giờ trước"
    return f"{int(delta_sec // 86400)} ngày trước"


def _device_views(devices: list[Device], latest_version: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    views = []
    for dev in devices:
        seen = _parse_utc(dev.last_heartbeat_utc)
        age = (now - seen).total_seconds() if seen else None
        online = age is not None and age <= DEVICE_ONLINE_WINDOW_SEC
        views.append({
            "id": dev.id,
            "name": dev.device_name,
            "online": online,
            "realtime": command_hub.is_connected(dev.id),
            "last_seen": _ago(age) if age is not None else "chưa kết nối lần nào",
            "policy_version": dev.applied_policy_version,
            "policy_current": dev.applied_policy_version >= latest_version,
            "clock_drift_sec": dev.last_clock_drift_sec,
            "clock_warning": dev.last_clock_drift_sec > CLOCK_DRIFT_WARN_SEC,
        })
    return views


def _live_used_min(devices: list[Device]) -> float | None:
    """Screen time counted by the agent itself, if a device reported today."""
    tz = local_tz()
    today = datetime.now(timezone.utc).astimezone(tz).date()
    best = None
    for dev in devices:
        entry = LIVE_USAGE.get(dev.id)
        seen = _parse_utc(entry["at_utc"]) if entry else None
        if seen and seen.astimezone(tz).date() == today:
            best = max(best or 0, entry["used_sec"])
    return round(best / 60, 1) if best is not None else None


def _today_view(report: dict, live_used_min: float | None) -> dict:
    """The 'calendar leaf': today's date, which limit applies, used and remaining time."""
    tz = local_tz()
    now_local = datetime.now(timezone.utc).astimezone(tz)
    used = live_used_min if live_used_min is not None else report.get("today_active_min", 0)
    limit = report.get("today_limit_min", 0) or 0
    remaining = max(0, limit - used)
    pct = min(100, round(used * 100 / limit)) if limit else 0
    return {
        "weekday_name": WEEKDAY_NAMES[now_local.weekday()],
        "day": now_local.day,
        "month": now_local.month,
        "year": now_local.year,
        "is_weekend": now_local.weekday() >= 5,
        "used_min": int(round(used)),
        "used_text": _fmt_minutes(used),
        "limit_min": limit,
        "limit_text": _fmt_minutes(limit),
        "remaining_min": int(round(remaining)),
        "remaining_text": _fmt_minutes(remaining),
        "pct": pct,
        "over": bool(limit) and used >= limit,
        "source_live": live_used_min is not None,
    }


def _week_view(report: dict) -> dict:
    daily = report.get("daily_breakdown", {})
    blocked = report.get("daily_blocked", {})
    minutes = {day: round(sec / 60) for day, sec in daily.items()}
    peak = max(list(minutes.values()) + [1])
    bars = []
    for day_key in sorted(minutes):
        day = datetime.fromisoformat(day_key).date()
        bars.append({
            "label": WEEKDAY_SHORT[day.weekday()],
            "date": day.strftime("%d/%m"),
            "minutes": minutes[day_key],
            "text": _fmt_minutes(minutes[day_key]),
            "pct": round(minutes[day_key] * 100 / peak),
            "is_weekend": day.weekday() >= 5,
            "is_today": day_key == report.get("local_date"),
            "blocked": blocked.get(day_key, 0),
        })
    total = sum(minutes.values())
    return {
        "bars": bars,
        "total_text": _fmt_minutes(total),
        "avg_text": _fmt_minutes(total / len(bars)) if bars else "0 phút",
        "has_data": total > 0,
    }


def _category_view(report: dict) -> list[dict]:
    breakdown = report.get("category_breakdown", {})
    total = sum(breakdown.values())
    rows = []
    for key, sec in sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True):
        rows.append({
            "key": key,
            "label": CATEGORY_LABELS.get(key, key),
            "text": _fmt_minutes(sec / 60),
            "pct": round(sec * 100 / total) if total else 0,
        })
    return rows


def _ranked(items: list[dict], value_key: str) -> list[dict]:
    peak = max([i.get(value_key, 0) for i in items] + [1])
    ranked = []
    for item in items:
        view = dict(item)
        view["pct"] = round(item.get(value_key, 0) * 100 / peak)
        view["category_label"] = CATEGORY_LABELS.get(item.get("category", ""), "")
        if value_key == "duration_sec":
            view["text"] = _fmt_minutes(item.get("duration_sec", 0) / 60)
        ranked.append(view)
    return ranked


def _empty_report() -> dict:
    return {
        "today_active_min": 0, "total_used_min": 0, "today_limit_min": 0,
        "total_blocked_events": 0, "blocked_count": 0, "blocked_today": 0,
        "daily_breakdown": {}, "daily_blocked": {}, "category_breakdown": {},
        "top_10_apps": [], "top_apps": [], "top_10_domains": [], "top_domains": [],
        "top_blocked": [], "recent_blocks": [], "pending_requests": [], "local_date": "",
    }


def _child_context(child: Child, db: Session) -> dict:
    """Everything the parent dashboard and the child's screen share about one child."""
    policy = db.query(Policy).filter(Policy.child_id == child.id).first()
    if not policy:
        policy = create_default_policy_for_child(child.id, db)
    devices = db.query(Device).filter(Device.child_id == child.id, Device.token_revoked == 0).all()
    report = build_child_report(child, db)
    today = _today_view(report, _live_used_min(devices))

    weekday = datetime.now(timezone.utc).astimezone(local_tz()).weekday()
    matrix = policy.schedule_matrix_7x48 if len(policy.schedule_matrix_7x48) == 336 else "1" * 336
    return {
        "policy": policy,
        "devices": _device_views(devices, policy.version),
        "report": report,
        "today": today,
        "week": _week_view(report),
        "categories": _category_view(report),
        "top_apps": _ranked(report["top_10_apps"], "duration_sec"),
        "top_domains": _ranked(report["top_10_domains"], "queries"),
        "today_slots": matrix[weekday * 48:(weekday + 1) * 48],
        "matrix": matrix,
    }


def _session_cookie_kwargs(request: Request) -> dict:
    return {
        "secure": request.url.scheme == "https",
        "samesite": "lax",
        "max_age": SESSION_COOKIE_EXPIRE_HOURS * 3600,
    }


@web_router.get("/", response_class=HTMLResponse)
def index(request: Request, user: Optional[User] = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@web_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: Optional[str] = None):
    csrf_token = generate_csrf_token("anon")
    response = templates.TemplateResponse(
        request,
        "login.html",
        {"csrf_token": csrf_token, "error": error, "current_user": None},
    )
    response.set_cookie(CSRF_COOKIE_NAME, csrf_token, httponly=False, samesite="lax")
    return response


def _login_csrf_ok(request: Request, csrf_token: str) -> bool:
    """Double-submit check: the form token must be a valid anonymous token AND match the
    ogk_csrf cookie set when the login page was served."""
    cookie = request.cookies.get(CSRF_COOKIE_NAME) or ""
    return bool(csrf_token) and csrf_token == cookie and verify_csrf_token("anon", csrf_token)


@web_router.post("/login")
@limiter.limit("10/minute")
def login_submit(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db)
):
    if not _login_csrf_ok(request, csrf_token):
        return login_page(request, error="Phiên đăng nhập đã hết hạn. Vui lòng tải lại trang và thử lại.")

    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user:
        return login_page(request, error="Tài khoản hoặc mật khẩu không chính xác.")

    # Check lockout
    now = datetime.now(timezone.utc)
    if user.locked_until_utc:
        locked_time = datetime.fromisoformat(user.locked_until_utc.replace("Z", "+00:00"))
        if now < locked_time:
            diff_min = int((locked_time - now).total_seconds() // 60) + 1
            return login_page(request, error=f"Tài khoản đang bị khóa tạm thời. Thử lại sau {diff_min} phút.")

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            lock_until = now + timedelta(minutes=15)
            user.locked_until_utc = lock_until.isoformat()
            db.commit()
            return login_page(request, error="Đăng nhập sai 5 lần! Tài khoản đã bị khóa 15 phút.")
        db.commit()
        return login_page(request, error="Tài khoản hoặc mật khẩu không chính xác.")

    # Successful login
    user.failed_login_count = 0
    user.locked_until_utc = None
    db.commit()

    token = create_jwt_token(
        data={"sub": user.id, "email": user.email, "role": user.role},
        expires_delta=timedelta(hours=SESSION_COOKIE_EXPIRE_HOURS),
    )
    csrf = generate_csrf_token(user.id)

    redirect_resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    cookie_kwargs = _session_cookie_kwargs(request)
    redirect_resp.set_cookie(key=SESSION_COOKIE_NAME, value=token, httponly=True, **cookie_kwargs)
    redirect_resp.set_cookie(key=CSRF_COOKIE_NAME, value=csrf, httponly=False, **cookie_kwargs)
    return redirect_resp


@web_router.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request, db: Session = Depends(get_db)):
    """Destroys the session on the server (jti revoked), not just in the browser."""
    revoke_session_token(db, request.cookies.get(SESSION_COOKIE_NAME))
    resp = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie(SESSION_COOKIE_NAME)
    resp.delete_cookie(CSRF_COOKIE_NAME)
    return resp


@web_router.get("/dashboard", response_class=HTMLResponse)
def parent_dashboard(
    request: Request,
    child_id: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    # A browser without a session (or with an expired one) lands on the login form, not raw JSON
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if session_role(user) == "child-view":
        return RedirectResponse(url="/child-view", status_code=status.HTTP_302_FOUND)
    children = db.query(Child).filter(Child.parent_id == user.id).all()
    selected_child = None
    context: dict = {"report": _empty_report(), "devices": [], "policy": None}
    boot: dict = {"childId": "", "csrfToken": ""}

    if children:
        selected_child = next((c for c in children if c.id == child_id), children[0])
        context = _child_context(selected_child, db)
        policy = context["policy"]
        boot.update({
            "childId": selected_child.id,
            "childName": selected_child.display_name,
            "policy": {
                "version": policy.version,
                "daily_limit_weekday_min": policy.daily_limit_weekday_min,
                "daily_limit_weekend_min": policy.daily_limit_weekend_min,
                "schedule_matrix_7x48": context["matrix"],
                "category_budgets": _load_json(policy.category_budgets_json, {}),
                "app_rules": _load_json(policy.app_rules_json, []),
                "domain_rules": _load_json(policy.domain_rules_json, []),
            },
            "pendingRequests": context["report"]["pending_requests"],
        })

    csrf_token = generate_csrf_token(user.id)
    boot["csrfToken"] = csrf_token
    boot["categoryLabels"] = CATEGORY_LABELS
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": user,
            "children": children,
            "selected_child": selected_child,
            "csrf_token": csrf_token,
            "category_labels": CATEGORY_LABELS,
            "boot": boot,
            "active_nav": "dashboard",
            **context,
        },
    )


@web_router.get("/child-view", response_class=HTMLResponse)
def child_transparency_portal(
    request: Request,
    child_id: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """'Hôm nay em đã dùng gì': the same data the parent sees, in a child's words."""
    children = db.query(Child).filter(Child.parent_id == user.id).all() if user else []
    if user and session_role(user) == "child-view":
        # A child-view session only ever sees the one child it was opened for
        children = [c for c in children if c.id == getattr(user, "child_scope", None)]
    child = next((c for c in children if c.id == child_id), children[0]) if children else None
    context = _child_context(child, db) if child else {"report": _empty_report()}

    return templates.TemplateResponse(
        request,
        "child_view.html",
        {
            "current_user": user,
            "children": children,
            "child": child,
            "category_labels": CATEGORY_LABELS,
            "csrf_token": generate_csrf_token(user.id if user else "anon"),
            "active_nav": "child",
            **context,
        },
    )


@web_router.post("/child-view/start")
def start_child_view_session(
    request: Request,
    child_id: str = Form(...),
    csrf_token: str = Form(...),
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Parent hands the browser to the child: the parent session is revoked and replaced by
    a read-only `child-view` session limited to this child (role 3 of F5)."""
    if not user or session_role(user) not in ("parent", "admin"):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not verify_csrf_token(user.id, csrf_token):
        return RedirectResponse(url="/child-view", status_code=status.HTTP_302_FOUND)
    child = db.query(Child).filter(Child.id == child_id, Child.parent_id == user.id).first()
    if not child:
        return RedirectResponse(url="/child-view", status_code=status.HTTP_302_FOUND)

    revoke_session_token(db, request.cookies.get(SESSION_COOKIE_NAME))
    db.add(AuditLog(
        actor_id=user.id,
        actor_role="parent",
        child_id=child.id,
        action="CHILD_VIEW_SESSION_STARTED",
        ip_address=request.client.host if request.client else "unknown",
        old_value_json=None,
        new_value_json=json.dumps({"child": child.display_name}, ensure_ascii=False),
    ))
    db.commit()

    token = create_jwt_token(
        data={"sub": user.id, "role": "child-view", "child_id": child.id},
        expires_delta=timedelta(hours=SESSION_COOKIE_EXPIRE_HOURS),
    )
    resp = RedirectResponse(url="/child-view", status_code=status.HTTP_302_FOUND)
    cookie_kwargs = _session_cookie_kwargs(request)
    resp.set_cookie(key=SESSION_COOKIE_NAME, value=token, httponly=True, **cookie_kwargs)
    resp.set_cookie(key=CSRF_COOKIE_NAME, value=generate_csrf_token(user.id), httponly=False, **cookie_kwargs)
    return resp


def _audit_value_text(raw: str | None) -> str:
    """Readable summary of an audit value, never exposing secrets such as pairing codes."""
    data = _load_json(raw, {})
    if not data:
        return ""
    parts = []
    for key, value in data.items():
        if key in SECRET_AUDIT_KEYS:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        text = str(value)
        parts.append(f"{key}: {text if len(text) <= 60 else text[:57] + '...'}")
    return "; ".join(parts)


@web_router.get("/audit/view", response_class=HTMLResponse)
def audit_view(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Audit trail (NT5). Only entries about the signed-in family's own children are shown."""
    entries = []
    if user:
        children = db.query(Child).filter(Child.parent_id == user.id).all()
        if session_role(user) == "child-view":
            children = [c for c in children if c.id == getattr(user, "child_scope", None)]
        names = {c.id: c.display_name for c in children}
        logs = []
        if names:
            logs = (
                db.query(AuditLog)
                .filter(AuditLog.child_id.in_(list(names)))
                .order_by(AuditLog.ts_utc.desc())
                .limit(100)
                .all()
            )
        tz = local_tz()
        for log in logs:
            when = _parse_utc(log.ts_utc)
            entries.append({
                "when": when.astimezone(tz).strftime("%d/%m/%Y %H:%M") if when else log.ts_utc,
                "who": "Bố mẹ" if log.actor_role == "parent" else ("Quản trị" if log.actor_role == "admin" else "Hệ thống"),
                "child": names.get(log.child_id, ""),
                "ip": log.ip_address,
                "action": AUDIT_ACTION_LABELS.get(log.action, log.action),
                "action_code": log.action,
                "old": _audit_value_text(log.old_value_json),
                "new": _audit_value_text(log.new_value_json),
            })

    return templates.TemplateResponse(
        request,
        "audit_log.html",
        {
            "current_user": user,
            "entries": entries,
            "csrf_token": generate_csrf_token(user.id if user else "anon"),
            "active_nav": "audit",
        },
    )
