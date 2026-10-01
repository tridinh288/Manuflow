"""Phase 9 assistant (BR-AI-01..04) on the seeded demo shop, with a scripted model."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant import tools as tool_module
from app.assistant.tools import TOOLS, ToolContext
from app.core.clock import FixedClock
from app.core.config import Settings
from app.models.audit_log import AuditLog
from app.models.idempotency_key import IdempotencyKey
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory
from app.models.production import ProductionOrder, ProductionOrderMaterial
from app.models.user import User
from app.services.auth_service import AuthenticatedUser
from tests.assistant_fakes import ScriptedChatModel, say, use_tool
from tests.integration.conftest import PASSWORD

READ_ONLY_TOOLS = {
    "calculate_material_requirements",
    "check_material_availability",
    "get_production_order_status",
    "get_order_risks",
    "get_bottlenecks",
    "get_low_stock_materials",
}


def headers(client: TestClient, username: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def ask(
    app: FastAPI, client: TestClient, username: str, model: ScriptedChatModel, question: str = "?"
) -> dict[str, Any]:
    app.state.chat_model = model
    response = client.post(
        "/api/v1/assistant/ask", json={"question": question}, headers=headers(client, username)
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def counts(session: Session) -> dict[str, Any]:
    session.expire_all()
    tables = (
        ProductionOrder,
        ProductionOrderMaterial,
        Inventory,
        InventoryTransaction,
        AuditLog,
        IdempotencyKey,
    )
    snapshot: dict[str, Any] = {
        t.__name__: session.scalar(select(func.count()).select_from(t)) for t in tables
    }
    snapshot["balances"] = sorted(
        (r.material_id, r.on_hand_quantity, r.reserved_quantity)
        for r in session.scalars(select(Inventory))
    )
    snapshot["statuses"] = sorted(session.scalars(select(ProductionOrder.status)))
    session.commit()  # end the read; services open their own transactions
    return snapshot


# --- BR-AI-01 / BR-AI-04: six read-only tools, and running them changes nothing ----------


def test_br_ai_01_and_br_ai_04_tools_are_read_only(
    db_session: Session,
    seeded: dict[str, int],
    clock: FixedClock,
    settings: Settings,
) -> None:
    assert set(TOOLS) == READ_ONLY_TOOLS
    admin = db_session.scalars(select(User).where(User.username == "demo.admin")).one()
    user = AuthenticatedUser(
        admin.id, admin.username, admin.full_name, admin.role, admin.work_center_id
    )
    context = ToolContext(db_session, clock, settings, user)
    arguments = {
        "calculate_material_requirements": {"product_code": "FRAME-A", "quantity": 150},
        "check_material_availability": {"product_code": "FRAME-A", "quantity": 400},
        "get_production_order_status": {"order_number": "PO-2026-00007"},
    }
    before = counts(db_session)
    for name, tool in TOOLS.items():
        tool.call(context, arguments.get(name, {}))
    assert counts(db_session) == before


# --- BR-AI-02: same data and same refusals as the REST API ------------------------------


def test_br_ai_02_tool_results_are_what_the_api_returns(
    app: FastAPI,
    db_client: TestClient,
    seeded: dict[str, int],
) -> None:
    model = ScriptedChatModel(use_tool("get_order_risks"), say("Có 2 lệnh có rủi ro."))
    body = ask(app, db_client, "demo.manager", model, "Lệnh nào đang trễ?")
    api = db_client.get("/api/v1/dashboard/risks", headers=headers(db_client, "demo.manager"))
    assert body["tool_calls"][0]["result"]["orders"] == api.json()["items"]
    assert body["answer"] == "Có 2 lệnh có rủi ro." and body["grounded"] is True


def test_br_ai_02_worker_gets_the_api_refusals(
    app: FastAPI,
    db_client: TestClient,
    seeded: dict[str, int],
) -> None:
    worker = headers(db_client, "demo.weld")
    api_403 = db_client.get("/api/v1/dashboard/risks", headers=worker).json()["error"]
    model = ScriptedChatModel(use_tool("get_order_risks"), say("Bạn không có quyền xem rủi ro."))
    run = ask(app, db_client, "demo.weld", model)["tool_calls"][0]
    assert run["ok"] is False
    assert run["result"]["error"] == {"code": api_403["code"], "message": api_403["message"]}

    # BR-AUTH-03: an order with no CNC step is invisible to the CNC operator, as a 404.
    order = seeded["at_risk"]
    api_404 = db_client.get(
        f"/api/v1/production-orders/{order}", headers=headers(db_client, "demo.cnc")
    ).json()["error"]
    model = ScriptedChatModel(
        use_tool("get_production_order_status", order_number="PO-2026-00004"), say("Không thấy.")
    )
    run = ask(app, db_client, "demo.cnc", model)["tool_calls"][0]
    assert run["result"]["error"]["code"] == api_404["code"] == "ORDER_NOT_FOUND"


# --- BR-AI-03: the model sees validated results only; numbers must come from them ---------


def test_br_ai_03_availability_matches_the_order_check_and_answers_are_checked(
    app: FastAPI,
    db_client: TestClient,
    seeded: dict[str, int],
) -> None:
    model = ScriptedChatModel(
        use_tool("check_material_availability", product_code="FRAME-A", quantity=400),
        say("Chưa đủ: thiếu 152.000 kg STEEL-001, nên khoảng 5 ngày nữa mới làm được."),
    )
    body = ask(app, db_client, "demo.manager", model, "Làm 400 FRAME-A được không?")
    result = body["tool_calls"][0]["result"]
    assert result["can_reserve_all"] is False
    lines = db_client.get(
        f"/api/v1/production-orders/{seeded['shortage']}/materials",
        headers=headers(db_client, "demo.manager"),
    ).json()["items"]
    # The what-if equals the shortage stored on PO 7 (same 400 FRAME-A, same stock).
    assert {i["material_code"]: i["shortage"] for i in result["items"]} == {
        line["material_code"]: line["shortage_quantity"] for line in lines
    }
    # "5 ngày" was invented by the model: flagged, never silently passed on.
    assert body["ungrounded_numbers"] == ["5"] and body["grounded"] is False

    shown = repr(model.calls)
    for secret in ("password", "Bearer", "access_token", "SELECT ", "INSERT ", PASSWORD):
        assert secret not in shown


def test_br_ai_03_tool_failures_reach_the_model_as_codes_only(
    app: FastAPI,
    db_client: TestClient,
    seeded: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("SELECT password_hash FROM users")

    monkeypatch.setitem(
        TOOLS,
        "get_bottlenecks",
        tool_module.Tool(
            "get_bottlenecks",
            "x",
            tool_module.NoArgs,
            (),
            broken,  # type: ignore[arg-type]
        ),
    )
    model = ScriptedChatModel(
        use_tool("get_bottlenecks"),
        use_tool("calculate_material_requirements", "t2", product_code="FRAME-A", quantity=-1),
        use_tool("no_such_tool", "t3"),
        say("Không tra được."),
    )
    runs = ask(app, db_client, "demo.manager", model)["tool_calls"]
    assert [r["result"]["error"]["code"] for r in runs] == [
        "TOOL_FAILED",
        "INVALID_ARGUMENTS",
        "UNKNOWN_TOOL",
    ]
    assert "SELECT" not in repr(model.calls) and "password" not in repr(model.calls)


# --- Configuration ------------------------------------------------------------------------


def test_assistant_is_off_without_a_key_and_stops_after_max_steps(
    app: FastAPI,
    db_client: TestClient,
    seeded: dict[str, int],
    settings: Settings,
) -> None:
    manager = headers(db_client, "demo.manager")
    app.state.chat_model = None
    status = db_client.get("/api/v1/assistant/status", headers=manager).json()
    assert status["enabled"] is False and set(status["tools"]) == READ_ONLY_TOOLS
    off = db_client.post("/api/v1/assistant/ask", json={"question": "?"}, headers=manager)
    assert (off.status_code, off.json()["error"]["code"]) == (503, "ASSISTANT_DISABLED")

    looping = ScriptedChatModel(*[use_tool("get_bottlenecks", f"t{i}") for i in range(20)])
    body = ask(app, db_client, "demo.manager", looping)
    assert len(body["tool_calls"]) == settings.assistant_max_steps
    assert body["answer"]


def test_an_empty_final_turn_gets_one_nudge_and_counts_as_a_step(
    app: FastAPI, db_client: TestClient, seeded: dict[str, int]
) -> None:
    model = ScriptedChatModel(
        say(""), say("Hãy dùng trang Tồn kho (POST /api/v1/inventory/receipts).")
    )
    body = ask(app, db_client, "demo.warehouse", model, "Nhập thêm 200 kg thép giúp tôi.")
    assert body["answer"].startswith("Hãy dùng trang Tồn kho")
    nudge = model.calls[1]["messages"][-1]
    assert nudge["role"] == "user" and "trả lời" in nudge["content"]


def test_a_model_that_fails_or_times_out_is_a_503_not_a_500(
    app: FastAPI, db_client: TestClient, seeded: dict[str, int]
) -> None:
    def timeout(_: object) -> Any:
        raise TimeoutError("read timed out after 120 s")

    app.state.chat_model = ScriptedChatModel(timeout)
    response = db_client.post(
        "/api/v1/assistant/ask", json={"question": "?"}, headers=headers(db_client, "demo.manager")
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ASSISTANT_UNAVAILABLE"
    assert "timed out" not in response.text  # no internals


def test_tools_without_parameters_ignore_stray_arguments(
    app: FastAPI, db_client: TestClient, seeded: dict[str, int]
) -> None:
    model = ScriptedChatModel(
        use_tool("get_low_stock_materials", material_code="STEEL-001"), say("Xong.")
    )
    run = ask(app, db_client, "demo.warehouse", model)["tool_calls"][0]
    assert run["ok"] is True
    assert {m["material_code"] for m in run["result"]["materials"]} == {"STEEL-001", "BOLT-M8"}
