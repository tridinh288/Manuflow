"""Fixed roles and the permission matrix of B4 (D-17): the only place it is defined."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    PRODUCTION_MANAGER = "PRODUCTION_MANAGER"
    WAREHOUSE = "WAREHOUSE"
    WORKER = "WORKER"


class Permission(StrEnum):
    USERS_MANAGE = "users:manage"
    MASTER_READ = "master:read"
    MASTER_WRITE = "master:write"
    BOM_WRITE = "bom:write"
    ROUTING_WRITE = "routing:write"
    INVENTORY_READ = "inventory:read"
    INVENTORY_RECEIVE = "inventory:receive"
    INVENTORY_ADJUST = "inventory:adjust"
    INVENTORY_ISSUE = "inventory:issue"
    INVENTORY_RETURN = "inventory:return"
    ORDER_READ = "order:read"
    ORDER_CREATE = "order:create"
    ORDER_PLAN = "order:plan"
    ORDER_START = "order:start"
    ORDER_CANCEL = "order:cancel"
    ORDER_CHECK_MATERIALS = "order:check_materials"
    OPERATION_REPORT = "operation:report"
    OPERATION_CORRECT = "operation:correct"
    DASHBOARD_READ = "dashboard:read"
    AUDIT_READ = "audit:read"


P = Permission

# ADMIN deliberately cannot move stock or report production (segregation of duties, B4).
# WORKER's order:read and operation:report are further limited to their own work
# center by the services (D-18, BR-AUTH-03).
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(
        {
            P.USERS_MANAGE,
            P.MASTER_READ,
            P.MASTER_WRITE,
            P.INVENTORY_READ,
            P.ORDER_READ,
            P.DASHBOARD_READ,
            P.AUDIT_READ,
        }
    ),
    Role.PRODUCTION_MANAGER: frozenset(
        {
            P.MASTER_READ,
            P.MASTER_WRITE,
            P.BOM_WRITE,
            P.ROUTING_WRITE,
            P.INVENTORY_READ,
            P.ORDER_READ,
            P.ORDER_CREATE,
            P.ORDER_PLAN,
            P.ORDER_START,
            P.ORDER_CANCEL,
            P.ORDER_CHECK_MATERIALS,
            P.OPERATION_REPORT,
            P.OPERATION_CORRECT,
            P.DASHBOARD_READ,
        }
    ),
    Role.WAREHOUSE: frozenset(
        {
            P.MASTER_READ,
            P.INVENTORY_READ,
            P.INVENTORY_RECEIVE,
            P.INVENTORY_ADJUST,
            P.INVENTORY_ISSUE,
            P.INVENTORY_RETURN,
            P.ORDER_READ,
            P.ORDER_CHECK_MATERIALS,
            P.DASHBOARD_READ,
        }
    ),
    Role.WORKER: frozenset({P.MASTER_READ, P.ORDER_READ, P.OPERATION_REPORT}),
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
