"""BR-AI-05: the evaluation set is sound before any model is asked.

Every expected fact must really be in what the expected tool returns for that user on
the seeded demo shop, and every expected refusal must be the error the tool gives.
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.evaluate import load_questions, score
from app.assistant.tools import TOOLS, ToolContext
from app.core.clock import FixedClock
from app.core.config import Settings
from app.domain.errors import DomainError
from app.models.user import User
from app.services.assistant_service import AssistantAnswer, ToolRun
from app.services.auth_service import AuthenticatedUser


def test_br_ai_05_twenty_questions_with_known_tools() -> None:
    questions = load_questions()
    assert [q["id"] for q in questions] == list(range(1, 21))
    for q in questions:
        assert set(q["tools"]) <= set(TOOLS), q["id"]
        assert q["facts"] or q.get("expect_error"), q["id"]


def test_br_ai_05_expected_facts_are_true_on_the_seed(
    db_client: TestClient,
    db_session: Session,
    seeded: dict[str, int],
    clock: FixedClock,
    settings: Settings,
) -> None:
    checked = 0
    for item in load_questions():
        if "check" not in item:
            continue
        row = db_session.scalars(select(User).where(User.username == item["user"])).one()
        db_session.commit()
        user = AuthenticatedUser(row.id, row.username, row.full_name, row.role, row.work_center_id)
        context = ToolContext(db_session, clock, settings, user)
        tool = TOOLS[item["check"]["tool"]]
        try:
            text = json.dumps(
                tool.call(context, item["check"]["arguments"]).model_dump(mode="json")
            )
            error = None
        except DomainError as exc:
            text, error = "", exc.code
        assert error == item.get("expect_error"), item["id"]
        for fact in item["facts"]:
            assert fact in text, (item["id"], fact)
        checked += 1
    assert checked == 18


def test_br_ai_05_scoring() -> None:
    item = {"tools": ["get_order_risks"], "facts": ["PO-2026-00003"], "expect_error": None}
    run = ToolRun("get_order_risks", {}, True, {"orders": []})
    good = AssistantAnswer("PO-2026-00003 đã quá hạn.", [run], [], 2)
    assert score(item, good).passed
    assert not score(item, AssistantAnswer("Không có lệnh trễ.", [run], [], 2)).passed
    assert not score(item, AssistantAnswer("PO-2026-00003 trễ.", [], [], 1)).passed

    refusal = {"tools": ["get_order_risks"], "facts": [], "expect_error": "FORBIDDEN"}
    denied = ToolRun("get_order_risks", {}, False, {"error": {"code": "FORBIDDEN", "message": ""}})
    assert score(refusal, AssistantAnswer("Bạn không có quyền.", [denied], [], 2)).passed
    assert not score(refusal, AssistantAnswer("Có 2 lệnh.", [run], [], 2)).passed
