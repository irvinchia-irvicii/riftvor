"""emailer.py — Gmail SMTP sender (setup ported from 3vor Fetch's
deck_engine emailer). Creds live in repo-local .env (gitignored):
RIFTVOR_EMAIL_FROM + RIFTVOR_SMTP_APP_PASSWORD (Gmail app password).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import config

log = logging.getLogger("riftvor.email")


def credentials() -> tuple[str, str, str] | None:
    config.load_env()
    sender = os.environ.get(config.EMAIL_FROM_ENV, "")
    password = os.environ.get(config.SMTP_APP_PASSWORD_ENV, "")
    to = os.environ.get(config.EMAIL_TO_ENV, "") or sender
    if not sender or not password:
        return None
    return sender, password, to


def send_to(to: str, subject: str, body: str) -> bool:
    creds = credentials()
    if creds is None:
        log.warning("email credentials missing (%s / %s in .env)",
                    config.EMAIL_FROM_ENV, config.SMTP_APP_PASSWORD_ENV)
        return False
    sender, password, _default_to = creds
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(sender, password)
            s.send_message(msg)
        log.info("emailed %r to %s", subject, to)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.error("email send failed: %s", exc)
        return False


def send(subject: str, body: str) -> bool:
    creds = credentials()
    if creds is None:
        log.warning("email credentials missing (%s / %s in .env)",
                    config.EMAIL_FROM_ENV, config.SMTP_APP_PASSWORD_ENV)
        return False
    return send_to(creds[2], subject, body)
