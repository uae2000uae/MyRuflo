"""Admin page for AI platforms: edit each platform's Google Secret Manager
secret ID, activate it live (no restart), and run a connectivity test.

Admin-only, same require_admin gate as the rest of /admin.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from myruflo.llm.specs import PROVIDER_SPECS
from myruflo.web import platform_settings
from myruflo.web.db import get_db
from myruflo.web.deps import require_admin
from myruflo.web.templating import base_context, templates

router = APIRouter(prefix="/admin/platforms")


def _rebuild_router(request: Request, conn: sqlite3.Connection):
    config = request.app.state.config
    new_router, errors = platform_settings.build_router_with_overrides(config, conn)
    request.app.state.router = new_router
    # Keep the legacy default client in sync so chat works even without an
    # Anthropic env key.
    if new_router is not None and getattr(request.app.state, "llm", None) is None:
        request.app.state.llm = new_router.providers[new_router.default_provider].client
    return new_router, errors


@router.get("")
def platforms_page(
    request: Request, user: sqlite3.Row = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    config = request.app.state.config
    current_router = getattr(request.app.state, "router", None)
    rows = platform_settings.platform_rows(config, conn, current_router)
    return templates.TemplateResponse(
        request,
        "admin_platforms.html",
        base_context(
            user,
            conn,
            platforms=rows,
            gcp_project=platform_settings.gcp_project(),
        ),
    )


@router.post("/{provider}/secret")
def save_and_activate(
    provider: str,
    request: Request,
    secret_id: str = Form(""),
    user: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Save the platform's Secret Manager secret ID and activate it now.

    An empty secret_id clears the admin override (the platform falls back to
    env vars / default secret IDs, or deactivates).
    """
    if provider not in PROVIDER_SPECS:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{provider}'")

    platform_settings.save_secret_id(conn, provider, secret_id, user["id"])
    new_router, errors = _rebuild_router(request, conn)

    active = new_router is not None and provider in new_router.providers
    handle = new_router.providers.get(provider) if new_router is not None else None
    return {
        "ok": provider not in errors,
        "active": active,
        "key_source": handle.key_source if handle else "unset",
        "error": errors.get(provider),
    }


@router.post("/{provider}/test")
def test_connectivity(
    provider: str,
    request: Request,
    user: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Live connectivity test: one tiny completion on the platform's fast
    model. Proves the secret ID resolves to a working key."""
    if provider not in PROVIDER_SPECS:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{provider}'")

    current_router = getattr(request.app.state, "router", None)
    handle = current_router.providers.get(provider) if current_router is not None else None
    if handle is None:
        return {
            "ok": False,
            "latency_ms": 0,
            "model": "",
            "message": "Platform is not active — save a working secret ID (or set its API key) first.",
        }
    return platform_settings.ping_provider(handle)
