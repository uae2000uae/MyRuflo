import json
from pathlib import Path

from myruflo.hooks.manager import HooksManager
from myruflo.memory.store import MemoryStore


def test_post_task_stores_pattern_and_pre_task_recalls_it(tmp_path: Path):
    memory = MemoryStore(tmp_path / "memory.db")
    hooks = HooksManager(tmp_path / "hooks.jsonl", memory)

    hooks.post_task(
        "coder", "fix the null pointer bug in the parser", success=True, summary="patched parser.py line 42"
    )

    hint = hooks.pre_task("coder", "there's a null pointer bug in the parser again")
    assert "parser.py line 42" in hint

    log_lines = (tmp_path / "hooks.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in log_lines]
    assert events[0]["type"] == "post_task"
    assert events[1]["type"] == "pre_task"
    memory.close()


def test_pre_task_returns_empty_hint_when_nothing_relevant(tmp_path: Path):
    memory = MemoryStore(tmp_path / "memory.db")
    hooks = HooksManager(tmp_path / "hooks.jsonl", memory)
    assert hooks.pre_task("coder", "totally novel task with no history") == ""
    memory.close()
