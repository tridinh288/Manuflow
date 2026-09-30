"""BR-RT-01..03, D-03, C-07 and BR-MD-04 for versioned routings."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.master_data import Product
from app.models.work_center import WorkCenter


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


@pytest.fixture
def frame(product_factory) -> Product:
    product: Product = product_factory("FRAME-A")
    return product


@pytest.fixture
def stations(work_center_factory) -> dict[str, WorkCenter]:
    """The five work centers of the sample routing for FRAME-A (B5)."""
    return {
        code: work_center_factory(code)
        for code in ("WC-CUT", "WC-CNC", "WC-WELD", "WC-PAINT", "WC-QC")
    }


def frame_a_steps(stations: dict[str, WorkCenter]) -> list[dict[str, Any]]:
    """10 CUTTING -> 20 CNC -> 30 WELDING -> 40 PAINTING -> 50 QC."""
    plan = [
        (10, "CUTTING", "WC-CUT"),
        (20, "CNC", "WC-CNC"),
        (30, "WELDING", "WC-WELD"),
        (40, "PAINTING", "WC-PAINT"),
        (50, "QC", "WC-QC"),
    ]
    return [
        {"sequence": seq, "operation_type": op, "work_center_id": stations[code].id}
        for seq, op, code in plan
    ]


def new_draft(client: TestClient, product: Product, headers: dict[str, str]) -> int:
    response = client.post(f"/api/v1/products/{product.id}/routings", headers=headers)
    assert response.status_code == 201, response.text
    routing_id: int = response.json()["id"]
    return routing_id


def put_steps(
    client: TestClient, routing_id: int, steps: list[dict[str, Any]], headers: dict[str, str]
) -> Any:
    return client.put(
        f"/api/v1/routings/{routing_id}/steps", json={"steps": steps}, headers=headers
    )


def activate(client: TestClient, routing_id: int, headers: dict[str, str]) -> Any:
    return client.post(f"/api/v1/routings/{routing_id}/activate", headers=headers)


def ready_draft(
    client: TestClient, product: Product, stations: dict[str, WorkCenter], headers: dict[str, str]
) -> int:
    routing_id = new_draft(client, product, headers)
    assert put_steps(client, routing_id, frame_a_steps(stations), headers).status_code == 200
    return routing_id


def error(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# --- Sample routing and lifecycle ------------------------------------------------------


def test_br_rt_03_sample_routing_for_frame_a_is_activated(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    stations: dict[str, WorkCenter],
) -> None:
    routing_id = ready_draft(db_client, frame, stations, pm)
    body = activate(db_client, routing_id, pm).json()
    assert body["status"] == "ACTIVE"
    assert [(s["sequence"], s["operation_type"], s["work_center_code"]) for s in body["steps"]] == [
        (10, "CUTTING", "WC-CUT"),
        (20, "CNC", "WC-CNC"),
        (30, "WELDING", "WC-WELD"),
        (40, "PAINTING", "WC-PAINT"),
        (50, "QC", "WC-QC"),
    ]
    [row] = db_session.scalars(select(AuditLog).where(AuditLog.action == "ROUTING_ACTIVATED"))
    assert row.new_value == {"product_id": frame.id, "version": 1, "retired_version": None}


def test_d03_activating_a_new_routing_retires_the_old_one(
    db_client: TestClient, pm: dict[str, str], frame: Product, stations: dict[str, WorkCenter]
) -> None:
    first = ready_draft(db_client, frame, stations, pm)
    activate(db_client, first, pm)
    second = ready_draft(db_client, frame, stations, pm)
    assert activate(db_client, second, pm).status_code == 200
    listed = db_client.get(f"/api/v1/products/{frame.id}/routings", headers=pm).json()
    assert {v["version"]: v["status"] for v in listed["items"]} == {1: "RETIRED", 2: "ACTIVE"}
    assert error(put_steps(db_client, first, frame_a_steps(stations), pm)) == (
        409,
        "VERSION_NOT_EDITABLE",
    )
    assert error(activate(db_client, first, pm)) == (409, "VERSION_NOT_EDITABLE")


# --- BR-RT-01: at least one step, unique sequence ----------------------------------------


def test_br_rt_01_routing_without_steps_cannot_be_activated(
    db_client: TestClient, pm: dict[str, str], frame: Product
) -> None:
    assert error(activate(db_client, new_draft(db_client, frame, pm), pm)) == (409, "ROUTING_EMPTY")


def test_br_rt_01_sequence_must_be_unique_within_a_version(
    db_client: TestClient, pm: dict[str, str], frame: Product, stations: dict[str, WorkCenter]
) -> None:
    routing_id = new_draft(db_client, frame, pm)
    qc = stations["WC-QC"].id
    response = put_steps(
        db_client,
        routing_id,
        [
            {"sequence": 10, "operation_type": "CUTTING", "work_center_id": qc},
            {"sequence": 10, "operation_type": "QC", "work_center_id": qc},
        ],
        pm,
    )
    assert error(response) == (422, "DUPLICATE_SEQUENCE")
    assert response.json()["error"]["details"] == [{"sequence": 10}]


@pytest.mark.parametrize("sequence", [0, -10, 10000])
def test_br_rt_01_sequence_out_of_range_is_422(
    db_client: TestClient,
    pm: dict[str, str],
    frame: Product,
    stations: dict[str, WorkCenter],
    sequence: int,
) -> None:
    routing_id = new_draft(db_client, frame, pm)
    step = {"sequence": sequence, "operation_type": "QC", "work_center_id": stations["WC-QC"].id}
    assert put_steps(db_client, routing_id, [step], pm).status_code == 422


# --- BR-RT-02: operation type and active work center ------------------------------------


def test_br_rt_02_unknown_operation_type_is_422(
    db_client: TestClient, pm: dict[str, str], frame: Product, stations: dict[str, WorkCenter]
) -> None:
    routing_id = new_draft(db_client, frame, pm)
    step = {"sequence": 10, "operation_type": "POLISHING", "work_center_id": stations["WC-QC"].id}
    assert error(put_steps(db_client, routing_id, [step], pm)) == (422, "VALIDATION_ERROR")


def test_br_rt_02_unknown_or_inactive_work_center_is_rejected(
    db_client: TestClient, pm: dict[str, str], frame: Product, work_center_factory
) -> None:
    routing_id = new_draft(db_client, frame, pm)
    unknown = {"sequence": 10, "operation_type": "QC", "work_center_id": 999999}
    assert error(put_steps(db_client, routing_id, [unknown], pm)) == (422, "WORK_CENTER_NOT_FOUND")

    closed = work_center_factory("WC-OLD")
    db_client.delete(f"/api/v1/work-centers/{closed.id}", headers=pm)
    step = {"sequence": 10, "operation_type": "QC", "work_center_id": closed.id}
    response = put_steps(db_client, routing_id, [step], pm)
    assert error(response) == (409, "WORK_CENTER_INACTIVE")
    assert response.json()["error"]["details"] == [{"work_center_code": "WC-OLD"}]


def test_br_rt_02_work_center_deactivated_after_drafting_blocks_activation(
    db_client: TestClient, pm: dict[str, str], frame: Product, stations: dict[str, WorkCenter]
) -> None:
    routing_id = ready_draft(db_client, frame, stations, pm)
    db_client.delete(f"/api/v1/work-centers/{stations['WC-PAINT'].id}", headers=pm)
    response = activate(db_client, routing_id, pm)
    assert error(response) == (409, "WORK_CENTER_INACTIVE")
    assert response.json()["error"]["details"] == [{"work_center_code": "WC-PAINT"}]


# --- BR-RT-03: the last step is QC -------------------------------------------------------


def test_br_rt_03_routing_not_ending_with_qc_cannot_be_activated(
    db_client: TestClient, pm: dict[str, str], frame: Product, stations: dict[str, WorkCenter]
) -> None:
    routing_id = new_draft(db_client, frame, pm)
    steps = frame_a_steps(stations)
    steps[-1]["sequence"] = 5  # QC is no longer the last step; PAINTING (40) is
    put_steps(db_client, routing_id, steps, pm)
    response = activate(db_client, routing_id, pm)
    assert error(response) == (409, "ROUTING_MUST_END_WITH_QC")
    assert response.json()["error"]["details"] == [{"sequence": 40, "operation_type": "PAINTING"}]


# --- BR-MD-04 and C-07 --------------------------------------------------------------------


def test_br_md_04_inactive_product_gets_no_new_routing(
    db_client: TestClient, pm: dict[str, str], product_factory
) -> None:
    retired = product_factory("OLD-FRAME", active=False)
    response = db_client.post(f"/api/v1/products/{retired.id}/routings", headers=pm)
    assert error(response) == (409, "PRODUCT_INACTIVE")


def test_c07_work_center_in_active_routing_cannot_be_deactivated(
    db_client: TestClient, pm: dict[str, str], frame: Product, stations: dict[str, WorkCenter]
) -> None:
    activate(db_client, ready_draft(db_client, frame, stations, pm), pm)
    response = db_client.delete(f"/api/v1/work-centers/{stations['WC-WELD'].id}", headers=pm)
    assert error(response) == (409, "WORK_CENTER_IN_USE")
    assert response.json()["error"]["details"] == [
        {"reason": "ACTIVE_ROUTING", "product_code": "FRAME-A", "routing_version": 1}
    ]


def test_c07_work_center_only_in_a_draft_can_be_deactivated(
    db_client: TestClient, pm: dict[str, str], frame: Product, stations: dict[str, WorkCenter]
) -> None:
    ready_draft(db_client, frame, stations, pm)
    response = db_client.delete(f"/api/v1/work-centers/{stations['WC-WELD'].id}", headers=pm)
    assert response.status_code == 204
