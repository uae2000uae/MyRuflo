"""Routes a task to a single agent or a sequential multi-agent pipeline.

There's no live inter-agent messaging here (that requires a host like Claude
Code) — instead each stage's final answer is appended as context for the
next stage, which is a reasonable stand-in for a pipeline handoff and is
easy to reason about/debug in a standalone process.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from myruflo.agents.agent import Agent, AgentResult
from myruflo.config import Config
from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMClient
from myruflo.memory.store import MemoryStore

FULL_PIPELINE = ["researcher", "planner", "coder", "tester", "reviewer"]

_ROUTES: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\b(security|vulnerab|audit|cve)\b", re.I), ["researcher", "reviewer"]),
    (re.compile(r"\b(fix|bug|broken|crash|failing)\b", re.I), ["researcher", "coder", "tester"]),
    (re.compile(r"\b(refactor|restructure|clean ?up|reorgani[sz]e)\b", re.I), ["researcher", "planner", "coder", "reviewer"]),
    (
        re.compile(
            r"\b(feature|implement|build|add)\b.*\b(feature|system|endpoint|module|app|tool|service|api)\b",
            re.I,
        ),
        FULL_PIPELINE,
    ),
    (re.compile(r"\btest(s|ing)?\b", re.I), ["tester"]),
    (re.compile(r"\breview\b", re.I), ["reviewer"]),
    (re.compile(r"\b(research|investigate|analy[sz]e|explore)\b", re.I), ["researcher"]),
]

_LONG_TASK_WORD_COUNT = 40


def choose_pipeline(task: str, force_swarm: bool | None = None) -> list[str]:
    if force_swarm is False:
        return ["generalist"]
    if force_swarm is True:
        return FULL_PIPELINE
    for pattern, roles in _ROUTES:
        if pattern.search(task):
            return roles
    if len(task.split()) > _LONG_TASK_WORD_COUNT:
        return FULL_PIPELINE
    return ["generalist"]


@dataclass
class SwarmReport:
    task: str
    pipeline: list[str]
    results: list[AgentResult] = field(default_factory=list)

    @property
    def final_text(self) -> str:
        return self.results[-1].final_text if self.results else ""


class Orchestrator:
    def __init__(self, config: Config, llm: LLMClient, memory: MemoryStore, hooks: HooksManager) -> None:
        self.config = config
        self.llm = llm
        self.memory = memory
        self.hooks = hooks

    def run(
        self,
        task: str,
        force_swarm: bool | None = None,
        *,
        enabled_tools: set[str] | None = None,
        image_attachments: list[dict] | None = None,
    ) -> SwarmReport:
        pipeline = choose_pipeline(task, force_swarm)
        report = SwarmReport(task=task, pipeline=pipeline)

        context = ""
        for role in pipeline:
            agent = Agent(role, self.config, self.llm, self.memory, self.hooks, enabled_tools=enabled_tools)
            result = agent.run(task, context=context, image_attachments=image_attachments)
            report.results.append(result)
            handoff = f"[{role} said]:\n{result.final_text}"
            context = f"{context}\n\n{handoff}" if context else handoff
            self.memory.add("swarm-log", f"role={role} task={task[:150]} -> {result.final_text[:300]}")

        return report
