"""Tests for Agent local SQLite cache (agent_db.py) and 4 core tables."""
import json
import os
import tempfile
import pytest

from agent.core.agent_db import AgentDatabase


@pytest.fixture
def temp_agent_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AgentDatabase(db_path=path)
    yield db
    if os.path.exists(path):
        os.remove(path)


def test_cached_policy_operations(temp_agent_db):
    """Verify saving and retrieving cached policy with signature."""
    assert temp_agent_db.get_cached_policy() is None

    policy_payload = json.dumps({"version": 1, "daily_limit_weekday_min": 90})
    temp_agent_db.save_cached_policy(
        version=1,
        policy_json=policy_payload,
        signature="mock_hmac_signature_v1"
    )

    cached = temp_agent_db.get_cached_policy()
    assert cached is not None
    assert cached["version"] == 1
    assert cached["signature"] == "mock_hmac_signature_v1"
    assert json.loads(cached["policy_json"])["daily_limit_weekday_min"] == 90

    # Test update to v2
    temp_agent_db.save_cached_policy(
        version=2,
        policy_json=json.dumps({"version": 2, "daily_limit_weekday_min": 100}),
        signature="mock_hmac_signature_v2"
    )
    cached_v2 = temp_agent_db.get_cached_policy()
    assert cached_v2["version"] == 2
    assert cached_v2["signature"] == "mock_hmac_signature_v2"


def test_event_queue_flow(temp_agent_db):
    """Verify offline event enqueue, fetch unsynced, mark synced, and purge."""
    # Enqueue 3 events
    temp_agent_db.enqueue_event(
        idempotency_key="key_1",
        ts="2026-11-10T15:30:00Z",
        device_id="dev_1",
        child_id="child_1",
        type_="app_start",
        subject="calculator.exe",
        duration_sec=0,
        policy_id="pol_1"
    )
    temp_agent_db.enqueue_event(
        idempotency_key="key_2",
        ts="2026-11-10T15:35:00Z",
        device_id="dev_1",
        child_id="child_1",
        type_="domain_query",
        subject="khanacademy.org",
        duration_sec=300,
        policy_id="pol_1"
    )
    # Duplicate insertion should be safely ignored (idempotent)
    inserted_dup = temp_agent_db.enqueue_event(
        idempotency_key="key_1",
        ts="2026-11-10T15:30:00Z",
        device_id="dev_1",
        child_id="child_1",
        type_="app_start",
        subject="calculator.exe",
        duration_sec=0,
        policy_id="pol_1"
    )
    assert inserted_dup is False

    unsynced = temp_agent_db.get_unsynced_events()
    assert len(unsynced) == 2

    # Mark key_1 as synced
    marked = temp_agent_db.mark_events_synced(["key_1"])
    assert marked == 1

    unsynced_after = temp_agent_db.get_unsynced_events()
    assert len(unsynced_after) == 1
    assert unsynced_after[0]["idempotency_key"] == "key_2"

    # Purge all (PURGE_DATA command)
    purged = temp_agent_db.purge_all_events()
    assert purged == 2
    assert len(temp_agent_db.get_unsynced_events()) == 0


def test_daily_usage_state(temp_agent_db):
    """Verify daily usage tracking with monotonic clock."""
    today = "2026-11-10"
    assert temp_agent_db.get_daily_usage(today) is None

    category_used = json.dumps({"education": 1200, "gaming": 600})
    temp_agent_db.save_daily_usage(
        date_local=today,
        used_total_sec=1800,
        category_used_json=category_used,
        last_monotonic_sec=12345.67
    )

    usage = temp_agent_db.get_daily_usage(today)
    assert usage is not None
    assert usage["used_total_sec"] == 1800
    assert usage["last_monotonic_sec"] == 12345.67
    assert json.loads(usage["category_used_json"])["gaming"] == 600


def test_system_snapshots_save_and_restore(temp_agent_db):
    """Verify system_snapshots capture and restoration tracking for DNS & Registry."""
    dns_data = json.dumps([{"interface_index": 12, "name": "Wi-Fi", "dhcp_enabled": True, "dns_servers": ["192.168.1.1"]}])
    temp_agent_db.save_snapshot("NETWORK_DNS", dns_data)

    registry_data = json.dumps({"Chrome_DnsOverHttpsMode": "automatic"})
    temp_agent_db.save_snapshot("BROWSER_REGISTRY", registry_data)

    snap_dns = temp_agent_db.get_snapshot("NETWORK_DNS")
    assert snap_dns is not None
    assert snap_dns["restored_at_utc"] is None
    assert json.loads(snap_dns["data_json"])[0]["name"] == "Wi-Fi"

    # Mark restored
    restored = temp_agent_db.mark_snapshot_restored("NETWORK_DNS")
    assert restored is True
    snap_dns_after = temp_agent_db.get_snapshot("NETWORK_DNS")
    assert snap_dns_after["restored_at_utc"] is not None


def test_device_secrets_are_encrypted_at_rest(tmp_path):
    """F5: access/refresh tokens and the policy HMAC secret are AES-256-GCM encrypted in agent.db."""
    import sqlite3
    from agent.core.agent_db import AgentDatabase

    db = AgentDatabase(tmp_path / "agent.db")
    db.save_device_credentials(device_id="dev-1", child_id="chd-1", access_token="acc.jwt",
                               refresh_token="ref.jwt", server_url="https://lab", policy_hmac_secret="s3cret")
    raw = sqlite3.connect(tmp_path / "agent.db").execute(
        "SELECT access_token, refresh_token, policy_hmac_secret, device_id FROM device_credentials").fetchone()
    assert all(v.startswith("enc:v1:") for v in raw[:3])
    assert "acc.jwt" not in "".join(raw[:3]) and raw[3] == "dev-1"   # identifiers stay readable

    creds = AgentDatabase(tmp_path / "agent.db").get_device_credentials()   # key reloaded from key file
    assert (creds["access_token"], creds["refresh_token"], creds["policy_hmac_secret"]) == ("acc.jwt", "ref.jwt", "s3cret")
    assert (tmp_path / "agent.key").exists()


def test_legacy_plaintext_credentials_still_load(tmp_path):
    import sqlite3
    from agent.core.agent_db import AgentDatabase

    db = AgentDatabase(tmp_path / "agent.db")
    with sqlite3.connect(tmp_path / "agent.db") as conn:
        conn.execute("INSERT INTO device_credentials (id, device_id, child_id, access_token, refresh_token, server_url, updated_at_utc) "
                     "VALUES (1, 'd', 'c', 'plain-acc', 'plain-ref', 'u', 'now')")
    assert db.get_device_credentials()["access_token"] == "plain-acc"
