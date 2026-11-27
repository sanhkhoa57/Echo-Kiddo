"""Local SQLite Cache for OGK-Agent (Section 4.2 of technical-specification.md).

Manages C:\\ProgramData\\OGK\\agent.db with 4 core tables:
1. cached_policy (offline policy enforcement)
2. event_queue (offline resilient event store)
3. daily_usage_state (monotonic screen-time & anti-clock tampering)
4. system_snapshots (safe system state capture for 100% clean rollback)
plus device_credentials (pairing identity that must survive a service restart).
"""
import json
import logging
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger("OGK.AgentDB")

DEFAULT_AGENT_DATA_DIR = Path(os.getenv("PROGRAMDATA", "C:\\ProgramData")) / "OGK"
DEFAULT_AGENT_DB_PATH = DEFAULT_AGENT_DATA_DIR / "agent.db"


# Well-known SIDs (language independent): LocalSystem, BUILTIN\Administrators
_SID_SYSTEM = "*S-1-5-18"
_SID_ADMINS = "*S-1-5-32-544"


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def _is_elevated() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def build_acl_command(directory: Path) -> list[str]:
    """icacls command giving ONLY SYSTEM and Administrators access to the agent data dir:
    inherited ACEs (e.g. Users:Write on ProgramData) are removed, so the child's standard
    account can neither change the cached policy nor delete the event queue (F5)."""
    return [
        "icacls", str(directory), "/inheritance:r",
        "/grant:r", f"{_SID_SYSTEM}:(OI)(CI)F",
        "/grant:r", f"{_SID_ADMINS}:(OI)(CI)F",
        "/Q",
    ]


