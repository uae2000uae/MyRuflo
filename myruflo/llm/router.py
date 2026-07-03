"""Platform routing: decide which AI platform + model handles each step.

Strategy = LLM classifier + rules (with graceful degradation):

1. A cheap fast-tier model classifies the task once per run — task type
   (coding / research / reasoning / writing / summarization / review /
   testing / general) and complexity (low / medium / high).
2. A deterministic routing table maps task type -> ordered provider
   preferences; the first *configured* provider wins, so missing API keys
   simply narrow the choice. Anthropic is the final fallback.
3. If the classifier call fails (or MYRUFLO_ROUTER=rules), a keyword
   classifier produces the same TaskProfile, so routing always works.

The classifier result also drives pipeline selection in the orchestrator.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from myruflo.llm.providers import PROVIDER_SPECS, ProviderHandle, build_provider

TASK_TYPES = (
    "coding",
    "research",
    "reasoning",
    "writing",
    "summarization",
    "review",
    "testing",
    "general",
)

COMPLEXITIES = ("low", "medium", "high")

# Ordered provider preference per task type. Only configured providers are
# considered; the default provider is always the last resort.
ROUTING_TABLE: dict[str, tuple[str, ...]] = {
    "coding": ("anthropic", "openai", "deepseek", "gemini", "mistral", "xai"),
    "research": ("gemini", "anthropic", "xai", "openai", "mistral", "deepseek"),
    "reasoning": ("openai", "anthropic", "deepseek", "xai", "gemini", "mistral"),
    "writing": ("anthropic", "mistral", "openai", "gemini", "xai", "deepseek"),
    "summarization": ("gemini", "deepseek", "mistral", "anthropic", "openai", "xai"),
    "review": ("anthropic", "openai", "gemini", "deepseek", "mistral", "xai"),
    "testing": ("anthropic", "deepseek", "openai", "gemini", "mistral", "xai"),
    "general": ("anthropic", "openai", "gemini", "xai", "deepseek", "mistral"),
}

_CLASSIFIER_SYSTEM = (
    "You are a task router. Classify the user's task and answer with ONLY a "
    "JSON object, no prose, of the form "
    '{"task_type": "<one of: ' + ", ".join(TASK_TYPES) + '>", '
    '"complexity": "<one of: low, medium, high>"}. '
    "coding=writing/fixing/refactoring code; research=investigating code or "
    "topics; reasoning=math/logic/multi-step analysis; writing=prose/docs; "
    "summarization=condensing existing content; review=critiquing code or "
    "text; testing=writing or running tests; general=anything else. "
    "complexity: low=one-step, medium=a few related steps, high=multi-part "
    "project touching several files or domains."
)

_KEYWORD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(test(s|ing)?|pytest|unit test)\b", re.I), "testing"),
    (re.compile(r"\b(review|critique|audit|security|vulnerab)\b", re.I), "review"),
    (re.compile(r"\b(summari[sz]e|tl;?dr|condense|digest)\b", re.I), "summarization"),
    (re.compile(r"\b(research|investigate|explore|find out|compare|analy[sz]e)\b", re.I), "research"),
    (re.compile(r"\b(prove|calculate|math|equation|logic|puzzle|optimi[sz]e)\b", re.I), "reasoning"),
    (re.compile(r"\b(fix|bug|refactor|implement|code|function|class|module|api|endpoint|script|app)\b", re.I), "coding"),
    (re.compile(r"\b(write|draft|essay|article|blog|email|document|report)\b", re.I), "writing"),
]


@dataclass
class TaskProfile:
    task_type: str = "general"
    complexity: str = "medium"
    source: str = "rules"  # "llm" | "rules" | "default"


@dataclass
class Route:
    provider: str
    model: str
    client: object


def classify_by_rules(task: str) -> TaskProfile:
    task_type = "general"
    for pattern, ttype in _KEYWORD_RULES:
        if pattern.search(task):
            task_type = ttype
            break
    words = len(task.split())
    complexity = "low" if words <= 15 else "medium" if words <= 60 else "high"
    return TaskProfile(task_type=task_type, complexity=complexity, source="rules")


def _parse_classifier_json(text: str) -> TaskProfile | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    task_type = str(data.get("task_type", "")).strip().lower()
    complexity = str(data.get("complexity", "")).strip().lower()
    if task_type not in TASK_TYPES or complexity not in COMPLEXITIES:
        return None
    return TaskProfile(task_type=task_type, complexity=complexity, source="llm")


class LLMRouter:
    """Holds every configured provider and picks the best one per call."""

    def __init__(
        self,
        providers: dict[str, ProviderHandle],
        *,
        default_provider: str = "anthropic",
        mode: str = "auto",  # "auto" (LLM classifier + rules) | "rules" | "off"
    ) -> None:
        if not providers:
            raise ValueError(
                "No AI provider is configured. Set at least one API key "
                "(ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, "
                "XAI_API_KEY, DEEPSEEK_API_KEY or MISTRAL_API_KEY)."
            )
        self.providers = providers
        self.mode = mode
        if default_provider in providers:
            self.default_provider = default_provider
        else:
            # prefer anthropic, else any configured provider
            self.default_provider = "anthropic" if "anthropic" in providers else next(iter(providers))

    # -- classification ----------------------------------------------------

    def classify(self, task: str) -> TaskProfile:
        if self.mode == "off":
            return TaskProfile(source="default")
        if self.mode == "auto":
            profile = self._classify_with_llm(task)
            if profile is not None:
                return profile
        return classify_by_rules(task)

    def _classify_with_llm(self, task: str) -> TaskProfile | None:
        handle = self._cheapest_handle()
        try:
            response = handle.client.call(
                model=handle.model_for_tier("fast"),
                system=_CLASSIFIER_SYSTEM,
                messages=[{"role": "user", "content": task[:4000]}],
                max_tokens=100,
            )
        except Exception:  # noqa: BLE001 - any failure falls back to rules
            return None
        return _parse_classifier_json(response.text)

    def _cheapest_handle(self) -> ProviderHandle:
        for name in ("gemini", "deepseek", "mistral", "anthropic", "openai", "xai"):
            if name in self.providers:
                return self.providers[name]
        return self.providers[self.default_provider]

    # -- routing ------------------------------------------------------------

    def route(self, tier: str, task_type: str = "general") -> Route:
        """Pick the best configured provider for this task type and return
        the (provider, model, client) to use at the given tier."""
        preferences = ROUTING_TABLE.get(task_type, ROUTING_TABLE["general"])
        if self.mode == "off":
            preferences = (self.default_provider,)

        for name in preferences:
            handle = self.providers.get(name)
            if handle is not None:
                return Route(provider=name, model=handle.model_for_tier(tier), client=handle.client)

        handle = self.providers[self.default_provider]
        return Route(provider=self.default_provider, model=handle.model_for_tier(tier), client=handle.client)

    def route_for_role(self, tier: str, profile: TaskProfile) -> Route:
        """Route for a pipeline role: heavy complexity bumps the default tier."""
        effective_tier = "heavy" if (tier == "default" and profile.complexity == "high") else tier
        return self.route(effective_tier, profile.task_type)

    def describe(self) -> list[dict]:
        """Provider status for doctor/admin displays."""
        return [
            {
                "name": handle.spec.name,
                "label": handle.spec.label,
                "key_source": handle.key_source,
                "models": {tier: handle.model_for_tier(tier) for tier in ("fast", "default", "heavy")},
            }
            for handle in self.providers.values()
        ]


def build_router(config) -> LLMRouter | None:
    """Build an LLMRouter from a Config, using every provider whose API key
    is configured. Returns None when no provider is usable.

    Falls back to treating ``config.api_key`` as the Anthropic key when
    ``provider_keys`` is empty (older Config objects, tests).
    """
    provider_keys: dict[str, tuple[str, str]] = dict(getattr(config, "provider_keys", {}) or {})
    if not any(key for key, _ in provider_keys.values()) and getattr(config, "api_key", ""):
        provider_keys["anthropic"] = (config.api_key, getattr(config, "api_key_source", "env"))

    provider_models = getattr(config, "provider_models", {}) or {}
    handles: dict[str, ProviderHandle] = {}
    for name, (key, source) in provider_keys.items():
        if not key or name not in PROVIDER_SPECS:
            continue
        try:
            handles[name] = build_provider(PROVIDER_SPECS[name], key, provider_models.get(name, {}), source)
        except Exception:  # noqa: BLE001 - a broken provider must not take the app down
            continue

    # legacy MYRUFLO_MODEL_* fields still win for anthropic if set
    if "anthropic" in handles:
        legacy = {
            "fast": getattr(config, "model_fast", ""),
            "default": getattr(config, "model_default", ""),
            "heavy": getattr(config, "model_heavy", ""),
        }
        for tier, model in legacy.items():
            if model:
                handles["anthropic"].models.setdefault(tier, model)

    if not handles:
        return None
    return LLMRouter(
        handles,
        default_provider=getattr(config, "default_provider", "anthropic"),
        mode=getattr(config, "router_mode", "auto"),
    )
