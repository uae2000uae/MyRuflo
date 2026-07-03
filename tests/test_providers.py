"""Tests for the OpenAI-compat adapter: dialect translation both ways and a
full simulated tool-use round trip, so agents work identically on every
platform (OpenAI, Gemini, xAI, DeepSeek, Mistral)."""
from __future__ import annotations

import json

from myruflo.llm.providers import (
    PROVIDER_SPECS,
    OpenAICompatClient,
    _messages_to_openai,
    _openai_message_to_blocks,
    _tools_to_openai,
)


def test_tools_translate_to_openai_functions():
    tools = [{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object"}}]
    out = _tools_to_openai(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "read_file"
    assert out[0]["function"]["parameters"] == {"type": "object"}


def test_messages_translate_tool_use_and_results():
    messages = [
        {"role": "user", "content": "do the thing"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "reading"},
                {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "a.txt"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "file contents"}],
        },
    ]
    out = _messages_to_openai("sys prompt", messages)
    assert out[0] == {"role": "system", "content": "sys prompt"}
    assert out[1] == {"role": "user", "content": "do the thing"}
    assistant = out[2]
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "a.txt"}
    tool_msg = out[3]
    assert tool_msg == {"role": "tool", "tool_call_id": "call_1", "content": "file contents"}


def test_image_blocks_translate_to_data_urls():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
            ],
        }
    ]
    out = _messages_to_openai("", messages)
    parts = out[0]["content"]
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"] == "data:image/png;base64,AAAA"


def test_openai_response_translates_back_to_blocks():
    message = {
        "content": "on it",
        "tool_calls": [
            {"id": "call_9", "type": "function", "function": {"name": "list_dir", "arguments": '{"path": "."}'}}
        ],
    }
    text, tool_calls, raw = _openai_message_to_blocks(message)
    assert text == "on it"
    assert tool_calls[0] == {"type": "tool_use", "id": "call_9", "name": "list_dir", "input": {"path": "."}}
    assert raw[0] == {"type": "text", "text": "on it"}


def test_full_tool_use_round_trip_through_compat_client(monkeypatch):
    """Simulate an OpenAI-style server: first response requests a tool, the
    second gives a final answer — the loop the Agent runs, provider-agnostic."""
    client = OpenAICompatClient(PROVIDER_SPECS["deepseek"], api_key="test-key")

    responses = [
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path": "x.txt"}'},
                            }
                        ],
                    },
                }
            ]
        },
        {"choices": [{"finish_reason": "stop", "message": {"content": "The file says hello."}}]},
    ]
    sent_payloads: list[dict] = []

    def fake_post(path, payload):
        sent_payloads.append(payload)
        return responses[len(sent_payloads) - 1]

    monkeypatch.setattr(client, "_post_with_retries", fake_post)

    messages = [{"role": "user", "content": "read x.txt"}]
    first = client.call(model="deepseek-v4-flash", system="be helpful", messages=messages)
    assert first.wants_tool_use
    assert first.tool_calls[0]["name"] == "read_file"

    # Feed the tool result back, exactly like Agent.run does.
    messages.append({"role": "assistant", "content": first.raw_content})
    messages.append(
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "hello"}]}
    )
    second = client.call(model="deepseek-v4-flash", system="be helpful", messages=messages)
    assert not second.wants_tool_use
    assert second.text == "The file says hello."

    # The second request must contain the tool call and its result in OpenAI form.
    roles = [m["role"] for m in sent_payloads[1]["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert sent_payloads[1]["max_tokens"] == 4096  # non-OpenAI providers keep max_tokens


def test_openai_provider_uses_max_completion_tokens(monkeypatch):
    client = OpenAICompatClient(PROVIDER_SPECS["openai"], api_key="test-key")
    captured: dict = {}

    def fake_post(path, payload):
        captured.update(payload)
        return {"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]}

    monkeypatch.setattr(client, "_post_with_retries", fake_post)
    client.call(model="gpt-5.5", system="", messages=[{"role": "user", "content": "hi"}], max_tokens=512)
    assert captured["max_completion_tokens"] == 512
    assert "max_tokens" not in captured
