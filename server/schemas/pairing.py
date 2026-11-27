"""Pairing Code Pydantic Schemas."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PairingCodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: str
    consent_confirmed: bool = Field(description="Must explicitly consent per Decree 13/2023")

    @field_validator("consent_confirmed")
    @classmethod
    def validate_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Parental consent confirmation (Decree 13/2023) is required to generate a pairing code.")
        return v


class PairingCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    child_id: str
    expires_at_utc: str
