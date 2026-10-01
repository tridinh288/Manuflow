"""Scripted stand-ins for the LLM (Phase 9 tests never call a real model)."""

from collections.abc import Callable
from typing import Any

from app.assistant.model import Reply, ToolCall

Script = Callable[[list[dict[str, Any]]], Reply]


class ScriptedChatModel:
    """Plays back one reply per call; records what the model was shown."""

    def __init__(self, *replies: Reply | Script) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Reply:
        self.calls.append(
            {"system": system, "messages": [dict(m) for m in messages], "tools": tools}
        )
        reply = self._replies.pop(0) if self._replies else Reply(text="Xong.")
        return reply(messages) if callable(reply) else reply


def use_tool(name: str, call_id: str = "t1", **arguments: Any) -> Reply:
    return Reply(
        text="",
        tool_calls=[ToolCall(call_id, name, arguments)],
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": arguments}],
    )


def say(text: str) -> Reply:
    return Reply(text=text, content=[{"type": "text", "text": text}])
