"""Event Pydantic v2 Schema - STRICT 7-field enforcement (Section F3 & BR-07)."""
import re
from enum import Enum
from typing import Annotated
import tldextract
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    APP_START = "app_start"
    APP_STOP = "app_stop"
    DOMAIN_QUERY = "domain_query"
    BLOCKED_APP = "blocked_app"
    BLOCKED_DOMAIN = "blocked_domain"
    QUOTA_WARNING = "quota_warning"
    LOCKED = "locked"
    UNLOCK_REQUEST = "unlock_request"
    OVERRIDE_GRANTED = "override_granted"


# Pre-configured tldextract instance using offline extraction
_extract = tldextract.TLDExtract(suffix_list_urls=None)


def extract_etld_plus_one(domain: str) -> str:
    """Extract registered domain (eTLD+1) for domain subjects."""
    domain_clean = domain.strip().lower().rstrip(".")
    ext = _extract(domain_clean)
    top_domain = getattr(ext, "top_domain_under_public_suffix", None) or getattr(ext, "registered_domain", None)
    if top_domain:
        return top_domain
    # Fallback for domains like localhost or intranet.test
    parts = domain_clean.split(".")
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    return domain_clean


class EventCreate(BaseModel):
    """Event ingestion schema.
    
    STRICTLY ENFORCES 7 BUSINESS FIELDS + idempotency_key:
    1. ts
    2. device_id
    3. child_id
    4. type
    5. subject
    6. duration_sec
    7. policy_id
    
    Extra fields are strictly forbidden to uphold data minimization (Nghị định 13/2023).
    """
    model_config = ConfigDict(extra="forbid")

    idempotency_key: Annotated[str, Field(min_length=1, max_length=64, description="Unique deduplication key")]
    ts: Annotated[str, Field(min_length=10, max_length=35, description="ISO-8601 UTC timestamp")]
    device_id: Annotated[str, Field(min_length=1, max_length=36)]
    child_id: Annotated[str, Field(min_length=1, max_length=36)]
    type: EventType
    subject: Annotated[str, Field(min_length=1, max_length=255, description="Application filename OR eTLD+1 domain")]
    duration_sec: Annotated[int, Field(ge=0, default=0)]
    policy_id: Annotated[str, Field(min_length=1, max_length=36)]

    @field_validator("subject")
    @classmethod
    def validate_and_sanitize_subject(cls, v: str, info) -> str:
        # STRICT PRIVACY RULE: Must not contain full URL path, query params, or fragments
        if "/" in v or "\\" in v:
            raise ValueError("Subject must not contain URL path or directory separator ('/' or '\\'). Full URLs are strictly rejected.")
        if "?" in v or "&" in v:
            raise ValueError("Subject must not contain query parameters ('?' or '&'). Full URLs are strictly rejected.")
        if "#" in v:
            raise ValueError("Subject must not contain URL fragments ('#').")

        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Subject cannot be empty.")

        event_type = info.data.get("type")
        if event_type in (EventType.DOMAIN_QUERY, EventType.BLOCKED_DOMAIN):
            # Normalize to eTLD+1 according to BR-07
            cleaned = extract_etld_plus_one(cleaned)
        elif event_type in (EventType.APP_START, EventType.APP_STOP, EventType.BLOCKED_APP):
            # Application name: sanitize and keep base filename
            cleaned = cleaned.lower()
            if not re.match(r"^[\w\-. ]+\.exe$", cleaned, re.IGNORECASE) and not re.match(r"^[\w\-. ]+$", cleaned):
                raise ValueError("App subject must be a valid executable name.")

        return cleaned


class EventBatchRequest(BaseModel):
    """Batch event upload payload (max 200 events per batch)."""
    model_config = ConfigDict(extra="forbid")

    events: Annotated[list[EventCreate], Field(min_length=1, max_length=200)]


class EventBatchResponse(BaseModel):
    accepted_count: int
    duplicate_count: int
    acked_keys: list[str]
