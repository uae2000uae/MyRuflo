"""Tests for platform routing: classification, provider preference,
graceful degradation, and pipeline selection from profiles."""
from __future__ import annotations

from myruflo.llm.client import LLMResponse
from myruflo.llm.providers import PROVIDER_SPECS, ProviderHandle
from myruflo.llm.router import (
    LLMRouter,
    TaskProfile,
    _parse_classifier_json,
    classify_by_rules,
)
from myruflo.swarm.orchestrator import FULL_PIPELINE, pipeline_for_profile


class FakeClient:
    def __init__(self, text: str = "ok") -> None:
        self.text = text
        self.calls: list[dict] = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(text=self.text, tool_calls=[], stop_reason="end_turn", raw_content=[])


def _handle(name: str, text: str = "ok") -> ProviderHandle:
    return ProviderHandle(spec=PROVIDER_SPECS[name], client=FakeClient(text), models={}, key_source="env")


def test_rules_classifier_detects_coding():
    profile = classify_by_rules("fix the bug in the login endpoint")
    assert profile.task_type in {"coding", "review"}  # 'fix'/'bug' keywords
    assert profile.source == "rules"


def test_rules_classifier_complexity_scales_with_length():
    assert classify_by_rules("hi there").complexity == "low"
    assert classify_by_rules(" ".join(["word"] * 100)).complexity == "high"


def test_parse_classifier_json_valid_and_invalid():
    ok = _parse_classifier_json('{"task_type": "coding", "complexity": "high"}')
    assert ok is not None and ok.task_type == "coding" and ok.source == "llm"
    assert _parse_classifier_json("not json") is None
    assert _parse_classifier_json('{"task_type": "nonsense", "complexity": "high"}') is None


def test_router_prefers_table_order_when_available():
    router = LLMRouter({"anthropic": _handle("anthropic"), "gemini": _handle("gemini")}, mode="rules")
    assert router.route("fast", "research").provider == "gemini"
    assert router.route("default", "coding").provider == "anthropic"


def test_router_degrades_to_only_configured_provider():
    router = LLMRouter({"anthropic": _handle("anthropic")}, mode="rules")
    for task_type in ("coding", "research", "summarization", "reasoning"):
        assert router.route("default", task_type).provider == "anthropic"


def test_router_mode_off_pins_default_provider():
    router = LLMRouter(
        {"anthropic": _handle("anthropic"), "openai": _handle("openai")},
        default_provider="openai",
        mode="off",
    )
    assert router.route("default", "coding").provider == "openai"


def test_llm_classifier_used_then_rules_fallback():
    good = _handle("anthropic", text='{"task_type": "research", "complexity": "low"}')
    router = LLMRouter({"anthropic": good}, mode="auto")
    profile = router.classify("look into this")
    assert profile.task_type == "research" and profile.source == "llm"

    bad = _handle("anthropic", text="I cannot classify that, sorry!")
    router = LLMRouter({"anthropic": bad}, mode="auto")
    profile = router.classify("fix the crash in parser code")
    assert profile.source == "rules"


def test_route_for_role_bumps_default_tier_on_high_complexity():
    handle = _handle("anthropic")
    router = LLMRouter({"anthropic": handle}, mode="rules")
    route = router.route_for_role("default", TaskProfile(task_type="coding", complexity="high"))
    assert route.model == handle.model_for_tier("heavy")


def test_pipeline_for_profile():
    assert pipeline_for_profile(TaskProfile(task_type="coding", complexity="high")) == FULL_PIPELINE
    assert pipeline_for_profile(TaskProfile(task_type="coding", complexity="medium")) == [
        "researcher",
        "coder",
        "tester",
    ]
    assert pipeline_for_profile(TaskProfile(task_type="coding", complexity="low")) == ["generalist"]
    assert pipeline_for_profile(TaskProfile(task_type="review", complexity="medium")) == ["reviewer"]
