"""Policy Pydantic Schemas."""
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RuleAction(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


class AppCategory(str, Enum):
    EDUCATION = "education"
    ENTERTAINMENT = "entertainment"
    SOCIAL = "social"
    GAMING = "gaming"
    INAPPROPRIATE = "inappropriate"
    UNCLASSIFIED = "unclassified"


class AppRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exe_name: str = Field(min_length=1, max_length=100)
    sha256: str | None = Field(default=None, max_length=64)
    original_filename: str | None = Field(default=None, max_length=100)
    category: AppCategory = AppCategory.UNCLASSIFIED
    action: RuleAction = RuleAction.ALLOW


class DomainRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=255)
    category: AppCategory = AppCategory.UNCLASSIFIED
    action: RuleAction = RuleAction.ALLOW


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: str
    daily_limit_weekday_min: int = Field(default=90, ge=0, le=1440)
    daily_limit_weekend_min: int = Field(default=120, ge=0, le=1440)
    schedule_matrix_7x48: str = Field(
        default="1" * 336,
        description="String of 336 characters ('0' or '1') representing 7 days x 48 half-hour slots"
    )
    category_budgets: dict[str, int] = Field(default_factory=dict)
    app_rules: list[AppRule] = Field(default_factory=list)
    domain_rules: list[DomainRule] = Field(default_factory=list)
    offline_pin: str | None = Field(default=None, min_length=4, max_length=32)

    @field_validator("schedule_matrix_7x48")
    @classmethod
    def validate_matrix(cls, v: str) -> str:
        if len(v) != 336:
            raise ValueError(f"Schedule matrix must be exactly 336 characters (7x48), got {len(v)}.")
        if not set(v).issubset({"0", "1"}):
            raise ValueError("Schedule matrix can only contain '0' (locked) and '1' (allowed).")
        return v


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_limit_weekday_min: int | None = Field(default=None, ge=0, le=1440)
    daily_limit_weekend_min: int | None = Field(default=None, ge=0, le=1440)
    schedule_matrix_7x48: str | None = None
    category_budgets: dict[str, int] | None = None
    app_rules: list[AppRule] | None = None
    domain_rules: list[DomainRule] | None = None
    offline_pin: str | None = Field(default=None, min_length=4, max_length=32)

    @field_validator("schedule_matrix_7x48")
    @classmethod
    def validate_matrix(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) != 336:
            raise ValueError(f"Schedule matrix must be exactly 336 characters (7x48), got {len(v)}.")
        if not set(v).issubset({"0", "1"}):
            raise ValueError("Schedule matrix can only contain '0' (locked) and '1' (allowed).")
        return v


class PolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    child_id: str
    version: int
    daily_limit_weekday_min: int
    daily_limit_weekend_min: int
    schedule_matrix_7x48: str
    category_budgets_json: str
    app_rules_json: str
    domain_rules_json: str
    updated_at_utc: str
    signature: str
    # Unsigned metadata: Argon2id hash used by the agent for offline parent-PIN checks
    offline_pin_hash: str | None = None


class PolicySignatureVerify(BaseModel):
    version: int
    payload_hash: str
    signature: str
    is_valid: bool
