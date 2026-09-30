"""Route access declarations (BR-AUTH-02).

Every route declares exactly one of:

* ``Depends(require(Permission.X))`` - authenticated and holding permission X;
* ``Depends(require_authenticated)`` - any authenticated user (e.g. ``/auth/me``);
* ``Depends(allow_public)`` - no authentication (login, health).

Each dependency carries an ``AccessRule`` in ``__access_rule__`` so a test can walk the
router and fail on any route that declares none, or more than one.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from app.api.deps import get_current_user
from app.core.permissions import Permission, has_permission
from app.domain.errors import PermissionDeniedError
from app.services.auth_service import AuthenticatedUser

ACCESS_RULE_ATTRIBUTE = "__access_rule__"


@dataclass(frozen=True)
class AccessRule:
    public: bool = False
    permission: Permission | None = None


def _tag(dependency: Callable[..., Any], rule: AccessRule) -> None:
    setattr(dependency, ACCESS_RULE_ATTRIBUTE, rule)


def allow_public() -> None:
    """Explicit marker for endpoints that need no authentication."""


_tag(allow_public, AccessRule(public=True))


def require_authenticated(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    return user


_tag(require_authenticated, AccessRule())

_permission_dependencies: dict[Permission, Callable[..., AuthenticatedUser]] = {}


def require(permission: Permission) -> Callable[..., AuthenticatedUser]:
    """Dependency that authenticates the caller and checks one permission on the server."""
    if permission in _permission_dependencies:
        return _permission_dependencies[permission]

    def dependency(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if not has_permission(user.role, permission):
            raise PermissionDeniedError(
                "FORBIDDEN", "You do not have permission to perform this action."
            )
        return user

    dependency.__name__ = f"require_{permission.value.replace(':', '_')}"
    _tag(dependency, AccessRule(permission=permission))
    _permission_dependencies[permission] = dependency
    return dependency
