"""BR-MD-01..04, D-19, C-07, C-13, C-14 and BR-INV-01 through the API."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.master_data import Inventory

PRODUCTS = "/api/v1/products"
MATERIALS = "/api/v1/materials"
WORK_CENTERS = "/api/v1/work-centers"


def steel(**overrides: Any) -> dict[str, Any]:
    return {
        "material_code": "STEEL-001",
        "name": "Steel sheet",
        "unit": "kg",
        "decimal_places": 3,
        "minimum_stock": "50",
        **overrides,
    }


def error_code(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


# --- BR-MD-01: unique, well-formed, immutable codes -----------------------------------


@pytest.mark.parametrize(
    ("url", "body"),
    [
        (PRODUCTS, {"product_code": "FRAME-A", "name": "Frame A"}),
        (MATERIALS, steel()),
        (WORK_CENTERS, {"code": "WC-WELD", "name": "Welding"}),
    ],
    ids=["product", "material", "work-center"],
)
def test_br_md_01_code_is_unique(
    db_client: TestClient, pm: dict[str, str], url: str, body: dict[str, Any]
) -> None:
    assert db_client.post(url, json=body, headers=pm).status_code == 201
    duplicate = db_client.post(url, json=body, headers=pm)
    assert duplicate.status_code == 409
    assert error_code(duplicate).endswith("_CODE_TAKEN")


@pytest.mark.parametrize("code", ["frame-a", "FR", "FRAME A", "FRAME_A", "F" * 33])
def test_br_md_01_code_format_enforced(
    db_client: TestClient, pm: dict[str, str], code: str
) -> None:
    response = db_client.post(PRODUCTS, json={"product_code": code, "name": "X"}, headers=pm)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("url", "create", "update"),
    [
        (PRODUCTS, {"product_code": "FRAME-A", "name": "A"}, {"product_code": "FRAME-B"}),
        (MATERIALS, steel(), {"material_code": "STEEL-002", "minimum_stock": "1"}),
        (WORK_CENTERS, {"code": "WC-CUT", "name": "Cut"}, {"code": "WC-CUT2"}),
    ],
    ids=["product", "material", "work-center"],
)
def test_br_md_01_code_cannot_be_changed(
    db_client: TestClient,
    pm: dict[str, str],
    url: str,
    create: dict[str, Any],
    update: dict[str, Any],
) -> None:
    created = db_client.post(url, json=create, headers=pm).json()
    response = db_client.put(f"{url}/{created['id']}", json={"name": "New", **update}, headers=pm)
    assert response.status_code == 422
    assert db_client.get(f"{url}/{created['id']}", headers=pm).json() == created


# --- BR-MD-02: units, decimal places, minimum stock -----------------------------------


def test_br_md_02_material_is_created_with_formatted_minimum_stock(
    db_client: TestClient, pm: dict[str, str]
) -> None:
    response = db_client.post(MATERIALS, json=steel(), headers=pm)
    assert response.status_code == 201
    body = response.json()
    assert (body["unit"], body["decimal_places"], body["minimum_stock"]) == ("kg", 3, "50.000")


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"unit": "pcs", "decimal_places": 2}, "INVALID_DECIMAL_PLACES"),
        ({"unit": "box"}, "VALIDATION_ERROR"),
        ({"decimal_places": 5}, "VALIDATION_ERROR"),
        ({"minimum_stock": "1.2345"}, "INVALID_QUANTITY_SCALE"),
        ({"minimum_stock": "-1"}, "VALIDATION_ERROR"),
        ({"minimum_stock": 5}, "VALIDATION_ERROR"),  # a JSON number, not a string (B13)
        ({"minimum_stock": "5.5e3"}, "VALIDATION_ERROR"),
    ],
    ids=[
        "pcs-with-decimals",
        "unknown-unit",
        "too-many-places",
        "scale",
        "negative",
        "number",
        "exp",
    ],
)
def test_br_md_02_invalid_material_is_422(
    db_client: TestClient, pm: dict[str, str], overrides: dict[str, Any], code: str
) -> None:
    response = db_client.post(MATERIALS, json=steel(**overrides), headers=pm)
    assert response.status_code == 422
    assert error_code(response) == code


@pytest.mark.parametrize("field", [{"unit": "l"}, {"decimal_places": 1}])
def test_c14_unit_and_decimal_places_cannot_be_changed(
    db_client: TestClient, pm: dict[str, str], field: dict[str, Any]
) -> None:
    material_id = db_client.post(MATERIALS, json=steel(), headers=pm).json()["id"]
    body = {"name": "Steel", "minimum_stock": "10", **field}
    response = db_client.put(f"{MATERIALS}/{material_id}", json=body, headers=pm)
    assert response.status_code == 422


def test_br_md_02_minimum_stock_update_respects_scale(
    db_client: TestClient, pm: dict[str, str]
) -> None:
    material_id = db_client.post(
        MATERIALS, json=steel(material_code="BOLT-M8", unit="pcs", decimal_places=0), headers=pm
    ).json()["id"]
    url = f"{MATERIALS}/{material_id}"
    refused = db_client.put(url, json={"name": "Bolt", "minimum_stock": "10.5"}, headers=pm)
    assert error_code(refused) == "INVALID_QUANTITY_SCALE"
    accepted = db_client.put(url, json={"name": "Bolt", "minimum_stock": "100"}, headers=pm)
    assert accepted.json()["minimum_stock"] == "100"


# --- BR-MD-03: products are made in pcs ------------------------------------------------


def test_br_md_03_product_unit_is_always_pcs(db_client: TestClient, pm: dict[str, str]) -> None:
    created = db_client.post(PRODUCTS, json={"product_code": "FRAME-A", "name": "A"}, headers=pm)
    assert created.json()["unit"] == "pcs"
    other_unit = {"product_code": "FRAME-B", "name": "B", "unit": "kg"}
    assert db_client.post(PRODUCTS, json=other_unit, headers=pm).status_code == 422


# --- BR-INV-01: a material always has a balance row -----------------------------------


def test_br_inv_01_material_creation_creates_zero_balance(
    db_client: TestClient, db_session: Session, pm: dict[str, str]
) -> None:
    material_id = db_client.post(MATERIALS, json=steel(), headers=pm).json()["id"]
    balance = db_session.scalars(
        select(Inventory).where(Inventory.material_id == material_id)
    ).one()
    assert (balance.on_hand_quantity, balance.reserved_quantity) == (Decimal(0), Decimal(0))


def test_br_inv_01_failed_material_creation_leaves_no_balance_row(
    db_client: TestClient, db_session: Session, pm: dict[str, str]
) -> None:
    db_client.post(MATERIALS, json=steel(), headers=pm)
    db_client.post(MATERIALS, json=steel(name="Duplicate"), headers=pm)  # 409
    assert len(db_session.scalars(select(Inventory)).all()) == 1


# --- BR-MD-04 / D-19: deactivate, never delete ----------------------------------------


@pytest.mark.parametrize(
    ("url", "body"),
    [
        (PRODUCTS, {"product_code": "FRAME-A", "name": "A"}),
        (MATERIALS, steel()),
        (WORK_CENTERS, {"code": "WC-PAINT", "name": "Paint"}),
    ],
    ids=["product", "material", "work-center"],
)
def test_br_md_04_delete_deactivates_once_and_keeps_the_row(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    url: str,
    body: dict[str, Any],
) -> None:
    row_id = db_client.post(url, json=body, headers=pm).json()["id"]
    assert db_client.delete(f"{url}/{row_id}", headers=pm).status_code == 204
    assert db_client.delete(f"{url}/{row_id}", headers=pm).status_code == 204  # no-op

    assert db_client.get(f"{url}/{row_id}", headers=pm).json()["active"] is False
    listed = db_client.get(url, params={"active": "false"}, headers=pm).json()
    assert [item["id"] for item in listed["items"]] == [row_id]
    deactivations = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "MASTER_DEACTIVATED")
    ).all()
    assert len(deactivations) == 1


def test_c13_product_deactivation_is_not_blocked_by_bom_versions(
    db_client: TestClient, pm: dict[str, str]
) -> None:
    # Until production orders exist (Phase 5) nothing blocks a product's deactivation;
    # its BOM and routing versions are kept but cannot be used (BR-MD-04).
    product_id = db_client.post(
        PRODUCTS, json={"product_code": "FRAME-A", "name": "A"}, headers=pm
    ).json()["id"]
    assert db_client.delete(f"{PRODUCTS}/{product_id}", headers=pm).status_code == 204


def test_c07_work_center_with_active_workers_cannot_be_deactivated(
    db_client: TestClient, db_session: Session, pm: dict[str, str], user_factory
) -> None:
    work_center_id = db_client.post(
        WORK_CENTERS, json={"code": "WC-WELD", "name": "Welding"}, headers=pm
    ).json()["id"]
    worker = user_factory(role=Role.WORKER, work_center_id=work_center_id)

    refused = db_client.delete(f"{WORK_CENTERS}/{work_center_id}", headers=pm)
    assert refused.status_code == 409
    assert error_code(refused) == "WORK_CENTER_IN_USE"
    assert refused.json()["error"]["details"] == [{"reason": "ACTIVE_WORKERS", "count": 1}]

    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        worker.active = False
    assert db_client.delete(f"{WORK_CENTERS}/{work_center_id}", headers=pm).status_code == 204


# --- Reads, audit, errors ----------------------------------------------------------------


def test_br_aud_01_master_data_changes_are_audited(
    db_client: TestClient, db_session: Session, pm: dict[str, str]
) -> None:
    material_id = db_client.post(MATERIALS, json=steel(), headers=pm).json()["id"]
    db_client.put(
        f"{MATERIALS}/{material_id}",
        json={"name": "Steel sheet", "minimum_stock": "75.5"},
        headers=pm,
    )
    created, updated = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "material", AuditLog.entity_id == material_id)
        .order_by(AuditLog.id)
    ).all()
    assert created.action == "MASTER_CREATED"
    assert created.new_value is not None
    assert created.new_value["minimum_stock"] == "50"
    assert updated.action == "MASTER_UPDATED"
    assert (updated.old_value, updated.new_value) == (
        {"minimum_stock": "50.0000"},
        {"minimum_stock": "75.5"},
    )


def test_list_is_sorted_by_code_and_paginated(db_client: TestClient, pm: dict[str, str]) -> None:
    for code in ("WC-QC", "WC-CNC", "WC-CUT"):
        db_client.post(WORK_CENTERS, json={"code": code, "name": code}, headers=pm)
    page = db_client.get(WORK_CENTERS, params={"limit": 2}, headers=pm).json()
    assert page["total"] == 3
    assert [item["code"] for item in page["items"]] == ["WC-CNC", "WC-CUT"]


@pytest.mark.parametrize("url", [PRODUCTS, MATERIALS, WORK_CENTERS])
def test_unknown_id_is_404(db_client: TestClient, pm: dict[str, str], url: str) -> None:
    response = db_client.get(f"{url}/999999", headers=pm)
    assert response.status_code == 404
    assert error_code(response).endswith("_NOT_FOUND")
