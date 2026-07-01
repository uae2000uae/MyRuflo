"""SQLite storage for the web app (accounts, conversations, stats, tool
toggles) — a separate database (`data/app.db`) from the agent's own
`memory.db`. Raw sqlite3, one fresh connection per request, matching the
style already used by `myruflo.memory.store.MemoryStore`.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request

from myruflo.web import tool_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL DEFAULT 'New conversation',
    created_at TEXT NOT NULL,
    status TEXT
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    pipeline TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    conversation_id INTEGER REFERENCES conversations(id),
    agent_role TEXT NOT NULL,
    task_snippet TEXT NOT NULL,
    success INTEGER NOT NULL,
    turns_used INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_runs_created ON task_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_task_runs_user ON task_runs(user_id);

CREATE TABLE IF NOT EXISTS tool_settings (
    tool_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    filename TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    kind TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Add a column to an existing table if it's missing. `CREATE TABLE IF NOT
    EXISTS` only helps for brand-new databases; existing ones need this to
    pick up columns added after they were first created — there's no formal
    migration framework here, so this lightweight ALTER is it.
    """
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        conn.commit()


def init_app_db(db_path: Path) -> None:
    """Create tables and seed tool_settings if missing. Safe to call on every startup."""
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _ensure_column(conn, "conversations", "status", "TEXT")
        tool_settings.seed_tool_settings(conn)
    finally:
        conn.close()


def sidebar_conversations(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, title FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
        (user_id,),
    ).fetchall()


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: a fresh connection per request, closed afterward."""
    conn = _connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()
