from pathlib import Path

import pytest

from myruflo.tools import file_ops, shell_ops
from myruflo.tools.registry import execute_tool


def test_write_then_read_round_trip(tmp_path: Path):
    file_ops.write_file(tmp_path, "notes.txt", "hello world")
    content = file_ops.read_file(tmp_path, "notes.txt")
    assert "hello world" in content


def test_read_missing_file_reports_error(tmp_path: Path):
    assert "ERROR" in file_ops.read_file(tmp_path, "missing.txt")


def test_edit_file_requires_unique_match(tmp_path: Path):
    file_ops.write_file(tmp_path, "a.py", "x = 1\nx = 1\n")
    result = file_ops.edit_file(tmp_path, "a.py", "x = 1", "x = 2")
    assert "not unique" in result


def test_edit_file_replaces_unique_match(tmp_path: Path):
    file_ops.write_file(tmp_path, "a.py", "def foo():\n    return 1\n")
    result = file_ops.edit_file(tmp_path, "a.py", "return 1", "return 2")
    assert result.startswith("OK")
    assert "return 2" in (tmp_path / "a.py").read_text()


def test_path_traversal_is_blocked(tmp_path: Path):
    with pytest.raises(file_ops.WorkspaceViolation):
        file_ops.resolve_in_workspace(tmp_path, "../outside.txt")


def test_glob_and_grep(tmp_path: Path):
    file_ops.write_file(tmp_path, "src/main.py", "def handler():\n    pass\n")
    assert "src/main.py" in file_ops.glob_search(tmp_path, "**/*.py")
    assert "handler" in file_ops.grep_search(tmp_path, "def handler")


def test_shell_disabled_by_default(tmp_path: Path):
    result = shell_ops.run_shell(tmp_path, "echo hi", allow_shell=False)
    assert "disabled" in result


def test_shell_denylist_blocks_destructive_commands(tmp_path: Path):
    result = shell_ops.run_shell(tmp_path, "rm -rf /", allow_shell=True)
    assert "blocked" in result


def test_registry_dispatches_read_file(tmp_path: Path):
    file_ops.write_file(tmp_path, "x.txt", "data")
    result = execute_tool(
        "read_file", {"path": "x.txt"}, workspace=tmp_path, allow_shell=False, memory=None
    )
    assert "data" in result


def test_registry_unknown_tool(tmp_path: Path):
    result = execute_tool("nonexistent", {}, workspace=tmp_path, allow_shell=False, memory=None)
    assert "unknown tool" in result
