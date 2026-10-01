"""Progress reports through the API: tests 16, 17 and 20 of B15, BR-OP-01..06, D-12, D-15."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.production import OperationProgressLog, ProductionOperation, ProductionOrder
from app.models.work_center import WorkCenter


class Line:
    """An IN_PROGRESS order of 100 with CUTTING -> WELDING -> QC at three work centers."""

    def __init__(
        self,
        client: TestClient,
        session: Session,
        order: ProductionOrder,
        operations: list[ProductionOperation],
        centers: list[WorkCenter],
    ) -> None:
        self.client, self.session, self.order = client, session, order
        self.cut, self.weld, self.qc = operations
        self.centers = centers
        self.n = 0

    def report(self, headers: dict[str, str], operation: ProductionOperation, **body: Any) -> Any:
        self.n += 1
        return self.client.post(
            f"/api/v1/production-operations/{operation.id}/progress",
            json=body,
            headers={**headers, "Idempotency-Key": f"progress-key-{self.n:04d}"},
        )

    def state(self) -> list[tuple[str, int, int]]:
        self.session.expire_all()
        rows = self.session.scalars(
            select(ProductionOperation)
            .where(ProductionOperation.production_order_id == self.order.id)
            .order_by(ProductionOperation.sequence)
        ).all()
        return [(row.status, row.good_quantity, row.rejected_quantity) for row in rows]

    def order_now(self) -> ProductionOrder:
        self.session.expire_all()
        order = self.session.get(ProductionOrder, self.order.id)
        assert order is not None
        return order


@pytest.fixture
def line(
    db_client: TestClient,
    db_session: Session,
    product_factory,
    order_factory,
    work_center_factory,
    operation_factory,
) -> Line:
    centers = [work_center_factory(code) for code in ("WC-CUT", "WC-WELD", "WC-QC")]
    order = order_factory(
        product_factory("FRAME-A"),
        status="IN_PROGRESS",
        planned_quantity=100,
        number="PO-2026-00001",
    )
    operations = [
        operation_factory(order, sequence, kind, center)
        for sequence, kind, center in zip(
            (10, 20, 30), ("CUTTING", "WELDING", "QC"), centers, strict=True
        )
    ]
    return Line(db_client, db_session, order, operations, centers)


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


@pytest.fixture
def welder(login_as, line: Line) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WORKER, work_center_id=line.centers[1].id)
    return headers


@pytest.fixture
def cutter(login_as, line: Line) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WORKER, work_center_id=line.centers[0].id)
    return headers


# --- Reports -----------------------------------------------------------------------------


def test_br_op_06_report_updates_totals_and_appends_a_log_line(
    line: Line, cutter: dict[str, str], clock: FixedClock
) -> None:
    response = line.report(cutter, line.cut, good_delta=40, rejected_delta=2)
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["good_quantity"], body["rejected_quantity"]) == (
        "IN_PROGRESS",
        40,
        2,
    )
    assert (body["processed_quantity"], body["limit"], body["order_status"]) == (
        42,
        100,
        "IN_PROGRESS",
    )
    [log] = line.session.scalars(select(OperationProgressLog)).all()
    assert (log.good_delta, log.rejected_delta, log.reason) == (40, 2, None)
    assert log.idem_key == "progress-key-0001" and log.reported_by is not None
    line.session.expire_all()
    cut = line.session.get(ProductionOperation, line.cut.id)
    assert cut is not None and cut.started_at == clock.now()  # BR-OP-04


def test_br_op_02_report_beyond_available_input_is_409_with_the_limit(
    line: Line, cutter: dict[str, str], welder: dict[str, str]
) -> None:
    """Test 16 of B15. Welding has received only the 30 good units cutting produced."""
    line.report(cutter, line.cut, good_delta=30)
    response = line.report(welder, line.weld, good_delta=25, rejected_delta=6)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "EXCEEDS_AVAILABLE_INPUT"
    assert error["details"] == [{"sequence": 20, "limit": 30, "processed": 0, "requested": 31}]
    assert line.state()[1] == ("PENDING", 0, 0)


def test_d14_overlapping_operations_follow_the_good_units(
    line: Line, cutter: dict[str, str], welder: dict[str, str]
) -> None:
    line.report(cutter, line.cut, good_delta=50)
    assert line.report(welder, line.weld, good_delta=48, rejected_delta=2).status_code == 200
    assert line.state()[:2] == [("IN_PROGRESS", 50, 0), ("IN_PROGRESS", 48, 2)]


# --- Completion (test 17, D-12) ----------------------------------------------------------


def test_d12_last_operation_completing_completes_the_order(
    line: Line, pm: dict[str, str], clock: FixedClock
) -> None:
    line.report(pm, line.cut, good_delta=100)
    line.report(pm, line.weld, good_delta=97, rejected_delta=3)
    response = line.report(pm, line.qc, good_delta=95, rejected_delta=2)
    assert (response.json()["order_status"], response.json()["completed_quantity"]) == (
        "COMPLETED",
        95,
    )
    assert line.state() == [("COMPLETED", 100, 0), ("COMPLETED", 97, 3), ("COMPLETED", 95, 2)]
    order = line.order_now()
    assert (order.status, order.completed_quantity, order.completed_at) == (
        "COMPLETED",
        95,
        clock.now(),
    )
    [audit] = line.session.scalars(select(AuditLog).where(AuditLog.action == "ORDER_COMPLETED"))
    assert (audit.old_value, audit.new_value) == (
        {"status": "IN_PROGRESS"},
        {"status": "COMPLETED", "completed_quantity": 95},
    )


def test_br_op_05_everything_rejected_upstream_completes_the_order_with_zero(
    line: Line, pm: dict[str, str]
) -> None:
    response = line.report(pm, line.cut, rejected_delta=100)
    assert (response.json()["order_status"], response.json()["completed_quantity"]) == (
        "COMPLETED",
        0,
    )
    assert line.state() == [("COMPLETED", 0, 100), ("COMPLETED", 0, 0), ("COMPLETED", 0, 0)]


def test_br_op_04_cascade_waits_for_the_predecessor(line: Line, pm: dict[str, str]) -> None:
    line.report(pm, line.cut, good_delta=60)
    line.report(pm, line.weld, good_delta=60)  # all it has received, but cutting is open
    assert line.state()[1] == ("IN_PROGRESS", 60, 0)
    line.report(pm, line.cut, good_delta=40)
    assert [s for s, _, _ in line.state()] == ["COMPLETED", "IN_PROGRESS", "PENDING"]


# --- Scope (test 20) and permissions -----------------------------------------------------


def test_br_auth_03_worker_reporting_at_another_work_center_gets_404(
    line: Line, welder: dict[str, str]
) -> None:
    """Test 20 of B15: the welder cannot see (let alone report) the cutting operation."""
    response = line.report(welder, line.cut, good_delta=1)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "OPERATION_NOT_FOUND")
    assert line.state()[0] == ("PENDING", 0, 0)


def test_unknown_operation_is_404(line: Line, pm: dict[str, str]) -> None:
    response = line.client.post(
        "/api/v1/production-operations/999999/progress",
        json={"good_delta": 1},
        headers={**pm, "Idempotency-Key": "progress-key-9999"},
    )
    assert response.json()["error"]["code"] == "OPERATION_NOT_FOUND"


@pytest.mark.parametrize("role", [Role.ADMIN, Role.WAREHOUSE])
def test_b4_admin_and_warehouse_cannot_report_production(line: Line, login_as, role: Role) -> None:
    assert line.report(login_as(role), line.cut, good_delta=1).status_code == 403


# --- Corrections (D-15, BR-OP-03, C-02) --------------------------------------------------


def test_d15_worker_cannot_correct(line: Line, cutter: dict[str, str]) -> None:
    line.report(cutter, line.cut, good_delta=10)
    response = line.report(cutter, line.cut, good_delta=-2, reason="Miscounted")
    assert (response.status_code, response.json()["error"]["code"]) == (403, "FORBIDDEN")


def test_d15_manager_corrects_with_a_reason_and_the_log_keeps_both_lines(
    line: Line, cutter: dict[str, str], pm: dict[str, str]
) -> None:
    line.report(cutter, line.cut, good_delta=10)
    missing = line.report(pm, line.cut, good_delta=-2)
    assert missing.json()["error"]["code"] == "REASON_REQUIRED"
    corrected = line.report(pm, line.cut, good_delta=-2, rejected_delta=2, reason="2 were scrap")
    assert (corrected.json()["good_quantity"], corrected.json()["rejected_quantity"]) == (8, 2)
    logs = line.session.scalars(
        select(OperationProgressLog).order_by(OperationProgressLog.id)
    ).all()
    assert [(log.good_delta, log.rejected_delta, log.reason) for log in logs] == [
        (10, 0, None),
        (-2, 2, "2 were scrap"),
    ]
    assert (
        line.session.scalars(
            select(AuditLog).where(AuditLog.action == "OPERATION_PROGRESS_CORRECTED")
        )
        .one()
        .reason
        == "2 were scrap"
    )


def test_br_op_03_correction_below_what_the_next_operation_used_is_409(
    line: Line, pm: dict[str, str]
) -> None:
    line.report(pm, line.cut, good_delta=50)
    line.report(pm, line.weld, good_delta=40)
    response = line.report(pm, line.cut, good_delta=-11, reason="Recount")
    assert response.json()["error"]["code"] == "CORRECTION_BELOW_DOWNSTREAM"


def test_c10_completed_operation_cannot_be_corrected(line: Line, pm: dict[str, str]) -> None:
    line.report(pm, line.cut, good_delta=100)
    response = line.report(pm, line.cut, good_delta=-1, reason="Recount")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "OPERATION_COMPLETED")


# --- Preconditions, validation, idempotency, append-only ---------------------------------


@pytest.mark.parametrize("status", ["READY_TO_PRODUCE", "COMPLETED", "CANCELLED"])
def test_br_op_01_only_an_in_progress_order_takes_reports(
    line: Line, pm: dict[str, str], status: str
) -> None:
    if line.session.in_transaction():
        line.session.commit()
    with line.session.begin():
        line.session.execute(
            text("UPDATE production_orders SET status = :s WHERE id = :id"),
            {"s": status, "id": line.order.id},
        )
    response = line.report(pm, line.cut, good_delta=1)
    error = response.json()["error"]
    assert (response.status_code, error["code"], error["details"][0]["current_status"]) == (
        409,
        "ORDER_NOT_IN_PROGRESS",
        status,
    )


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({}, "EMPTY_REPORT"),
        ({"good_delta": 0, "rejected_delta": 0}, "EMPTY_REPORT"),
        ({"good_delta": 1.5}, "VALIDATION_ERROR"),
        ({"good_delta": True}, "VALIDATION_ERROR"),
        ({"good_delta": "3"}, "VALIDATION_ERROR"),
        ({"good_delta": 1, "operation_id": 5}, "VALIDATION_ERROR"),
    ],
    ids=["empty", "zeros", "float", "bool", "string", "extra"],
)
def test_br_op_02_invalid_reports_are_422(
    line: Line, pm: dict[str, str], body: dict[str, Any], code: str
) -> None:
    response = line.report(pm, line.cut, **body)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)


def test_d22_retried_report_is_counted_once(line: Line, pm: dict[str, str]) -> None:
    headers = {**pm, "Idempotency-Key": "same-report-key"}
    url = f"/api/v1/production-operations/{line.cut.id}/progress"
    first = line.client.post(url, json={"good_delta": 10}, headers=headers)
    second = line.client.post(url, json={"good_delta": 10}, headers=headers)
    assert second.json() == first.json()
    assert line.state()[0] == ("IN_PROGRESS", 10, 0)
    missing = line.client.post(url, json={"good_delta": 10}, headers=pm)
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_br_op_06_progress_log_is_append_only(line: Line, pm: dict[str, str]) -> None:
    line.report(pm, line.cut, good_delta=10)
    for statement in (
        "UPDATE operation_progress_logs SET good_delta = 99",
        "DELETE FROM operation_progress_logs",
    ):
        with pytest.raises(DBAPIError, match="append-only"), line.session.begin():
            line.session.execute(text(statement))
