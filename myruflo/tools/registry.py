"""Wires tool schemas to their Python implementations."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from myruflo.tools import file_ops, shell_ops
from myruflo.tools.schemas import FILE_TOOL_SCHEMAS, MEMORY_TOOL_SCHEMAS, SHELL_TOOL_SCHEMA

if TYPE_CHECKING:
    from myruflo.memory.store import MemoryStore


def build_tool_schemas(*, include_shell: bool, include_memory: bool) -> list[dict]:
    schemas = list(FILE_TOOL_SCHEMAS)
    if include_shell:
        schemas.append(SHELL_TOOL_SCHEMA)
    if include_memory:
        schemas.extend(MEMORY_TOOL_SCHEMAS)
    return schemas


def execute_tool(
    name: str,
    tool_input: dict[str, Any],
    *,
    workspace: Path,
    allow_shell: bool,
    memory: "MemoryStore | None" = None,
) -> str:
    try:
        if name == "read_file":
            return file_ops.read_file(workspace, tool_input["path"])
        if name == "write_file":
            return file_ops.write_file(workspace, tool_input["path"], tool_input["content"])
        if name == "edit_file":
            return file_ops.edit_file(
                workspace, tool_input["path"], tool_input["old_string"], tool_input["new_string"]
            )
        if name == "list_dir":
            return file_ops.list_dir(workspace, tool_input.get("path", "."))
        if name == "glob_search":
            return file_ops.glob_search(workspace, tool_input["pattern"], tool_input.get("path", "."))
        if name == "grep_search":
            return file_ops.grep_search(
                workspace,
                tool_input["pattern"],
                tool_input.get("glob", "**/*"),
                tool_input.get("path", "."),
            )
        if name == "run_shell":
            return shell_ops.run_shell(
                workspace, tool_input["command"], allow_shell, tool_input.get("timeout", 30)
            )
        if name == "memory_store":
            if memory is None:
                return "ERROR: memory is not available in this context"
            memory.add(tool_input["namespace"], tool_input["text"])
            return "OK: stored"
        if name == "memory_search":
            if memory is None:
                return "ERROR: memory is not available in this context"
            hits = memory.search(tool_input["namespace"], tool_input["query"], tool_input.get("top_k", 5))
            if not hits:
                return "(no matching memories)"
            return "\n---\n".join(f"[score={score:.3f}] {text}" for score, text in hits)
        return f"ERROR: unknown tool '{name}'"
    except file_ops.WorkspaceViolation as exc:
        return f"ERROR: {exc}"
    except KeyError as exc:
        return f"ERROR: missing required argument {exc}"
