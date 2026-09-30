"""B4 / D-17: the permission matrix in code matches the specification table exactly."""

import pytest

from app.core.permissions import ROLE_PERMISSIONS, Permission, Role, has_permission

ADMIN, PM, WH, WORKER = (
    Role.ADMIN,
    Role.PRODUCTION_MANAGER,
    Role.WAREHOUSE,
    Role.WORKER,
)

# Transcribed from the "Ma trận quyền" table in docs/requirements.md (B4).
SPEC_MATRIX: dict[str, set[Role]] = {
    "users:manage": {ADMIN},
    "master:read": {ADMIN, PM, WH, WORKER},
    "master:write": {ADMIN, PM},
    "bom:write": {PM},
    "routing:write": {PM},
    "inventory:read": {ADMIN, PM, WH},
    "inventory:receive": {WH},
    "inventory:adjust": {WH},
    "inventory:issue": {WH},
    "inventory:return": {WH},
    "order:read": {ADMIN, PM, WH, WORKER},
    "order:create": {PM},
    "order:plan": {PM},
    "order:start": {PM},
    "order:cancel": {PM},
    "order:check_materials": {PM, WH},
    "operation:report": {PM, WORKER},
    "operation:correct": {PM},
    "dashboard:read": {ADMIN, PM, WH},
    "audit:read": {ADMIN},
}


def test_d17_every_permission_is_in_the_spec_matrix() -> None:
    assert {p.value for p in Permission} == set(SPEC_MATRIX)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("permission", sorted(SPEC_MATRIX))
def test_b4_role_permission_matches_spec(role: Role, permission: str) -> None:
    expected = role in SPEC_MATRIX[permission]
    assert has_permission(role, Permission(permission)) is expected


def test_b4_admin_cannot_move_stock_or_report_production() -> None:
    forbidden = {
        Permission.INVENTORY_RECEIVE,
        Permission.INVENTORY_ADJUST,
        Permission.INVENTORY_ISSUE,
        Permission.INVENTORY_RETURN,
        Permission.OPERATION_REPORT,
        Permission.OPERATION_CORRECT,
    }
    assert not forbidden & ROLE_PERMISSIONS[Role.ADMIN]
