"""Session helpers for long-running request handlers."""

from __future__ import annotations

import time

from sqlalchemy.exc import OperationalError

from app.extensions import db


def release_db_connection() -> None:
    """Return the scoped session connection to the pool (e.g. before S3 I/O)."""
    db.session.remove()


def commit_with_retry(*, attempts: int = 3, pause_sec: float = 0.5) -> None:
    """Commit; on stale/disconnected Postgres, rollback, refresh pool, retry."""
    last: OperationalError | None = None
    for attempt in range(max(1, attempts)):
        try:
            db.session.commit()
            return
        except OperationalError as exc:
            last = exc
            db.session.rollback()
            release_db_connection()
            if attempt + 1 >= attempts:
                break
            time.sleep(pause_sec * (attempt + 1))
    assert last is not None
    raise last
