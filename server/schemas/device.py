"""Device and Heartbeat Pydantic Schemas."""
from pydantic import BaseModel, ConfigDict, Field


class DeviceEnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairing_code: str = Field(min_length=8, max_length=8, pattern=r"^[A-Z0-9]{8}$")
    device_name: str = Field(min_length=1, max_length=100)
    device_fingerprint: str = Field(min_length=10, max_length=64)
    windows_user_sid: str | None = Field(default=None, max_length=128)


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    child_id: str
    device_name: str
    applied_policy_version: int
    last_heartbeat_utc: str | None
    created_at_utc: str


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used_sec: int = Field(ge=0)
    local_utc: str
    monotonic_sec: float = Field(ge=0.0)
    policy_version: int = Field(ge=0)


class HeartbeatResponse(BaseModel):
    server_utc: str
    latest_policy_version: int
    pending_commands: list[dict] = Field(default_factory=list)
    clock_drift_sec: int = 0
