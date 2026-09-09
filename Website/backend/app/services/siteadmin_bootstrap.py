"""Ensure siteadmin exists on startup (no login email / no temp password)."""

from __future__ import annotations

import logging
import os

from app.extensions import db
from app.models.user import SITEADMIN_ROLE, User
from app.services.login_email import start_login_email_worker

logger = logging.getLogger(__name__)


def ensure_siteadmin_user() -> User | None:
    email = os.getenv("SITEADMIN_EMAIL", "").strip().lower()
    if not email:
        logger.warning("SITEADMIN_EMAIL missing — skipping siteadmin bootstrap")
        return None

    password = os.getenv("SITEADMIN_PASSWORD", "").strip()
    existing = User.query.filter_by(email=email).first()

    if existing:
        # Keep siteadmin off the temp-password / email flow.
        changed = False
        if existing.role != SITEADMIN_ROLE:
            existing.role = SITEADMIN_ROLE
            changed = True
        if existing.temp_login or existing.temp_pass or not existing.login_email_sent:
            existing.temp_login = False
            existing.temp_pass = None
            existing.login_email_sent = True
            changed = True
        if password:
            existing.set_password(password, temporary=False)
            existing.login_email_sent = True
            changed = True
        if changed:
            db.session.commit()
            logger.info("Updated existing siteadmin %s (no email / no temp login)", email)
        else:
            logger.info("Siteadmin already exists: %s", email)
        return existing

    if not password:
        logger.error(
            "SITEADMIN_PASSWORD missing — cannot create siteadmin for %s",
            email,
        )
        return None

    user = User(
        email=email,
        full_name="Site Admin",
        role=SITEADMIN_ROLE,
        is_active=True,
        temp_login=False,
        temp_pass=None,
        login_email_sent=True,
    )
    user.set_password(password, temporary=False)
    user.login_email_sent = True
    db.session.add(user)
    db.session.commit()
    logger.info("Created siteadmin user %s (permanent password, email skipped)", email)
    return user


def bootstrap_siteadmin_on_startup(app) -> None:
    """Create/normalize siteadmin, then start email worker for other users only."""
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    with app.app_context():
        try:
            ensure_siteadmin_user()
        except Exception:  # noqa: BLE001
            logger.exception("Siteadmin bootstrap failed")

    start_login_email_worker(app)
