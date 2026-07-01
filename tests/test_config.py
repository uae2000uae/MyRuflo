import myruflo.config as config_module


def test_env_var_wins_over_secret_manager(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "some-project")
    monkeypatch.setattr(config_module, "_fetch_gcp_secret", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not call Secret Manager when env var is set")
    ))

    key, source = config_module._resolve_api_key()
    assert key == "sk-from-env"
    assert source == "env"


def test_falls_back_to_secret_manager_when_env_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "some-project")
    monkeypatch.setattr(config_module, "_fetch_gcp_secret", lambda project, name: "sk-from-secret-manager")

    key, source = config_module._resolve_api_key()
    assert key == "sk-from-secret-manager"
    assert source == "secret-manager"


def test_uses_custom_secret_name(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "some-project")
    monkeypatch.setenv("MYRUFLO_SECRET_NAME", "CUSTOM_SECRET")

    seen = {}

    def fake_fetch(project, name):
        seen["project"] = project
        seen["name"] = name
        return "sk-custom"

    monkeypatch.setattr(config_module, "_fetch_gcp_secret", fake_fetch)

    key, source = config_module._resolve_api_key()
    assert key == "sk-custom"
    assert seen == {"project": "some-project", "name": "CUSTOM_SECRET"}


def test_unset_when_no_env_and_no_project(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("MYRUFLO_GCP_PROJECT", raising=False)

    key, source = config_module._resolve_api_key()
    assert key == ""
    assert source == "unset"


def test_unset_when_secret_manager_fetch_fails(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "some-project")
    monkeypatch.setattr(config_module, "_fetch_gcp_secret", lambda *a, **k: None)

    key, source = config_module._resolve_api_key()
    assert key == ""
    assert source == "unset"


def test_fetch_gcp_secret_returns_none_without_package_installed():
    # google-cloud-secret-manager is an optional extra; when it's not
    # installed the helper must degrade to None rather than raising.
    assert config_module._fetch_gcp_secret("some-project", "SOME_SECRET") is None
