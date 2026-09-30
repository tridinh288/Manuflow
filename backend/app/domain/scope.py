"""Data scope of a WORKER (D-18, BR-AUTH-03).

A worker only sees operations, and the orders that contain them, at their own work
center. Anything outside that scope is reported as *not found* (404, not 403) so IDs
cannot be probed.
"""

from app.core.permissions import Role
from app.domain.errors import NotFoundError


def work_center_scope(role: Role, work_center_id: int | None) -> int | None:
    """The only work center the caller may see, or ``None`` for no restriction."""
    if role is not Role.WORKER:
        return None
    if work_center_id is None:  # guarded by a DB CHECK; fail closed regardless
        raise NotFoundError("NOT_FOUND", "Resource not found.")
    return work_center_id


def ensure_in_scope(
    role: Role,
    user_work_center_id: int | None,
    resource_work_center_id: int,
    *,
    code: str,
    message: str,
) -> None:
    scope = work_center_scope(role, user_work_center_id)
    if scope is not None and scope != resource_work_center_id:
        raise NotFoundError(code, message)
