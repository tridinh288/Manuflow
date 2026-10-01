"""The LLM behind the assistant, as a small protocol (B17: provider and model are config).

Messages use the Anthropic shape: ``{"role": "user" | "assistant", "content": [...]}``
with ``text``, ``tool_use`` and ``tool_result`` blocks. Tests use a scripted model.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, cast


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The assistant turn to send back verbatim on the next call.
    content: list[dict[str, Any]] = field(default_factory=list)


class ChatModel(Protocol):
    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Reply: ...


class AnthropicChatModel:
    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        import anthropic  # only needed when the assistant is switched on

        self._client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)
        self._model = model
        self._max_tokens = max_tokens

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Reply:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=cast(Any, messages),
            tools=cast(Any, tools),
        )
        texts: list[str] = []
        calls: list[ToolCall] = []
        content: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                arguments = dict(cast(dict[str, Any], block.input))
                calls.append(ToolCall(block.id, block.name, arguments))
                content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": arguments}
                )
        return Reply(text="\n".join(texts).strip(), tool_calls=calls, content=content)
