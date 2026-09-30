from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.permissions import Role


class LoginRequest(BaseModel):
    # BR-AUTH-01: unknown fields (e.g. "role", "user_id") are rejected, never trusted.
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    # Upper bound keeps a single request from forcing a huge Argon2 input.
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (OAuth2 token type, not a secret)
    expires_in: int


class MeResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: Role
    work_center_id: int | None
    permissions: list[str]
