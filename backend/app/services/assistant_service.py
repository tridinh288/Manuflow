"""Phase 9 assistant (B17, BR-AI-01..04): answers questions by calling read-only tools.

The model only ever sees the system prompt, the question, and tool results, which are
the API's own validated response models for this caller. Tool failures reach it as an
error code and message, never as a stack trace or SQL. Nothing here writes.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.assistant.grounding import allowed_numbers, ungrounded_numbers
from app.assistant.model import ChatModel, Reply
from app.assistant.tools import TOOLS, Tool, ToolContext
from app.core.clock import Clock
from app.core.config import Settings
from app.domain.errors import DomainError, ServiceUnavailableError
from app.services.auth_service import AuthenticatedUser

logger = logging.getLogger(__name__)

# Reviewed like code: the rules the model must follow (BR-AI-03, BR-AI-04).
SYSTEM_PROMPT = (Path(__file__).parents[1] / "assistant" / "system_prompt.md").read_text(
    encoding="utf-8"
)


@dataclass(frozen=True)
class ToolRun:
    name: str
    arguments: dict[str, Any]
    ok: bool
    result: dict[str, Any]


@dataclass(frozen=True)
class AssistantAnswer:
    answer: str
    tool_runs: list[ToolRun]
    ungrounded_numbers: list[str]
    steps: int


class AssistantService:
    def __init__(
        self,
        session: Session,
        clock: Clock,
        settings: Settings,
        model: ChatModel | None,
        tools: dict[str, Tool] = TOOLS,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings
        self._model = model
        self._tools = tools

    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema()}
            for t in self._tools.values()
        ]

    def ask(self, question: str, user: AuthenticatedUser) -> AssistantAnswer:
        if self._model is None:
            raise ServiceUnavailableError(
                "ASSISTANT_DISABLED", "The assistant is not configured on this server."
            )
        context = ToolContext(self._session, self._clock, self._settings, user)
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        runs: list[ToolRun] = []
        specs = self.tool_specs()
        reply = Reply(text="")
        for step in range(1, self._settings.assistant_max_steps + 1):
            reply = self._model.complete(SYSTEM_PROMPT, messages, specs)
            if not reply.tool_calls:
                return self._answer(question, reply.text, runs, step)
            messages.append({"role": "assistant", "content": reply.content})
            results = []
            for call in reply.tool_calls:
                run = self._run(context, call.name, call.arguments)
                runs.append(run)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(run.result, ensure_ascii=False),
                        "is_error": not run.ok,
                    }
                )
            messages.append({"role": "user", "content": results})
        text = reply.text or "Câu hỏi cần quá nhiều bước tra cứu; hãy hỏi cụ thể hơn."
        return self._answer(question, text, runs, self._settings.assistant_max_steps)

    def _answer(self, question: str, text: str, runs: list[ToolRun], steps: int) -> AssistantAnswer:
        allowed = allowed_numbers(question, [run.result for run in runs if run.ok])
        return AssistantAnswer(text, runs, ungrounded_numbers(text, allowed), steps)

    def _run(self, context: ToolContext, name: str, arguments: dict[str, Any]) -> ToolRun:
        tool = self._tools.get(name)
        if tool is None:
            return _failed(name, arguments, "UNKNOWN_TOOL", f"There is no tool named {name}.")
        try:
            result = tool.call(context, arguments)
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, e["loc"])) for e in exc.errors())
            return _failed(name, arguments, "INVALID_ARGUMENTS", f"Invalid arguments: {fields}.")
        except DomainError as exc:
            return _failed(name, arguments, exc.code, exc.message)
        except Exception:
            logger.exception("Assistant tool %s failed", name)
            return _failed(name, arguments, "TOOL_FAILED", "The tool failed.")
        return ToolRun(name, arguments, True, result.model_dump(mode="json"))


def _failed(name: str, arguments: dict[str, Any], code: str, message: str) -> ToolRun:
    return ToolRun(name, arguments, False, {"error": {"code": code, "message": message}})
