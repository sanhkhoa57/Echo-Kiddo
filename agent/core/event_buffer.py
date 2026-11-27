"""Event Buffer for OGK-Agent (FR-F3-01, Section 4.2 & 4.3).
Strictly validates and queues 7-field events into local SQLite database.
Guarantees subjects are clean (no URLs with '/' or '?'), normalized to eTLD+1 for domains,
and executable names for applications.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import tldextract

from agent.core.agent_db import AgentDatabase, DEFAULT_AGENT_DB_PATH

logger = logging.getLogger("OGK.EventBuffer")

VALID_EVENT_TYPES = {
    "app_start", "app_stop", "domain_query",
    "blocked_app", "blocked_domain", "quota_warning",
    "locked", "unlock_request", "override_granted"
}

# Offline tldextract instance
_extractor = tldextract.TLDExtract(suffix_list_urls=None)


def normalize_subject(subject: str, event_type: str) -> str:
    """
    Validates and normalizes subject string.
    Raises ValueError if invalid or contains URL components like '/' or '?'.
    """
    if not subject:
        raise ValueError("Subject cannot be empty")

    cleaned = subject.strip()
    if any(ch in cleaned for ch in "/\\?&#"):
        raise ValueError(
            "Strict schema violation: subject must not contain URL path, query or fragment "
            "characters ('/', '\\', '?', '&', '#')"
        )

    if event_type in ("domain_query", "blocked_domain"):
        extracted = _extractor(cleaned.lower().rstrip("."))
        if not extracted.domain or not extracted.suffix:
            # Handle simulated .test or single-word domains
            parts = cleaned.lower().rstrip(".").split(".")
            if len(parts) >= 2:
                return f"{parts[-2]}.{parts[-1]}"
            return cleaned.lower()
        return f"{extracted.domain}.{extracted.suffix}"
    else:
        # App or system event
        return cleaned.lower()


class EventBuffer:
    """Manages offline event queue with strict schema enforcement."""

    def __init__(self, db: Optional[AgentDatabase] = None, device_id: str = "", child_id: str = ""):
        self.db = db or AgentDatabase(DEFAULT_AGENT_DB_PATH)
        self.device_id = device_id
        self.child_id = child_id

    def record_event(
        self,
        event_type: str,
        subject: str,
        policy_id: str,
        duration_sec: int = 0,
        ts: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        device_id: Optional[str] = None,
        child_id: Optional[str] = None,
    ) -> str:
        """
        Records a single 7-field event into the local SQLite event queue.
        Returns the idempotency_key.
        """
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event type '{event_type}'. Must be one of {VALID_EVENT_TYPES}")

        norm_subject = normalize_subject(subject, event_type)
        key = idempotency_key or str(uuid.uuid4())
        timestamp = ts or datetime.now(timezone.utc).isoformat()
        dev_id = device_id or self.device_id
        c_id = child_id or self.child_id

        if not dev_id:
            raise ValueError("device_id must be provided")
        if not c_id:
            raise ValueError("child_id must be provided")

        self.db.enqueue_event(
            idempotency_key=key,
            ts=timestamp,
            device_id=dev_id,
            child_id=c_id,
            type_=event_type,
            subject=norm_subject,
            duration_sec=max(0, int(duration_sec)),
            policy_id=policy_id,
        )
        logger.debug("Enqueued event: %s | %s | %s", event_type, norm_subject, key)
        return key

    def get_pending_batch(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Retrieves up to `limit` unsynced events for uploading to server."""
        return self.db.get_unsynced_events(limit=limit)

    def mark_synced(self, keys: List[str]) -> None:
        """Marks successfully uploaded events as synced."""
        self.db.mark_events_synced(keys)

    def purge_local_events(self) -> None:
        """Purges local event queue (FR-F3-04 / PURGE_DATA command)."""
        self.db.purge_all_events()
        logger.info("Purged all local queued events.")
