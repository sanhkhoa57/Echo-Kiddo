"""Demo Seeder Script for EC - Echo Kiddo.
Seeds realistic demo data into EC Server database:
- Parent user (parent@ogk.local / AdminPassword123!)
- Child profile (Bé Minh, age 6-11)
- Paired Windows 11 device (PC-MINH-WIN11)
- Signed Policy v1 with 7x48 schedule matrix and domain/app rules
- 7-field events across past 7 days for rich Dashboard charts
- Audit log records demonstrating NT5 transparency
"""
import os
import sys
import uuid
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from server.models.database import create_ogk_engine, SessionLocal
from server.models.base import Base
from server.models.user import User
from server.models.child import Child
from server.models.device import Device
from server.models.policy import Policy
from server.models.event import Event
from server.models.audit_log import AuditLog
from server.auth.security import get_password_hash
from server.services.policy_service import sign_policy_payload


def seed_demo_data():
    print("==================================================")
    print("      EC - Echo Kiddo Demo Data Seeder        ")
    print("==================================================")

    # Initialize tables
    engine = create_ogk_engine()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 1. Create or get Parent User
        parent_email = "parent@ogk.local"
        parent = db.query(User).filter(User.email == parent_email).first()
        if not parent:
            parent = User(
                email=parent_email,
                password_hash=get_password_hash("AdminPassword123!"),
                role="parent",
            )
            db.add(parent)
            db.commit()
            db.refresh(parent)
            print(f"✓ Created Parent account: {parent.email}")
        else:
            print(f"• Parent account exists: {parent.email}")

        # 2. Create or get Child
        child = db.query(Child).filter(Child.parent_id == parent.id).first()
        if not child:
            child = Child(
                parent_id=parent.id,
                display_name="Bé Minh",
                age_group="6-11",
            )
            db.add(child)
            db.commit()
            db.refresh(child)
            print(f"✓ Created Child profile: {child.display_name} (ID: {child.id})")
        else:
            print(f"• Child profile exists: {child.display_name}")

        # 3. Create or get Device
        device = db.query(Device).filter(Device.child_id == child.id).first()
        if not device:
            device = Device(
                child_id=child.id,
                device_name="PC-MINH-WIN11",
                fingerprint_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                windows_user_sid="S-1-5-21-3623811015-3361044348-30300820-1001",
                applied_policy_version=1,
                last_heartbeat_utc=datetime.now(timezone.utc).isoformat(),
            )
            db.add(device)
            db.commit()
            db.refresh(device)
            print(f"✓ Paired Device: {device.device_name} (ID: {device.id})")
        else:
            print(f"• Device exists: {device.device_name}")

        # 4. Create or update Signed Policy
        policy = db.query(Policy).filter(Policy.child_id == child.id).first()
        now_iso = datetime.now(timezone.utc).isoformat()
        domain_rules = [
            {"domain": "scratch.mit.edu", "category": "education", "action": "allow"},
            {"domain": "khanacademy.org", "category": "education", "action": "allow"},
            {"domain": "uit.edu.vn", "category": "education", "action": "allow"},
            {"domain": "wikipedia.org", "category": "education", "action": "allow"},
            {"domain": "roblox.com", "category": "gaming", "action": "allow"},
            {"domain": "bad-simulated-site.test", "category": "inappropriate", "action": "block"},
            {"domain": "gambling-sim.test", "category": "inappropriate", "action": "block"},
        ]
        app_rules = [
            {"exe_name": "notepad.exe", "category": "education", "action": "allow"},
            {"exe_name": "calc.exe", "category": "education", "action": "allow"},
            {"exe_name": "game.exe", "category": "gaming", "action": "block"},
        ]
        category_budgets = {
            "education": 180,
            "entertainment": 60,
            "gaming": 45,
            "social": 0,
        }

        # 7x48 binary schedule: Mon-Fri night lock (22h-6h), weekend open
        schedule_matrix = []
        for day in range(7):
            for slot in range(48):
                hour = slot // 2
                # Lock night 22:00 - 06:00
                if hour >= 22 or hour < 6:
                    schedule_matrix.append("0")
                else:
                    schedule_matrix.append("1")
        schedule_str = "".join(schedule_matrix)

        sig_payload = {
            "child_id": child.id,
            "version": 1,
            "daily_limit_weekday_min": 120,
            "daily_limit_weekend_min": 180,
            "schedule_matrix_7x48": schedule_str,
            "category_budgets_json": json.dumps(category_budgets),
            "app_rules_json": json.dumps(app_rules),
            "domain_rules_json": json.dumps(domain_rules),
            "updated_at_utc": now_iso,
        }
        signature = sign_policy_payload(sig_payload)

        if not policy:
            policy = Policy(
                child_id=child.id,
                version=1,
                daily_limit_weekday_min=120,
                daily_limit_weekend_min=180,
                schedule_matrix_7x48=schedule_str,
                category_budgets_json=json.dumps(category_budgets),
                app_rules_json=json.dumps(app_rules),
                domain_rules_json=json.dumps(domain_rules),
                offline_pin_hash=get_password_hash("1234"),
                signature=signature,
                updated_at_utc=now_iso,
            )
            db.add(policy)
            db.commit()
            print("✓ Created Signed Policy v1 with 7x48 Schedule Matrix")
        else:
            print("• Policy exists for child.")

        # 5. Seed Events for the past 7 days (Strict 7-field schema)
        now = datetime.now(timezone.utc)
        events_to_seed = []

        # Daily usage progression
        apps_sample = [
            ("notepad.exe", 1200),
            ("code.exe", 2400),
            ("scratch.exe", 1800),
            ("calculator.exe", 600),
            ("zoom.exe", 3000),
            ("chrome.exe", 1500),
        ]
        domains_sample = [
            "mit.edu", "khanacademy.org", "wikipedia.org",
            "uit.edu.vn", "google.com", "youtube.com", "tuoitre.vn"
        ]

        # Check existing events count
        evt_count = db.query(Event).filter(Event.child_id == child.id).count()
        newest = db.query(Event.ts).filter(Event.child_id == child.id).order_by(Event.ts.desc()).first()
        stale = newest is not None and newest[0] < (now - timedelta(hours=12)).isoformat()
        if stale:
            # Reports cover the last 7 days: refresh demo events seeded on an earlier day
            db.query(Event).filter(Event.child_id == child.id).delete()
            db.commit()
            print(f"• Removed {evt_count} stale demo events (newest {newest[0][:16]}).")
            evt_count = 0
        if evt_count < 20:
            # Usage varies by day (index 0 = today), so the weekly chart looks like a real week
            day_factor = [0.55, 1.1, 0.8, 1.25, 0.7, 1.4, 0.95]
            for day_offset in range(7):
                day_time = now - timedelta(days=day_offset)

                # Apps
                for app_name, base_dur in apps_sample:
                    dur = int(base_dur * day_factor[day_offset])
                    events_to_seed.append(Event(
                        idempotency_key=str(uuid.uuid4()),
                        ts=(day_time - timedelta(minutes=dur // 60)).isoformat(),
                        device_id=device.id,
                        child_id=child.id,
                        type="app_start",
                        subject=app_name,
                        duration_sec=dur,
                        policy_id="v1",
                    ))

                # Domains
                for dom in domains_sample:
                    events_to_seed.append(Event(
                        idempotency_key=str(uuid.uuid4()),
                        ts=day_time.isoformat(),
                        device_id=device.id,
                        child_id=child.id,
                        type="domain_query",
                        subject=dom,
                        duration_sec=0,
                        policy_id="v1",
                    ))

                # Blocked events
                events_to_seed.append(Event(
                    idempotency_key=str(uuid.uuid4()),
                    ts=day_time.isoformat(),
                    device_id=device.id,
                    child_id=child.id,
                    type="blocked_domain",
                    subject="bad-simulated-site.test",
                    duration_sec=0,
                    policy_id="v1",
                ))
                events_to_seed.append(Event(
                    idempotency_key=str(uuid.uuid4()),
                    ts=day_time.isoformat(),
                    device_id=device.id,
                    child_id=child.id,
                    type="blocked_app",
                    subject="game.exe",
                    duration_sec=0,
                    policy_id="v1",
                ))

            # One pending "Xin thêm giờ" from the child, so the approve / deny flow can be demoed
            events_to_seed.append(Event(
                idempotency_key=str(uuid.uuid4()),
                ts=(now - timedelta(minutes=8)).isoformat(),
                device_id=device.id,
                child_id=child.id,
                type="unlock_request",
                subject="system",
                duration_sec=900,
                policy_id="v1",
            ))
            db.bulk_save_objects(events_to_seed)
            db.commit()
            print(f"✓ Seeded {len(events_to_seed)} realistic 7-field events across 7 days.")
        else:
            print(f"• Events already exist ({evt_count} records).")

        # 6. Seed Audit Logs (NT5 Transparency)
        # Only entries tied to the child show up on the audit page (filtered per family)
        audit_count = db.query(AuditLog).filter(AuditLog.child_id == child.id).count()
        if audit_count < 3:
            logs = [
                AuditLog(
                    actor_id=parent.id,
                    actor_role="parent",
                    ip_address="127.0.0.1",
                    child_id=child.id,
                    action="CREATE_PAIRING_CODE",
                    old_value_json=None,
                    new_value_json=json.dumps({"child_id": child.id, "consent": True}),
                    ts_utc=(now - timedelta(days=2)).isoformat(),
                ),
                AuditLog(
                    actor_id=parent.id,
                    actor_role="parent",
                    ip_address="127.0.0.1",
                    child_id=child.id,
                    action="UPDATE_POLICY",
                    old_value_json=json.dumps({"daily_limit_weekday_min": 90}),
                    new_value_json=json.dumps({"daily_limit_weekday_min": 120}),
                    ts_utc=(now - timedelta(days=1)).isoformat(),
                ),
                AuditLog(
                    actor_id=parent.id,
                    actor_role="parent",
                    ip_address="127.0.0.1",
                    child_id=child.id,
                    action="COMMAND_ADD_TIME_15M",
                    old_value_json=None,
                    new_value_json=json.dumps({"command": "ADD_TIME_15M"}),
                    ts_utc=now.isoformat(),
                ),
            ]
            db.bulk_save_objects(logs)
            db.commit()
            print(f"✓ Seeded {len(logs)} audit log trail entries.")
        else:
            print(f"• Audit logs already exist ({audit_count} entries).")

        print("==================================================")
        print("✓ Khởi tạo dữ liệu mẫu Demo thành công!")
        print(f"Đăng nhập Web Dashboard tại: http://127.0.0.1:8000/login")
        print(f"Email:    {parent_email}")
        print(f"Mật khẩu: AdminPassword123!")
        print("==================================================")

    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
