"""File tools, sandboxed to a workspace root.

Every path an agent supplies is resolved relative to the workspace and
checked to still be inside it — agents cannot read/write outside the
configured MYRUFLO_WORKSPACE directory.
"""
from __future__ import annotations

from pathlib import Path

MAX_READ_BYTES = 200_000


class WorkspaceViolation(ValueError):
    pass


def resolve_in_workspace(workspace: Path, rel_path: str) -> Path:
    candidate = (workspace / rel_path).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        raise WorkspaceViolation(
            f"Path '{rel_path}' escapes the workspace root ({workspace})"
        ) from None
    return candidate


def read_file(workspace: Path, path: str) -> str:
    target = resolve_in_workspace(workspace, path)
    if not target.is_file():
        return f"ERROR: file not found: {path}"
    data = target.read_bytes()
    if len(data) > MAX_READ_BYTES:
        data = data[:MAX_READ_BYTES]
        suffix = f"\n...[truncated, file exceeds {MAX_READ_BYTES} bytes]"
    else:
        suffix = ""
    text = data.decode("utf-8", errors="replace")
    numbered = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(text.splitlines()))
    return numbered + suffix


def write_file(workspace: Path, path: str, content: str) -> str:
    target = resolve_in_workspace(workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"OK: wrote {len(content)} bytes to {path}"


def edit_file(workspace: Path, path: str, old_string: str, new_string: str) -> str:
    target = resolve_in_workspace(workspace, path)
    if not target.is_file():
        return f"ERROR: file not found: {path}"
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return "ERROR: old_string not found in file"
    if count > 1:
        return f"ERROR: old_string is not unique ({count} occurrences) — provide more context"
    target.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
    return f"OK: edited {path}"


def list_dir(workspace: Path, path: str = ".") -> str:
    target = resolve_in_workspace(workspace, path)
    if not target.is_dir():
        return f"ERROR: not a directory: {path}"
    entries = []
    for child in sorted(target.iterdir()):
        marker = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{marker}")
    return "\n".join(entries) if entries else "(empty)"


def glob_search(workspace: Path, pattern: str, path: str = ".") -> str:
    base = resolve_in_workspace(workspace, path)
    matches = sorted(p.relative_to(workspace.resolve()).as_posix() for p in base.glob(pattern))
    return "\n".join(matches) if matches else "(no matches)"


def grep_search(
    workspace: Path,
    pattern: str,
    glob: str = "**/*",
    path: str = ".",
    max_results: int = 200,
) -> str:
    import re

    base = resolve_in_workspace(workspace, path)
    regex = re.compile(pattern)
    results: list[str] = []
    for file_path in sorted(base.glob(glob)):
        if not file_path.is_file() or len(results) >= max_results:
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = file_path.relative_to(workspace.resolve()).as_posix()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                results.append(f"{rel}:{line_no}: {line.strip()}")
                if len(results) >= max_results:
                    break
    return "\n".join(results) if results else "(no matches)"
