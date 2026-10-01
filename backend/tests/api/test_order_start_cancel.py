"""start and cancel: tests 14 and 15 of B15 (D-11, D-13), the rest of test 13 via the API."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material, Product
from app.models.production import ProductionOperation, ProductionOrder, ProductionOrderMaterial

ORDERS = "/api/v1/production-orders"


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


@pytest.fixture
def warehouse(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WAREHOUSE)
    return headers


class Flow:
    """A planned READY order of 10 frames: 20 kg steel and 80 bolts reserved."""

    def __init__(
        self,
        client: TestClient,
        session: Session,
        order: ProductionOrder,
        steel: Material,
        bolt: Material,
    ) -> None:
        self.client, self.session, self.order = client, session, order
        self.steel, self.bolt = steel, bolt
        self.n = 0

    def key(self) -> str:
        self.n += 1
        return f"flow-key-{self.n:04d}"

    def act(self, headers: dict[str, str], action: str, body: Any = None) -> Any:
        return self.client.post(
            f"{ORDERS}/{self.order.id}/{action}",
            json=body,
            headers={**headers, "Idempotency-Key": self.key()},
        )

    def line(self, material: Material) -> ProductionOrderMaterial:
        self.session.expire_all()
        return self.session.scalars(
            select(ProductionOrderMaterial).where(
                ProductionOrderMaterial.production_order_id == self.order.id,
                ProductionOrderMaterial.material_id == material.id,
            )
        ).one()

    def issue(self, headers: dict[str, str], material: Material, quantity: str) -> Any:
        return self.client.post(
            "/api/v1/inventory/issues",
            json={"order_material_id": self.line(material).id, "quantity": quantity},
            headers={**headers, "Idempotency-Key": self.key()},
        )

    def balance(self, material: Material) -> tuple[Decimal, Decimal]:
        self.session.expire_all()
        row = self.session.scalars(
            select(Inventory).where(Inventory.material_id == material.id)
        ).one()
        return row.on_hand_quantity, row.reserved_quantity

    def status(self) -> str:
        self.session.expire_all()
        order = self.session.get(ProductionOrder, self.order.id)
        assert order is not None
        return order.status


@pytest.fixture
def flow(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    warehouse: dict[str, str],
    product_factory,
    material_factory,
    work_center_factory,
    bom_factory,
    routing_factory,
    order_factory,
) -> Flow:
    product: Product = product_factory("FRAME-A")
    steel = material_factory("STEEL-001", unit="kg", decimal_places=3)
    bolt = material_factory("BOLT-M8", unit="pcs", decimal_places=0)
    bom_factory(product, [(steel, "2", "0"), (bolt, "8", "0")], status="ACTIVE")
    routing_factory(
        product,
        [(10, "WELDING", work_center_factory()), (20, "QC", work_center_factory())],
        status="ACTIVE",
    )
    order = order_factory(product, planned_quantity=10)
    flow = Flow(db_client, db_session, order, steel, bolt)
    for material, quantity in ((steel, "100"), (bolt, "500")):
        db_client.post(
            "/api/v1/inventory/receipts",
            json={"material_id": material.id, "quantity": quantity},
            headers={**warehouse, "Idempotency-Key": flow.key()},
        )
    assert flow.act(pm, "plan").json()["status"] == "READY_TO_PRODUCE"
    return flow


# --- start (test 14) ---------------------------------------------------------------------------


def test_d11_start_is_refused_until_every_line_is_issued_in_full(
    flow: Flow, pm: dict[str, str], warehouse: dict[str, str]
) -> None:
    flow.issue(warehouse, flow.steel, "20")
    flow.issue(warehouse, flow.bolt, "79")
    response = flow.act(pm, "start")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "MATERIALS_NOT_FULLY_ISSUED"
    assert error["details"] == [{"material_code": "BOLT-M8", "required": "80", "issued": "79"}]
    assert flow.status() == "READY_TO_PRODUCE"


def test_d11_start_after_full_issue_moves_to_in_progress(
    flow: Flow, pm: dict[str, str], warehouse: dict[str, str], clock: FixedClock
) -> None:
    flow.issue(warehouse, flow.steel, "20")
    flow.issue(warehouse, flow.bolt, "80")
    response = flow.act(pm, "start")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["allowed_actions"]) == ("IN_PROGRESS", [])
    assert body["started_at"] == clock.now().isoformat().replace("+00:00", "Z")
    [audit] = flow.session.scalars(select(AuditLog).where(AuditLog.action == "ORDER_STARTED"))
    assert (audit.old_value, audit.new_value) == (
        {"status": "READY_TO_PRODUCE"},
        {"status": "IN_PROGRESS"},
    )


# --- cancel (test 15) --------------------------------------------------------------------------


def test_d13_cancel_from_ready_releases_what_is_still_reserved(
    flow: Flow, pm: dict[str, str], warehouse: dict[str, str]
) -> None:
    flow.issue(warehouse, flow.bolt, "30")  # 50 bolts still reserved
    response = flow.act(pm, "cancel", {"reason": "Customer cancelled"})
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["cancel_reason"]) == (
        "CANCELLED",
        "Customer cancelled",
    )
    assert flow.balance(flow.steel) == (Decimal(100), Decimal(0))
    assert flow.balance(flow.bolt) == (Decimal(470), Decimal(0))
    bolt_line = flow.line(flow.bolt)
    assert (bolt_line.reserved_quantity, bolt_line.issued_quantity) == (Decimal(0), Decimal(30))

    releases = flow.session.scalars(
        select(InventoryTransaction)
        .where(
            InventoryTransaction.production_order_id == flow.order.id,
            InventoryTransaction.type == "RELEASE",
        )
        .order_by(InventoryTransaction.material_id)
    ).all()
    assert sorted((line.material_id, line.reserved_delta) for line in releases) == sorted(
        [(flow.steel.id, Decimal(-20)), (flow.bolt.id, Decimal(-50))]
    )
    assert all(line.reason == "Customer cancelled" for line in releases)
    operations = flow.session.scalars(
        select(ProductionOperation).where(ProductionOperation.production_order_id == flow.order.id)
    ).all()
    assert {op.status for op in operations} == {"CANCELLED"}
    [audit] = flow.session.scalars(select(AuditLog).where(AuditLog.action == "ORDER_CANCELLED"))
    assert audit.reason == "Customer cancelled"
    assert audit.new_value == {
        "status": "CANCELLED",
        "released": {"STEEL-001": "20.000", "BOLT-M8": "50"},
    }


def test_c05_issued_material_is_returned_after_cancel_and_the_ledger_reconciles(
    flow: Flow, pm: dict[str, str], warehouse: dict[str, str], login_as
) -> None:
    flow.issue(warehouse, flow.bolt, "30")
    flow.act(pm, "cancel", {"reason": "Customer cancelled"})
    returned = flow.client.post(
        "/api/v1/inventory/returns",
        json={"order_material_id": flow.line(flow.bolt).id, "quantity": "30"},
        headers={**warehouse, "Idempotency-Key": flow.key()},
    )
    assert returned.status_code == 201
    assert flow.balance(flow.bolt) == (Decimal(500), Decimal(0))
    report = flow.client.get(
        "/api/v1/admin/inventory-reconciliation", headers=login_as(Role.ADMIN)
    ).json()
    assert report["consistent"] is True


@pytest.mark.parametrize("status", ["DRAFT", "MATERIAL_SHORTAGE"])
def test_d13_cancel_without_reservations_releases_nothing(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    product_factory,
    order_factory,
    status: str,
) -> None:
    order = order_factory(product_factory(), status=status)
    response = db_client.post(
        f"{ORDERS}/{order.id}/cancel",
        json={"reason": "Not needed"},
        headers={**pm, "Idempotency-Key": "cancel-key-0001"},
    )
    assert (response.status_code, response.json()["status"]) == (200, "CANCELLED")
    assert (
        db_session.scalars(
            select(InventoryTransaction).where(InventoryTransaction.production_order_id == order.id)
        ).all()
        == []
    )


def test_d13_in_progress_order_cannot_be_cancelled(
    flow: Flow, pm: dict[str, str], warehouse: dict[str, str]
) -> None:
    flow.issue(warehouse, flow.steel, "20")
    flow.issue(warehouse, flow.bolt, "80")
    flow.act(pm, "start")
    response = flow.act(pm, "cancel", {"reason": "Too late"})
    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["details"][0]["current_status"]) == (
        "INVALID_STATE_TRANSITION",
        "IN_PROGRESS",
    )
    assert flow.status() == "IN_PROGRESS"


@pytest.mark.parametrize(
    ("body", "key", "code"),
    [
        ({}, True, "VALIDATION_ERROR"),
        ({"reason": "  "}, True, "VALIDATION_ERROR"),
        ({"reason": "Customer cancelled"}, False, "IDEMPOTENCY_KEY_REQUIRED"),
    ],
    ids=["no-reason", "blank-reason", "no-key"],
)
def test_d13_cancel_needs_a_reason_and_a_key(
    db_client: TestClient,
    pm: dict[str, str],
    product_factory,
    order_factory,
    body: dict[str, str],
    key: bool,
    code: str,
) -> None:
    order = order_factory(product_factory())
    headers = {**pm, "Idempotency-Key": "cancel-key-0002"} if key else pm
    response = db_client.post(f"{ORDERS}/{order.id}/cancel", json=body, headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)


# --- test 13 through the API: the remaining refused pairs ----------------------------------------


@pytest.mark.parametrize(
    ("status", "action"),
    [
        ("CANCELLED", "start"),
        ("COMPLETED", "start"),
        ("DRAFT", "start"),
        ("MATERIAL_SHORTAGE", "start"),
        ("IN_PROGRESS", "cancel"),
        ("COMPLETED", "cancel"),
        ("CANCELLED", "cancel"),
        ("CANCELLED", "check-materials"),
        ("COMPLETED", "plan"),
    ],
)
def test_br_po_01_refused_transitions_through_the_api(
    db_client: TestClient,
    pm: dict[str, str],
    product_factory,
    order_factory,
    status: str,
    action: str,
) -> None:
    order = order_factory(product_factory(), status=status)
    response = db_client.post(
        f"{ORDERS}/{order.id}/{action}",
        json={"reason": "Test"} if action == "cancel" else None,
        headers={**pm, "Idempotency-Key": "refused-key-0001"},
    )
    assert response.status_code == 409
    detail = response.json()["error"]["details"][0]
    assert (detail["current_status"], detail["action"]) == (status, action)


# --- BR-PO-04: every status change is audited with the old and new status -----------------------


def test_br_po_04_every_transition_of_an_order_is_audited(
    flow: Flow, pm: dict[str, str], warehouse: dict[str, str]
) -> None:
    flow.issue(warehouse, flow.steel, "20")
    flow.issue(warehouse, flow.bolt, "80")
    flow.act(pm, "start")
    rows = flow.session.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "production_order", AuditLog.entity_id == flow.order.id)
        .order_by(AuditLog.id)
    ).all()
    assert [
        (row.action, (row.old_value or {}).get("status"), (row.new_value or {}).get("status"))
        for row in rows
    ] == [
        ("ORDER_PLANNED", "DRAFT", "READY_TO_PRODUCE"),
        ("ORDER_STARTED", "READY_TO_PRODUCE", "IN_PROGRESS"),
    ]
