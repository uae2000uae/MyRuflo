"""Multi-provider LLM support.

MyRuflo's internal message format is Anthropic-style content blocks
(`text` / `tool_use` / `tool_result` / `image`) — the Agent loop only ever
speaks that dialect. This module adds every other platform behind the same
`call()` interface:

- ``AnthropicClient``   — native Anthropic SDK (myruflo.llm.client.LLMClient).
- ``OpenAICompatClient``— one httpx-based adapter that covers OpenAI, Google
  Gemini, xAI (Grok), DeepSeek and Mistral, since all of them expose
  OpenAI-compatible chat-completions endpoints. It translates messages/tools
  to the OpenAI dialect on the way out and back to Anthropic-style blocks on
  the way in, so agents can't tell providers apart.

Every model name below is a *default* and can be overridden per tier with
``MYRUFLO_<PROVIDER>_MODEL_<TIER>`` env vars (see config.py).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx

from myruflo.llm.client import LLMClient as AnthropicClient
from myruflo.llm.client import LLMResponse
from myruflo.llm.specs import PROVIDER_SPECS, ProviderSpec

__all__ = [
    "PROVIDER_SPECS",
    "ProviderSpec",
    "ProviderError",
    "ProviderHandle",
    "OpenAICompatClient",
    "build_provider",
]

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class ProviderError(RuntimeError):
    """A provider call failed after retries (bad key, quota, outage, ...)."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


# --------------------------------------------------------------------------
# Anthropic-dialect <-> OpenAI-dialect translation
# --------------------------------------------------------------------------

def _tools_to_openai(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _block_text(content: str | list) -> str:
    """Flatten a tool_result content payload (string or block list) to text."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def _messages_to_openai(system: str, messages: list[dict]) -> list[dict]:
    """Translate Anthropic-style messages into OpenAI chat-completions form."""
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})

    for message in messages:
        role = message["role"]
        content = message["content"]

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )
            entry: dict = {"role": "assistant", "content": "\n".join(text_parts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
            continue

        # user message with blocks: tool results become role="tool" messages;
        # text/image blocks become a single multimodal user message.
        user_parts: list[dict] = []
        for block in content:
            btype = block.get("type")
            if btype == "tool_result":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": _block_text(block.get("content", "")),
                    }
                )
            elif btype == "text":
                user_parts.append({"type": "text", "text": block.get("text", "")})
            elif btype == "image":
                source = block.get("source", {})
                if source.get("type") == "base64":
                    data_url = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
                    user_parts.append({"type": "image_url", "image_url": {"url": data_url}})
        if user_parts:
            out.append({"role": "user", "content": user_parts})

    return out


def _openai_message_to_blocks(message: dict) -> tuple[str, list[dict], list[dict]]:
    """Translate an OpenAI response message back into (text, tool_calls,
    raw Anthropic-style content blocks)."""
    text = message.get("content") or ""
    if isinstance(text, list):  # some providers return content parts
        text = "\n".join(p.get("text", "") for p in text if isinstance(p, dict))

    raw_content: list[dict] = []
    if text:
        raw_content.append({"type": "text", "text": text})

    tool_calls: list[dict] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function", {})
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {"_raw": function.get("arguments", "")}
        block = {
            "type": "tool_use",
            "id": call.get("id", ""),
            "name": function.get("name", ""),
            "input": arguments,
        }
        tool_calls.append(block)
        raw_content.append(block)

    return text, tool_calls, raw_content


class OpenAICompatClient:
    """Chat-completions client for any OpenAI-compatible platform.

    Presents the exact same ``call()`` interface as the Anthropic client and
    returns the same ``LLMResponse``, so the agent tool-use loop is entirely
    provider-agnostic.
    """

    def __init__(self, spec: ProviderSpec, api_key: str, *, timeout: float = 180.0) -> None:
        if not api_key:
            raise ValueError(f"No API key configured for provider '{spec.name}'.")
        self.spec = spec
        self._api_key = api_key
        self._http = httpx.Client(
            base_url=spec.base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload: dict = {
            "model": model,
            "messages": _messages_to_openai(system, messages),
        }
        # OpenAI's GPT-5-era models reject `max_tokens` in favour of
        # `max_completion_tokens`; every other compat endpoint takes `max_tokens`.
        if self.spec.name == "openai":
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = _tools_to_openai(tools)

        data = self._post_with_retries("/chat/completions", payload)

        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(self.spec.name, f"malformed response: {data!r:.500}") from exc

        text, tool_calls, raw_content = _openai_message_to_blocks(message)
        finish = choice.get("finish_reason", "stop")
        stop_reason = "tool_use" if (finish == "tool_calls" or tool_calls) else "end_turn"

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw_content=raw_content,
        )

    def _post_with_retries(self, path: str, payload: dict) -> dict:
        last_error = "unknown error"
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._http.post(path, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    return response.json()
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in _RETRYABLE_STATUS:
                    break
            if attempt < _MAX_ATTEMPTS:
                time.sleep(min(2 ** attempt, 8))
        raise ProviderError(self.spec.name, last_error)

    def close(self) -> None:
        self._http.close()


@dataclass
class ProviderHandle:
    """A configured, ready-to-call provider."""

    spec: ProviderSpec
    client: object  # AnthropicClient | OpenAICompatClient
    models: dict[str, str] = field(default_factory=dict)  # tier -> model
    key_source: str = "env"

    def model_for_tier(self, tier: str) -> str:
        return self.models.get(tier) or self.spec.default_models.get(tier) or self.spec.default_models["default"]


def build_provider(spec: ProviderSpec, api_key: str, models: dict[str, str], key_source: str) -> ProviderHandle:
    if spec.api_style == "anthropic":
        client: object = AnthropicClient(api_key)
    else:
        client = OpenAICompatClient(spec, api_key)
    return ProviderHandle(spec=spec, client=client, models=models, key_source=key_source)
