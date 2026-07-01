"""FastAPI application factory for the MyRuflo web UI."""
from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from myruflo.config import Config
from myruflo.llm.client import LLMClient
from myruflo.web import admin, auth, chat, memory_ui, settings
from myruflo.web.db import init_app_db
from myruflo.web.deps import NotAuthenticated
from myruflo.web.templating import STATIC_DIR, templates


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="MyRuflo")

    secret_key = config.web_secret_key or secrets.token_hex(32)
    if not config.web_secret_key:
        print(
            "WARNING: WEB_SECRET_KEY is not set - using a random ephemeral key for this process. "
            "Sessions will not survive a restart. Set WEB_SECRET_KEY in .env for real use."
        )
    app.add_middleware(SessionMiddleware, secret_key=secret_key, same_site="lax")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.state.config = config
    app.state.db_path = config.app_db_path
    try:
        app.state.llm = LLMClient(config.api_key) if config.api_key else None
    except ValueError:
        app.state.llm = None

    init_app_db(config.app_db_path)

    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    app.include_router(settings.router)
    app.include_router(memory_ui.router)

    @app.exception_handler(NotAuthenticated)
    async def _redirect_to_login(request: Request, exc: NotAuthenticated) -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 403:
            return templates.TemplateResponse(request, "errors/403.html", {"user": None}, status_code=403)
        if exc.status_code == 404:
            return templates.TemplateResponse(request, "errors/404.html", {"user": None}, status_code=404)
        return await default_http_exception_handler(request, exc)

    return app
