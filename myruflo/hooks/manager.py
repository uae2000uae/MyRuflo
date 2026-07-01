"""Pre/post-task hooks — the simplified self-learning loop.

Every task run is logged to an append-only JSONL file. Successful runs are
also distilled into the memory store's "patterns" namespace; the next
`pre_task` call for a similar task surfaces those as hints, so agents get
better with repeated use without any actual model fine-tuning.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from myruflo.memory.store import MemoryStore

PATTERNS_NAMESPACE = "patterns"
RELEVANCE_THRESHOLD = 0.15


class HooksManager:
    def __init__(self, log_path: Path, memory: MemoryStore) -> None:
        self._log_path = log_path
        self._memory = memory

    def _append(self, event: dict) -> None:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def pre_task(self, role: str, task: str) -> str:
        """Log task start; return a hint string built from similar past outcomes."""
        self._append({"type": "pre_task", "role": role, "task": task})
        hits = self._memory.search(PATTERNS_NAMESPACE, task, top_k=3)
        relevant = [text for score, text in hits if score > RELEVANCE_THRESHOLD]
        if not relevant:
            return ""
        return "Relevant lessons from past tasks:\n" + "\n".join(f"- {r}" for r in relevant)

    def post_task(self, role: str, task: str, success: bool, summary: str) -> None:
        self._append(
            {"type": "post_task", "role": role, "task": task, "success": success, "summary": summary}
        )
        if success and summary:
            pattern = f"[{role}] task: {task[:200]} -> outcome: {summary[:400]}"
            self._memory.add(PATTERNS_NAMESPACE, pattern)
