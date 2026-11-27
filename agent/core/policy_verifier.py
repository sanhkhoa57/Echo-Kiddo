"""Policy Verifier for OGK-Agent (FR-F4-03, Section 4.3).
Verifies HMAC-SHA256 signature on local/downloaded policy payload against the policy secret.
Rejects any tampered policy to protect against local tampering.

Wire format (server): the 9 fields in SIGNED_POLICY_KEYS are signed; `id` and other
metadata are not. Legacy payloads (unit tests, old caches) that do not carry the full
server field set are signed over every field except `signature`.
"""
import hmac
import hashlib
import json
import logging
import os
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger("OGK.PolicyVerifier")

# Must stay identical to server/services/policy_service.py
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

# Lab default, identical to server/auth/security.py. Production must set OGK_JWT_SECRET /
# OGK_POLICY_SECRET, or rely on the policy_hmac_secret issued at enrollment.
_LAB_JWT_SECRET = "ogk-insecure-dev-jwt-secret-replace-in-prod-32bytes!"
_POLICY_KEY_LABEL = b"ogk-policy-signing-v1"


class PolicyVerificationError(Exception):
    """Raised when policy verification fails."""
    pass


def derive_policy_secret(jwt_secret: str) -> str:
    """Derives the policy-signing key from the server JWT secret (same formula as server)."""
    return hmac.new(jwt_secret.encode("utf-8"), _POLICY_KEY_LABEL, hashlib.sha256).hexdigest()


def default_policy_secret() -> str:
    """Policy secret used when enrollment did not issue one (lab / env configured)."""
    explicit = os.getenv("OGK_POLICY_SECRET")
    if explicit:
        return explicit
    return derive_policy_secret(os.getenv("OGK_JWT_SECRET") or _LAB_JWT_SECRET)


def is_server_format(payload: Dict[str, Any]) -> bool:
    """True when the payload carries the complete server field set."""
    return all(k in payload for k in SIGNED_POLICY_KEYS)


def canonical_policy_bytes(payload: Dict[str, Any]) -> bytes:
    """Creates deterministic UTF-8 byte representation identical to server implementation."""
    if is_server_format(payload):
        data = {k: payload[k] for k in SIGNED_POLICY_KEYS}
    else:
        data = {k: v for k, v in payload.items() if k != "signature"}
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return canonical_json.encode("utf-8")


def calculate_policy_signature(payload: Dict[str, Any], secret: str) -> str:
    """Calculates HMAC-SHA256 digest on canonical representation."""
    data_bytes = canonical_policy_bytes(payload)
    return hmac.new(secret.encode("utf-8"), data_bytes, hashlib.sha256).hexdigest()


def policy_field(policy: Dict[str, Any], *names: str, default: Any = None) -> Any:
    """Returns the first present field among `names` (canonical name first, then aliases)."""
    for name in names:
        if name in policy and policy[name] is not None:
            return policy[name]
    return default


def _decode_json_field(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default if value is None else value


def decode_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a runtime copy of a verified policy with decoded helper keys
    (`app_rules`, `domain_rules`, `category_budgets`, `category_quotas`, `schedule_matrix`,
    `daily_limit_minutes_weekday`, `daily_limit_minutes_weekend`).

    For server-format payloads every helper key is derived from a signed field and any
    unsigned extra field is dropped, so nothing unsigned can influence enforcement.
    """
    if is_server_format(payload):
        out: Dict[str, Any] = {k: payload[k] for k in SIGNED_POLICY_KEYS}
        for meta in ("id", "signature"):
            if meta in payload:
                out[meta] = payload[meta]
    else:
        out = dict(payload)

    budgets = _decode_json_field(
        policy_field(out, "category_budgets_json", "category_budgets", "category_quotas"), {}
    )
    if not isinstance(budgets, dict):
        budgets = {}
    app_rules = _decode_json_field(policy_field(out, "app_rules_json", "app_rules"), [])
    domain_rules = _decode_json_field(policy_field(out, "domain_rules_json", "domain_rules"), [])

    out["category_budgets"] = budgets
    out["category_quotas"] = budgets
    out["app_rules"] = app_rules if isinstance(app_rules, list) else []
    out["domain_rules"] = domain_rules if isinstance(domain_rules, list) else []

    matrix = policy_field(out, "schedule_matrix_7x48", "schedule_matrix")
    if matrix is not None:
        out["schedule_matrix"] = matrix
    weekday = policy_field(out, "daily_limit_weekday_min", "daily_limit_minutes_weekday")
    if weekday is not None:
        out["daily_limit_minutes_weekday"] = weekday
    weekend = policy_field(out, "daily_limit_weekend_min", "daily_limit_minutes_weekend")
    if weekend is not None:
        out["daily_limit_minutes_weekend"] = weekend
    return out


def verify_policy(payload: Dict[str, Any], secret: str) -> Tuple[bool, str]:
    """
    Verifies policy integrity and format.
    Returns (True, "OK") or (False, reason).
    """
    if not isinstance(payload, dict):
        return False, "Policy payload must be a JSON object"

    signature = payload.get("signature")
    if not signature or not isinstance(signature, str):
        return False, "Missing signature in policy payload"

    # Verify HMAC-SHA256 in constant time
    expected_sig = calculate_policy_signature(payload, secret)
    if not hmac.compare_digest(expected_sig, signature):
        logger.warning("Policy signature mismatch for policy version %s", payload.get("version"))
        return False, "Policy signature mismatch (tampering detected)"

    # Basic structural validations (canonical server names first, then legacy aliases)
    matrix = policy_field(payload, "schedule_matrix_7x48", "schedule_matrix")
    if matrix is not None:
        if not isinstance(matrix, str) or len(matrix) != 336 or any(c not in "01" for c in matrix):
            return False, "Invalid schedule_matrix format (must be 336 binary characters)"

    weekday_limit = policy_field(payload, "daily_limit_weekday_min", "daily_limit_minutes_weekday")
    if weekday_limit is not None and (not isinstance(weekday_limit, int) or weekday_limit < 0):
        return False, "daily_limit_minutes_weekday must be non-negative integer"

    weekend_limit = policy_field(payload, "daily_limit_weekend_min", "daily_limit_minutes_weekend")
    if weekend_limit is not None and (not isinstance(weekend_limit, int) or weekend_limit < 0):
        return False, "daily_limit_minutes_weekend must be non-negative integer"

    return True, "OK"
