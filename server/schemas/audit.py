"""Audit Log Pydantic Schemas."""
from pydantic import BaseModel, ConfigDict, Field


class AuditLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1, max_length=36)
    actor_role: str = Field(min_length=1, max_length=20)
    child_id: str | None = Field(default=None, max_length=36)
    ip_address: str = Field(min_length=1, max_length=45)
    action: str = Field(min_length=1, max_length=100)
    old_value_json: str | None = None
    new_value_json: str | None = None


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ts_utc: str
    actor_id: str
    actor_role: str
    child_id: str | None
    ip_address: str
    action: str
    old_value_json: str | None
    new_value_json: str | None
