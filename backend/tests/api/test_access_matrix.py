"""B4 / B13 access control: test 21 (router scan) and test 19 (role x endpoint).

``ENDPOINT_ACCESS`` transcribes the endpoint table of B13. Every route in the app must
appear here with the access rule it declares in code, so adding a route without a
permission (or with the wrong one) fails the build.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from app.api.access import ACCESS_RULE_ATTRIBUTE, AccessRule, require
from app.core.permissions import Permission, Role, has_permission

PUBLIC = AccessRule(public=True)
AUTHENTICATED = AccessRule()


def perm(permission: Permission) -> AccessRule:
    return AccessRule(permission=permission)


ENDPOINT_ACCESS: dict[tuple[str, str], AccessRule] = {
    ("GET", "/health"): PUBLIC,
    ("POST", "/api/v1/auth/login"): PUBLIC,
    ("GET", "/api/v1/auth/me"): AUTHENTICATED,
    ("GET", "/api/v1/users"): perm(Permission.USERS_MANAGE),
    ("POST", "/api/v1/users"): perm(Permission.USERS_MANAGE),
    ("PATCH", "/api/v1/users/{user_id}"): perm(Permission.USERS_MANAGE),
    ("GET", "/api/v1/products"): perm(Permission.MASTER_READ),
    ("GET", "/api/v1/products/{product_id}"): perm(Permission.MASTER_READ),
    ("POST", "/api/v1/products"): perm(Permission.MASTER_WRITE),
    ("PUT", "/api/v1/products/{product_id}"): perm(Permission.MASTER_WRITE),
    ("DELETE", "/api/v1/products/{product_id}"): perm(Permission.MASTER_WRITE),
    ("GET", "/api/v1/materials"): perm(Permission.MASTER_READ),
    ("GET", "/api/v1/materials/{material_id}"): perm(Permission.MASTER_READ),
    ("POST", "/api/v1/materials"): perm(Permission.MASTER_WRITE),
    ("PUT", "/api/v1/materials/{material_id}"): perm(Permission.MASTER_WRITE),
    ("DELETE", "/api/v1/materials/{material_id}"): perm(Permission.MASTER_WRITE),
    ("GET", "/api/v1/work-centers"): perm(Permission.MASTER_READ),
    ("GET", "/api/v1/work-centers/{work_center_id}"): perm(Permission.MASTER_READ),
    ("POST", "/api/v1/work-centers"): perm(Permission.MASTER_WRITE),
    ("PUT", "/api/v1/work-centers/{work_center_id}"): perm(Permission.MASTER_WRITE),
    ("DELETE", "/api/v1/work-centers/{work_center_id}"): perm(Permission.MASTER_WRITE),
    ("GET", "/api/v1/products/{product_id}/boms"): perm(Permission.MASTER_READ),
    ("POST", "/api/v1/products/{product_id}/boms"): perm(Permission.BOM_WRITE),
    ("PUT", "/api/v1/boms/{bom_id}/items"): perm(Permission.BOM_WRITE),
    ("POST", "/api/v1/boms/{bom_id}/activate"): perm(Permission.BOM_WRITE),
    ("POST", "/api/v1/products/{product_id}/bom/explode"): perm(Permission.MASTER_READ),
    ("GET", "/api/v1/products/{product_id}/routings"): perm(Permission.MASTER_READ),
    ("POST", "/api/v1/products/{product_id}/routings"): perm(Permission.ROUTING_WRITE),
    ("PUT", "/api/v1/routings/{routing_id}/steps"): perm(Permission.ROUTING_WRITE),
    ("POST", "/api/v1/routings/{routing_id}/activate"): perm(Permission.ROUTING_WRITE),
    ("POST", "/api/v1/inventory/receipts"): perm(Permission.INVENTORY_RECEIVE),
    ("POST", "/api/v1/inventory/adjustments"): perm(Permission.INVENTORY_ADJUST),
    ("GET", "/api/v1/inventory"): perm(Permission.INVENTORY_READ),
    ("GET", "/api/v1/inventory/transactions"): perm(Permission.INVENTORY_READ),
    ("GET", "/api/v1/admin/inventory-reconciliation"): perm(Permission.AUDIT_READ),
    ("GET", "/api/v1/production-orders"): perm(Permission.ORDER_READ),
    ("GET", "/api/v1/production-orders/{order_id}"): perm(Permission.ORDER_READ),
    ("GET", "/api/v1/production-orders/{order_id}/materials"): perm(Permission.ORDER_READ),
    ("GET", "/api/v1/production-orders/{order_id}/operations"): perm(Permission.ORDER_READ),
    ("POST", "/api/v1/production-orders"): perm(Permission.ORDER_CREATE),
    ("PATCH", "/api/v1/production-orders/{order_id}"): perm(Permission.ORDER_CREATE),
    ("POST", "/api/v1/production-orders/{order_id}/plan"): perm(Permission.ORDER_PLAN),
    ("POST", "/api/v1/production-orders/{order_id}/check-materials"): perm(
        Permission.ORDER_CHECK_MATERIALS
    ),
    ("POST", "/api/v1/production-orders/{order_id}/start"): perm(Permission.ORDER_START),
    ("POST", "/api/v1/production-orders/{order_id}/cancel"): perm(Permission.ORDER_CANCEL),
    ("POST", "/api/v1/production-operations/{operation_id}/progress"): perm(
        Permission.OPERATION_REPORT
    ),
    ("POST", "/api/v1/inventory/issues"): perm(Permission.INVENTORY_ISSUE),
    ("POST", "/api/v1/inventory/returns"): perm(Permission.INVENTORY_RETURN),
}


def declared_rules(dependant: Dependant) -> list[AccessRule]:
    rules: list[AccessRule] = []
    for dependency in dependant.dependencies:
        rule = getattr(dependency.call, ACCESS_RULE_ATTRIBUTE, None)
        if rule is not None:
            rules.append(rule)
        else:
            rules.extend(declared_rules(dependency))
    return rules


def route_access(app: FastAPI) -> dict[tuple[str, str], list[AccessRule]]:
    # iter_route_contexts: FastAPI >= 0.14x keeps included routers nested, so app.routes
    # alone no longer lists API routes. The context carries the full path and the
    # effective dependant, including router-level dependencies.
    return {
        (method, context.path): declared_rules(context.dependant)
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute)
        for method in context.methods or ()
    }


# --- Test 21: every route declares exactly one access rule (BR-AUTH-02) ---------------


def test_br_auth_02_every_route_declares_exactly_one_access_rule(app: FastAPI) -> None:
    access = route_access(app)
    assert len(access) >= len(ENDPOINT_ACCESS), "the scan must see every API route"
    offenders = {key: rules for key, rules in access.items() if len(rules) != 1}
    assert offenders == {}


def test_br_auth_02_declared_rules_match_the_spec_endpoint_table(app: FastAPI) -> None:
    actual = {key: rules[0] for key, rules in route_access(app).items()}
    assert actual == ENDPOINT_ACCESS


def test_br_auth_02_scan_catches_undeclared_and_doubly_declared_routes(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/unguarded")
    def unguarded() -> None: ...

    @router.get("/double", dependencies=[Depends(require(Permission.AUDIT_READ))])
    def double(_: Annotated[Any, Depends(require(Permission.MASTER_READ))]) -> None: ...

    app.include_router(router)
    access = route_access(app)
    assert access[("GET", "/unguarded")] == []
    assert len(access[("GET", "/double")]) == 2


# --- Test 19: each role x each endpoint gets 2xx or 403 (B4) --------------------------


@dataclass(frozen=True)
class Call:
    method: str
    path: str
    json: Callable[[int], dict[str, Any]] | None = None
    idempotency_key: bool = False  # D-22: the endpoint requires Idempotency-Key
    # Path placeholder -> targets key, when the default target is in the wrong state.
    params: tuple[tuple[str, str], ...] = ()
    # BR-AUTH-03: a WORKER passes the permission check but may only see their own work
    # center's data, so 404 is as valid as 2xx for them; 403 never is.
    worker_scoped: bool = False


PROTECTED_CALLS: list[Call] = [
    Call("GET", "/api/v1/auth/me"),
    Call("GET", "/api/v1/users"),
    Call(
        "POST",
        "/api/v1/users",
        json=lambda n: {
            "username": f"created{n}",
            "password": "a-long-enough-pass",
            "full_name": "Created",
            "role": "WAREHOUSE",
        },
    ),
    Call("PATCH", "/api/v1/users/{user_id}", json=lambda n: {"full_name": f"Renamed {n}"}),
    Call("GET", "/api/v1/products"),
    Call("GET", "/api/v1/products/{product_id}"),
    Call("POST", "/api/v1/products", json=lambda n: {"product_code": f"NEW-P{n}", "name": "P"}),
    Call("PUT", "/api/v1/products/{product_id}", json=lambda n: {"name": f"Renamed {n}"}),
    Call("DELETE", "/api/v1/products/{product_id}"),
    Call("GET", "/api/v1/materials"),
    Call("GET", "/api/v1/materials/{material_id}"),
    Call(
        "POST",
        "/api/v1/materials",
        json=lambda n: {
            "material_code": f"NEW-M{n}",
            "name": "M",
            "unit": "kg",
            "decimal_places": 3,
        },
    ),
    Call(
        "PUT",
        "/api/v1/materials/{material_id}",
        json=lambda n: {"name": f"Renamed {n}", "minimum_stock": "1.5"},
    ),
    Call("DELETE", "/api/v1/materials/{material_id}"),
    Call("GET", "/api/v1/work-centers"),
    Call("GET", "/api/v1/work-centers/{work_center_id}"),
    Call("POST", "/api/v1/work-centers", json=lambda n: {"code": f"NEW-W{n}", "name": "W"}),
    Call("PUT", "/api/v1/work-centers/{work_center_id}", json=lambda n: {"name": f"W {n}"}),
    Call("DELETE", "/api/v1/work-centers/{work_center_id}"),
    Call("GET", "/api/v1/products/{product_id}/boms"),
    Call("POST", "/api/v1/products/{product_id}/boms"),
    Call(
        "PUT",
        "/api/v1/boms/{bom_id}/items",
        json=lambda n: {"items": [{"material_id": 0, "qty_per_unit": f"{n}"}]},
    ),
    Call("POST", "/api/v1/boms/{bom_id}/activate"),
    Call(
        "POST",
        "/api/v1/products/{product_id}/bom/explode",
        json=lambda n: {"quantity": n, "bom_header_id": 0},
    ),
    Call("GET", "/api/v1/products/{product_id}/routings"),
    Call("POST", "/api/v1/products/{product_id}/routings"),
    Call(
        "PUT",
        "/api/v1/routings/{routing_id}/steps",
        json=lambda n: {
            "steps": [{"sequence": 10 * n, "operation_type": "QC", "work_center_id": 0}]
        },
    ),
    Call("POST", "/api/v1/routings/{routing_id}/activate"),
    Call(
        "POST",
        "/api/v1/inventory/receipts",
        json=lambda n: {"material_id": 0, "quantity": f"{n}"},
        idempotency_key=True,
    ),
    Call(
        "POST",
        "/api/v1/inventory/adjustments",
        json=lambda n: {"material_id": 0, "quantity_delta": f"{n}", "reason": "Recount"},
        idempotency_key=True,
    ),
    Call("GET", "/api/v1/inventory"),
    Call("GET", "/api/v1/inventory/transactions"),
    Call("GET", "/api/v1/admin/inventory-reconciliation"),
    Call("GET", "/api/v1/production-orders"),
    Call("GET", "/api/v1/production-orders/{order_id}", worker_scoped=True),
    Call("GET", "/api/v1/production-orders/{order_id}/materials", worker_scoped=True),
    Call("GET", "/api/v1/production-orders/{order_id}/operations", worker_scoped=True),
    Call(
        "POST",
        "/api/v1/production-orders",
        json=lambda n: {
            "product_id": 0,
            "planned_quantity": 10 * n,
            "due_date": "2030-01-01T00:00:00Z",
        },
    ),
    Call("PATCH", "/api/v1/production-orders/{order_id}", json=lambda n: {"notes": f"n{n}"}),
    Call("POST", "/api/v1/production-orders/{order_id}/plan", idempotency_key=True),
    Call(
        "POST",
        "/api/v1/production-orders/{order_id}/check-materials",
        idempotency_key=True,
        params=(("order_id", "shortage_order_id"),),
    ),
    Call(
        "POST",
        "/api/v1/production-orders/{order_id}/start",
        params=(("order_id", "startable_order_id"),),
    ),
    Call(
        "POST",
        "/api/v1/production-orders/{order_id}/cancel",
        json=lambda n: {"reason": f"Matrix {n}"},
        idempotency_key=True,
    ),
    Call(
        "POST",
        "/api/v1/production-operations/{operation_id}/progress",
        json=lambda n: {"good_delta": n},
        idempotency_key=True,
        worker_scoped=True,
    ),
    Call(
        "POST",
        "/api/v1/inventory/issues",
        json=lambda n: {"order_material_id": -1, "quantity": "1"},
        idempotency_key=True,
    ),
    Call(
        "POST",
        "/api/v1/inventory/returns",
        json=lambda n: {"order_material_id": -2, "quantity": "1"},
        idempotency_key=True,
    ),
]


def test_b4_protected_call_list_covers_every_protected_route() -> None:
    covered = {(c.method, c.path) for c in PROTECTED_CALLS}
    protected = {key for key, rule in ENDPOINT_ACCESS.items() if not rule.public}
    assert covered == protected


@pytest.fixture
def targets(
    user_factory,
    product_factory,
    material_factory,
    work_center_factory,
    bom_factory,
    routing_factory,
    order_factory,
    order_line_factory,
    operation_factory,
) -> dict[str, int]:
    """One existing, unused row of each kind for the path parameters."""
    product = product_factory()
    component = material_factory()
    station = work_center_factory()
    plannable = product_factory()
    bom_factory(plannable, [(material_factory(), "1", "0")], status="ACTIVE")
    routing_factory(plannable, [(10, "QC", work_center_factory())], status="ACTIVE")
    return {
        "user_id": user_factory(role=Role.WAREHOUSE).id,
        "product_id": product.id,
        "material_id": material_factory().id,
        "work_center_id": work_center_factory().id,
        "bom_id": bom_factory(product, [(component, "2", "0")]).id,
        "component_id": component.id,
        "routing_id": routing_factory(product, [(10, "QC", station)]).id,
        # Own product, ready to plan; an open order also blocks deactivating the target
        # product (C-13).
        "order_id": order_factory(plannable).id,
        "shortage_order_id": order_factory(plannable, status="MATERIAL_SHORTAGE").id,
        # READY with no material lines: nothing left to issue, so start is allowed.
        "startable_order_id": order_factory(plannable, status="READY_TO_PRODUCE").id,
        "operation_id": operation_factory(
            order_factory(plannable, status="IN_PROGRESS"), 10, "QC", work_center_factory()
        ).id,
        "ready_line_id": order_line_factory(
            order_factory(plannable, status="READY_TO_PRODUCE"),
            material_factory(),
            required="10",
            reserved="10",
        ).id,
        "cancelled_line_id": order_line_factory(
            order_factory(plannable, status="CANCELLED"),
            material_factory(),
            required="10",
            issued="10",
        ).id,
        "station_id": station.id,
    }


def _send(
    client: TestClient, call: Call, targets: dict[str, int], headers: dict[str, str], n: int
) -> int:
    path = call.path.format(**{**targets, **{k: targets[v] for k, v in call.params}})
    body = call.json(n) if call.json else None
    if body and "bom_header_id" in body:  # explode the target's own DRAFT version
        body = {**body, "bom_header_id": targets["bom_id"]}
    if body and body.get("order_material_id") == -1:  # a READY order's reserved line
        body = {**body, "order_material_id": targets["ready_line_id"]}
    if body and body.get("order_material_id") == -2:  # a CANCELLED order's issued line
        body = {**body, "order_material_id": targets["cancelled_line_id"]}
    if body and body.get("product_id") == 0:  # a real, active product
        body = {**body, "product_id": targets["product_id"]}
    if body and body.get("material_id") == 0:  # a real, active material
        body = {**body, "material_id": targets["material_id"]}
    if call.idempotency_key:
        headers = {**headers, "Idempotency-Key": f"matrix-{uuid.uuid4()}"}
    if body and "steps" in body:  # routing steps need a real work center
        steps = [{**step, "work_center_id": targets["station_id"]} for step in body["steps"]]
        body = {"steps": steps}
    if body and "items" in body:  # BOM lines need a real material
        lines = [{**line, "material_id": targets["component_id"]} for line in body["items"]]
        body = {"items": lines}
    return client.request(call.method, path, json=body, headers=headers).status_code


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("call", PROTECTED_CALLS, ids=lambda c: f"{c.method} {c.path}")
def test_b4_role_gets_2xx_or_403_per_permission_matrix(
    db_client: TestClient, login_as, targets: dict[str, int], role: Role, call: Call
) -> None:
    headers = login_as(role)
    status = _send(db_client, call, targets, headers, n=1)

    rule = ENDPOINT_ACCESS[(call.method, call.path)]
    allowed = rule.permission is None or has_permission(role, rule.permission)
    if allowed and call.worker_scoped and role is Role.WORKER:
        assert status == 200 or status == 404, status
    elif allowed:
        assert 200 <= status < 300, status
    else:
        assert status == 403


@pytest.mark.parametrize("call", PROTECTED_CALLS, ids=lambda c: f"{c.method} {c.path}")
def test_br_auth_02_protected_route_without_token_is_401(
    db_client: TestClient, targets: dict[str, int], call: Call
) -> None:
    assert _send(db_client, call, targets, headers={}, n=2) == 401
