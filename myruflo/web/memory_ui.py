"""Read-only browser for the agent's shared memory store — mirrors the
existing `myruflo memory list`/`myruflo memory search` CLI commands.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from myruflo.memory.store import MemoryStore
from myruflo.web.db import get_db
from myruflo.web.deps import require_login
from myruflo.web.templating import base_context, templates

router = APIRouter(prefix="/memory")


@router.get("")
def memory_page(
    request: Request,
    namespace: str = "",
    q: str = "",
    top_k: int = 5,
    user: sqlite3.Row = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    config = request.app.state.config
    memory = MemoryStore(config.memory_db_path)
    try:
        namespaces = [{"name": ns, "count": memory.count(ns)} for ns in memory.list_namespaces()]
        results = memory.search(namespace, q, top_k) if namespace and q else []
    finally:
        memory.close()

    return templates.TemplateResponse(
        request,
        "memory.html",
        base_context(
            user, conn, namespaces=namespaces, results=results, query=q, selected_namespace=namespace, top_k=top_k
        ),
    )
