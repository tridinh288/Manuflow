from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.services.assistant_service import AssistantAnswer


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]


class ToolRunResponse(BaseModel):
    name: str
    arguments: dict[str, Any]
    ok: bool
    result: dict[str, Any]


class AskResponse(BaseModel):
    answer: str
    tool_calls: list[ToolRunResponse]
    # BR-AI-03: numbers in the answer that no tool returned; empty when grounded.
    ungrounded_numbers: list[str]
    grounded: bool

    @classmethod
    def of(cls, answer: AssistantAnswer) -> "AskResponse":
        return cls(
            answer=answer.answer,
            tool_calls=[
                ToolRunResponse(name=r.name, arguments=r.arguments, ok=r.ok, result=r.result)
                for r in answer.tool_runs
            ],
            ungrounded_numbers=answer.ungrounded_numbers,
            grounded=not answer.ungrounded_numbers,
        )


class AssistantStatusResponse(BaseModel):
    enabled: bool
    provider: str
    model: str | None
    tools: list[str]
