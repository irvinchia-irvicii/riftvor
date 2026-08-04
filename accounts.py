"""Local Soraka's Wish accounts and session helpers.

Email/password is the development-stage identity provider. The user table and
session boundary are intentionally provider-neutral so hosted Google OAuth can
attach to the same accounts later without changing feature ownership.
"""
from __future__ import annotations

import re
import sqlite3
import time
from functools import wraps

from flask import g, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

import db

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ACCOUNT_REQUIRED = {
    "error": "Create a free account or sign in to unlock this feature.",
    "code": "account_required",
}


def _clean_email(value: str) -> str:
    return (value or "").strip().lower()


def public_account(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "tier": row["tier"],
        "entitlements": {
            "multi_card_search": True,
            "collection": True,
            "portfolio_analytics": row["tier"] in ("founder", "pro"),
        },
    }


def current() -> dict | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, email, tier FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None:
        session.clear()
        return None
    return public_account(row)


def current_user_id() -> int | None:
    account = getattr(g, "account", None)
    if account is None:
        account = current()
        g.account = account
    return account["id"] if account else None


def create(email: str, password: str) -> tuple[dict | None, str | None]:
    email = _clean_email(email)
    if not EMAIL_RE.match(email) or len(email) > 254:
        return None, "Enter a valid email address."
    if len(password or "") < 8:
        return None, "Use at least 8 characters for your password."
    if len(password) > 128:
        return None, "Password is too long."

    try:
        with db.connect() as conn:
            cursor = conn.execute(
                """INSERT INTO users (email, password_hash, tier, created_at)
                   VALUES (?, ?, 'member', ?)""",
                (email, generate_password_hash(password), time.time()),
            )
            user_id = cursor.lastrowid
            row = conn.execute(
                "SELECT id, email, tier FROM users WHERE id = ?", (user_id,)
            ).fetchone()
    except sqlite3.IntegrityError:
        return None, "An account with that email already exists."

    db.claim_legacy_data(user_id)
    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    return public_account(row), None


def authenticate(email: str, password: str) -> tuple[dict | None, str | None]:
    email = _clean_email(email)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, tier FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        return None, "Email or password is incorrect."
    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    return public_account(row), None


def logout() -> None:
    session.clear()


def required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            return jsonify(ACCOUNT_REQUIRED), 401
        return view(*args, **kwargs)
    return wrapped
