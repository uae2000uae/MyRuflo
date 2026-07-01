"""Chat file attachments: storage, classification, and conversion into
LLM-consumable content — inlined text for readable files, native Claude
vision blocks for images. Unsupported binary formats are stored but not
fed to the model beyond a note that they exist.
"""
from __future__ import annotations

import base64
import mimetypes
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import UploadFile

from myruflo.tools.file_ops import WorkspaceViolation, resolve_in_workspace

if TYPE_CHECKING:
    from myruflo.agents.agent import AgentResult

MAX_FILES_PER_MESSAGE = 5
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_INLINED_TEXT_CHARS = 20_000

_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.\-]")
_WRITE_TOOL_NAMES = {"write_file", "edit_file"}


class AttachmentError(ValueError):
    """Raised for any attachment validation failure; caught by the route
    handler and surfaced to the user as a 400."""


def _safe_filename(name: str) -> str:
    name = Path(name).name  # strip any directory components (path traversal guard)
    name = _UNSAFE_CHARS.sub("_", name)
    return name or "file"


def _classify(content_type: str | None, data: bytes) -> tuple[str, str | None]:
    """Return (kind, text) where kind is 'image' | 'text' | 'unsupported'."""
    if content_type in _IMAGE_CONTENT_TYPES:
        return "image", None
    try:
        return "text", data.decode("utf-8")
    except UnicodeDecodeError:
        return "unsupported", None


def save_attachments(
    files: list[UploadFile],
    *,
    conn: sqlite3.Connection,
    message_id: int,
    conversation_id: int,
    workspace: Path,
) -> tuple[list[dict], str]:
    """Persist uploaded files and insert attachment rows.

    Returns (image_content_blocks, inlined_text) ready to feed into the
    orchestrator/agent call for this message.
    """
    files = [f for f in files if f.filename]
    if len(files) > MAX_FILES_PER_MESSAGE:
        raise AttachmentError(f"Attach at most {MAX_FILES_PER_MESSAGE} files per message.")

    upload_dir = workspace / "uploads" / str(conversation_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    image_blocks: list[dict] = []
    inlined_parts: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    for upload in files:
        data = upload.file.read()
        if len(data) > MAX_FILE_BYTES:
            raise AttachmentError(f"'{upload.filename}' is larger than {MAX_FILE_BYTES // (1024 * 1024)}MB.")

        safe_name = _safe_filename(upload.filename)
        kind, text = _classify(upload.content_type, data)

        stored_path = upload_dir / f"{message_id}_{safe_name}"
        stored_path.write_bytes(data)

        conn.execute(
            "INSERT INTO attachments "
            "(message_id, filename, content_type, size_bytes, kind, stored_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, safe_name, upload.content_type, len(data), kind, str(stored_path), now),
        )

        if kind == "image":
            image_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": upload.content_type,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )
        elif kind == "text":
            truncated = text[:MAX_INLINED_TEXT_CHARS]
            suffix = "\n...[truncated]" if len(text) > MAX_INLINED_TEXT_CHARS else ""
            inlined_parts.append(
                f"--- Attached file: {safe_name} ---\n{truncated}{suffix}\n--- end of {safe_name} ---"
            )
        else:
            inlined_parts.append(f"(Attached file '{safe_name}' is a binary format that can't be read as text.)")

    conn.commit()
    return image_blocks, "\n\n".join(inlined_parts)


def list_for_message(conn: sqlite3.Connection, message_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM attachments WHERE message_id = ? ORDER BY id", (message_id,)
    ).fetchall()


def extract_generated_paths(results: list["AgentResult"]) -> list[str]:
    """Scan agent transcripts for write_file/edit_file tool calls and return
    the deduped workspace-relative paths they touched, in call order.
    """
    seen: list[str] = []
    for result in results:
        for message in result.transcript:
            if message.get("role") != "assistant":
                continue
            for block in message.get("content", []) or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") not in _WRITE_TOOL_NAMES:
                    continue
                path = block.get("input", {}).get("path")
                if path and path not in seen:
                    seen.append(path)
    return seen


def record_generated_files(
    conn: sqlite3.Connection, message_id: int, workspace: Path, relative_paths: list[str]
) -> None:
    """Record files the agent wrote/edited during this run as downloadable
    attachments on the assistant's reply.
    """
    now = datetime.now(timezone.utc).isoformat()
    for rel_path in relative_paths:
        try:
            resolved = resolve_in_workspace(workspace, rel_path)
        except WorkspaceViolation:
            continue
        if not resolved.is_file():
            continue
        content_type, _ = mimetypes.guess_type(resolved.name)
        conn.execute(
            "INSERT INTO attachments "
            "(message_id, filename, content_type, size_bytes, kind, stored_path, created_at) "
            "VALUES (?, ?, ?, ?, 'generated', ?, ?)",
            (message_id, resolved.name, content_type, resolved.stat().st_size, str(resolved), now),
        )
    conn.commit()
