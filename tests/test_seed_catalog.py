"""Tests for domain_catalog.json: 6 categories, >= 200 entries, no real adult domains, default 6-11 policy."""
import json
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parent.parent / "server" / "seeds" / "domain_catalog.json"

EXPECTED_CATEGORIES = {
    "education",
    "entertainment",
    "social",
    "gaming",
    "inappropriate",
    "unclassified",
}


def test_seed_catalog_structure():
    """Verify seed catalog exists, is valid JSON, and contains expected keys."""
    assert SEED_PATH.exists(), f"Seed file not found at {SEED_PATH}"

    with open(SEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "categories" in data
    assert "default_policy_6_11" in data
    assert set(data["categories"].keys()) == EXPECTED_CATEGORIES


def test_seed_catalog_entry_count():
    """Verify total classified domain count is >= 200 entries."""
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_count = sum(len(domains) for domains in data["categories"].values())
    assert total_count >= 200, f"Expected >= 200 entries, found {total_count}"

    for cat in EXPECTED_CATEGORIES:
        assert len(data["categories"][cat]) > 0, f"Category {cat} is empty"


def test_seed_catalog_safety_constraint():
    """STRICT TEST: Verify NO real adult/porn domains are present.
    
    All inappropriate test domains must strictly use simulated domains ending
    in .test or .example per project safety guardrails and Teacher F2 rule.
    """
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    inappropriate_domains = data["categories"]["inappropriate"]
    assert len(inappropriate_domains) >= 30

    for domain in inappropriate_domains:
        # Must be simulated safe domain ending with .test or .example
        assert domain.endswith(".test") or domain.endswith(".example"), (
            f"Violated safety constraint: inappropriate domain '{domain}' must end with .test or .example"
        )


def test_default_policy_6_11():
    """Verify default policy template for kids aged 6-11."""
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    policy = data["default_policy_6_11"]
    assert policy["daily_limit_weekday_min"] == 90
    assert policy["daily_limit_weekend_min"] == 120
    assert len(policy["schedule_matrix_7x48"]) == 336
    assert set(policy["schedule_matrix_7x48"]).issubset({"0", "1"})

    rules = policy["category_rules"]
    assert rules["education"] == "allow"
    assert rules["gaming"] == "limit"
    assert rules["social"] == "block"
    assert rules["inappropriate"] == "block"
    assert policy["safesearch_enforced"] is True
    assert policy["doh_canary_blocked"] is True
