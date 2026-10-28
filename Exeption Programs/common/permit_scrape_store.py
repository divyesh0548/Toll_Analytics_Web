"""Shared E6 permit scrape rows in Toll_Analytics_DB.

Not plaza-specific. A vehicle saved here is reused for every plaza.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

PERMIT_TYPE = "Permit Type"
PERMIT_NO = "Permit/Authorization No"
PERMIT_VALIDITY = "Permit Validity"
VEHICLE_COL = "Veh Reg No"
_USEFUL_SKIP = {"", "none", "nan", "null", "na", "nat", "-"}
_INSERT_CHUNK = 500


def _load_dotenv_files() -> None:
    from common.mapping_store import _load_dotenv_files as load_env

    load_env()


def _connect():
    from common.mapping_store import _connect as connect

    return connect()


def _useful(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in _USEFUL_SKIP:
        return ""
    return text


def _normalize_vehicle(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text.casefold() in _USEFUL_SKIP:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def rows_from_frame(frame, vehicle_col: str) -> list[tuple]:
    """Useful permit rows only. Failures stored as 'none' are left out."""
    if frame is None or getattr(frame, "empty", True):
        return []
    if vehicle_col not in frame.columns:
        return []
    now = datetime.now(timezone.utc)
    out: list[tuple] = []
    seen: set[str] = set()
    type_col = PERMIT_TYPE if PERMIT_TYPE in frame.columns else None
    no_col = PERMIT_NO if PERMIT_NO in frame.columns else None
    validity_col = PERMIT_VALIDITY if PERMIT_VALIDITY in frame.columns else None
    types = frame[type_col].tolist() if type_col else [""] * len(frame)
    numbers = frame[no_col].tolist() if no_col else [""] * len(frame)
    validities = frame[validity_col].tolist() if validity_col else [""] * len(frame)
    for vehicle_raw, permit_type, permit_no, validity in zip(
        frame[vehicle_col].tolist(), types, numbers, validities
    ):
        vehicle = _normalize_vehicle(vehicle_raw)
        if not vehicle or vehicle in seen:
            continue
        permit_type = _useful(permit_type)
        permit_no = _useful(permit_no)
        validity = _useful(validity)
        if not (permit_type or permit_no or validity):
            continue
        seen.add(vehicle)
        out.append((vehicle, permit_type, permit_no, validity, now))
    return out


def upsert_permit_rows(rows: list[tuple]) -> int:
    """Insert or replace permit rows. Returns how many were written."""
    if not rows:
        return 0
    _load_dotenv_files()
    from psycopg2.extras import execute_values

    sql = """
        INSERT INTO permit_scrape_cache (
            vehicle_reg_no,
            permit_type,
            permit_authorization_no,
            permit_validity,
            scraped_at
        ) VALUES %s
        ON CONFLICT (vehicle_reg_no) DO UPDATE SET
            permit_type = EXCLUDED.permit_type,
            permit_authorization_no = EXCLUDED.permit_authorization_no,
            permit_validity = EXCLUDED.permit_validity,
            scraped_at = EXCLUDED.scraped_at
    """
    written = 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for start in range(0, len(rows), _INSERT_CHUNK):
                chunk = rows[start : start + _INSERT_CHUNK]
                execute_values(cur, sql, chunk)
                written += len(chunk)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return written


def upsert_permit_frame(frame, vehicle_col: str) -> int:
    rows = rows_from_frame(frame, vehicle_col)
    if not rows:
        return 0
    try:
        count = upsert_permit_rows(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING permit DB save failed: {exc}", flush=True)
        return -1
    if count:
        print(f"Saved {count:,} permit row(s) to the shared database.", flush=True)
    return count


def fetch_cached_permits(vehicle_keys: set[str], *, vehicle_col: str):
    """Return a dataframe of stored permits for these vehicles."""
    import pandas as pd

    keys = [key for key in vehicle_keys if key]
    if not keys:
        return pd.DataFrame(columns=[vehicle_col, PERMIT_TYPE, PERMIT_NO, PERMIT_VALIDITY])
    _load_dotenv_files()
    frames = []
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for start in range(0, len(keys), _INSERT_CHUNK):
                chunk = keys[start : start + _INSERT_CHUNK]
                cur.execute(
                    """
                    SELECT vehicle_reg_no, permit_type,
                           permit_authorization_no, permit_validity
                    FROM permit_scrape_cache
                    WHERE vehicle_reg_no = ANY(%s)
                    """,
                    (chunk,),
                )
                frames.extend(cur.fetchall())
    finally:
        conn.close()
    if not frames:
        return pd.DataFrame(columns=[vehicle_col, PERMIT_TYPE, PERMIT_NO, PERMIT_VALIDITY])
    out = pd.DataFrame(
        frames,
        columns=[vehicle_col, PERMIT_TYPE, PERMIT_NO, PERMIT_VALIDITY],
    )
    return out


def cached_vehicle_keys(vehicle_keys: set[str]) -> set[str]:
    """Vehicles that already have a stored permit row."""
    keys = [key for key in vehicle_keys if key]
    if not keys:
        return set()
    _load_dotenv_files()
    found: set[str] = set()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for start in range(0, len(keys), _INSERT_CHUNK):
                chunk = keys[start : start + _INSERT_CHUNK]
                cur.execute(
                    """
                    SELECT vehicle_reg_no
                    FROM permit_scrape_cache
                    WHERE vehicle_reg_no = ANY(%s)
                    """,
                    (chunk,),
                )
                found.update(row[0] for row in cur.fetchall() if row and row[0])
    finally:
        conn.close()
    return found
