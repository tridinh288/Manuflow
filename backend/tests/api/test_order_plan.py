"""plan and check-materials: tests 5, 6, 7 and 23 of B15 (BR-INV-05/06, D-04, D-08, D-09).

The stock scenario is the worked example of B6 (order of 100 x FRAME-A).
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.bom import BomHeader
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material, Product
from app.models.production import ProductionOperation, ProductionOrder, ProductionOrderMaterial
from app.services.audit_service import AuditService

ORDERS = "/api/v1/production-orders"


class Scenario:
    def __init__(self, product: Product, materials: dict[str, Material], bom: BomHeader) -> None:
        self.product, self.materials, self.bom = product, materials, bom


@pytest.fixture
def frame(
    product_factory, material_factory, work_center_factory, bom_factory, routing_factory
) -> Scenario:
    product = product_factory("FRAME-A")
    materials = {
        "STEEL-001": material_factory("STEEL-001", unit="kg", decimal_places=3),
        "BOLT-M8": material_factory("BOLT-M8", unit="pcs", decimal_places=0),
        "PAINT-RED": material_factory("PAINT-RED", unit="kg", decimal_places=3),
    }
    bom = bom_factory(
        product,
        [
            (materials["STEEL-001"], "2.0000", "0.02"),
            (materials["BOLT-M8"], "8", "0.05"),
            (materials["PAINT-RED"], "0.2000", "0"),
        ],
        status="ACTIVE",
    )
    stations = [work_center_factory(code) for code in ("WC-CUT", "WC-WELD", "WC-QC")]
    routing_factory(
        product,
        [(10, "CUTTING", stations[0]), (20, "WELDING", stations[1]), (30, "QC", stations[2])],
        status="ACTIVE",
    )
    return Scenario(product, materials, bom)


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


def set_stock(session: Session, scenario: Scenario, **balances: tuple[str, str]) -> None:
    """``BOLT_M8=("600", "100")`` -> on hand 600, of which 100 reserved by other orders."""
    if session.in_transaction():
        session.commit()
    with session.begin():
        for name, (on_hand, reserved) in balances.items():
            session.execute(
                text(
                    "UPDATE inventory SET on_hand_quantity = :o, reserved_quantity = :r "
                    "WHERE material_id = :id"
                ),
                {"o": on_hand, "r": reserved, "id": scenario.materials[name.replace("_", "-")].id},
            )


def b6_stock(session: Session, scenario: Scenario) -> None:
    set_stock(
        session,
        scenario,
        STEEL_001=("250", "0"),
        BOLT_M8=("600", "100"),
        PAINT_RED=("30", "5"),
    )


def ample_stock(session: Session, scenario: Scenario) -> None:
    set_stock(
        session, scenario, STEEL_001=("250", "0"), BOLT_M8=("1000", "0"), PAINT_RED=("30", "0")
    )


def act(client: TestClient, headers: dict[str, str], order_id: int, action: str, key: str) -> Any:
    return client.post(f"{ORDERS}/{order_id}/{action}", headers={**headers, "Idempotency-Key": key})


def balances(session: Session, scenario: Scenario) -> dict[str, tuple[Decimal, Decimal]]:
    rows = session.execute(
        select(Material.material_code, Inventory.on_hand_quantity, Inventory.reserved_quantity)
        .join(Inventory, Inventory.material_id == Material.id)
        .where(Material.id.in_([m.id for m in scenario.materials.values()]))
        .execution_options(populate_existing=True)
    ).all()
    return {code: (on_hand, reserved) for code, on_hand, reserved in rows}


def reserve_lines(session: Session, order_id: int) -> list[InventoryTransaction]:
    return list(
        session.scalars(
            select(InventoryTransaction)
            .where(
                InventoryTransaction.production_order_id == order_id,
                InventoryTransaction.type == "RESERVE",
            )
            .order_by(InventoryTransaction.material_id)
        )
    )


def order_lines(session: Session, order_id: int) -> dict[int, ProductionOrderMaterial]:
    rows = session.scalars(
        select(ProductionOrderMaterial)
        .where(ProductionOrderMaterial.production_order_id == order_id)
        .execution_options(populate_existing=True)
    )
    return {row.material_id: row for row in rows}


# --- Test 5: enough stock -> READY, everything reserved -----------------------------------


def test_br_inv_05_plan_with_enough_stock_reserves_every_line(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Scenario,
    order_factory,
) -> None:
    ample_stock(db_session, frame)
    order = order_factory(frame.product, planned_quantity=100)
    response = act(db_client, pm, order.id, "plan", "plan-key-0001")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["reserved"], body["allowed_actions"]) == (
        "READY_TO_PRODUCE",
        True,
        ["start", "cancel"],
    )
    assert body["bom_header_id"] == frame.bom.id and body["routing_id"] is not None  # D-04
    assert [(c["material_code"], c["required"], c["shortage"]) for c in body["material_check"]] == [
        ("STEEL-001", "204.000", "0.000"),
        ("BOLT-M8", "840", "0"),
        ("PAINT-RED", "20.000", "0.000"),
    ]

    assert balances(db_session, frame) == {
        "STEEL-001": (Decimal(250), Decimal(204)),
        "BOLT-M8": (Decimal(1000), Decimal(840)),
        "PAINT-RED": (Decimal(30), Decimal(20)),
    }
    lines = order_lines(db_session, order.id)
    assert all(line.reserved_quantity == line.required_quantity for line in lines.values())
    ledger = reserve_lines(db_session, order.id)  # BR-INV-03: one RESERVE line per material
    assert [(line.reserved_delta, line.on_hand_delta) for line in ledger] == [
        (Decimal(204), Decimal(0)),
        (Decimal(840), Decimal(0)),
        (Decimal(20), Decimal(0)),
    ]
    assert {line.order_material_id for line in ledger} == {line.id for line in lines.values()}
    operations = db_session.scalars(
        select(ProductionOperation)
        .where(ProductionOperation.production_order_id == order.id)
        .order_by(ProductionOperation.sequence)
    ).all()
    assert [(op.sequence, op.operation_type, op.status) for op in operations] == [
        (10, "CUTTING", "PENDING"),
        (20, "WELDING", "PENDING"),
        (30, "QC", "PENDING"),
    ]
    [audit] = db_session.scalars(select(AuditLog).where(AuditLog.action == "ORDER_PLANNED"))
    assert (audit.old_value, audit.new_value) == (
        {"status": "DRAFT"},
        {"status": "READY_TO_PRODUCE", "bom_version": 1, "routing_version": 1},
    )


# --- Test 6: shortage -> MATERIAL_SHORTAGE, nothing reserved (the B6 example) ---------------


def test_d08_plan_with_a_shortage_reserves_nothing_and_reports_every_line(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Scenario,
    order_factory,
) -> None:
    b6_stock(db_session, frame)
    order = order_factory(frame.product, planned_quantity=100)
    response = act(db_client, pm, order.id, "plan", "plan-key-0001")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["reserved"], body["allowed_actions"]) == (
        "MATERIAL_SHORTAGE",
        False,
        ["check-materials", "cancel"],
    )
    # The table of B6, line for line.
    assert [
        (c["material_code"], c["required"], c["available"], c["shortage"])
        for c in body["material_check"]
    ] == [
        ("STEEL-001", "204.000", "250.000", "0.000"),
        ("BOLT-M8", "840", "500", "340"),
        ("PAINT-RED", "20.000", "25.000", "0.000"),
    ]
    assert balances(db_session, frame) == {  # nothing reserved anywhere (D-08)
        "STEEL-001": (Decimal(250), Decimal(0)),
        "BOLT-M8": (Decimal(600), Decimal(100)),
        "PAINT-RED": (Decimal(30), Decimal(5)),
    }
    assert reserve_lines(db_session, order.id) == []
    lines = order_lines(db_session, order.id)
    assert {
        frame.materials[c].id: lines[frame.materials[c].id].shortage_quantity
        for c in frame.materials
    } == {
        frame.materials["STEEL-001"].id: Decimal(0),
        frame.materials["BOLT-M8"].id: Decimal(340),
        frame.materials["PAINT-RED"].id: Decimal(0),
    }
    assert all(line.reserved_quantity == 0 for line in lines.values())


# --- Test 7: never reserved twice -----------------------------------------------------------


def test_br_inv_06_plan_twice_or_check_materials_when_ready_is_409(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Scenario,
    order_factory,
) -> None:
    ample_stock(db_session, frame)
    order = order_factory(frame.product, planned_quantity=100)
    first = act(db_client, pm, order.id, "plan", "plan-key-0001")
    replay = act(db_client, pm, order.id, "plan", "plan-key-0001")  # D-22: same key
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"

    for action, key in (("plan", "plan-key-0002"), ("check-materials", "check-key-0001")):
        response = act(db_client, pm, order.id, action, key)
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "INVALID_STATE_TRANSITION"
        assert error["details"][0]["current_status"] == "READY_TO_PRODUCE"
    assert len(reserve_lines(db_session, order.id)) == 3
    assert balances(db_session, frame)["BOLT-M8"] == (Decimal(1000), Decimal(840))


def test_d22_plan_and_check_materials_require_an_idempotency_key(
    db_client: TestClient, pm: dict[str, str], frame: Scenario, order_factory
) -> None:
    order = order_factory(frame.product)
    for action in ("plan", "check-materials"):
        response = db_client.post(f"{ORDERS}/{order.id}/{action}", headers=pm)
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# --- check-materials (D-09) -----------------------------------------------------------------


def test_d09_receipt_alone_never_changes_the_order_until_check_materials(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    login_as,
    frame: Scenario,
    order_factory,
) -> None:
    b6_stock(db_session, frame)
    order = order_factory(frame.product, planned_quantity=100)
    act(db_client, pm, order.id, "plan", "plan-key-0001")
    warehouse = login_as(Role.WAREHOUSE)
    db_client.post(
        "/api/v1/inventory/receipts",
        json={"material_id": frame.materials["BOLT-M8"].id, "quantity": "340"},
        headers={**warehouse, "Idempotency-Key": "receipt-key-0001"},
    )
    db_session.expire_all()
    assert db_session.get(ProductionOrder, order.id).status == "MATERIAL_SHORTAGE"  # type: ignore[union-attr]

    response = act(db_client, warehouse, order.id, "check-materials", "check-key-0001")
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["reserved"]) == ("READY_TO_PRODUCE", True)
    assert balances(db_session, frame)["BOLT-M8"] == (Decimal(940), Decimal(940))
    assert len(reserve_lines(db_session, order.id)) == 3
    [audit] = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "ORDER_MATERIALS_CHECKED")
    )
    assert (audit.old_value, audit.new_value) == (
        {"status": "MATERIAL_SHORTAGE"},
        {"status": "READY_TO_PRODUCE"},
    )


def test_d09_check_materials_still_short_stays_in_shortage(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Scenario,
    order_factory,
) -> None:
    b6_stock(db_session, frame)
    order = order_factory(frame.product, planned_quantity=100)
    act(db_client, pm, order.id, "plan", "plan-key-0001")
    response = act(db_client, pm, order.id, "check-materials", "check-key-0001")
    assert (response.status_code, response.json()["status"]) == (200, "MATERIAL_SHORTAGE")
    assert reserve_lines(db_session, order.id) == []


def test_d04_check_materials_uses_the_snapshot_not_the_current_bom(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Scenario,
    order_factory,
    bom_factory,
) -> None:
    b6_stock(db_session, frame)
    order = order_factory(frame.product, planned_quantity=100)
    act(db_client, pm, order.id, "plan", "plan-key-0001")
    # The BOM changes after planning: version 2 needs only 1 bolt per frame.
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        db_session.execute(
            text("UPDATE bom_headers SET status = 'RETIRED' WHERE id = :id"), {"id": frame.bom.id}
        )
    bom_factory(frame.product, [(frame.materials["BOLT-M8"], "1", "0")], version=2, status="ACTIVE")
    response = act(db_client, pm, order.id, "check-materials", "check-key-0001")
    bolt = next(c for c in response.json()["material_check"] if c["material_code"] == "BOLT-M8")
    assert (bolt["required"], bolt["shortage"]) == ("840", "340")


# --- Preconditions -------------------------------------------------------------------------


def test_br_po_01_plan_from_other_statuses_is_409(
    db_client: TestClient, pm: dict[str, str], frame: Scenario, order_factory
) -> None:
    for n, status in enumerate(["MATERIAL_SHORTAGE", "IN_PROGRESS", "COMPLETED", "CANCELLED"]):
        order = order_factory(frame.product, status=status)
        response = act(db_client, pm, order.id, "plan", f"plan-key-{n:04d}")
        assert (response.status_code, response.json()["error"]["code"]) == (
            409,
            "INVALID_STATE_TRANSITION",
        )


@pytest.mark.parametrize(
    ("retire", "code"),
    [("bom_headers", "NO_ACTIVE_BOM"), ("routings", "NO_ACTIVE_ROUTING")],
)
def test_b7_plan_needs_an_active_bom_and_routing(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Scenario,
    order_factory,
    retire: str,
    code: str,
) -> None:
    order = order_factory(frame.product)
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        db_session.execute(
            text(f"UPDATE {retire} SET status = 'RETIRED' WHERE product_id = :id"),  # noqa: S608
            {"id": frame.product.id},
        )
    response = act(db_client, pm, order.id, "plan", "plan-key-0001")
    assert (response.status_code, response.json()["error"]["code"]) == (409, code)
    db_session.expire_all()
    assert db_session.get(ProductionOrder, order.id).status == "DRAFT"  # type: ignore[union-attr]


# --- Test 23: a failure after reserving leaves no trace ------------------------------------


def test_b12_failure_after_reservation_rolls_everything_back(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Scenario,
    order_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ample_stock(db_session, frame)
    order = order_factory(frame.product, planned_quantity=100)
    audit_rows_before = db_session.scalar(select(func.count()).select_from(AuditLog))
    original = AuditService.record

    def failing_record(self: AuditService, **kwargs: Any) -> Any:
        if kwargs["action"] == "ORDER_PLANNED":  # runs after lines, operations, reservations
            raise RuntimeError("injected failure after the reservation step")
        return original(self, **kwargs)

    monkeypatch.setattr(AuditService, "record", failing_record)
    response = act(db_client, pm, order.id, "plan", "plan-key-0001")
    assert response.status_code == 500

    db_session.expire_all()
    stored = db_session.get(ProductionOrder, order.id)
    assert stored is not None
    assert (stored.status, stored.bom_header_id, stored.routing_id) == ("DRAFT", None, None)
    assert order_lines(db_session, order.id) == {}
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ProductionOperation)
            .where(ProductionOperation.production_order_id == order.id)
        )
        == 0
    )
    assert reserve_lines(db_session, order.id) == []
    assert all(reserved == 0 for _, reserved in balances(db_session, frame).values())
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == audit_rows_before
    assert db_session.scalar(text("SELECT COUNT(*) FROM idempotency_keys")) == 0
