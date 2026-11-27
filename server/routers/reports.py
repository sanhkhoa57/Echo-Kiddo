"""Reporting Router (/api/v1/reports/{child_id}) - Transparent data for Parent & Child."""
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.auth.dependencies import get_child_for_parent, get_current_user
from server.models.audit_log import AuditLog
from server.models.child import Child
from server.models.database import get_db
from server.models.event import Event
from server.models.policy import Policy
from server.models.user import User

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])

CATEGORIES = ("education", "entertainment", "social", "gaming", "inappropriate", "unclassified")
USAGE_TYPES = ("app_start", "app_stop")
BLOCK_TYPES = ("blocked_app", "blocked_domain")
REQUEST_DENIED_ACTION = "UNLOCK_REQUEST_DENIED"
PENDING_REQUEST_WINDOW_HOURS = 24

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "seeds" / "domain_catalog.json"


def local_tz() -> timezone:
    """Day boundaries follow the family's wall clock, not UTC (default UTC+7, Vietnam)."""
    try:
        offset_min = int(os.getenv("OGK_TZ_OFFSET_MIN", "420"))
    except ValueError:
        offset_min = 420
    return timezone(timedelta(minutes=offset_min))


def _parse_ts(ts: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@lru_cache(maxsize=1)
def _catalog_index() -> dict[str, str]:
    """domain -> category, from the seeded classification catalog."""
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    index: dict[str, str] = {}
    for category, domains in data.get("categories", {}).items():
        if isinstance(domains, list):
            for domain in domains:
                index[str(domain).lower()] = category
    return index


def _load_json(raw: str | None, fallback):
    try:
        value = json.loads(raw) if raw else fallback
    except ValueError:
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def classify_domain(domain: str, domain_rules: list[dict]) -> str:
    """Parent rules win over the catalog; a rule or catalog entry also covers subdomains."""
    name = domain.lower().strip(".")
    rule_index = {str(r.get("domain", "")).lower(): r.get("category", "unclassified") for r in domain_rules}
    catalog = _catalog_index()
    labels = name.split(".")
    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        if candidate in rule_index:
            return rule_index[candidate]
        if candidate in catalog:
            return catalog[candidate]
    return "unclassified"


def override_key_for(request_key: str) -> str:
    """Deterministic idempotency key linking an override_granted event to its unlock_request."""
    return "ovr_" + hashlib.sha256(request_key.encode("utf-8")).hexdigest()[:56]


def pending_unlock_requests(child_id: str, db: Session) -> list[dict]:
    """unlock_request events of the last 24h that have been neither approved nor denied."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=PENDING_REQUEST_WINDOW_HOURS)).isoformat()
    requests = db.scalars(
        select(Event)
        .where(Event.child_id == child_id, Event.type == "unlock_request", Event.ts >= cutoff)
        .order_by(Event.ts.desc())
        .limit(20)
    ).all()
    if not requests:
        return []

    granted_keys = set(
        db.scalars(
            select(Event.idempotency_key).where(
                Event.idempotency_key.in_([override_key_for(r.idempotency_key) for r in requests])
            )
        ).all()
    )
    denied_keys: set[str] = set()
    denials = db.scalars(
        select(AuditLog.new_value_json).where(
            AuditLog.child_id == child_id,
            AuditLog.action == REQUEST_DENIED_ACTION,
            AuditLog.ts_utc >= cutoff,
        )
    ).all()
    for raw in denials:
        key = _load_json(raw, {}).get("request_key")
        if key:
            denied_keys.add(key)

    tz = local_tz()
    pending = []
    for req in requests:
        if override_key_for(req.idempotency_key) in granted_keys or req.idempotency_key in denied_keys:
            continue
        parsed = _parse_ts(req.ts)
        pending.append({
            "request_key": req.idempotency_key,
            "ts": req.ts,
            "local_time": parsed.astimezone(tz).strftime("%H:%M") if parsed else "",
            "minutes": max(1, req.duration_sec // 60) if req.duration_sec else 15,
            "device_id": req.device_id,
        })
    return pending


def build_child_report(child: Child, db: Session) -> dict:
    """Aggregates the last 7 local days of events for one child."""
    tz = local_tz()
    now_local = datetime.now(timezone.utc).astimezone(tz)
    today = now_local.date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    window_start = datetime.combine(days[0], datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)

    policy = db.query(Policy).filter(Policy.child_id == child.id).first()
    app_rules = _load_json(policy.app_rules_json if policy else None, [])
    domain_rules = _load_json(policy.domain_rules_json if policy else None, [])
    app_category = {str(r.get("exe_name", "")).lower(): r.get("category", "unclassified") for r in app_rules}

    # Stored timestamps are ISO-8601 UTC, so a one-day margin keeps the string filter safe.
    events = db.scalars(
        select(Event)
        .where(Event.child_id == child.id, Event.ts >= (window_start - timedelta(days=1)).isoformat())
        .order_by(Event.ts.desc())
    ).all()

    daily_sec = {d.isoformat(): 0 for d in days}
    daily_blocked = {d.isoformat(): 0 for d in days}
    app_usage: Counter = Counter()
    domain_queries: Counter = Counter()
    category_sec: Counter = Counter()
    blocked_subjects: Counter = Counter()
    recent_blocks: list[dict] = []
    blocked_total = 0
    blocked_today = 0
    today_active_sec = 0
    today_key = today.isoformat()

    for evt in events:
        parsed = _parse_ts(evt.ts)
        if parsed is None:
            continue
        local_dt = parsed.astimezone(tz)
        day_key = local_dt.date().isoformat()
        if day_key not in daily_sec:
            continue

        if evt.type in USAGE_TYPES:
            daily_sec[day_key] += evt.duration_sec
            app_usage[evt.subject] += evt.duration_sec
            category_sec[app_category.get(evt.subject.lower(), "unclassified")] += evt.duration_sec
            if day_key == today_key:
                today_active_sec += evt.duration_sec
        elif evt.type == "domain_query":
            domain_queries[evt.subject] += 1
        elif evt.type in BLOCK_TYPES:
            blocked_total += 1
            daily_blocked[day_key] += 1
            blocked_subjects[evt.subject] += 1
            if day_key == today_key:
                blocked_today += 1
            if len(recent_blocks) < 8:
                recent_blocks.append({
                    "subject": evt.subject,
                    "kind": "app" if evt.type == "blocked_app" else "domain",
                    "local_time": local_dt.strftime("%d/%m %H:%M"),
                })

    top_apps = [
        {"subject": k, "duration_sec": v, "category": app_category.get(k.lower(), "unclassified")}
        for k, v in app_usage.most_common(10)
    ]
    top_domains = [
        {"subject": k, "queries": v, "count": v, "category": classify_domain(k, domain_rules)}
        for k, v in domain_queries.most_common(10)
    ]
    category_breakdown = {c: category_sec.get(c, 0) for c in CATEGORIES if category_sec.get(c, 0) > 0}

    is_weekend = today.weekday() >= 5
    limit_min = 0
    if policy:
        limit_min = policy.daily_limit_weekend_min if is_weekend else policy.daily_limit_weekday_min
    week_total_sec = sum(daily_sec.values())
    today_active_min = round(today_active_sec / 60, 1)
    pending = pending_unlock_requests(child.id, db)

    return {
        "child_id": child.id,
        "display_name": child.display_name,
        "local_date": today_key,
        "is_weekend": is_weekend,
        "today_limit_min": limit_min,
        "today_active_sec": today_active_sec,
        "today_active_min": today_active_min,
        "total_used_min": today_active_min,  # alias
        "week_total_min": round(week_total_sec / 60, 1),
        "total_blocked_events": blocked_total,
        "blocked_count": blocked_total,  # alias
        "blocked_today": blocked_today,
        "daily_breakdown": daily_sec,
        "daily_blocked": daily_blocked,
        "category_breakdown": category_breakdown,
        "top_10_apps": top_apps,
        "top_apps": top_apps,  # alias
        "top_10_domains": top_domains,
        "top_domains": top_domains,  # alias
        "top_blocked": [{"subject": k, "count": v} for k, v in blocked_subjects.most_common(5)],
        "recent_blocks": recent_blocks,
        "pending_requests": pending,
    }


@router.get("/export/csv")
def export_events_csv(
    child_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Exports events for child as clean CSV according to strict 7-field schema."""
    import csv
    import io
    from fastapi.responses import Response

    child = get_child_for_parent(child_id, db, current_user)
    events_stmt = (
        select(Event)
        .where(Event.child_id == child.id)
        .order_by(Event.ts.desc())
        .limit(2000)
    )
    events = db.scalars(events_stmt).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ts", "device_id", "child_id", "type", "subject", "duration_sec", "policy_id"])
    for e in events:
        writer.writerow([e.ts, e.device_id, e.child_id, e.type, e.subject, e.duration_sec, e.policy_id])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ogk_events_{child.id}.csv"}
    )


@router.get("/{child_id}")
def get_child_report(
    child_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Daily and weekly usage, top 10 apps and domains, block counts, pending child requests."""
    child = get_child_for_parent(child_id, db, current_user)  # anti-IDOR
    return build_child_report(child, db)
