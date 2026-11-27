"""Policy Signer and Management Service (Section F4, FR-F4-03)."""
import hmac
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from server.models.policy import Policy
from server.models.audit_log import AuditLog
from server.auth.security import JWT_SECRET, get_password_hash

SEED_PATH = Path(__file__).resolve().parent.parent / "seeds" / "domain_catalog.json"

# The single list of fields covered by the policy HMAC. Must stay identical to
# agent/core/policy_verifier.py. Metadata such as `id` is never signed.
SIGNED_POLICY_KEYS = (
    "child_id",
    "version",
    "daily_limit_weekday_min",
    "daily_limit_weekend_min",
    "schedule_matrix_7x48",
    "category_budgets_json",
    "app_rules_json",
    "domain_rules_json",
    "updated_at_utc",
)


def derive_policy_secret(jwt_secret: str) -> str:
    """Derives a dedicated policy-signing key so the JWT secret itself never leaves the server."""
    return hmac.new(jwt_secret.encode("utf-8"), b"ogk-policy-signing-v1", hashlib.sha256).hexdigest()


# Policy signing key shared with enrolled agents (issued as `policy_hmac_secret` at enrollment).
POLICY_SECRET = os.getenv("OGK_POLICY_SECRET") or derive_policy_secret(JWT_SECRET)


def canonical_policy_bytes(payload: dict) -> bytes:
    """Creates a deterministic UTF-8 byte representation for cryptographic signing."""
    if any(k in payload for k in SIGNED_POLICY_KEYS):
        data = {k: payload[k] for k in SIGNED_POLICY_KEYS if k in payload}
    else:
        data = {k: v for k, v in payload.items() if k != "signature"}
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return canonical_json.encode("utf-8")


def sign_policy_payload(payload: dict, secret: str = POLICY_SECRET) -> str:
    """Signs policy payload with HMAC-SHA256."""
    data_bytes = canonical_policy_bytes(payload)
    return hmac.new(secret.encode("utf-8"), data_bytes, hashlib.sha256).hexdigest()


def verify_policy_signature(payload: dict, signature: str, secret: str = POLICY_SECRET) -> bool:
    """Verifies HMAC-SHA256 signature in constant time."""
    expected = sign_policy_payload(payload, secret)
    return hmac.compare_digest(expected, signature)


def policy_signed_dict(policy: Policy) -> dict:
    """Builds the exact signed field set from a Policy row."""
    return {k: getattr(policy, k) for k in SIGNED_POLICY_KEYS}


def policy_wire_dict(policy: Policy) -> dict:
    """Signed fields + signature, as delivered to the agent at enrollment."""
    data = policy_signed_dict(policy)
    data["signature"] = policy.signature
    return data


def ensure_policy_signature(policy: Policy, db: Session) -> Policy:
    """Re-signs a stored policy whose signature does not match the current signing key
    (rows created before the signing key / field list was unified). Version is unchanged."""
    payload = policy_signed_dict(policy)
    if not policy.signature or not verify_policy_signature(payload, policy.signature):
        policy.signature = sign_policy_payload(payload)
        db.commit()
        db.refresh(policy)
    return policy


