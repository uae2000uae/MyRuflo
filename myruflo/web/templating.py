"""Shared Jinja2 environment + a context helper so every page gets the
sidebar's conversation list without repeating the same query everywhere.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from starlette.templating import Jinja2Templates

from myruflo.web.db import sidebar_conversations

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def base_context(
    user: sqlite3.Row | None, conn: sqlite3.Connection | None = None, **extra: Any
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "user": user,
        "conversations": sidebar_conversations(conn, user["id"]) if user and conn else [],
    }
    context.update(extra)
    return context
