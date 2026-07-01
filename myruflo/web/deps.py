"""Auth dependencies. Enforced server-side on every protected route — this,
not link visibility, is what actually keeps the admin panel hidden.
"""
from __future__ import annotations

import sqlite3

from fastapi import Depends, HTTPException, Request

from myruflo.web.db import get_db


class NotAuthenticated(Exception):
    """Raised by require_login; an app-level handler turns this into a redirect to /login."""


def get_current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def require_login(user: sqlite3.Row | None = Depends(get_current_user)) -> sqlite3.Row:
    if user is None:
        raise NotAuthenticated()
    return user


def require_admin(user: sqlite3.Row = Depends(require_login)) -> sqlite3.Row:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user
