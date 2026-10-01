"""The LLM adapters: provider chosen by configuration (B17) and the OpenAI-shape mapping
used for free local models (Ollama)."""

from pydantic import SecretStr

from app.assistant.model import (
    AnthropicChatModel,
    OpenAICompatibleChatModel,
    build_chat_model,
    from_openai,
    to_openai,
)
from app.core.config import Settings


def test_b17_provider_is_configuration(settings: Settings) -> None:
    assert build_chat_model(settings) is None  # anthropic without a key: off
    keyed = settings.model_copy(update={"assistant_api_key": SecretStr("sk-test-not-real")})
    assert isinstance(build_chat_model(keyed), AnthropicChatModel)
    local = settings.model_copy(
        update={"assistant_provider": "ollama", "assistant_model": "qwen2.5:7b"}
    )
    assert isinstance(build_chat_model(local), OpenAICompatibleChatModel)


def test_conversation_maps_to_openai_messages_and_back() -> None:
    messages = [
        {"role": "user", "content": "Lệnh nào trễ?"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "c1", "name": "get_order_risks", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "c1",
                    "content": '{"orders": []}',
                    "is_error": False,
                },
            ],
        },
    ]
    assert to_openai(messages) == [
        {"role": "user", "content": "Lệnh nào trễ?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_order_risks", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"orders": []}'},
    ]

    reply = from_openai(
        {
            "content": None,
            "tool_calls": [
                {"id": "x", "function": {"name": "get_bottlenecks", "arguments": "{}"}},
                {
                    "function": {
                        "name": "calculate_material_requirements",
                        "arguments": '{"product_code": "FRAME-A", "quantity": 150}',
                    }
                },
            ],
        }
    )
    assert [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [
        ("x", "get_bottlenecks", {}),
        ("call_1", "calculate_material_requirements", {"product_code": "FRAME-A", "quantity": 150}),
    ]


def test_reasoning_blocks_are_dropped_and_broken_arguments_reach_the_tool() -> None:
    reply = from_openai({"content": "<think>let me see</think>\nPO-2026-00003 trễ."})
    assert reply.text == "PO-2026-00003 trễ." and reply.tool_calls == []

    broken = from_openai(
        {"tool_calls": [{"id": "b", "function": {"name": "get_order_risks", "arguments": "{oops"}}]}
    )
    # The tool's own validation then answers INVALID_ARGUMENTS (extra fields are forbidden).
    assert broken.tool_calls[0].arguments == {"_unparsable": "{oops"}
