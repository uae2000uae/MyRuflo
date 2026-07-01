"""Per-user profile/password settings."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from myruflo.web.db import get_db
from myruflo.web.deps import require_login
from myruflo.web.security import hash_password, verify_password
from myruflo.web.templating import base_context, templates

router = APIRouter(prefix="/settings")


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


@router.get("")
def settings_page(
    request: Request, user: sqlite3.Row = Depends(require_login), conn: sqlite3.Connection = Depends(get_db)
):
    return templates.TemplateResponse(request, "settings.html", base_context(user, conn))


@router.post("/profile")
def update_profile(
    payload: ProfileRequest, user: sqlite3.Row = Depends(require_login), conn: sqlite3.Connection = Depends(get_db)
):
    conn.execute("UPDATE users SET name = ? WHERE id = ?", (payload.name.strip(), user["id"]))
    conn.commit()
    return {"ok": True}


@router.post("/password")
def update_password(
    payload: PasswordRequest, user: sqlite3.Row = Depends(require_login), conn: sqlite3.Connection = Depends(get_db)
):
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(payload.new_password), user["id"])
    )
    conn.commit()
    return {"ok": True}
