"""Static provider specifications (dependency-free).

Kept separate from providers.py so config.py and the CLI doctor can inspect
which platforms exist and which env vars configure them without importing
the anthropic/httpx client machinery.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    """Static description of a platform: how to auth, where to call, which
    models map to each tier, and which task types it is preferred for."""

    name: str
    label: str
    api_style: str  # "anthropic" | "openai"
    base_url: str
    key_env_vars: tuple[str, ...]
    default_models: dict[str, str]  # tier ("fast"|"default"|"heavy") -> model
    strengths: tuple[str, ...] = ()
    # GCP Secret Manager secret IDs to try (in order) when no env var is set
    # and a GCP project is inferable. Override with MYRUFLO_SECRET_<PROVIDER>.
    secret_names: tuple[str, ...] = ()


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        name="anthropic",
        label="Anthropic (Claude)",
        api_style="anthropic",
        base_url="https://api.anthropic.com",
        key_env_vars=("ANTHROPIC_API_KEY", "MYRUFLO_EVL", "ANTHROPIC_AI_KEY"),
        default_models={
            "fast": "claude-haiku-4-5-20251001",
            "default": "claude-sonnet-5",
            "heavy": "claude-opus-4-8",
        },
        strengths=("coding", "review", "writing", "general"),
        secret_names=("ANTHROPIC_AI_KEY", "ANTHROPIC_API_KEY"),
    ),
    "openai": ProviderSpec(
        name="openai",
        label="OpenAI (GPT)",
        api_style="openai",
        base_url="https://api.openai.com/v1",
        key_env_vars=("OPENAI_API_KEY",),
        default_models={
            "fast": "gpt-5.4-mini",
            "default": "gpt-5.5",
            "heavy": "gpt-5.5-pro",
        },
        strengths=("reasoning", "math", "coding", "general"),
        secret_names=("OPENAI_API_KEY",),
    ),
    "gemini": ProviderSpec(
        name="gemini",
        label="Google Gemini",
        api_style="openai",  # Gemini's OpenAI-compatibility endpoint
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        default_models={
            "fast": "gemini-3.1-flash-lite",
            "default": "gemini-3.5-flash",
            "heavy": "gemini-3-pro",
        },
        strengths=("research", "summarization", "long-context", "general"),
        secret_names=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    ),
    "xai": ProviderSpec(
        name="xai",
        label="xAI (Grok)",
        api_style="openai",
        base_url="https://api.x.ai/v1",
        key_env_vars=("XAI_API_KEY", "GROK_API_KEY"),
        default_models={
            "fast": "grok-4.1-fast",
            "default": "grok-4.3",
            "heavy": "grok-4.3",
        },
        strengths=("research", "reasoning", "general"),
        secret_names=("XAI_API_KEY", "GROK_API_KEY"),
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        label="DeepSeek",
        api_style="openai",
        base_url="https://api.deepseek.com/v1",
        key_env_vars=("DEEPSEEK_API_KEY",),
        default_models={
            "fast": "deepseek-v4-flash",
            "default": "deepseek-v4-flash",
            "heavy": "deepseek-v4-pro",
        },
        strengths=("coding", "math", "summarization"),
        secret_names=("DEEPSEEK_API_KEY",),
    ),
    "mistral": ProviderSpec(
        name="mistral",
        label="Mistral",
        api_style="openai",
        base_url="https://api.mistral.ai/v1",
        key_env_vars=("MISTRAL_API_KEY",),
        default_models={
            "fast": "mistral-small-latest",
            "default": "mistral-large-latest",
            "heavy": "mistral-large-latest",
        },
        strengths=("writing", "summarization", "coding"),
        secret_names=("MISTRAL_API_KEY",),
    ),
}
