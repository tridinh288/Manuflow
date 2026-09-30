from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.permissions import Role
from app.domain.users import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, USERNAME_PATTERN

_NOT_NULLABLE = ("full_name", "role", "active", "password")


class UserCreateRequest(BaseModel):
    # BR-AUTH-01: fields such as created_by or id are rejected, not trusted.
    model_config = ConfigDict(extra="forbid")

    username: str = Field(pattern=USERNAME_PATTERN.pattern)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: str = Field(min_length=1, max_length=100)
    role: Role
    work_center_id: int | None = Field(default=None, gt=0)


class UserUpdateRequest(BaseModel):
    """PATCH: only the fields present in the body are changed."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = None
    work_center_id: int | None = Field(default=None, gt=0)
    active: bool | None = None
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH
    )

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> Self:
        # Only work_center_id may be cleared with null (e.g. WORKER -> WAREHOUSE).
        nulls = [name for name in _NOT_NULLABLE if name in self.model_fields_set]
        nulls = [name for name in nulls if getattr(self, name) is None]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: Role
    work_center_id: int | None
    active: bool
    locked_until: datetime | None
