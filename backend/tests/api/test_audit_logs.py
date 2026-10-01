"""GET /audit-logs (BR-AUD-06): ADMIN reads who did what and when, with filters."""

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.permissions import Role

URL = "/api/v1/audit-logs"


@pytest.fixture
def history(db_client: TestClient, login_as) -> dict[str, dict[str, str]]:
    """Two products by two managers, then a failed login."""
    pm = login_as(Role.PRODUCTION_MANAGER, username="planner01")
    db_client.post(
        "/api/v1/products", json={"product_code": "FRAME-A", "name": "Frame"}, headers=pm
    )
    pm = login_as(Role.PRODUCTION_MANAGER, username="planner02")
    db_client.post(
        "/api/v1/products", json={"product_code": "FRAME-B", "name": "Frame B"}, headers=pm
    )
    db_client.post("/api/v1/auth/login", json={"username": "planner02", "password": "wrong-pass1"})
    return {"admin": login_as(Role.ADMIN)}


def items(client: TestClient, headers: dict[str, str], **params: object) -> list[dict]:  # type: ignore[type-arg]
    response = client.get(URL, params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: list[dict] = response.json()["items"]  # type: ignore[type-arg]
    return body


def test_br_aud_06_admin_reads_newest_first_with_the_br_aud_03_fields(
    db_client: TestClient, history: dict[str, dict[str, str]]
) -> None:
    rows = items(db_client, history["admin"], entity_type="product")
    assert [r["new_value"]["product_code"] for r in rows] == ["FRAME-B", "FRAME-A"]
    assert set(rows[0]) >= {
        "actor_user_id",
        "actor_username",
        "action",
        "entity_type",
        "entity_id",
        "old_value",
        "new_value",
        "reason",
        "request_id",
        "ip_address",
        "created_at",
    }
    assert rows[0]["actor_username"] == "planner02" and rows[0]["request_id"]


def test_br_aud_06_filters_by_actor_action_entity_and_time(
    db_client: TestClient, history: dict[str, dict[str, str]]
) -> None:
    admin = history["admin"]
    by_actor = items(db_client, admin, actor_username="planner01", action="MASTER_CREATED")
    assert [r["new_value"]["product_code"] for r in by_actor] == ["FRAME-A"]

    failed = items(db_client, admin, action="LOGIN_FAILED")
    assert [r["actor_username"] for r in failed] == ["planner02"]

    first = by_actor[0]
    by_entity = items(db_client, admin, entity_type="product", entity_id=first["entity_id"])
    assert [r["id"] for r in by_entity] == [first["id"]]

    # created_at is the database time; created_to is exclusive, so a window ending at
    # FRAME-B's timestamp holds FRAME-A only.
    products = items(db_client, admin, entity_type="product")
    b_at, a_at = products[0]["created_at"], products[1]["created_at"]
    early = items(db_client, admin, entity_type="product", created_from=a_at, created_to=b_at)
    assert [r["new_value"]["product_code"] for r in early] == ["FRAME-A"]


def test_br_aud_06_paging_and_bad_ranges(
    db_client: TestClient, history: dict[str, dict[str, str]], clock: FixedClock
) -> None:
    admin = history["admin"]
    page = db_client.get(
        URL, params={"entity_type": "product", "limit": 1, "offset": 1}, headers=admin
    ).json()
    assert page["total"] == 2 and [r["new_value"]["product_code"] for r in page["items"]] == [
        "FRAME-A"
    ]
    now = clock.now().isoformat()
    backwards = db_client.get(URL, params={"created_from": now, "created_to": now}, headers=admin)
    assert backwards.status_code == 422
    assert backwards.json()["error"]["code"] == "INVALID_DATE_RANGE"
    naive = db_client.get(URL, params={"created_from": "2026-09-30T08:00:00"}, headers=admin)
    assert naive.status_code == 422  # D-23: a timezone is required
    unknown = db_client.get(URL, params={"action": "DROP_TABLE"}, headers=admin)
    assert unknown.status_code == 422


def test_br_aud_05_audit_log_api_never_returns_secrets(
    db_client: TestClient, history: dict[str, dict[str, str]]
) -> None:
    response = db_client.get(URL, params={"limit": 200}, headers=history["admin"])
    keys: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            keys.update(k.lower() for k in value)
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(response.json())
    assert (
        keys & {"password", "password_hash", "token", "authorization", "secret", "api_key"} == set()
    )
    assert "wrong-pass1" not in response.text  # the failed attempt's password


@pytest.mark.parametrize("role", [Role.PRODUCTION_MANAGER, Role.WAREHOUSE, Role.WORKER])
def test_br_aud_06_only_admin_reads_the_audit_log(
    db_client: TestClient, login_as, role: Role
) -> None:
    assert db_client.get(URL, headers=login_as(role)).status_code == 403
