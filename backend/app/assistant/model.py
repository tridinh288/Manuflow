"""The LLM behind the assistant, as a small protocol (B17: provider and model are config).

Messages use the Anthropic shape: ``{"role": "user" | "assistant", "content": [...]}``
with ``text``, ``tool_use`` and ``tool_result`` blocks. Tests use a scripted model.
"""

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from app.core.config import Settings


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


class OpenAICompatibleChatModel:
    """Local models through an OpenAI-compatible endpoint (Ollama's ``/v1``): free, no key.

    Converts the Anthropic-shaped conversation to OpenAI chat messages and back. Uses the
    standard library only, so it adds no dependency.
    """

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._timeout = timeout

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Reply:
        body = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *to_openai(messages)],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ],
            "temperature": 0,
            "stream": False,
        }
        request = urllib.request.Request(  # noqa: S310 - URL comes from configuration
            self._url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            message = json.load(response)["choices"][0]["message"]
        return from_openai(message)


def to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            converted.append({"role": message["role"], "content": content})
            continue
        if message["role"] == "assistant":
            text = "".join(b["text"] for b in content if b["type"] == "text")
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in content
                if b["type"] == "tool_use"
            ]
            converted.append({"role": "assistant", "content": text, "tool_calls": calls})
        else:
            converted.extend(
                {"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]}
                for b in content
                if b["type"] == "tool_result"
            )
    return converted


def from_openai(message: dict[str, Any]) -> Reply:
    text = _strip_thinking(message.get("content") or "")
    calls: list[ToolCall] = []
    for index, call in enumerate(message.get("tool_calls") or []):
        raw = call["function"].get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            arguments = {"_unparsable": raw}  # the tool then reports INVALID_ARGUMENTS
        if not isinstance(arguments, dict):
            arguments = {"_unparsable": raw}
        calls.append(
            ToolCall(call.get("id") or f"call_{index}", call["function"]["name"], arguments)
        )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    content += [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in calls
    ]
    return Reply(text=text, tool_calls=calls, content=content)


def _strip_thinking(text: str) -> str:
    """Reasoning models (e.g. qwen3) may prefix the answer with a <think> block."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def build_chat_model(settings: "Settings") -> ChatModel | None:
    """B17: the provider is configuration; ``None`` means the assistant is off."""
    if settings.assistant_provider == "ollama":
        return OpenAICompatibleChatModel(settings.assistant_base_url, settings.assistant_model)
    key = settings.assistant_api_key
    return AnthropicChatModel(key.get_secret_value(), settings.assistant_model) if key else None
