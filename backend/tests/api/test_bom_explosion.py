"""Test 1 and 2 of B15 through the API: the B5 example is reproduced end to end."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.bom import BomHeader
from app.models.master_data import Material, Product


@pytest.fixture
def worker(login_as) -> dict[str, str]:
    # master:read is enough; even a WORKER may preview requirements.
    headers: dict[str, str] = login_as(Role.WORKER)
    return headers


@pytest.fixture
def frame(product_factory) -> Product:
    product: Product = product_factory("FRAME-A")
    return product


@pytest.fixture
def b5(material_factory) -> dict[str, Material]:
    return {
        "STEEL-001": material_factory("STEEL-001", unit="kg", decimal_places=3),
        "BOLT-M8": material_factory("BOLT-M8", unit="pcs", decimal_places=0),
        "PAINT-RED": material_factory("PAINT-RED", unit="kg", decimal_places=3),
    }


@pytest.fixture
def active_bom(bom_factory, frame: Product, b5: dict[str, Material]) -> BomHeader:
    header: BomHeader = bom_factory(
        frame,
        [
            (b5["STEEL-001"], "2.0000", "0.02"),
            (b5["BOLT-M8"], "8", "0.05"),
            (b5["PAINT-RED"], "0.2000", "0"),
        ],
        status="ACTIVE",
    )
    return header


def explode(
    client: TestClient, product: Product | int, body: dict[str, Any], headers: dict[str, str]
) -> Any:
    product_id = product if isinstance(product, int) else product.id
    return client.post(f"/api/v1/products/{product_id}/bom/explode", json=body, headers=headers)


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        (100, [("BOLT-M8", "840"), ("PAINT-RED", "20.000"), ("STEEL-001", "204.000")]),
        (7, [("BOLT-M8", "59"), ("PAINT-RED", "1.400"), ("STEEL-001", "14.280")]),
    ],
)
def test_br_bom_05_b5_example_reproduced_through_the_api(
    db_client: TestClient,
    worker: dict[str, str],
    frame: Product,
    active_bom: BomHeader,
    quantity: int,
    expected: list[tuple[str, str]],
) -> None:
    response = explode(db_client, frame, {"quantity": quantity}, worker)
    assert response.status_code == 200
    body = response.json()
    assert (body["product_id"], body["quantity"]) == (frame.id, quantity)
    assert [(i["material_code"], i["required_quantity"]) for i in body["items"]] == expected
    bolt = body["items"][0]
    assert (bolt["unit"], bolt["qty_per_unit"], bolt["scrap_rate"]) == ("pcs", "8.0000", "0.0500")


def test_br_bom_05_explosion_writes_nothing(
    db_client: TestClient, db_session: Session, worker: dict[str, str], frame: Product, active_bom
) -> None:
    before = db_session.scalar(select(func.count()).select_from(AuditLog))
    explode(db_client, frame, {"quantity": 100}, worker)
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == before


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "100", True, None], ids=repr)
def test_br_bom_05_invalid_quantity_is_422(
    db_client: TestClient, worker: dict[str, str], frame: Product, active_bom, quantity: Any
) -> None:
    response = explode(db_client, frame, {"quantity": quantity}, worker)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "INVALID_QUANTITY")


def test_br_bom_05_missing_product_is_404(db_client: TestClient, worker: dict[str, str]) -> None:
    response = explode(db_client, 999999, {"quantity": 1}, worker)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "PRODUCT_NOT_FOUND")


def test_br_bom_05_inactive_product_is_409(
    db_client: TestClient, worker: dict[str, str], product_factory
) -> None:
    retired = product_factory("OLD-FRAME", active=False)
    response = explode(db_client, retired, {"quantity": 1}, worker)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "PRODUCT_INACTIVE")


def test_br_bom_05_product_without_active_bom_is_409(
    db_client: TestClient, worker: dict[str, str], frame: Product, bom_factory, b5
) -> None:
    bom_factory(frame, [(b5["BOLT-M8"], "8", "0")], status="DRAFT")
    response = explode(db_client, frame, {"quantity": 1}, worker)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "NO_ACTIVE_BOM")


def test_br_bom_05_inactive_material_is_409_with_its_code(
    db_client: TestClient,
    db_session: Session,
    worker: dict[str, str],
    frame: Product,
    active_bom: BomHeader,
    b5: dict[str, Material],
) -> None:
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        b5["PAINT-RED"].active = False  # e.g. deactivated before C-13/D-19 guards existed
    response = explode(db_client, frame, {"quantity": 1}, worker)
    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["details"]) == (
        "MATERIAL_INACTIVE",
        [{"material_code": "PAINT-RED"}],
    )


def test_br_bom_05_explicit_version_can_be_previewed(
    db_client: TestClient,
    worker: dict[str, str],
    frame: Product,
    active_bom: BomHeader,
    bom_factory,
    b5: dict[str, Material],
) -> None:
    draft = bom_factory(frame, [(b5["BOLT-M8"], "10", "0")], version=2, status="DRAFT")
    response = explode(db_client, frame, {"quantity": 7, "bom_header_id": draft.id}, worker)
    assert [(i["material_code"], i["required_quantity"]) for i in response.json()["items"]] == [
        ("BOLT-M8", "70")
    ]


def test_br_bom_05_version_of_another_product_is_404(
    db_client: TestClient,
    worker: dict[str, str],
    frame: Product,
    active_bom: BomHeader,
    product_factory,
) -> None:
    other = product_factory("OTHER-P")
    response = explode(db_client, other, {"quantity": 1, "bom_header_id": active_bom.id}, worker)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "BOM_NOT_FOUND")
