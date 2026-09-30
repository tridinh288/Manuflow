"""B4 / B13 access control: test 21 (router scan) and test 19 (role x endpoint).

``ENDPOINT_ACCESS`` transcribes the endpoint table of B13. Every route in the app must
appear here with the access rule it declares in code, so adding a route without a
permission (or with the wrong one) fails the build.
"""

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
]


def test_b4_protected_call_list_covers_every_protected_route() -> None:
    covered = {(c.method, c.path) for c in PROTECTED_CALLS}
    protected = {key for key, rule in ENDPOINT_ACCESS.items() if not rule.public}
    assert covered == protected


@pytest.fixture
def targets(user_factory, product_factory, material_factory, work_center_factory) -> dict[str, int]:
    """One existing, unused row of each kind for the path parameters."""
    return {
        "user_id": user_factory(role=Role.WAREHOUSE).id,
        "product_id": product_factory().id,
        "material_id": material_factory().id,
        "work_center_id": work_center_factory().id,
    }


def _send(
    client: TestClient, call: Call, targets: dict[str, int], headers: dict[str, str], n: int
) -> int:
    path = call.path.format(**targets)
    body = call.json(n) if call.json else None
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
    if allowed:
        assert 200 <= status < 300, status
    else:
        assert status == 403


@pytest.mark.parametrize("call", PROTECTED_CALLS, ids=lambda c: f"{c.method} {c.path}")
def test_br_auth_02_protected_route_without_token_is_401(
    db_client: TestClient, targets: dict[str, int], call: Call
) -> None:
    assert _send(db_client, call, targets, headers={}, n=2) == 401
