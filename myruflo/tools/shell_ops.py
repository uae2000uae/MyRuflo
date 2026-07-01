"""Shell execution tool.

Off by default (MYRUFLO_ALLOW_SHELL=false). When enabled, commands run with
cwd pinned to the workspace root, under a timeout, with a denylist for
obviously catastrophic commands. This is a guardrail, not a sandbox — only
enable it in a workspace you're comfortable letting an LLM operate in.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

MAX_OUTPUT_CHARS = 20_000

_DENYLIST = [
    r"rm\s+-rf\s+/(\s|$)",
    r"rm\s+-rf\s+~",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}",  # fork bomb
    r"mkfs\.",
    r">\s*/dev/sd",
    r"del\s+/[fsq]+.*[a-zA-Z]:\\\\?\s*$",
    r"format\s+[a-zA-Z]:",
    r"shutdown\b",
    r"Remove-Item.*-Recurse.*-Force.*[a-zA-Z]:\\\\?\s*$",
]
_DENY_RE = re.compile("|".join(_DENYLIST), re.IGNORECASE)


def run_shell(workspace: Path, command: str, allow_shell: bool, timeout: int = 30) -> str:
    if not allow_shell:
        return (
            "ERROR: shell execution is disabled. Set MYRUFLO_ALLOW_SHELL=true "
            "in .env to enable it for this workspace."
        )
    if _DENY_RE.search(command):
        return "ERROR: command blocked by safety denylist (looks destructive)"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"

    output = f"exit_code={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return output
