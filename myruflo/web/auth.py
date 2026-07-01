"""Register / login / logout. Forms submit as JSON via fetch (see
static/js/auth.js) so no python-multipart dependency is needed.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from myruflo.web.db import get_db
from myruflo.web.deps import get_current_user
from myruflo.web.security import hash_password, verify_password
from myruflo.web.templating import templates

router = APIRouter()


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    return email


@router.get("/register")
def register_page(request: Request, user: sqlite3.Row | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"user": None})


@router.post("/register")
def register_submit(
    payload: RegisterRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)
):
    email = _normalize_email(payload.email)
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="An account with that email already exists")

    user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    role = "admin" if user_count == 0 else "user"
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (payload.name.strip(), email, hash_password(payload.password), role, now),
    )
    conn.commit()
    request.session["user_id"] = cursor.lastrowid
    return {"ok": True, "redirect": "/"}


@router.get("/login")
def login_page(request: Request, user: sqlite3.Row | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/login")
def login_submit(payload: LoginRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    email = _normalize_email(payload.email)
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session["user_id"] = row["id"]
    return {"ok": True, "redirect": "/"}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