def create_default_policy_for_child(child_id: str, db: Session) -> Policy:
    """Initializes signed default policy for kids aged 6-11 from seed catalog."""
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    default_template = catalog["default_policy_6_11"]
    categories = catalog["categories"]

    # Construct app rules
    app_rules = [
        {"exe_name": "notepad.exe", "category": "education", "action": "allow"},
        {"exe_name": "calc.exe", "category": "education", "action": "allow"},
        {"exe_name": "explorer.exe", "category": "unclassified", "action": "allow"},
        {"exe_name": "robloxplayerbeta.exe", "category": "gaming", "action": "allow"},
    ]

    # Construct domain rules from seed
    domain_rules = []
    for cat_name, domains in categories.items():
        rule_action = default_template["category_rules"].get(cat_name, "allow")
        for dom in domains:
            domain_rules.append({
                "domain": dom,
                "category": cat_name,
                "action": "block" if rule_action == "block" else "allow"
            })

    category_budgets_json = json.dumps(default_template["category_budgets_min"])
    app_rules_json = json.dumps(app_rules)
    domain_rules_json = json.dumps(domain_rules)

    now_utc = datetime.now(timezone.utc).isoformat()

    policy_dict_to_sign = {
        "child_id": child_id,
        "version": 1,
        "daily_limit_weekday_min": default_template["daily_limit_weekday_min"],
        "daily_limit_weekend_min": default_template["daily_limit_weekend_min"],
        "schedule_matrix_7x48": default_template["schedule_matrix_7x48"],
        "category_budgets_json": category_budgets_json,
        "app_rules_json": app_rules_json,
        "domain_rules_json": domain_rules_json,
        "updated_at_utc": now_utc,
    }

    sig = sign_policy_payload(policy_dict_to_sign)

    policy = Policy(
        child_id=child_id,
        version=1,
        daily_limit_weekday_min=default_template["daily_limit_weekday_min"],
        daily_limit_weekend_min=default_template["daily_limit_weekend_min"],
        schedule_matrix_7x48=default_template["schedule_matrix_7x48"],
        category_budgets_json=category_budgets_json,
        app_rules_json=app_rules_json,
        domain_rules_json=domain_rules_json,
        updated_at_utc=now_utc,
        signature=sig,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def update_policy_for_child(
    child_id: str,
    update_data: dict,
    actor_id: str,
    actor_role: str,
    ip_address: str,
    db: Session,
) -> Policy:
    """Updates child policy, increments version, signs new payload, and records audit trail."""
    policy = db.query(Policy).filter(Policy.child_id == child_id).first()
    if not policy:
        policy = create_default_policy_for_child(child_id, db)

    # Snapshot old state for AuditLog
    old_value_dict = {
        "version": policy.version,
        "daily_limit_weekday_min": policy.daily_limit_weekday_min,
        "daily_limit_weekend_min": policy.daily_limit_weekend_min,
        "schedule_matrix_7x48": policy.schedule_matrix_7x48,
        "category_budgets_json": policy.category_budgets_json,
        "app_rules_json": policy.app_rules_json,
        "domain_rules_json": policy.domain_rules_json,
    }

    # Apply updates
    if "daily_limit_weekday_min" in update_data and update_data["daily_limit_weekday_min"] is not None:
        policy.daily_limit_weekday_min = update_data["daily_limit_weekday_min"]
    if "daily_limit_weekend_min" in update_data and update_data["daily_limit_weekend_min"] is not None:
        policy.daily_limit_weekend_min = update_data["daily_limit_weekend_min"]
    if "schedule_matrix_7x48" in update_data and update_data["schedule_matrix_7x48"] is not None:
        policy.schedule_matrix_7x48 = update_data["schedule_matrix_7x48"]
    if "category_budgets" in update_data and update_data["category_budgets"] is not None:
        policy.category_budgets_json = json.dumps(update_data["category_budgets"])
    if "app_rules" in update_data and update_data["app_rules"] is not None:
        policy.app_rules_json = json.dumps([r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in update_data["app_rules"]])
    if "domain_rules" in update_data and update_data["domain_rules"] is not None:
        policy.domain_rules_json = json.dumps([r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in update_data["domain_rules"]])
    if update_data.get("offline_pin"):
        # Only the Argon2id hash is stored; the PIN never enters the audit log
        policy.offline_pin_hash = get_password_hash(update_data["offline_pin"])

    # Increment version and update timestamp
    policy.version += 1
    policy.updated_at_utc = datetime.now(timezone.utc).isoformat()

    # Re-sign
    new_payload = policy_signed_dict(policy)
    policy.signature = sign_policy_payload(new_payload)

    # Record AuditLog
    audit_entry = AuditLog(
        actor_id=actor_id,
        actor_role=actor_role,
        child_id=child_id,
        ip_address=ip_address,
        action="UPDATE_POLICY",
        old_value_json=json.dumps(old_value_dict),
        new_value_json=json.dumps(new_payload),
    )
    db.add(audit_entry)

    db.commit()
    db.refresh(policy)
    return policy
