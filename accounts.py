"""Local Soraka's Wish accounts and session helpers.

Username-or-email/password is the development-stage identity provider. The user table and
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
import config

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
ACCOUNT_REQUIRED = {
    "error": "Create a free account or sign in to unlock this feature.",
    "code": "account_required",
}


def _clean_email(value: str) -> str:
    return (value or "").strip().lower()


def _valid_identifier(value: str) -> bool:
    return bool(EMAIL_RE.match(value) or USERNAME_RE.match(value))


def ensure_review_account() -> bool:
    """Provision the private hosted reviewer after an ephemeral DB reset.

    This is an internal access account, not a claim that its username is an
    official public Riot identity. No analytics consent or terms acceptance is
    recorded on the reviewer's behalf.
    """
    username = config.REVIEW_ACCOUNT_USERNAME
    password_hash = config.REVIEW_ACCOUNT_PASSWORD_HASH
    if not username or not password_hash:
        return False
    if not USERNAME_RE.match(username):
        raise RuntimeError("Invalid configured review-account username")
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (username,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, existing["id"]),
            )
            return False
        conn.execute(
            """INSERT INTO users
               (email, password_hash, tier, created_at, analytics_consent)
               VALUES (?, ?, 'member', ?, 0)""",
            (username, password_hash, time.time()),
        )
    return True


def public_account(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "tier": row["tier"],
        "privacy": {
            "analytics_consent": bool(row["analytics_consent"]),
            "consent_version": row["analytics_consent_version"],
            "terms_version": row["terms_version"],
        },
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
            """SELECT id, email, tier, terms_version, analytics_consent,
                      analytics_consent_version
               FROM users WHERE id = ?""", (user_id,)
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


def create(email: str, password: str, *, accept_terms: bool = False,
           analytics_consent: bool = False) -> tuple[dict | None, str | None]:
    email = _clean_email(email)
    if not _valid_identifier(email) or len(email) > 254:
        return None, "Enter a valid email address or username."
    if len(password or "") < 8:
        return None, "Use at least 8 characters for your password."
    if len(password) > 128:
        return None, "Password is too long."
    if accept_terms is not True:
        return None, "Please accept the Terms and Privacy Notice."

    try:
        with db.connect() as conn:
            now = time.time()
            cursor = conn.execute(
                """INSERT INTO users
                   (email, password_hash, tier, created_at, terms_version,
                    terms_accepted_at, analytics_consent,
                    analytics_consent_version, analytics_consented_at)
                   VALUES (?, ?, 'member', ?, ?, ?, ?, ?, ?)""",
                (email, generate_password_hash(password), now,
                 config.CONSENT_VERSION, now, int(bool(analytics_consent)),
                 config.CONSENT_VERSION if analytics_consent else None,
                 now if analytics_consent else None),
            )
            user_id = cursor.lastrowid
            conn.executemany(
                """INSERT INTO privacy_consents
                   (user_id, purpose, granted, version, recorded_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [(user_id, "terms_and_privacy", 1, config.CONSENT_VERSION, now),
                 (user_id, "community_analytics", int(bool(analytics_consent)),
                  config.CONSENT_VERSION, now)],
            )
            row = conn.execute(
                """SELECT id, email, tier, terms_version, analytics_consent,
                          analytics_consent_version
                   FROM users WHERE id = ?""", (user_id,)
            ).fetchone()
    except sqlite3.IntegrityError:
        return None, "An account with that email or username already exists."

    db.claim_legacy_data(user_id)
    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    return public_account(row), None


def authenticate(email: str, password: str) -> tuple[dict | None, str | None]:
    email = _clean_email(email)
    with db.connect() as conn:
        row = conn.execute(
            """SELECT id, email, password_hash, tier, terms_version,
                      analytics_consent, analytics_consent_version
               FROM users WHERE email = ?""",
            (email,),
        ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        return None, "Email/username or password is incorrect."
    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    return public_account(row), None


def logout() -> None:
    session.clear()


def set_analytics_consent(user_id: int, enabled: bool) -> dict:
    """Record every preference change; withdrawal also removes raw events."""
    now = time.time()
    with db.connect() as conn:
        conn.execute(
            """UPDATE users SET analytics_consent = ?,
                      analytics_consent_version = ?, analytics_consented_at = ?
               WHERE id = ?""",
            (int(enabled), config.CONSENT_VERSION if enabled else None,
             now if enabled else None, user_id),
        )
        conn.execute(
            """INSERT INTO privacy_consents
               (user_id, purpose, granted, version, recorded_at)
               VALUES (?, 'community_analytics', ?, ?, ?)""",
            (user_id, int(enabled), config.CONSENT_VERSION, now),
        )
        removed = 0
        if not enabled:
            removed = conn.execute(
                "DELETE FROM analytics_events WHERE user_id = ?", (user_id,)
            ).rowcount
    return {"analytics_consent": enabled, "events_removed": removed,
            "version": config.CONSENT_VERSION}


def required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            return jsonify(ACCOUNT_REQUIRED), 401
        return view(*args, **kwargs)
    return wrapped
