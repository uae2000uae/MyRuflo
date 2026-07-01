"""Verifies enabled_tools gates run_shell even when MYRUFLO_ALLOW_SHELL is on,
and that enabled_tools=None (the CLI's default) preserves today's behavior.
No real Anthropic calls — a fake LLM client returns canned tool-use turns.
"""
from pathlib import Path

from myruflo.agents.agent import Agent
from myruflo.config import Config
from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMResponse
from myruflo.memory.store import MemoryStore


class FakeLLMClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    def call(self, **kwargs):
        return self._responses.pop(0)


def _shell_call_then_done() -> list[LLMResponse]:
    return [
        LLMResponse(
            text="",
            tool_calls=[{"id": "call1", "name": "run_shell", "input": {"command": "echo hi"}}],
            stop_reason="tool_use",
            raw_content=[
                {"type": "tool_use", "id": "call1", "name": "run_shell", "input": {"command": "echo hi"}}
            ],
        ),
        LLMResponse(text="done", tool_calls=[], stop_reason="end_turn", raw_content=[{"type": "text", "text": "done"}]),
    ]


def _make_config(tmp_path: Path, allow_shell: bool) -> Config:
    return Config(api_key="test", workspace=tmp_path, data_dir=tmp_path, allow_shell=allow_shell)


def _run_agent(tmp_path: Path, allow_shell: bool, enabled_tools):
    config = _make_config(tmp_path, allow_shell)
    memory = MemoryStore(config.memory_db_path)
    hooks = HooksManager(config.hooks_log_path, memory)
    agent = Agent(
        "generalist", config, FakeLLMClient(_shell_call_then_done()), memory, hooks, enabled_tools=enabled_tools
    )
    result = agent.run("run a command")
    memory.close()
    return result


def _tool_result_text(result) -> str:
    # transcript = [user task, assistant tool_use, user tool_results, assistant final text]
    return result.transcript[-2]["content"][0]["content"]


def test_enabled_tools_none_preserves_config_allow_shell(tmp_path: Path):
    result = _run_agent(tmp_path, allow_shell=True, enabled_tools=None)
    assert "disabled" not in _tool_result_text(result)


def test_enabled_tools_excludes_run_shell_even_if_allow_shell_true(tmp_path: Path):
    result = _run_agent(tmp_path, allow_shell=True, enabled_tools=set())
    assert "disabled" in _tool_result_text(result)


def test_allow_shell_false_stays_disabled_regardless_of_enabled_tools(tmp_path: Path):
    result = _run_agent(tmp_path, allow_shell=False, enabled_tools={"run_shell"})
    assert "disabled" in _tool_result_text(result)
