"""Tests for admin-editable platform secret IDs: storage, key resolution
with overrides, router rebuild, and the connectivity test helper.

Uses a bare sqlite connection (no FastAPI) — platform_settings.py is kept
framework-free on purpose.
"""
from __future__ import annotations

import sqlite3
import time

from myruflo.config import Config
from myruflo.llm.client import LLMResponse
from myruflo.llm.providers import PROVIDER_SPECS, ProviderHandle
from myruflo.web import platform_settings

_TABLE = """
CREATE TABLE platform_settings (
    provider TEXT PRIMARY KEY,
    secret_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    updated_by INTEGER
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_TABLE)
    return conn


def test_save_and_load_secret_ids():
    conn = _conn()
    platform_settings.save_secret_id(conn, "openai", "my-openai-secret", admin_user_id=1)
    platform_settings.save_secret_id(conn, "gemini", "  my-gemini-secret  ", admin_user_id=1)
    platform_settings.save_secret_id(conn, "xai", "", admin_user_id=1)  # cleared -> excluded

    ids = platform_settings.load_secret_ids(conn)
    assert ids == {"openai": "my-openai-secret", "gemini": "my-gemini-secret"}

    # upsert overwrites
    platform_settings.save_secret_id(conn, "openai", "new-secret", admin_user_id=2)
    assert platform_settings.load_secret_ids(conn)["openai"] == "new-secret"


def test_admin_secret_overrides_env_key(monkeypatch):
    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")
    monkeypatch.setattr(
        platform_settings, "_fetch_gcp_secret", lambda project, name: {"oai-secret": "sk-from-sm"}.get(name)
    )
    config = Config(
        api_key="sk-ant", provider_keys={"anthropic": ("sk-ant", "env"), "openai": ("sk-env", "env:OPENAI_API_KEY")}
    )
    keys, errors = platform_settings.resolve_overridden_keys(config, {"openai": "oai-secret"})
    assert errors == {}
    assert keys["openai"] == ("sk-from-sm", "secret-manager:oai-secret (admin)")
    assert keys["anthropic"] == ("sk-ant", "env")


def test_unreadable_secret_reports_error_and_keeps_platform_off(monkeypatch):
    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")
    monkeypatch.setattr(platform_settings, "_fetch_gcp_secret", lambda project, name: None)
    config = Config(api_key="sk-ant", provider_keys={"anthropic": ("sk-ant", "env")})
    keys, errors = platform_settings.resolve_overridden_keys(config, {"mistral": "missing-secret"})
    assert "mistral" in errors
    # message names the unreadable secret, or the environment gap (missing
    # google-cloud-secret-manager package) that prevented the lookup entirely
    assert "missing-secret" in errors["mistral"] or "google-cloud-secret-manager" in errors["mistral"]
    assert "mistral" not in keys or keys["mistral"][0] == ""


def test_no_gcp_project_reports_clear_error(monkeypatch):
    monkeypatch.delenv("MYRUFLO_GCP_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    config = Config(api_key="sk-ant", provider_keys={"anthropic": ("sk-ant", "env")})
    keys, errors = platform_settings.resolve_overridden_keys(config, {"openai": "some-secret"})
    assert "GCP project" in errors["openai"]


def test_build_router_with_overrides_activates_platform(monkeypatch):
    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")
    monkeypatch.setattr(
        platform_settings, "_fetch_gcp_secret", lambda project, name: {"ds-secret": "sk-ds"}.get(name)
    )
    conn = _conn()
    platform_settings.save_secret_id(conn, "deepseek", "ds-secret", admin_user_id=1)
    config = Config(api_key="sk-ant", provider_keys={"anthropic": ("sk-ant", "env")})

    router, errors = platform_settings.build_router_with_overrides(config, conn)
    assert errors == {}
    assert router is not None
    assert set(router.providers) == {"anthropic", "deepseek"}
    assert router.providers["deepseek"].key_source == "secret-manager:ds-secret (admin)"


def test_refresh_picks_up_secret_added_after_startup(monkeypatch):
    """The exact 'I added my key to the secret, Test must find it' flow:
    the key didn't exist at startup, gets a version later, and a refresh
    rebuild activates the platform with no restart."""
    import myruflo.config as config_module

    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY",
                "GROK_API_KEY", "DEEPSEEK_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    secrets: dict[str, str] = {}  # Secret Manager contents, mutable
    monkeypatch.setattr(config_module, "_fetch_gcp_secret", lambda p, n: secrets.get(n))
    monkeypatch.setattr(platform_settings, "_fetch_gcp_secret", lambda p, n: secrets.get(n))

    conn = _conn()
    config = Config(api_key="sk-ant-env", provider_keys=config_module._resolve_provider_keys())

    router, _ = platform_settings.build_router_with_overrides(config, conn)
    assert "openai" not in router.providers  # nothing there at startup

    secrets["OPENAI_API_KEY"] = "sk-real-key-added-later"  # user adds the version

    router, errors = platform_settings.build_router_with_overrides(config, conn, refresh=True)
    assert errors == {}
    assert "openai" in router.providers
    assert router.providers["openai"].key_source == "secret-manager:OPENAI_API_KEY"
    assert "anthropic" in router.providers  # untouched


def test_secret_manager_status_messages(monkeypatch):
    monkeypatch.delenv("MYRUFLO_GCP_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert "GCP project" in platform_settings.secret_manager_status()
    monkeypatch.setenv("MYRUFLO_GCP_PROJECT", "my-proj")
    # with a project set, the answer depends on whether the SM package exists
    status = platform_settings.secret_manager_status()
    assert status is None or "google-cloud-secret-manager" in status


class _FakeClient:
    def __init__(self, text="OK", fail=False):
        self.text = text
        self.fail = fail

    def call(self, **kwargs):
        if self.fail:
            raise RuntimeError("401 invalid api key")
        return LLMResponse(text=self.text, tool_calls=[], stop_reason="end_turn", raw_content=[])


def test_ping_provider_success_and_failure():
    good = ProviderHandle(spec=PROVIDER_SPECS["openai"], client=_FakeClient("OK"))
    result = platform_settings.ping_provider(good)
    assert result["ok"] is True
    assert result["message"] == "OK"
    assert result["model"] == PROVIDER_SPECS["openai"].default_models["fast"]
    assert isinstance(result["latency_ms"], int)

    bad = ProviderHandle(spec=PROVIDER_SPECS["mistral"], client=_FakeClient(fail=True))
    result = platform_settings.ping_provider(bad)
    assert result["ok"] is False
    assert "401" in result["message"]
