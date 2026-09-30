"""Who is acting and from which request; built by the API layer, passed to services."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class Actor:
    user_id: int | None
    username: str | None
