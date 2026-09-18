"""Ensure audit exception types exist (idempotent seed)."""

from __future__ import annotations

import logging
import os

from app.extensions import db
from app.models.audit_exception import AUDIT_EXCEPTION_CATALOG, AuditExceptionType

logger = logging.getLogger(__name__)


def ensure_audit_exception_types() -> int:
    """
    Insert missing catalog rows (E01–E15) and refresh label/sort_order for existing codes.
    Returns number of rows created.
    """
    created = 0
    for entry in AUDIT_EXCEPTION_CATALOG:
        row = AuditExceptionType.query.filter_by(code=entry["code"]).first()
        if row is None:
            db.session.add(
                AuditExceptionType(
                    code=entry["code"],
                    label=entry["label"],
                    sort_order=entry["sort_order"],
                    is_active=True,
                )
            )
            created += 1
            continue

        changed = False
        if row.label != entry["label"]:
            row.label = entry["label"]
            changed = True
        if row.sort_order != entry["sort_order"]:
            row.sort_order = entry["sort_order"]
            changed = True
        if not row.is_active:
            row.is_active = True
            changed = True
        if changed:
            db.session.add(row)

    db.session.commit()
    if created:
        logger.info("Seeded %s audit exception type(s)", created)
    else:
        logger.info("Audit exception types already present (%s)", len(AUDIT_EXCEPTION_CATALOG))
    return created


def bootstrap_audit_exception_types_on_startup(app) -> None:
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    with app.app_context():
        try:
            ensure_audit_exception_types()
        except Exception:  # noqa: BLE001
            logger.exception("Audit exception type bootstrap failed")
