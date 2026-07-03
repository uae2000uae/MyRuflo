"""Tests for resolving platform API keys from GCP Secret Manager."""
from __future__ import annotations

from myruflo import config as config_module


def _clear_provider_env(monkeypatch):
    for var in (
        "ANTHROPIC_API_KEY", "MYRUFLO_EVL", "ANTHROPIC_AI_KEY",
        "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "XAI_API_KEY", "GROK_API_KEY", "DEEPSEEK_API_KEY", "MISTRAL_API_KEY",
        "MYRUFLO_GCP_PROJECT", "GOOGLE_CLOUD_PROJECT",
        "MYRUFLO_SECRET_OPENAI", "MYRUFLO_SECRET_GEMINI",
    ):
        monkeypatch.delenv(var, raising=False)


def test_default_secret_ids_used_when_project_set(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")

    fake_secrets = {"OPENAI_API_KEY": "sk-openai-from-sm", "GEMINI_API_KEY": "gm-key-from-sm"}
    monkeypatch.setattr(
        config_module, "_fetch_gcp_secret", lambda project, name: fake_secrets.get(name)
    )

    keys = config_module._resolve_provider_keys()
    assert keys["openai"] == ("sk-openai-from-sm", "secret-manager:OPENAI_API_KEY")
    assert keys["gemini"] == ("gm-key-from-sm", "secret-manager:GEMINI_API_KEY")
    assert keys["deepseek"] == ("", "unset")  # no secret, no env -> gracefully unset


def test_secret_override_takes_precedence_over_defaults(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")
    monkeypatch.setenv("MYRUFLO_SECRET_OPENAI", "custom-openai-secret")

    fake_secrets = {"custom-openai-secret": "sk-custom", "OPENAI_API_KEY": "sk-default"}
    monkeypatch.setattr(
        config_module, "_fetch_gcp_secret", lambda project, name: fake_secrets.get(name)
    )

    keys = config_module._resolve_provider_keys()
    assert keys["openai"] == ("sk-custom", "secret-manager:custom-openai-secret")


def test_env_var_wins_over_secret_manager(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

    monkeypatch.setattr(
        config_module, "_fetch_gcp_secret", lambda project, name: "sk-from-sm"
    )

    keys = config_module._resolve_provider_keys()
    assert keys["openai"] == ("sk-from-env", "env:OPENAI_API_KEY")


def test_no_project_means_no_secret_lookup(monkeypatch):
    _clear_provider_env(monkeypatch)

    def boom(project, name):
        raise AssertionError("Secret Manager must not be queried without a project")

    monkeypatch.setattr(config_module, "_fetch_gcp_secret", boom)
    keys = config_module._resolve_provider_keys()
    assert keys["openai"] == ("", "unset")
    assert keys["mistral"] == ("", "unset")
