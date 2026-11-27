"""Tests for OGK-Server Database, PRAGMA configuration, and 7 core models."""
import os
import tempfile
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from server.models.base import Base
from server.models.database import create_ogk_engine
from server.models.user import User
from server.models.child import Child
from server.models.device import Device
from server.models.pairing_code import PairingCode
from server.models.policy import Policy
from server.models.event import Event
from server.models.audit_log import AuditLog


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database with OGK PRAGMA settings."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    engine = create_ogk_engine(db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield TestingSessionLocal, engine

    engine.dispose()
    if os.path.exists(path):
        os.remove(path)


def test_sqlite_pragmas(temp_db):
    """Verify PRAGMA journal_mode=WAL, foreign_keys=ON, busy_timeout=5000."""
    _, engine = temp_db
    with engine.connect() as conn:
        wal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert wal_mode.lower() == "wal"

        fk_mode = conn.execute(text("PRAGMA foreign_keys;")).scalar()
        assert fk_mode == 1

        busy_timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()
        assert busy_timeout == 5000


def test_user_and_child_cascade(temp_db):
    """Verify 1 User : n Children with CASCADE delete."""
    SessionLocal, _ = temp_db
    session = SessionLocal()

    # Create User
    user = User(
        email="parent@example.com",
        password_hash="$argon2id$mock_hash_for_testing",
        role="parent"
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Create Children
    child1 = Child(parent_id=user.id, display_name="Kid One", age_group="6-11")
    child2 = Child(parent_id=user.id, display_name="Kid Two", age_group="12-14")
    session.add_all([child1, child2])
    session.commit()

    children = session.scalars(select(Child).where(Child.parent_id == user.id)).all()
    assert len(children) == 2

    # Delete User -> Children should be deleted via ON DELETE CASCADE
    session.delete(user)
    session.commit()

    remaining_children = session.scalars(select(Child)).all()
    assert len(remaining_children) == 0
    session.close()


def test_pairing_code_consent_check(temp_db):
    """Verify pairing_codes requires consent_confirmed = 1 per Decree 13/2023."""
    SessionLocal, _ = temp_db
    session = SessionLocal()

    user = User(email="parent2@example.com", password_hash="hash")
    session.add(user)
    session.commit()

    child = Child(parent_id=user.id, display_name="An")
    session.add(child)
    session.commit()

    # Valid pairing code (consent_confirmed = 1)
    code_valid = PairingCode(
        code="ABCDEF12",
        parent_id=user.id,
        child_id=child.id,
        consent_confirmed=1,
        expires_at_utc="2026-11-10T16:00:00Z"
    )
    session.add(code_valid)
    session.commit()

    # Invalid pairing code (consent_confirmed = 0) should fail CheckConstraint
    code_invalid = PairingCode(
        code="INVALID1",
        parent_id=user.id,
        child_id=child.id,
        consent_confirmed=0,
        expires_at_utc="2026-11-10T16:00:00Z"
    )
    session.add(code_invalid)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()
    session.close()


def test_event_strict_7_fields_and_type_constraint(temp_db):
    """Verify Event model adheres to strict 7 fields and type check constraint."""
    SessionLocal, _ = temp_db
    session = SessionLocal()

    user = User(email="parent3@example.com", password_hash="hash")
    session.add(user)
    session.commit()

    child = Child(parent_id=user.id, display_name="Binh")
    session.add(child)
    session.commit()

    device = Device(
        child_id=child.id,
        device_name="DESKTOP-TEST",
        fingerprint_hash="a"*64
    )
    session.add(device)
    session.commit()

    # Valid event
    evt_valid = Event(
        idempotency_key="idemp_001",
        ts="2026-11-10T15:30:00Z",
        device_id=device.id,
        child_id=child.id,
        type="domain_query",
        subject="wikipedia.org",
        duration_sec=30,
        policy_id="pol_v1"
    )
    session.add(evt_valid)
    session.commit()

    retrieved = session.get(Event, "idemp_001")
    assert retrieved is not None
    assert retrieved.subject == "wikipedia.org"
    assert retrieved.type == "domain_query"

    # Invalid event type should fail CheckConstraint
    evt_invalid = Event(
        idempotency_key="idemp_002",
        ts="2026-11-10T15:31:00Z",
        device_id=device.id,
        child_id=child.id,
        type="invalid_event_type",
        subject="test.com",
        duration_sec=0,
        policy_id="pol_v1"
    )
    session.add(evt_invalid)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()
    session.close()


def test_audit_log_creation(temp_db):
    """Verify audit_logs records administrative and policy actions."""
    SessionLocal, _ = temp_db
    session = SessionLocal()

    audit = AuditLog(
        actor_id="parent_user_123",
        actor_role="parent",
        ip_address="192.168.1.50",
        action="UPDATE_POLICY_DAILY_LIMIT",
        old_value_json='{"daily_limit": 60}',
        new_value_json='{"daily_limit": 90}'
    )
    session.add(audit)
    session.commit()

    retrieved = session.get(AuditLog, audit.id)
    assert retrieved is not None
    assert retrieved.action == "UPDATE_POLICY_DAILY_LIMIT"
    assert retrieved.actor_role == "parent"
    session.close()
