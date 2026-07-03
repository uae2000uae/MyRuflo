"""Offline end-to-end test of the full multi-platform workflow:
classifier -> router -> pipeline -> tool-use loop (through the OpenAI-compat
translation) -> memory/hooks. No network calls."""
from __future__ import annotations

from pathlib import Path

from myruflo.config import Config
from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMResponse
from myruflo.llm.providers import PROVIDER_SPECS, OpenAICompatClient, ProviderHandle
from myruflo.llm.router import LLMRouter
from myruflo.memory.store import MemoryStore
from myruflo.swarm.orchestrator import Orchestrator


class FakeAnthropicClient:
    def call(self, **kwargs):
        return LLMResponse(
            text="claude answer",
            tool_calls=[],
            stop_reason="end_turn",
            raw_content=[{"type": "text", "text": "claude answer"}],
        )


class ScriptedOpenAIServer:
    """Plays an OpenAI-compatible platform: classifies, asks for a tool,
    then answers using the tool result."""

    def __init__(self):
        self.calls: list[dict] = []

    def post(self, path, payload):
        self.calls.append(payload)
        n = len(self.calls)
        if n == 1:  # classifier call
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"task_type": "summarization", "complexity": "medium"}'},
                    }
                ]
            }
        if n == 2:  # agent requests the file
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": '{"path": "notes.txt"}'},
                                }
                            ],
                        },
                    }
                ]
            }
        return {"choices": [{"finish_reason": "stop", "message": {"content": "Summary: v2 ships Friday."}}]}


def test_full_workflow_across_platforms(tmp_path: Path):
    workspace = tmp_path / "workspace"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    data_dir.mkdir()
    (workspace / "notes.txt").write_text("meeting notes: ship v2 friday", encoding="utf-8")

    config = Config(api_key="sk-ant-test", workspace=workspace, data_dir=data_dir)

    server = ScriptedOpenAIServer()
    ds_client = OpenAICompatClient(PROVIDER_SPECS["deepseek"], api_key="test")
    ds_client._post_with_retries = server.post

    router = LLMRouter(
        {
            "anthropic": ProviderHandle(spec=PROVIDER_SPECS["anthropic"], client=FakeAnthropicClient()),
            "deepseek": ProviderHandle(spec=PROVIDER_SPECS["deepseek"], client=ds_client),
        },
        mode="auto",
    )

    memory = MemoryStore(config.memory_db_path)
    hooks = HooksManager(config.hooks_log_path, memory)
    orchestrator = Orchestrator(config, FakeAnthropicClient(), memory, hooks, router=router)

    statuses: list[str] = []
    report = orchestrator.run("summarize the notes file", on_progress=statuses.append)

    # classifier drove pipeline + platform choice
    assert report.routing_source == "llm"
    assert report.task_type == "summarization"
    assert report.pipeline == ["generalist"]
    assert report.results[0].provider == "deepseek"
    assert report.results[0].model == "deepseek-v4-flash"

    # tool round trip actually happened and the result reached the model
    assert report.results[0].turns_used == 2
    assert report.final_text == "Summary: v2 ships Friday."
    final_messages = server.calls[-1]["messages"]
    assert [m["role"] for m in final_messages] == ["system", "user", "assistant", "tool"]
    assert "meeting notes: ship v2 friday" in final_messages[-1]["content"]

    # tool schemas were sent in OpenAI function format
    assert any(t["function"]["name"] == "read_file" for t in server.calls[1]["tools"])

    # memory + hooks recorded the run, progress showed the platform
    hits = memory.search("swarm-log", "summarize notes", 3)
    assert hits and "provider=deepseek" in hits[0][1]
    assert config.hooks_log_path.exists()
    assert any("deepseek" in status for status in statuses)

    memory.close()
