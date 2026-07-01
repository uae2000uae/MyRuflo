"""Thin wrapper around the Anthropic SDK.

Keeps the raw `anthropic` client details (content-block parsing, tool_use
extraction) in one place so agents.agent.Agent only deals with plain
dataclasses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import anthropic


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict]
    stop_reason: str
    raw_content: list[dict] = field(default_factory=list)

    @property
    def wants_tool_use(self) -> bool:
        return self.stop_reason == "tool_use" and bool(self.tool_calls)


class LLMClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self._client = anthropic.Anthropic(api_key=api_key)

    def call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools or [],
        )

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        raw_content: list[dict] = []

        for block in response.content:
            block_dict = block.model_dump() if hasattr(block, "model_dump") else dict(block)
            raw_content.append(block_dict)
            if block_dict.get("type") == "text":
                text_parts.append(block_dict["text"])
            elif block_dict.get("type") == "tool_use":
                tool_calls.append(block_dict)

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            raw_content=raw_content,
        )
