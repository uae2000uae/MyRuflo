"""SQLite-backed vector memory store.

Small-scale by design (loads a namespace's vectors into memory to score
cosine similarity) — fine for thousands of entries on a local machine. If
MyRuflo's memory grows past that, swap this for a real vector DB behind the
same `add`/`search` interface.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from myruflo.memory.embedding import cosine_similarity, embed


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_namespace ON memory(namespace)")
        self._conn.commit()

    def add(self, namespace: str, text: str) -> None:
        vector = embed(text)
        self._conn.execute(
            "INSERT INTO memory (namespace, text, vector, created_at) VALUES (?, ?, ?, ?)",
            (namespace, text, vector.tobytes(), datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def search(self, namespace: str, query: str, top_k: int = 5) -> list[tuple[float, str]]:
        query_vec = embed(query)
        cursor = self._conn.execute(
            "SELECT text, vector FROM memory WHERE namespace = ?", (namespace,)
        )
        scored: list[tuple[float, str]] = []
        for text, vector_blob in cursor.fetchall():
            vector = np.frombuffer(vector_blob, dtype=np.float32)
            scored.append((cosine_similarity(query_vec, vector), text))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]

    def list_namespaces(self) -> list[str]:
        cursor = self._conn.execute("SELECT DISTINCT namespace FROM memory ORDER BY namespace")
        return [row[0] for row in cursor.fetchall()]

    def count(self, namespace: str | None = None) -> int:
        if namespace:
            cursor = self._conn.execute("SELECT COUNT(*) FROM memory WHERE namespace = ?", (namespace,))
        else:
            cursor = self._conn.execute("SELECT COUNT(*) FROM memory")
        return cursor.fetchone()[0]

    def close(self) -> None:
        self._conn.close()
