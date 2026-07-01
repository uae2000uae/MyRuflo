"""The core chat experience: conversations, messages, and running the
existing Orchestrator/Agent pipeline on behalf of a logged-in user.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMClient
from myruflo.memory.store import MemoryStore
from myruflo.swarm.orchestrator import Orchestrator
from myruflo.web import tool_settings
from myruflo.web.db import get_db
from myruflo.web.deps import require_login
from myruflo.web.templating import base_context, templates

router = APIRouter()

_MODE_TO_FORCE_SWARM = {"auto": None, "single": False, "swarm": True}


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    mode: str = "auto"


def _get_owned_conversation(conn: sqlite3.Connection, conversation_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


def _load_messages(conn: sqlite3.Connection, conversation_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
    ).fetchall()


@router.get("/")
def home(request: Request, user: sqlite3.Row = Depends(require_login), conn: sqlite3.Connection = Depends(get_db)):
    conversations = conn.execute(
        "SELECT id, title FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user["id"],)
    ).fetchone()
    if conversations is not None:
        return RedirectResponse(url=f"/chat/{conversations['id']}", status_code=303)
    return templates.TemplateResponse(
        request, "chat.html", base_context(user, conn, conversation=None, messages=[])
    )


@router.get("/chat/{conversation_id}")
def chat_page(
    conversation_id: int,
    request: Request,
    user: sqlite3.Row = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    conversation = _get_owned_conversation(conn, conversation_id, user["id"])
    messages = _load_messages(conn, conversation_id)
    return templates.TemplateResponse(
        request, "chat.html", base_context(user, conn, conversation=conversation, messages=messages)
    )


@router.post("/chat/new")
def new_conversation(user: sqlite3.Row = Depends(require_login), conn: sqlite3.Connection = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO conversations (user_id, title, created_at) VALUES (?, ?, ?)",
        (user["id"], "New conversation", now),
    )
    conn.commit()
    return RedirectResponse(url=f"/chat/{cursor.lastrowid}", status_code=303)


@router.post("/chat/{conversation_id}/message")
def post_message(
    conversation_id: int,
    payload: MessageRequest,
    request: Request,
    user: sqlite3.Row = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    conversation = _get_owned_conversation(conn, conversation_id, user["id"])
    config = request.app.state.config
    llm: LLMClient | None = request.app.state.llm
    if llm is None:
        raise HTTPException(
            status_code=500, detail="ANTHROPIC_API_KEY is not configured on the server — chat is unavailable."
        )

    force_swarm = _MODE_TO_FORCE_SWARM.get(payload.mode, None)
    enabled_tools = tool_settings.load_enabled_tools(conn)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, pipeline, created_at) VALUES (?, 'user', ?, NULL, ?)",
        (conversation_id, payload.text, now),
    )
    if conversation["title"] == "New conversation":
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (payload.text[:60], conversation_id)
        )
    conn.commit()

    memory = MemoryStore(config.memory_db_path)
    hooks = HooksManager(config.hooks_log_path, memory)
    orchestrator = Orchestrator(config, llm, memory, hooks)

    started = time.perf_counter()
    try:
        try:
            report = orchestrator.run(payload.text, force_swarm, enabled_tools=enabled_tools)
        except Exception as exc:  # noqa: BLE001 - surface any LLM/agent failure as a clean chat error
            raise HTTPException(status_code=502, detail=f"The agent failed to respond: {exc}") from exc
    finally:
        memory.close()
    duration_ms = int((time.perf_counter() - started) * 1000)

    assistant_now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, pipeline, created_at) "
        "VALUES (?, 'assistant', ?, ?, ?)",
        (conversation_id, report.final_text, " -> ".join(report.pipeline), assistant_now),
    )
    for result in report.results:
        conn.execute(
            "INSERT INTO task_runs "
            "(user_id, conversation_id, agent_role, task_snippet, success, turns_used, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user["id"],
                conversation_id,
                result.role,
                payload.text[:200],
                int(bool(result.final_text.strip())),
                result.turns_used,
                duration_ms // max(len(report.results), 1),
                assistant_now,
            ),
        )
    conn.commit()

    messages = _load_messages(conn, conversation_id)
    return templates.TemplateResponse(request, "_message_list.html", {"messages": messages})
