"""Admin-controlled availability of the agent's own tools.

Seeds/reads/writes the `tool_settings` table. `load_enabled_tools` is what
the chat flow calls before running the orchestrator, to pass the current
set of enabled tool names all the way down to `Agent.run`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from myruflo.tools.schemas import FILE_TOOL_SCHEMAS, SHELL_TOOL_SCHEMA

TOGGLEABLE_TOOLS = [schema["name"] for schema in FILE_TOOL_SCHEMAS] + [SHELL_TOOL_SCHEMA["name"]]

_DESCRIPTIONS = {schema["name"]: schema["description"] for schema in [*FILE_TOOL_SCHEMAS, SHELL_TOOL_SCHEMA]}

# run_shell is off by default, matching MYRUFLO_ALLOW_SHELL's default of false.
_DEFAULT_ENABLED = {name: (name != "run_shell") for name in TOGGLEABLE_TOOLS}


def seed_tool_settings(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for name in TOGGLEABLE_TOOLS:
        conn.execute(
            "INSERT OR IGNORE INTO tool_settings (tool_name, enabled, updated_at, updated_by) "
            "VALUES (?, ?, ?, NULL)",
            (name, int(_DEFAULT_ENABLED[name]), now),
        )
    conn.commit()


def load_enabled_tools(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT tool_name FROM tool_settings WHERE enabled = 1").fetchall()
    return {row["tool_name"] for row in rows}


def list_tools_with_state(conn: sqlite3.Connection) -> list[dict]:
    rows = {row["tool_name"]: row for row in conn.execute("SELECT * FROM tool_settings").fetchall()}
    return [
        {
            "name": name,
            "description": _DESCRIPTIONS[name],
            "enabled": bool(rows[name]["enabled"]) if name in rows else _DEFAULT_ENABLED[name],
            "updated_at": rows[name]["updated_at"] if name in rows else None,
        }
        for name in TOGGLEABLE_TOOLS
    ]


def toggle(conn: sqlite3.Connection, tool_name: str, admin_user_id: int) -> None:
    if tool_name not in TOGGLEABLE_TOOLS:
        raise ValueError(f"Unknown tool '{tool_name}'")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE tool_settings SET enabled = 1 - enabled, updated_at = ?, updated_by = ? WHERE tool_name = ?",
        (now, admin_user_id, tool_name),
    )
    conn.commit()
