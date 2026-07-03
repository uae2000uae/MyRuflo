"""The core chat experience: conversations, messages, file attachments, and
running the existing Orchestrator/Agent pipeline on behalf of a logged-in
user.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMClient
from myruflo.memory.store import MemoryStore
from myruflo.swarm.orchestrator import Orchestrator
from myruflo.web import attachments as attachments_module
from myruflo.web import tool_settings
from myruflo.web.db import get_db
from myruflo.web.deps import require_login
from myruflo.web.templating import base_context, templates

router = APIRouter()

_MODE_TO_FORCE_SWARM = {"auto": None, "single": False, "swarm": True}

_ENHANCE_SYSTEM_PROMPT = (
    "You improve draft prompts for an AI coding/research assistant. Rewrite the "
    "user's draft to be clearer, more specific, and more actionable, preserving "
    "their original intent, technical details, and language. Return ONLY the "
    "rewritten prompt text — no preamble, no quotes, no commentary."
)


class EnhanceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


def _get_owned_conversation(conn: sqlite3.Connection, conversation_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


def _load_messages(conn: sqlite3.Connection, conversation_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
    ).fetchall()
    messages = []
    for row in rows:
        atts = attachments_module.list_for_message(conn, row["id"])
        messages.append(
            {
                **dict(row),
                "attachments": [a for a in atts if a["kind"] != "generated"],
                "generated_files": [a for a in atts if a["kind"] == "generated"],
            }
        )
    return messages


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


@router.get("/chat/{conversation_id}/attachments/{attachment_id}")
def get_attachment(
    conversation_id: int,
    attachment_id: int,
    user: sqlite3.Row = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    _get_owned_conversation(conn, conversation_id, user["id"])
    row = conn.execute(
        "SELECT attachments.* FROM attachments "
        "JOIN messages ON messages.id = attachments.message_id "
        "WHERE attachments.id = ? AND messages.conversation_id = ?",
        (attachment_id, conversation_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        row["stored_path"], media_type=row["content_type"] or "application/octet-stream", filename=row["filename"]
    )


@router.get("/chat/{conversation_id}/status")
def get_status(
    conversation_id: int,
    user: sqlite3.Row = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Polled by the composer while a message is in flight, to drive a single
    live status line instead of a static 'working on it' message."""
    conversation = _get_owned_conversation(conn, conversation_id, user["id"])
    return {"status": conversation["status"]}


@router.post("/chat/{conversation_id}/enhance")
def enhance_message(
    conversation_id: int,
    payload: EnhanceRequest,
    request: Request,
    user: sqlite3.Row = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Rewrite the user's draft into a clearer prompt via a single quick LLM
    call — no tool use, no orchestrator pipeline, just a fast-tier completion.
    """
    _get_owned_conversation(conn, conversation_id, user["id"])
    config = request.app.state.config
    llm: LLMClient | None = request.app.state.llm
    router = getattr(request.app.state, "router", None)
    if llm is None and router is None:
        raise HTTPException(status_code=500, detail="No AI platform API key is configured on the server.")

    if router is not None:
        route = router.route("fast", "writing")
        client, model = route.client, route.model
    else:
        client, model = llm, config.model_for_tier("fast")

    try:
        response = client.call(
            model=model,
            system=_ENHANCE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload.text}],
            max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001 - surface any LLM failure as a clean error
        raise HTTPException(status_code=502, detail=f"Could not enhance the prompt: {exc}") from exc

    return {"text": response.text.strip()}


@router.post("/chat/{conversation_id}/message")
def post_message(
    conversation_id: int,
    request: Request,
    text: str = Form(..., min_length=1, max_length=8000),
    mode: str = Form("auto"),
    files: list[UploadFile] = File(default=[]),
    user: sqlite3.Row = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    conversation = _get_owned_conversation(conn, conversation_id, user["id"])
    config = request.app.state.config
    llm: LLMClient | None = request.app.state.llm
    router = getattr(request.app.state, "router", None)
    if llm is None and router is None:
        raise HTTPException(
            status_code=500, detail="No AI platform API key is configured on the server — chat is unavailable."
        )

    force_swarm = _MODE_TO_FORCE_SWARM.get(mode, None)
    enabled_tools = tool_settings.load_enabled_tools(conn)

    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, pipeline, created_at) VALUES (?, 'user', ?, NULL, ?)",
        (conversation_id, text, now),
    )
    user_message_id = cursor.lastrowid
    if conversation["title"] == "New conversation":
        conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (text[:60], conversation_id))
    conn.commit()

    image_blocks: list[dict] = []
    inlined_text = ""
    if files:
        try:
            image_blocks, inlined_text = attachments_module.save_attachments(
                files,
                conn=conn,
                message_id=user_message_id,
                conversation_id=conversation_id,
                workspace=config.workspace,
            )
        except attachments_module.AttachmentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_text = f"{text}\n\n{inlined_text}" if inlined_text else text

    memory = MemoryStore(config.memory_db_path)
    hooks = HooksManager(config.hooks_log_path, memory)
    orchestrator = Orchestrator(config, llm, memory, hooks, router=router)

    def _update_status(status_text: str) -> None:
        conn.execute("UPDATE conversations SET status = ? WHERE id = ?", (status_text, conversation_id))
        conn.commit()

    started = time.perf_counter()
    try:
        try:
            report = orchestrator.run(
                task_text,
                force_swarm,
                enabled_tools=enabled_tools,
                image_attachments=image_blocks or None,
                on_progress=_update_status,
            )
        except Exception as exc:  # noqa: BLE001 - surface any LLM/agent failure as a clean chat error
            raise HTTPException(status_code=502, detail=f"The agent failed to respond: {exc}") from exc
    finally:
        memory.close()
        conn.execute("UPDATE conversations SET status = NULL WHERE id = ?", (conversation_id,))
        conn.commit()
    duration_ms = int((time.perf_counter() - started) * 1000)

    assistant_now = datetime.now(timezone.utc).isoformat()
    assistant_cursor = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, pipeline, created_at) "
        "VALUES (?, 'assistant', ?, ?, ?)",
        (conversation_id, report.final_text, " -> ".join(report.pipeline), assistant_now),
    )
    assistant_message_id = assistant_cursor.lastrowid

    generated_paths = attachments_module.extract_generated_paths(report.results)
    if generated_paths:
        attachments_module.record_generated_files(conn, assistant_message_id, config.workspace, generated_paths)

    for result in report.results:
        conn.execute(
            "INSERT INTO task_runs "
            "(user_id, conversation_id, agent_role, task_snippet, success, turns_used, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user["id"],
                conversation_id,
                result.role,
                text[:200],
                int(bool(result.final_text.strip())),
                result.turns_used,
                duration_ms // max(len(report.results), 1),
                assistant_now,
            ),
        )
    conn.commit()

    messages = _load_messages(conn, conversation_id)
    return templates.TemplateResponse(request, "_message_list.html", {"messages": messages})
