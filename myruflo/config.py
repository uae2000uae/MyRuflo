"""Environment-driven configuration for MyRuflo.

No external config-loading dependency: reads a `.env` file (if present) into
the process environment, then reads everything from `os.environ`. In GCP
hosting (Cloud Run, GCE, ...) the API key instead comes from Secret Manager
— see `_resolve_api_key` below.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _fetch_gcp_secret(project: str, secret_name: str) -> str | None:
    """Best-effort fetch of `secret_name`'s latest version from Secret Manager.

    Returns None (never raises) on any failure — missing package, missing
    permissions, missing secret — so callers can fall back to treating the
    key as simply unset.
    """
    try:
        from google.cloud import secretmanager
    except ImportError:
        return None

    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(name=name)
        return response.payload.data.decode("utf-8").strip()
    except Exception:
        return None


def _resolve_api_key() -> tuple[str, str]:
    """Return (api_key, source) where source is one of:
    env, env:MYRUFLO_EVL, env:ANTHROPIC_AI_KEY, secret-manager, unset.

    Resolution order:
    1. ANTHROPIC_API_KEY env var — covers local `.env` files AND Cloud Run's
       `--set-secrets=ANTHROPIC_API_KEY=MYRUFLO_EVL:latest`, which injects the
       secret as a plain env var with zero extra code/dependency needed.
    2. MYRUFLO_EVL env var — some deployments bind the Secret Manager secret
       under its own name instead of renaming it to ANTHROPIC_API_KEY (e.g.
       `--set-secrets=MYRUFLO_EVL=MYRUFLO_EVL:latest`, or a secret reference
       set up by hand through the Cloud Run console, which defaults the env
       var name to match the secret name).
    3. ANTHROPIC_AI_KEY env var — an alternate name used on the `myruflo`
       web Service's secret binding.
    4. Secret Manager, read directly via the API — for hosting setups where
       the key isn't bound as an env var at all. Only attempted when a GCP
       project is inferable (MYRUFLO_GCP_PROJECT, or GOOGLE_CLOUD_PROJECT
       which GCP compute environments set automatically) and only if the
       `google-cloud-secret-manager` package is installed.

    Supporting multiple env var names directly means hosting setups don't
    have to rename anything on the Cloud Run side to work with this app.
    """
    env_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if env_key:
        return env_key, "env"

    evl_key = os.environ.get("MYRUFLO_EVL", "")
    if evl_key:
        return evl_key, "env:MYRUFLO_EVL"

    ai_key = os.environ.get("ANTHROPIC_AI_KEY", "")
    if ai_key:
        return ai_key, "env:ANTHROPIC_AI_KEY"

    project = os.environ.get("MYRUFLO_GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        secret_name = os.environ.get("MYRUFLO_SECRET_NAME", "MYRUFLO_EVL")
        fetched = _fetch_gcp_secret(project, secret_name)
        if fetched:
            return fetched, "secret-manager"

    return "", "unset"


@dataclass
class Config:
    api_key: str
    api_key_source: str = "unset"
    model_fast: str = "claude-haiku-4-5-20251001"
    model_default: str = "claude-sonnet-5"
    model_heavy: str = "claude-opus-4-8"
    workspace: Path = field(default_factory=lambda: Path("./workspace"))
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    allow_shell: bool = False
    max_turns: int = 25
    max_tokens: int = 4096
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    web_secret_key: str = ""

    @property
    def memory_db_path(self) -> Path:
        return self.data_dir / "memory.db"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def hooks_log_path(self) -> Path:
        return self.data_dir / "hooks.jsonl"

    def model_for_tier(self, tier: str) -> str:
        return {
            "fast": self.model_fast,
            "default": self.model_default,
            "heavy": self.model_heavy,
        }.get(tier, self.model_default)


def load_config(project_root: Path | None = None) -> Config:
    root = project_root or Path.cwd()
    _load_dotenv(root / ".env")

    api_key, api_key_source = _resolve_api_key()

    cfg = Config(
        api_key=api_key,
        api_key_source=api_key_source,
        model_fast=os.environ.get("MYRUFLO_MODEL_FAST", "claude-haiku-4-5-20251001"),
        model_default=os.environ.get("MYRUFLO_MODEL_DEFAULT", "claude-sonnet-5"),
        model_heavy=os.environ.get("MYRUFLO_MODEL_HEAVY", "claude-opus-4-8"),
        workspace=Path(os.environ.get("MYRUFLO_WORKSPACE", "./workspace")).resolve(),
        data_dir=Path(os.environ.get("MYRUFLO_DATA_DIR", "./data")).resolve(),
        allow_shell=_bool(os.environ.get("MYRUFLO_ALLOW_SHELL", "false")),
        max_turns=int(os.environ.get("MYRUFLO_MAX_TURNS", "25")),
        max_tokens=int(os.environ.get("MYRUFLO_MAX_TOKENS", "4096")),
        web_host=os.environ.get("MYRUFLO_WEB_HOST", "0.0.0.0"),
        web_port=int(os.environ.get("MYRUFLO_WEB_PORT", "8080")),
        web_secret_key=os.environ.get("WEB_SECRET_KEY", ""),
    )
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
