"""Admin-editable Secret Manager IDs per AI platform.

Stores each platform's Google Secret Manager secret ID in the app DB
(`platform_settings` table), so an admin can activate a platform from the
web UI the moment its secret exists — no redeploy, no .env edit. The
resolved keys are merged over the config/env-resolved ones (an admin-set
secret ID always wins for its platform) and the app's router is rebuilt.

Kept free of FastAPI imports so it can be unit-tested standalone (same
pattern as tool_settings.py).
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import replace
from datetime import datetime, timezone

from myruflo.config import Config, _fetch_gcp_secret
from myruflo.llm.specs import PROVIDER_SPECS


def gcp_project() -> str:
    return os.environ.get("MYRUFLO_GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or ""


def load_secret_ids(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT provider, secret_id FROM platform_settings").fetchall()
    return {row["provider"]: row["secret_id"] for row in rows if row["secret_id"]}


def save_secret_id(conn: sqlite3.Connection, provider: str, secret_id: str, admin_user_id: int) -> None:
    if provider not in PROVIDER_SPECS:
        raise ValueError(f"Unknown platform '{provider}'")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO platform_settings (provider, secret_id, updated_at, updated_by) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(provider) DO UPDATE SET "
        "secret_id = excluded.secret_id, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
        (provider, secret_id.strip(), now, admin_user_id),
    )
    conn.commit()


def resolve_overridden_keys(
    config: Config, secret_ids: dict[str, str]
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Merge admin-set secret IDs over the config-resolved provider keys.

    Returns (provider_keys, errors): errors maps provider -> human-readable
    reason why its admin-set secret ID could not be turned into a key.
    """
    keys: dict[str, tuple[str, str]] = dict(config.provider_keys)
    # Older/lean Config objects may carry only api_key — seed anthropic from it.
    if not any(key for key, _ in keys.values()) and config.api_key:
        keys["anthropic"] = (config.api_key, config.api_key_source)

    errors: dict[str, str] = {}
    project = gcp_project()
    for name, secret_id in secret_ids.items():
        if name not in PROVIDER_SPECS or not secret_id:
            continue
        if not project:
            errors[name] = (
                "No GCP project detected — set MYRUFLO_GCP_PROJECT in .env "
                "(automatic on Cloud Run via GOOGLE_CLOUD_PROJECT)."
            )
            continue
        fetched = _fetch_gcp_secret(project, secret_id)
        if fetched:
            keys[name] = (fetched, f"secret-manager:{secret_id} (admin)")
        else:
            errors[name] = (
                f"Could not read secret '{secret_id}' from project '{project}' — "
                "check the secret exists, the runner has secretmanager.secretAccessor, "
                "and google-cloud-secret-manager is installed."
            )
    return keys, errors


def build_router_with_overrides(config: Config, conn: sqlite3.Connection):
    """Rebuild the LLM router with admin-set secret IDs applied.

    Returns (router | None, errors). Never raises.
    """
    from myruflo.llm.router import build_router

    try:
        secret_ids = load_secret_ids(conn)
    except sqlite3.Error:
        secret_ids = {}
    keys, errors = resolve_overridden_keys(config, secret_ids)
    try:
        router = build_router(replace(config, provider_keys=keys))
    except Exception as exc:  # noqa: BLE001 - activation must never take the app down
        return None, {**errors, "_router": str(exc)}
    return router, errors


def ping_provider(handle) -> dict:
    """Live connectivity test: one tiny completion against the platform's
    fast-tier model. Returns {ok, latency_ms, model, message}."""
    model = handle.model_for_tier("fast")
    started = time.perf_counter()
    try:
        response = handle.client.call(
            model=model,
            system="You are a connectivity check. Reply with the single word OK.",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=8,
        )
    except Exception as exc:  # noqa: BLE001 - report any failure as a test result
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "latency_ms": latency_ms, "model": model, "message": str(exc)[:300]}
    latency_ms = int((time.perf_counter() - started) * 1000)
    reply = (response.text or "").strip()[:80]
    return {"ok": True, "latency_ms": latency_ms, "model": model, "message": reply or "(empty reply)"}


def platform_rows(config: Config, conn: sqlite3.Connection, router) -> list[dict]:
    """Everything the admin page needs to render, one row per platform."""
    secret_ids = load_secret_ids(conn)
    saved_rows = {
        row["provider"]: row for row in conn.execute("SELECT * FROM platform_settings").fetchall()
    }
    rows = []
    for name, spec in PROVIDER_SPECS.items():
        handle = router.providers.get(name) if router is not None else None
        env_key, env_source = (config.provider_keys or {}).get(name, ("", "unset"))
        if handle is not None:
            source = handle.key_source
        elif env_key:
            source = env_source
        else:
            source = "unset"
        rows.append(
            {
                "name": name,
                "label": spec.label,
                "active": handle is not None,
                "key_source": source,
                "secret_id": secret_ids.get(name, ""),
                "default_secret_ids": ", ".join(spec.secret_names),
                "fast_model": (handle.model_for_tier("fast") if handle else spec.default_models["fast"]),
                "updated_at": saved_rows[name]["updated_at"] if name in saved_rows else None,
            }
        )
    return rows
