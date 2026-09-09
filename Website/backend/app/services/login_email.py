"""Background worker that emails temporary login credentials."""

from __future__ import annotations

import logging
import os
import smtplib
import threading
import time
from email.message import EmailMessage

from app.extensions import db
from app.models.user import SITEADMIN_ROLE, User

logger = logging.getLogger(__name__)

_worker_started = False


def _siteadmin_email() -> str:
    return os.getenv("SITEADMIN_EMAIL", "").strip().lower()


def _smtp_settings() -> dict:
    user = (
        os.getenv("SMTP_USER", "")
        or os.getenv("SENDER_EMAIL", "")
        or os.getenv("SMTP_FROM", "")
    ).strip()
    password = (
        os.getenv("SMTP_PASSWORD", "")
        or os.getenv("SMTP_PASS", "")
        or os.getenv("SENDER_PASSWORD", "")
    ).strip()
    sender = (os.getenv("SMTP_FROM", "") or os.getenv("SENDER_EMAIL", "") or user).strip()
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": user,
        "password": password,
        "sender": sender,
        "use_tls": os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes"},
    }


def send_login_email(user: User) -> None:
    settings = _smtp_settings()
    temp_password = user.temp_pass
    if not temp_password:
        raise RuntimeError(f"User {user.email} has no temp_pass to email")

    subject = "Toll Analytics — temporary login"
    body = (
        f"Hello{f' {user.full_name}' if user.full_name else ''},\n\n"
        "Your Toll Analytics account is ready.\n\n"
        f"Email: {user.email}\n"
        f"Temporary password: {temp_password}\n"
        f"Role: {user.role}\n\n"
        "Sign in with this temporary password. You can change it later if needed.\n"
    )

    if not settings["host"] or not settings["sender"]:
        logger.warning(
            "SMTP not configured — login email for %s logged to console instead.\n%s",
            user.email,
            body,
        )
        print(f"[login-email-fallback]\nTo: {user.email}\n{body}", flush=True)
        return

    if not settings["user"] or not settings["password"]:
        raise RuntimeError(
            "SMTP host is set but credentials are missing. "
            "Set SMTP_USER and SMTP_PASS (or SMTP_PASSWORD) in .env"
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["sender"]
    message["To"] = user.email
    message.set_content(body)

    with smtplib.SMTP(settings["host"], settings["port"], timeout=30) as server:
        server.ehlo()
        if settings["use_tls"]:
            server.starttls()
            server.ehlo()
        server.login(settings["user"], settings["password"])
        server.send_message(message)


def process_pending_login_emails(app) -> int:
    sent = 0
    siteadmin_email = _siteadmin_email()
    with app.app_context():
        pending_query = (
            User.query.filter_by(login_email_sent=False, is_active=True, temp_login=True)
            .filter(User.temp_pass.isnot(None))
            .filter(User.role != SITEADMIN_ROLE)
            .order_by(User.id.asc())
        )
        if siteadmin_email:
            pending_query = pending_query.filter(User.email != siteadmin_email)

        pending = pending_query.limit(20).all()
        for user in pending:
            try:
                send_login_email(user)
                user.login_email_sent = True
                db.session.commit()
                sent += 1
                logger.info("Login email marked sent for %s", user.email)
            except Exception:  # noqa: BLE001
                db.session.rollback()
                logger.exception("Failed sending login email to %s", user.email)
    return sent


def start_login_email_worker(app, *, interval_seconds: int = 20) -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def _loop():
        # Small delay so migrations/bootstrap settle.
        time.sleep(2)
        while True:
            try:
                process_pending_login_emails(app)
            except Exception:  # noqa: BLE001
                logger.exception("Login email worker iteration failed")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, name="login-email-worker", daemon=True)
    thread.start()
    logger.info("Login email background worker started")
