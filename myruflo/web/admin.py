"""The hidden admin control panel: usage dashboard + agent tool availability.

Every route here depends on `require_admin`, so it 403s for anyone whose
account role isn't 'admin' — that server-side check, not the absence of a
nav link, is what actually keeps this section hidden.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from myruflo.web import tool_settings
from myruflo.web.db import get_db
from myruflo.web.deps import require_admin
from myruflo.web.templating import base_context, templates

router = APIRouter(prefix="/admin")


@router.get("")
def dashboard(
    request: Request, user: sqlite3.Row = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    today = datetime.now(timezone.utc).date().isoformat()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    total_users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    total_conversations = conn.execute("SELECT COUNT(*) AS n FROM conversations").fetchone()["n"]
    tasks_today = conn.execute(
        "SELECT COUNT(*) AS n FROM task_runs WHERE created_at >= ?", (today,)
    ).fetchone()["n"]

    week_row = conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(success), 0) AS succeeded "
        "FROM task_runs WHERE created_at >= ?",
        (week_ago,),
    ).fetchone()
    tasks_7d = week_row["total"]
    success_rate_7d = round(100 * week_row["succeeded"] / tasks_7d) if tasks_7d else None

    recent = conn.execute(
        "SELECT task_runs.*, users.name AS user_name, users.email AS user_email "
        "FROM task_runs JOIN users ON users.id = task_runs.user_id "
        "ORDER BY task_runs.id DESC LIMIT 25"
    ).fetchall()

    stats = {
        "total_users": total_users,
        "total_conversations": total_conversations,
        "tasks_today": tasks_today,
        "tasks_7d": tasks_7d,
        "success_rate_7d": success_rate_7d,
    }
    return templates.TemplateResponse(
        request, "admin_dashboard.html", base_context(user, conn, stats=stats, recent=recent)
    )


@router.get("/tools")
def tools_page(
    request: Request, user: sqlite3.Row = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    tools = tool_settings.list_tools_with_state(conn)
    return templates.TemplateResponse(request, "admin_tools.html", base_context(user, conn, tools=tools))


@router.post("/tools/{tool_name}/toggle")
def toggle_tool(
    tool_name: str, user: sqlite3.Row = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    tool_settings.toggle(conn, tool_name, user["id"])
    return RedirectResponse(url="/admin/tools", status_code=303)


@router.get("/users")
def users_page(
    request: Request, user: sqlite3.Row = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    users = conn.execute(
        "SELECT users.*, "
        "(SELECT COUNT(*) FROM conversations WHERE conversations.user_id = users.id) AS conversation_count "
        "FROM users ORDER BY users.created_at"
    ).fetchall()
    return templates.TemplateResponse(request, "admin_users.html", base_context(user, conn, users=users))
