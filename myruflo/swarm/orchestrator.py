"""Routes a task to a single agent or a sequential multi-agent pipeline.

There's no live inter-agent messaging here (that requires a host like Claude
Code) — instead each stage's final answer is appended as context for the
next stage, which is a reasonable stand-in for a pipeline handoff and is
easy to reason about/debug in a standalone process.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from myruflo.agents.agent import Agent, AgentResult
from myruflo.agents.roles import ROLES
from myruflo.config import Config
from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMClient
from myruflo.llm.router import LLMRouter, TaskProfile
from myruflo.memory.store import MemoryStore

FULL_PIPELINE = ["researcher", "planner", "coder", "tester", "reviewer"]

ROLE_STATUS = {
    "generalist": "Thinking...",
    "planner": "Planning the approach...",
    "researcher": "Researching...",
    "coder": "Writing code...",
    "tester": "Testing the changes...",
    "reviewer": "Reviewing the result...",
}

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

# TaskProfile-driven pipeline selection: (task_type, complexity) -> roles.
# Falls back to the regex routes below when no classifier profile is available.
_PROFILE_PIPELINES: dict[str, list[str]] = {
    "coding": ["researcher", "coder", "tester"],
    "research": ["researcher"],
    "reasoning": ["generalist"],
    "writing": ["generalist"],
    "summarization": ["generalist"],
    "review": ["reviewer"],
    "testing": ["tester"],
    "general": ["generalist"],
}


def pipeline_for_profile(profile: TaskProfile) -> list[str]:
    if profile.complexity == "high":
        return FULL_PIPELINE
    if profile.complexity == "low" and profile.task_type in {"coding", "general", "writing"}:
        return ["generalist"]
    return _PROFILE_PIPELINES.get(profile.task_type, ["generalist"])


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
    task_type: str = "general"
    complexity: str = "medium"
    routing_source: str = "rules"

    @property
    def final_text(self) -> str:
        return self.results[-1].final_text if self.results else ""


class Orchestrator:
    def __init__(
        self,
        config: Config,
        llm: LLMClient,
        memory: MemoryStore,
        hooks: HooksManager,
        router: LLMRouter | None = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.memory = memory
        self.hooks = hooks
        self.router = router

    def run(
        self,
        task: str,
        force_swarm: bool | None = None,
        *,
        enabled_tools: set[str] | None = None,
        image_attachments: list[dict] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> SwarmReport:
        # 1. Classify once (LLM classifier + rules fallback), then choose the
        #    pipeline: the classifier profile drives it when available, with
        #    the regex routes as safety net and force_swarm always winning.
        profile = self.router.classify(task) if self.router else TaskProfile(source="default")
        if force_swarm is True:
            pipeline = FULL_PIPELINE
        elif force_swarm is False:
            pipeline = ["generalist"]
        elif self.router and profile.source == "llm":
            pipeline = pipeline_for_profile(profile)
        else:
            pipeline = choose_pipeline(task, force_swarm)

        report = SwarmReport(
            task=task,
            pipeline=pipeline,
            task_type=profile.task_type,
            complexity=profile.complexity,
            routing_source=profile.source,
        )

        context = ""
        for role in pipeline:
            # 2. Route each role to the best configured platform for this
            #    task type at the role's model tier.
            if self.router:
                tier = ROLES[role][0]
                route = self.router.route_for_role(tier, profile)
                llm_client, model, provider = route.client, route.model, route.provider
            else:
                llm_client, model, provider = self.llm, None, "anthropic"

            if on_progress:
                status = ROLE_STATUS.get(role, f"Working as {role}...")
                on_progress(f"{status} ({provider})" if self.router else status)

            agent = Agent(
                role,
                self.config,
                llm_client,
                self.memory,
                self.hooks,
                enabled_tools=enabled_tools,
                model=model,
                provider=provider,
            )
            result = agent.run(task, context=context, image_attachments=image_attachments, on_progress=on_progress)
            report.results.append(result)
            handoff = f"[{role} said]:\n{result.final_text}"
            context = f"{context}\n\n{handoff}" if context else handoff
            self.memory.add(
                "swarm-log",
                f"role={role} provider={result.provider} model={result.model} "
                f"task={task[:150]} -> {result.final_text[:300]}",
            )

        return report
