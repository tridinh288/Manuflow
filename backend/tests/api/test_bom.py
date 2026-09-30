"""BR-BOM-01..04, D-03, D-19 and BR-MD-04 for versioned BOMs (tests 3 and 4 of B15)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.master_data import Material, Product


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


@pytest.fixture
def frame(product_factory) -> Product:
    product: Product = product_factory("FRAME-A")
    return product


@pytest.fixture
def materials(material_factory) -> dict[str, Material]:
    """The worked example of B5."""
    return {
        "STEEL-001": material_factory("STEEL-001", unit="kg", decimal_places=3),
        "BOLT-M8": material_factory("BOLT-M8", unit="pcs", decimal_places=0),
        "PAINT-RED": material_factory("PAINT-RED", unit="kg", decimal_places=3),
    }


def example_items(materials: dict[str, Material]) -> list[dict[str, Any]]:
    return [
        {"material_id": materials["STEEL-001"].id, "qty_per_unit": "2.0000", "scrap_rate": "0.02"},
        {"material_id": materials["BOLT-M8"].id, "qty_per_unit": "8", "scrap_rate": "0.05"},
        {"material_id": materials["PAINT-RED"].id, "qty_per_unit": "0.2", "scrap_rate": "0"},
    ]


def new_draft(client: TestClient, product: Product, headers: dict[str, str]) -> int:
    response = client.post(f"/api/v1/products/{product.id}/boms", headers=headers)
    assert response.status_code == 201, response.text
    bom_id: int = response.json()["id"]
    return bom_id


def put_items(
    client: TestClient, bom_id: int, items: list[dict[str, Any]], headers: dict[str, str]
) -> Any:
    return client.put(f"/api/v1/boms/{bom_id}/items", json={"items": items}, headers=headers)


def activate(client: TestClient, bom_id: int, headers: dict[str, str]) -> Any:
    return client.post(f"/api/v1/boms/{bom_id}/activate", headers=headers)


def ready_draft(
    client: TestClient, product: Product, materials: dict[str, Material], headers: dict[str, str]
) -> int:
    bom_id = new_draft(client, product, headers)
    assert put_items(client, bom_id, example_items(materials), headers).status_code == 200
    return bom_id


# --- Drafts and lines -------------------------------------------------------------------


def test_d03_new_versions_are_numbered_per_product(
    db_client: TestClient, pm: dict[str, str], frame: Product
) -> None:
    versions = [
        db_client.post(f"/api/v1/products/{frame.id}/boms", headers=pm).json()["version"]
        for _ in range(3)
    ]
    assert versions == [1, 2, 3]


def test_br_bom_01_lines_are_stored_and_returned_as_strings(
    db_client: TestClient, pm: dict[str, str], frame: Product, materials: dict[str, Material]
) -> None:
    bom_id = new_draft(db_client, frame, pm)
    body = put_items(db_client, bom_id, example_items(materials), pm).json()
    assert body["status"] == "DRAFT"
    assert [
        (i["material_code"], i["unit"], i["qty_per_unit"], i["scrap_rate"]) for i in body["items"]
    ] == [
        ("STEEL-001", "kg", "2.0000", "0.0200"),
        ("BOLT-M8", "pcs", "8.0000", "0.0500"),
        ("PAINT-RED", "kg", "0.2000", "0.0000"),
    ]


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ({"qty_per_unit": "0"}, "INVALID_QTY_PER_UNIT"),
        ({"qty_per_unit": "1.23456"}, "VALIDATION_ERROR"),
        ({"qty_per_unit": "-1"}, "VALIDATION_ERROR"),
        ({"qty_per_unit": 2}, "VALIDATION_ERROR"),
        ({"qty_per_unit": "1", "scrap_rate": "1"}, "INVALID_SCRAP_RATE"),
        ({"qty_per_unit": "1", "scrap_rate": "1.5"}, "INVALID_SCRAP_RATE"),
    ],
    ids=["zero", "five-decimals", "negative", "number", "scrap-one", "scrap-above-one"],
)
def test_br_bom_01_invalid_quantities_are_422(
    db_client: TestClient,
    pm: dict[str, str],
    frame: Product,
    materials: dict[str, Material],
    line: dict[str, Any],
    code: str,
) -> None:
    bom_id = new_draft(db_client, frame, pm)
    response = put_items(db_client, bom_id, [{"material_id": materials["BOLT-M8"].id, **line}], pm)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_br_bom_02_material_listed_twice_is_422(
    db_client: TestClient, pm: dict[str, str], frame: Product, materials: dict[str, Material]
) -> None:
    bom_id = new_draft(db_client, frame, pm)
    bolt = materials["BOLT-M8"].id
    response = put_items(
        db_client,
        bom_id,
        [{"material_id": bolt, "qty_per_unit": "8"}, {"material_id": bolt, "qty_per_unit": "2"}],
        pm,
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["code"], error["details"]) == ("DUPLICATE_MATERIAL", [{"material_id": bolt}])


def test_put_items_replaces_all_lines(
    db_client: TestClient, pm: dict[str, str], frame: Product, materials: dict[str, Material]
) -> None:
    bom_id = ready_draft(db_client, frame, materials, pm)
    only_bolt = [{"material_id": materials["BOLT-M8"].id, "qty_per_unit": "4"}]
    body = put_items(db_client, bom_id, only_bolt, pm).json()
    assert [(i["material_code"], i["qty_per_unit"]) for i in body["items"]] == [
        ("BOLT-M8", "4.0000")
    ]


def test_br_md_04_unknown_or_inactive_material_cannot_be_used(
    db_client: TestClient, pm: dict[str, str], frame: Product, material_factory
) -> None:
    bom_id = new_draft(db_client, frame, pm)
    unknown = put_items(db_client, bom_id, [{"material_id": 999999, "qty_per_unit": "1"}], pm)
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (422, "MATERIAL_NOT_FOUND")

    retired = material_factory("OLD-PART", active=False)
    inactive = put_items(db_client, bom_id, [{"material_id": retired.id, "qty_per_unit": "1"}], pm)
    assert inactive.status_code == 409
    assert inactive.json()["error"]["details"] == [{"material_code": "OLD-PART"}]


def test_br_md_04_inactive_product_gets_no_new_bom(
    db_client: TestClient, pm: dict[str, str], product_factory
) -> None:
    retired = product_factory("OLD-FRAME", active=False)
    response = db_client.post(f"/api/v1/products/{retired.id}/boms", headers=pm)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "PRODUCT_INACTIVE")


# --- Activation (BR-BOM-03, BR-BOM-04; test 4) -------------------------------------------


def test_br_bom_03_activation_needs_at_least_one_line(
    db_client: TestClient, pm: dict[str, str], frame: Product
) -> None:
    response = activate(db_client, new_draft(db_client, frame, pm), pm)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "BOM_EMPTY")


def test_br_bom_03_activating_a_new_version_retires_the_old_one(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    materials: dict[str, Material],
) -> None:
    first = ready_draft(db_client, frame, materials, pm)
    assert activate(db_client, first, pm).json()["status"] == "ACTIVE"
    second = ready_draft(db_client, frame, materials, pm)
    activated = activate(db_client, second, pm).json()
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] is not None

    statuses = {
        v["id"]: v["status"]
        for v in db_client.get(f"/api/v1/products/{frame.id}/boms", headers=pm).json()["items"]
    }
    assert statuses == {first: "RETIRED", second: "ACTIVE"}
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "BOM_ACTIVATED").order_by(AuditLog.id)
    ).all()
    assert [row.new_value for row in audit] == [
        {"product_id": frame.id, "version": 1, "retired_version": None},
        {"product_id": frame.id, "version": 2, "retired_version": 1},
    ]


@pytest.mark.parametrize("action", ["put_items", "activate"])
def test_br_bom_03_active_and_retired_versions_are_frozen(
    db_client: TestClient,
    pm: dict[str, str],
    frame: Product,
    materials: dict[str, Material],
    action: str,
) -> None:
    first = ready_draft(db_client, frame, materials, pm)
    activate(db_client, first, pm)
    activate(db_client, ready_draft(db_client, frame, materials, pm), pm)  # first -> RETIRED
    for bom_id in (first,):
        response = (
            put_items(db_client, bom_id, example_items(materials), pm)
            if action == "put_items"
            else activate(db_client, bom_id, pm)
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "VERSION_NOT_EDITABLE"


def test_br_bom_03_inactive_material_blocks_activation(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    materials: dict[str, Material],
) -> None:
    bom_id = ready_draft(db_client, frame, materials, pm)
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        materials["PAINT-RED"].active = False
    response = activate(db_client, bom_id, pm)
    assert response.status_code == 409
    assert response.json()["error"]["details"] == [{"material_code": "PAINT-RED"}]


# --- D-19: a material used by an ACTIVE BOM cannot be deactivated -------------------------


def test_d19_material_in_active_bom_cannot_be_deactivated(
    db_client: TestClient, pm: dict[str, str], frame: Product, materials: dict[str, Material]
) -> None:
    activate(db_client, ready_draft(db_client, frame, materials, pm), pm)
    response = db_client.delete(f"/api/v1/materials/{materials['BOLT-M8'].id}", headers=pm)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "MATERIAL_IN_USE"
    assert error["details"] == [{"product_code": "FRAME-A", "bom_version": 1}]


def test_d19_material_only_in_a_draft_can_be_deactivated(
    db_client: TestClient, pm: dict[str, str], frame: Product, materials: dict[str, Material]
) -> None:
    ready_draft(db_client, frame, materials, pm)
    response = db_client.delete(f"/api/v1/materials/{materials['BOLT-M8'].id}", headers=pm)
    assert response.status_code == 204