def harden_data_dir_acl(directory: Path) -> bool:
    """Applies the SYSTEM/Administrators-only ACL. Only when running as SYSTEM or an
    elevated admin, so a non-elevated developer never locks themselves out."""
    if sys.platform != "win32" or not _is_elevated():
        return False
    try:
        res = subprocess.run(build_acl_command(directory), capture_output=True, text=True,
                             check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if res.returncode != 0:
            logger.warning("Could not harden ACL on %s: %s", directory, res.stderr.strip())
        return res.returncode == 0
    except Exception as e:
        logger.warning("Could not harden ACL on %s: %s", directory, e)
        return False


class AgentDatabase:
    """Encapsulates local SQLite operations on OGK-Agent."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            env_path = os.getenv("OGK_AGENT_DB_PATH")
            self.db_path = Path(env_path) if env_path else DEFAULT_AGENT_DB_PATH
        else:
            self.db_path = Path(db_path)

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if _same_dir(self.db_path.parent, DEFAULT_AGENT_DATA_DIR):
            harden_data_dir_acl(self.db_path.parent)
        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a connection with required PRAGMAs configured."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        try:
            # WAL mode and concurrency tuning
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=5000;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initializes the 4 tables defined in technical-specification.md Section 4.2."""
        with self.get_connection() as conn:
            # 1. cached_policy table (single active row id=1)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cached_policy (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL,
                    policy_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    fetched_at_utc TEXT NOT NULL
                );
            """)

            # 2. event_queue table (offline storage with idempotency key)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS event_queue (
                    idempotency_key TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    duration_sec INTEGER NOT NULL DEFAULT 0,
                    policy_id TEXT NOT NULL,
                    synced INTEGER NOT NULL DEFAULT 0,
                    created_at_utc TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_queue_synced ON event_queue(synced);
            """)

            # 3. daily_usage_state table (monotonic clock tracking & anti-tampering)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_usage_state (
                    date_local TEXT PRIMARY KEY,
                    used_total_sec INTEGER NOT NULL DEFAULT 0,
                    category_used_json TEXT NOT NULL DEFAULT '{}',
                    last_monotonic_sec REAL NOT NULL DEFAULT 0.0,
                    last_wall_clock_utc TEXT NOT NULL
                );
            """)

            # 4. system_snapshots table (network DNS and browser registry snapshots)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_snapshots (
                    snapshot_type TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    captured_at_utc TEXT NOT NULL,
                    restored_at_utc TEXT
                );
            """)

            # 5. device_credentials table (single row id=1, written at enrollment)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS device_credentials (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    device_id TEXT NOT NULL DEFAULT '',
                    child_id TEXT NOT NULL DEFAULT '',
                    access_token TEXT NOT NULL DEFAULT '',
                    refresh_token TEXT NOT NULL DEFAULT '',
                    server_url TEXT NOT NULL DEFAULT '',
                    offline_pin_hash TEXT,
                    policy_hmac_secret TEXT,
                    updated_at_utc TEXT NOT NULL
                );
            """)

    # --- 0. Device Credentials Methods ---
    _CREDENTIAL_FIELDS = (
        "device_id", "child_id", "access_token", "refresh_token",
        "server_url", "offline_pin_hash", "policy_hmac_secret",
    )
    # Encrypted at rest with AES-256-GCM (agent/core/field_crypto.py)
    _ENCRYPTED_FIELDS = ("access_token", "refresh_token", "policy_hmac_secret")

    @property
    def cipher(self):
        if getattr(self, "_cipher", None) is None:
            from agent.core.field_crypto import FieldCipher, load_or_create_key
            self._cipher = FieldCipher(load_or_create_key(self.db_path.parent))
        return self._cipher

    def save_device_credentials(self, **fields: Any) -> None:
        """Upserts device credentials. Only the fields passed (and not None) are changed."""
        unknown = set(fields) - set(self._CREDENTIAL_FIELDS)
        if unknown:
            raise ValueError(f"Unknown credential fields: {sorted(unknown)}")
        current = self.get_device_credentials() or {}
        merged = {k: current.get(k) for k in self._CREDENTIAL_FIELDS}
        merged.update({k: v for k, v in fields.items() if v is not None})
        for required in ("device_id", "child_id", "access_token", "refresh_token", "server_url"):
            merged[required] = merged[required] or ""
        for name in self._ENCRYPTED_FIELDS:
            merged[name] = self.cipher.encrypt(merged[name])
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO device_credentials (
                    id, device_id, child_id, access_token, refresh_token,
                    server_url, offline_pin_hash, policy_hmac_secret, updated_at_utc
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    device_id = excluded.device_id,
                    child_id = excluded.child_id,
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    server_url = excluded.server_url,
                    offline_pin_hash = excluded.offline_pin_hash,
                    policy_hmac_secret = excluded.policy_hmac_secret,
                    updated_at_utc = excluded.updated_at_utc;
            """, (*(merged[k] for k in self._CREDENTIAL_FIELDS), now))

    def get_device_credentials(self) -> dict[str, Any] | None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM device_credentials WHERE id = 1;").fetchone()
        if not row:
            return None
        data = dict(row)
        for name in self._ENCRYPTED_FIELDS:
            data[name] = self.cipher.decrypt(data.get(name))
        return data

    def clear_device_credentials(self) -> None:
        """Removes pairing identity (un-enroll / privacy wipe)."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM device_credentials;")

    # --- 1. Policy Cache Methods ---
    def save_cached_policy(self, version: int, policy_json: str, signature: str, fetched_at_utc: str | None = None) -> None:
        fetched_at = fetched_at_utc or datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO cached_policy (id, version, policy_json, signature, fetched_at_utc)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version = excluded.version,
                    policy_json = excluded.policy_json,
                    signature = excluded.signature,
                    fetched_at_utc = excluded.fetched_at_utc;
            """, (version, policy_json, signature, fetched_at))

    def get_cached_policy(self) -> dict[str, Any] | None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM cached_policy WHERE id = 1;").fetchone()
            if row:
                data = dict(row)
                # Decoded copy of policy_json for callers that need the policy object
                try:
                    parsed = json.loads(data["policy_json"])
                    data["policy"] = parsed if isinstance(parsed, dict) else None
                except Exception:
                    data["policy"] = None
                return data
            return None

    # --- 2. Event Queue Methods ---
    def enqueue_event(
        self,
        idempotency_key: str,
        ts: str,
        device_id: str,
        child_id: str,
        type_: str,
        subject: str,
        duration_sec: int,
        policy_id: str,
    ) -> bool:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO event_queue (
                    idempotency_key, ts, device_id, child_id, type, subject, duration_sec, policy_id, synced, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?);
            """, (idempotency_key, ts, device_id, child_id, type_, subject, duration_sec, policy_id, created_at))
            return cursor.rowcount > 0

    def get_unsynced_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT idempotency_key, ts, device_id, child_id, type, subject, duration_sec, policy_id
                FROM event_queue
                WHERE synced = 0
                ORDER BY ts ASC
                LIMIT ?;
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def mark_events_synced(self, idempotency_keys: list[str]) -> int:
        if not idempotency_keys:
            return 0
        with self.get_connection() as conn:
            placeholders = ",".join("?" for _ in idempotency_keys)
            cursor = conn.execute(f"""
                UPDATE event_queue
                SET synced = 1
                WHERE idempotency_key IN ({placeholders});
            """, idempotency_keys)
            return cursor.rowcount

    def purge_all_events(self) -> int:
        """Purge all events for privacy wipe (PURGE_DATA command)."""
        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM event_queue;")
            return cursor.rowcount

    def get_today_usage_summary(self, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
        """Top apps / domains of the current local day, from the 7-field event queue only
        (exe names and eTLD+1 domains; shown to the child on the transparency screen)."""
        local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        since_dt = local_midnight.astimezone(timezone.utc)
        # Event timestamps are UTC ISO-8601 strings, so string comparison is chronological
        since = since_dt.isoformat()
        until = (since_dt + timedelta(days=1)).isoformat()
        with self.get_connection() as conn:
            apps = conn.execute("""
                SELECT subject,
                       COALESCE(SUM(duration_sec), 0) AS duration_sec,
                       COUNT(*) AS count,
                       SUM(CASE WHEN type = 'blocked_app' THEN 1 ELSE 0 END) AS blocked_count
                FROM event_queue
                WHERE type IN ('app_start', 'app_stop', 'blocked_app') AND ts >= ? AND ts < ?
                GROUP BY subject
                ORDER BY duration_sec DESC, count DESC, subject ASC
                LIMIT ?;
            """, (since, until, limit)).fetchall()
            domains = conn.execute("""
                SELECT subject,
                       COUNT(*) AS count,
                       SUM(CASE WHEN type = 'blocked_domain' THEN 1 ELSE 0 END) AS blocked_count
                FROM event_queue
                WHERE type IN ('domain_query', 'blocked_domain') AND ts >= ? AND ts < ?
                GROUP BY subject
                ORDER BY count DESC, subject ASC
                LIMIT ?;
            """, (since, until, limit)).fetchall()
        return {
            "top_apps": [dict(r) for r in apps],
            "top_domains": [dict(r) for r in domains],
        }

    # --- 3. Daily Usage State Methods ---
    def get_daily_usage(self, date_local: str) -> dict[str, Any] | None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM daily_usage_state WHERE date_local = ?;", (date_local,)).fetchone()
            if row:
                return dict(row)
            return None

    def save_daily_usage(
        self,
        date_local: str,
        used_total_sec: int,
        category_used_json: str,
        last_monotonic_sec: float,
        last_wall_clock_utc: str | None = None
    ) -> None:
        wall_clock = last_wall_clock_utc or datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO daily_usage_state (
                    date_local, used_total_sec, category_used_json, last_monotonic_sec, last_wall_clock_utc
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(date_local) DO UPDATE SET
                    used_total_sec = excluded.used_total_sec,
                    category_used_json = excluded.category_used_json,
                    last_monotonic_sec = excluded.last_monotonic_sec,
                    last_wall_clock_utc = excluded.last_wall_clock_utc;
            """, (date_local, used_total_sec, category_used_json, last_monotonic_sec, wall_clock))

    # --- 4. System Snapshot Methods ---
    def save_snapshot(self, snapshot_type: str, data_json: str, captured_at_utc: str | None = None) -> None:
        captured_at = captured_at_utc or datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO system_snapshots (snapshot_type, data_json, captured_at_utc, restored_at_utc)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT(snapshot_type) DO UPDATE SET
                    data_json = excluded.data_json,
                    captured_at_utc = excluded.captured_at_utc,
                    restored_at_utc = NULL;
            """, (snapshot_type, data_json, captured_at))

    def has_active_snapshot(self, snapshot_type: str) -> bool:
        """True when a snapshot exists that has not been restored yet, i.e. OGK's own
        settings are (or may still be) applied and the stored original must be kept."""
        row = self.get_snapshot(snapshot_type)
        return bool(row and row.get("data_json") and not row.get("restored_at_utc"))

    def get_snapshot(self, snapshot_type: str) -> dict[str, Any] | None:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM system_snapshots WHERE snapshot_type = ?;", (snapshot_type,)).fetchone()
            if row:
                return dict(row)
            return None

    def mark_snapshot_restored(self, snapshot_type: str, restored_at_utc: str | None = None) -> bool:
        restored_at = restored_at_utc or datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE system_snapshots
                SET restored_at_utc = ?
                WHERE snapshot_type = ?;
            """, (restored_at, snapshot_type))
            return cursor.rowcount > 0
