"""Tests for Pydantic v2 schemas: strict 7 fields, URL rejection, eTLD+1 normalization."""
import pytest
from pydantic import ValidationError

from server.schemas.event import (
    EventCreate,
    EventType,
    EventBatchRequest,
    extract_etld_plus_one,
)
from server.schemas.policy import PolicyCreate
from server.schemas.pairing import PairingCodeCreate


def test_event_create_valid():
    """Verify valid EventCreate accepts correct 7 business fields."""
    evt = EventCreate(
        idempotency_key="evt_001_idempotent",
        ts="2026-11-10T15:30:00Z",
        device_id="dev_123",
        child_id="child_456",
        type=EventType.DOMAIN_QUERY,
        subject="wikipedia.org",
        duration_sec=45,
        policy_id="pol_001"
    )
    assert evt.subject == "wikipedia.org"
    assert evt.type == EventType.DOMAIN_QUERY
    assert evt.duration_sec == 45


def test_event_create_rejects_extra_fields():
    """Verify extra fields are strictly forbidden (data minimization principle)."""
    with pytest.raises(ValidationError) as exc:
        EventCreate(
            idempotency_key="evt_002",
            ts="2026-11-10T15:30:00Z",
            device_id="dev_123",
            child_id="child_456",
            type=EventType.DOMAIN_QUERY,
            subject="google.com",
            duration_sec=0,
            policy_id="pol_001",
            full_url="https://google.com/search?q=test",  # FORBIDDEN
            screenshot_base64="mock_screenshot"           # FORBIDDEN
        )
    errors = str(exc.value)
    assert "Extra inputs are not permitted" in errors or "extra_forbidden" in errors


@pytest.mark.parametrize("invalid_subject", [
    "youtube.com/watch?v=dQw4w9WgXcQ",
    "https://facebook.com/messages",
    "google.com/search",
    "m.tiktok.com/@user/video/123",
    "example.com/api/v1?token=123",
    "school.edu.vn/?query=math",
    "site.com?user=test#profile",
])
def test_event_create_rejects_url_path_and_query(invalid_subject):
    """Verify subject with '/' or '?' is strictly rejected (HTTP 422 equivalent)."""
    with pytest.raises(ValidationError) as exc:
        EventCreate(
            idempotency_key="evt_test_url",
            ts="2026-11-10T15:30:00Z",
            device_id="dev_123",
            child_id="child_456",
            type=EventType.DOMAIN_QUERY,
            subject=invalid_subject,
            duration_sec=10,
            policy_id="pol_001"
        )
    assert "Full URLs are strictly rejected" in str(exc.value)


@pytest.mark.parametrize("input_domain,expected_etld1", [
    ("m.youtube.com", "youtube.com"),
    ("sub.school.edu.vn", "school.edu.vn"),
    ("portal.uit.edu.vn", "uit.edu.vn"),
    ("chat.openai.com", "openai.com"),
    ("maps.google.com", "google.com"),
    ("wikipedia.org.", "wikipedia.org"),
])
def test_etld_plus_one_normalization(input_domain, expected_etld1):
    """Verify subdomains are trimmed to registered domain eTLD+1 per BR-07."""
    assert extract_etld_plus_one(input_domain) == expected_etld1

    evt = EventCreate(
        idempotency_key="evt_norm",
        ts="2026-11-10T15:30:00Z",
        device_id="dev_123",
        child_id="child_456",
        type=EventType.DOMAIN_QUERY,
        subject=input_domain,
        duration_sec=0,
        policy_id="pol_001"
    )
    assert evt.subject == expected_etld1


def test_app_subject_validation():
    """Verify application subjects must be clean executable names."""
    evt = EventCreate(
        idempotency_key="evt_app",
        ts="2026-11-10T15:30:00Z",
        device_id="dev_123",
        child_id="child_456",
        type=EventType.APP_START,
        subject="RobloxPlayerBeta.exe",
        duration_sec=0,
        policy_id="pol_001"
    )
    assert evt.subject == "robloxplayerbeta.exe"

    # Reject path in app name
    with pytest.raises(ValidationError):
        EventCreate(
            idempotency_key="evt_app_path",
            ts="2026-11-10T15:30:00Z",
            device_id="dev_123",
            child_id="child_456",
            type=EventType.APP_START,
            subject="C:\\Games\\game.exe",
            duration_sec=0,
            policy_id="pol_001"
        )


def test_batch_request_limits():
    """Verify EventBatchRequest allows up to 200 items and rejects empty list."""
    # Empty list
    with pytest.raises(ValidationError):
        EventBatchRequest(events=[])

    # Valid batch of 5
    events = [
        EventCreate(
            idempotency_key=f"key_{i}",
            ts="2026-11-10T15:30:00Z",
            device_id="dev_123",
            child_id="child_456",
            type=EventType.DOMAIN_QUERY,
            subject=f"test{i}.example",
            duration_sec=5,
            policy_id="pol_001"
        )
        for i in range(5)
    ]
    batch = EventBatchRequest(events=events)
    assert len(batch.events) == 5

    # Reject > 200 events
    too_many = [
        EventCreate(
            idempotency_key=f"key_{i}",
            ts="2026-11-10T15:30:00Z",
            device_id="dev_123",
            child_id="child_456",
            type=EventType.DOMAIN_QUERY,
            subject=f"test{i}.example",
            duration_sec=1,
            policy_id="pol_001"
        )
        for i in range(201)
    ]
    with pytest.raises(ValidationError):
        EventBatchRequest(events=too_many)


def test_schedule_matrix_validation():
    """Verify schedule matrix strictly requires 336 chars of 0 and 1."""
    # Valid matrix 336
    p = PolicyCreate(child_id="c1", schedule_matrix_7x48="1" * 336)
    assert len(p.schedule_matrix_7x48) == 336

    # Invalid length (335)
    with pytest.raises(ValidationError):
        PolicyCreate(child_id="c1", schedule_matrix_7x48="1" * 335)

    # Invalid character ('2')
    with pytest.raises(ValidationError):
        PolicyCreate(child_id="c1", schedule_matrix_7x48=("1" * 335) + "2")


def test_pairing_code_requires_consent():
    """Verify pairing code generation requires consent_confirmed=True."""
    with pytest.raises(ValidationError):
        PairingCodeCreate(child_id="c1", consent_confirmed=False)

    p = PairingCodeCreate(child_id="c1", consent_confirmed=True)
    assert p.consent_confirmed is True
