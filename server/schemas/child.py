"""Child Pydantic Schemas."""
from pydantic import BaseModel, ConfigDict, Field


class ChildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=100)
    birth_year: int | None = Field(default=None, ge=2000, le=2030)
    age_group: str = Field(default="6-11", max_length=20)
    avatar_code: str = Field(default="kid_default", max_length=50)


class ChildUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    birth_year: int | None = Field(default=None, ge=2000, le=2030)
    age_group: str | None = Field(default=None, max_length=20)
    avatar_code: str | None = Field(default=None, max_length=50)


class ChildResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: str
    display_name: str
    birth_year: int | None
    age_group: str
    avatar_code: str | None
    created_at_utc: str
