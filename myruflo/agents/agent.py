"""Single-agent execution loop: system prompt + tool-use loop against the
Anthropic API, backed by workspace file/shell tools and the memory store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from myruflo.agents.roles import ROLES
from myruflo.config import Config
from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMClient
from myruflo.memory.store import MemoryStore
from myruflo.tools.registry import build_tool_schemas, execute_tool


@dataclass
class AgentResult:
    role: str
    task: str
    final_text: str
    turns_used: int
    transcript: list[dict] = field(default_factory=list)
    provider: str = "anthropic"
    model: str = ""


class Agent:
    def __init__(
        self,
        role: str,
        config: Config,
        llm: LLMClient,
        memory: MemoryStore,
        hooks: HooksManager,
        *,
        enabled_tools: set[str] | None = None,
        model: str | None = None,
        provider: str = "anthropic",
    ) -> None:
        if role not in ROLES:
            raise ValueError(f"Unknown role '{role}'. Known roles: {sorted(ROLES)}")
        self.role = role
        self.config = config
        self.llm = llm  # any client exposing .call(...) -> LLMResponse
        self.memory = memory
        self.hooks = hooks
        self._enabled_tools = enabled_tools
        self._tier, self._system_prompt = ROLES[role]
        self._model_override = model
        self.provider = provider

    def run(
        self,
        task: str,
        context: str = "",
        *,
        image_attachments: list[dict] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> AgentResult:
        hint = self.hooks.pre_task(self.role, task)
        system = self._system_prompt if not hint else f"{self._system_prompt}\n\n{hint}"

        user_text = task if not context else f"{context}\n\n---\n\nYour task:\n{task}"
        user_content: str | list[dict] = (
            [{"type": "text", "text": user_text}, *image_attachments] if image_attachments else user_text
        )
        messages: list[dict] = [{"role": "user", "content": user_content}]

        effective_allow_shell = self.config.allow_shell and (
            self._enabled_tools is None or "run_shell" in self._enabled_tools
        )
        tools = build_tool_schemas(
            include_shell=self.config.allow_shell, include_memory=True, enabled_tools=self._enabled_tools
        )
        model = self._model_override or self.config.model_for_tier(self._tier)

        final_text = ""
        turns = 0
        while turns < self.config.max_turns:
            turns += 1
            response = self.llm.call(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=self.config.max_tokens,
            )
            messages.append({"role": "assistant", "content": response.raw_content})
            final_text = response.text

            if not response.wants_tool_use:
                break

            if on_progress:
                tool_names = ", ".join(sorted({call["name"] for call in response.tool_calls}))
                on_progress(f"Using {tool_names}...")

            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": execute_tool(
                        call["name"],
                        call.get("input", {}),
                        workspace=self.config.workspace,
                        allow_shell=effective_allow_shell,
                        memory=self.memory,
                    ),
                }
                for call in response.tool_calls
            ]
            messages.append({"role": "user", "content": tool_results})
        else:
            final_text = final_text or "(stopped: reached max_turns without a final answer)"

        self.hooks.post_task(
            self.role, task, success=bool(final_text.strip()), summary=final_text[:500]
        )
        return AgentResult(
            role=self.role,
            task=task,
            final_text=final_text,
            turns_used=turns,
            transcript=messages,
            provider=self.provider,
            model=model,
        )
