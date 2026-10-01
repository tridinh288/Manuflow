"""BR-AI-05: run the 20 evaluation questions against the real model before a demo.

    # on a freshly seeded database, with ASSISTANT_API_KEY set
    docker compose exec -T api python -m app.assistant.evaluate > docs/assistant-eval.md

Each question passes when the assistant called the expected tools, its answer contains
every expected fact (and, for refusals, a tool returned the expected error code). The
expected facts themselves are checked against the seeded data by
``tests/integration/test_assistant_eval.py``, without any model.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.assistant.model import AnthropicChatModel
from app.core.clock import SystemClock
from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory
from app.models.user import User
from app.services.assistant_service import AssistantAnswer, AssistantService
from app.services.auth_service import AuthenticatedUser

QUESTIONS_FILE = Path(__file__).with_name("eval_questions.json")


def load_questions() -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    return questions


@dataclass(frozen=True)
class Score:
    tools_ok: bool
    facts_ok: bool
    error_ok: bool
    grounded: bool

    @property
    def passed(self) -> bool:
        return self.tools_ok and self.facts_ok and self.error_ok


def score(item: dict[str, Any], answer: AssistantAnswer) -> Score:
    called = {run.name for run in answer.tool_runs}
    text = answer.answer.lower()
    expected_error = item.get("expect_error")
    errors = {run.result["error"]["code"] for run in answer.tool_runs if not run.ok}
    return Score(
        tools_ok=set(item["tools"]) <= called,
        facts_ok=all(fact.lower() in text for fact in item["facts"]),
        error_ok=expected_error is None or expected_error in errors,
        grounded=not answer.ungrounded_numbers,
    )


def main() -> int:
    settings = get_settings()
    if settings.assistant_api_key is None:
        print("ASSISTANT_API_KEY is not set: nothing to evaluate", file=sys.stderr)
        return 1
    model = AnthropicChatModel(
        settings.assistant_api_key.get_secret_value(), settings.assistant_model
    )
    factory = build_session_factory(build_engine(settings.database_url.get_secret_value()))
    rows = []
    passed = 0
    for item in load_questions():
        with factory() as session:
            found = session.scalars(select(User).where(User.username == item["user"])).one()
            session.commit()
            user = AuthenticatedUser(
                found.id, found.username, found.full_name, found.role, found.work_center_id
            )
            service = AssistantService(session, SystemClock(), settings, model)
            answer = service.ask(item["question"], user)
        result = score(item, answer)
        passed += result.passed
        tools = ", ".join(
            f"{r.name}{'' if r.ok else ' ✗' + r.result['error']['code']}" for r in answer.tool_runs
        )
        mark = {True: "✓", False: "✗"}
        grounded = "✓" if result.grounded else "✗ " + ", ".join(answer.ungrounded_numbers)
        text = answer.answer.replace("|", "/").replace("\n", " ")
        rows.append(
            f"| {item['id']} | {item['user']} | {item['question']} | {tools or '—'} | "
            f"{mark[result.tools_ok]} | {mark[result.facts_ok and result.error_ok]} | "
            f"{grounded} | {text} |"
        )
    print(
        f"# Assistant evaluation (BR-AI-05)\n\nModel: `{settings.assistant_model}`. "
        f"Passed **{passed}/{len(rows)}**.\n"
    )
    print("| # | User | Question | Tools called | Tools | Facts | Grounded | Answer |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    print("\n".join(rows))
    return 0 if passed == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
