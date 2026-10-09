"""Delete non-final (staging) exception output files older than N days."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.audit_exception import AuditExceptionOutputFile
from app.services.exception_job_s3 import delete_keys

logger = logging.getLogger(__name__)

STAGING_RETENTION_DAYS = 7


def cleanup_expired_staging_outputs(*, retention_days: int = STAGING_RETENTION_DAYS) -> int:
    """
    Remove staging rows (is_final_output=False) older than retention_days
    from S3 and audit_exception_output_files.
    Returns number of rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(retention_days)))
    rows = (
        AuditExceptionOutputFile.query.filter_by(is_final_output=False)
        .filter(AuditExceptionOutputFile.created_at < cutoff)
        .order_by(AuditExceptionOutputFile.id.asc())
        .all()
    )
    if not rows:
        return 0

    keys = [r.s3_key for r in rows if r.s3_key]
    try:
        if keys:
            delete_keys(keys)
    except Exception:  # noqa: BLE001
        logger.exception("Failed deleting staging S3 keys (continuing DB cleanup)")

    for row in rows:
        db.session.delete(row)
    db.session.commit()
    logger.info(
        "Cleaned %s staging output file(s) older than %s days",
        len(rows),
        retention_days,
    )
    return len(rows)
