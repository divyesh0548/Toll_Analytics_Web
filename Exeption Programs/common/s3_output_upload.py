"""
Shared S3 upload for exception-program output files.

Usage from an exception main (later, when you wire each one):

    UPLOAD_OUTPUT_TO_S3 = False  # default off

    from common.s3_output_upload import upload_exception_output

    if UPLOAD_OUTPUT_TO_S3:
        upload_exception_output(
            local_path=out_path,
            plaza_identifier=PLAZA_IDENTIFIER,
            exception_type_id=4,          # or exception_code="E04"
            month_periods=[(2026, 1), (2026, 8)],  # or month_label="2026-Jan-Aug"
        )

S3 layout:
  Toll Analytics Dashboard Output/{plaza_name}/{file_name}

File name example:
  E04_Bassi_2026-Jan-Aug_20261005_123045.xlsx

Each call INSERTs a new row into audit_exception_output_files (history kept).
Credentials and DB come from Website/backend/.env.

plazas / audit_exception_types / audit_exception_output_files live in
toll_analytics (Website DB_NAME). Exception mains may have already loaded
E4/.env with a different DB_NAME (submissions), so this module always
re-loads Website/backend/.env with override=True before connecting.
"""

from __future__ import annotations

import calendar
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

try:
    import boto3
except ImportError as exc:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    _BOTO3_IMPORT_ERROR = exc
else:
    _BOTO3_IMPORT_ERROR = None

COMMON_DIR = Path(__file__).resolve().parent
REPO_ROOT = COMMON_DIR.parent.parent
ENV_FILE = REPO_ROOT / "Website" / "backend" / ".env"

S3_ROOT_PREFIX = "Toll Analytics Dashboard Output"
OUTPUT_TABLE = "audit_exception_output_files"


def load_env() -> None:
    if not ENV_FILE.is_file():
        raise FileNotFoundError(f"Env file not found: {ENV_FILE}")
    # override=True so E4/other .env DB_NAME (submissions) does not stick.
    load_dotenv(ENV_FILE, override=True)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name} (in {ENV_FILE})")
    return value


def toll_analytics_db_name() -> str:
    """
    Database that holds plazas (and output-file history).
    Prefer ANALYTICS_DB_NAME, else Website DB_NAME (toll_analytics).
    """
    return (
        os.getenv("ANALYTICS_DB_NAME", "").strip()
        or require_env("DB_NAME")
    )


def connection_kwargs() -> dict:
    return {
        "host": require_env("DB_HOST"),
        "port": int(os.getenv("DB_PORT") or "5432"),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": toll_analytics_db_name(),
    }


def _safe_name(value: str) -> str:
    text = re.sub(r"[^\w.\-]+", "_", str(value or "").strip())
    return text.strip("._") or "unknown"


def month_label_from_periods(
    periods: Sequence[tuple[int, int]] | Iterable[tuple[int, int]],
) -> str:
    """
    Build a month_label from (year, month) pairs.

    One month: 2026-Jan
    Same year, several months: 2026-Jan-Feb-Mar (each month present, sorted)
    Cross year: 2026-Nov-Dec_2027-Jan-Feb
    """
    pairs = sorted({(int(y), int(m)) for y, m in periods if 1 <= int(m) <= 12})
    if not pairs:
        raise ValueError("month_periods is empty — cannot build month_label")

    by_year: dict[int, list[int]] = {}
    for year, month in pairs:
        by_year.setdefault(year, []).append(month)

    parts: list[str] = []
    for year in sorted(by_year):
        months = "-".join(calendar.month_abbr[m] for m in by_year[year])
        parts.append(f"{year}-{months}")
    return "_".join(parts)


def month_label_from_dates(dates: Iterable[date | datetime]) -> str:
    periods: list[tuple[int, int]] = []
    for value in dates:
        if value is None:
            continue
        if isinstance(value, datetime):
            periods.append((value.year, value.month))
        else:
            periods.append((value.year, value.month))
    return month_label_from_periods(periods)


def fetch_plaza(conn, plaza_identifier: str) -> dict:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT plaza_identifier, plaza_name
            FROM plazas
            WHERE plaza_identifier = %s
            """,
            (plaza_identifier,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"plaza_identifier {plaza_identifier!r} not found in plazas table."
        )
    return dict(row)


def resolve_exception_type_id(
    conn,
    *,
    exception_type_id: int | None = None,
    exception_code: str | None = None,
) -> tuple[int, str]:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        if exception_type_id is not None:
            cursor.execute(
                """
                SELECT id, code
                FROM audit_exception_types
                WHERE id = %s
                """,
                (int(exception_type_id),),
            )
        else:
            code = str(exception_code or "").strip().upper()
            if not code:
                raise RuntimeError(
                    "Pass exception_type_id or exception_code (e.g. E04)."
                )
            cursor.execute(
                """
                SELECT id, code
                FROM audit_exception_types
                WHERE UPPER(code) = %s
                """,
                (code,),
            )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "exception type not found "
            f"(id={exception_type_id!r}, code={exception_code!r})."
        )
    return int(row["id"]), str(row["code"])


def build_output_file_name(
    *,
    exception_code: str,
    plaza_name: str,
    month_label: str,
    original_suffix: str,
    original_file_name: str | None = None,
    when: datetime | None = None,
) -> str:
    """
    S3 object / download name.

    Keeps the original workbook stem (role, e.g. LNC_CT, NLNC) and adds
    exception code, plaza, month_label, and upload timestamp.
    Example:
      E01_Bassi_LNC_CT_2026-Apr-May_20261009_143022.xlsx
    """
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    suffix = original_suffix if original_suffix.startswith(".") else f".{original_suffix}"
    if not suffix or suffix == ".":
        suffix = ".xlsx"

    original = Path(str(original_file_name or "")).name
    stem = Path(original).stem if original else ""
    stem_safe = _safe_name(stem) if stem else ""

    parts = [
        _safe_name(exception_code),
        _safe_name(plaza_name),
    ]
    if stem_safe:
        parts.append(stem_safe)
    parts.append(_safe_name(month_label))
    parts.append(stamp)
    return "_".join(parts) + suffix


def build_s3_key(plaza_name: str, file_name: str) -> str:
    # Keep plaza_name readable in the folder; only strip path separators.
    folder = str(plaza_name or "unknown").replace("\\", "_").replace("/", "_").strip()
    folder = folder or "unknown"
    return f"{S3_ROOT_PREFIX}/{folder}/{file_name}"


def object_url(bucket: str, region: str, key: str) -> str:
    """Permanent virtual-hosted URL (not a presigned link)."""
    region = (region or "us-east-1").strip()
    if region == "us-east-1":
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _s3_client():
    if boto3 is None:
        raise RuntimeError(
            "boto3 is required for S3 upload. "
            f"Install it in this environment. ({_BOTO3_IMPORT_ERROR})"
        )
    return boto3.client(
        "s3",
        region_name=require_env("AWS_REGION"),
        aws_access_key_id=require_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=require_env("AWS_SECRET_ACCESS_KEY"),
    )


def upload_exception_output(
    local_path: str | Path,
    plaza_identifier: str,
    *,
    exception_type_id: int | None = None,
    exception_code: str | None = None,
    month_label: str | None = None,
    month_periods: Sequence[tuple[int, int]] | None = None,
    is_final_output: bool = True,
    name_stem: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Upload one output file to S3 and INSERT a history row.

    is_final_output=False → staging / intermediate (hidden from Audit downloads).
    name_stem overrides the original filename stem in the S3 object name
    (e.g. pass plaza_name so staging invalid tables are easy to spot).

    Returns dict with file_name, s3_key, file_url, month_label, db_id (None if dry_run).
    """
    path = Path(local_path)
    if not path.is_file():
        raise FileNotFoundError(f"Output file not found: {path}")

    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required for S3 upload.")

    if not month_label:
        if not month_periods:
            raise RuntimeError(
                "Pass month_label (e.g. '2026-Jan-Mar') or month_periods "
                "[(2026, 1), (2026, 3)]."
            )
        month_label = month_label_from_periods(month_periods)
    month_label = str(month_label).strip()
    if not month_label:
        raise RuntimeError("month_label is empty.")

    load_env()
    bucket = require_env("AWS_S3_BUCKET_NAME")
    region = require_env("AWS_REGION")
    conn_kw = connection_kwargs()
    print(
        f"S3 DB lookup → {conn_kw['database']}.plazas "
        f"(plaza_identifier={plaza_identifier!r})"
    )

    conn = psycopg2.connect(**conn_kw)
    try:
        plaza = fetch_plaza(conn, plaza_identifier)
        type_id, code = resolve_exception_type_id(
            conn,
            exception_type_id=exception_type_id,
            exception_code=exception_code,
        )
        plaza_name = str(plaza["plaza_name"])
        original_name = path.name
        # Prefer explicit stem (e.g. invalid_table_<plaza>); always include plaza_name
        # via build_output_file_name's plaza segment.
        stem_source = (
            f"{name_stem}{path.suffix}"
            if name_stem
            else original_name
        )
        file_name = build_output_file_name(
            exception_code=code if is_final_output else f"{code}_staging",
            plaza_name=plaza_name,
            month_label=month_label,
            original_suffix=path.suffix or ".xlsx",
            original_file_name=stem_source,
        )
        s3_key = build_s3_key(plaza_name, file_name)
        file_url = object_url(bucket, region, s3_key)
        size = path.stat().st_size

        print(f"S3 upload → s3://{bucket}/{s3_key}")
        print(
            f"  original={original_name!r}, plaza={plaza_name!r}, "
            f"month_label={month_label!r}, is_final_output={is_final_output}, "
            f"size={size:,} bytes"
        )

        if dry_run:
            print("  dry_run=True — S3 put and DB insert skipped.")
            return {
                "db_id": None,
                "plaza_identifier": plaza_identifier,
                "plaza_name": plaza_name,
                "exception_type_id": type_id,
                "exception_code": code,
                "month_label": month_label,
                "file_name": file_name,
                "original_file_name": original_name,
                "s3_key": s3_key,
                "file_url": file_url,
                "file_size_bytes": size,
                "is_final_output": bool(is_final_output),
                "dry_run": True,
            }

        client = _s3_client()
        upload_kwargs: dict = {}
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xlsm"}:
            upload_kwargs["ExtraArgs"] = {
                "ContentType": (
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                )
            }
        elif suffix == ".csv":
            upload_kwargs["ExtraArgs"] = {"ContentType": "text/csv"}
        client.upload_file(str(path), bucket, s3_key, **upload_kwargs)

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""
                INSERT INTO {OUTPUT_TABLE} (
                    plaza_identifier,
                    exception_type_id,
                    month_label,
                    file_name,
                    s3_key,
                    file_url,
                    original_file_name,
                    file_size_bytes,
                    is_final_output,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    NOW(), NOW()
                )
                RETURNING id
                """,
                (
                    plaza_identifier,
                    type_id,
                    month_label,
                    file_name,
                    s3_key,
                    file_url,
                    original_name,
                    size,
                    bool(is_final_output),
                ),
            )
            row = cursor.fetchone()
        conn.commit()
        db_id = int(row["id"]) if row else None
        print(f"  DB row inserted id={db_id} is_final_output={is_final_output}")
        print(f"  file_url={file_url}")
        return {
            "db_id": db_id,
            "plaza_identifier": plaza_identifier,
            "plaza_name": plaza_name,
            "exception_type_id": type_id,
            "exception_code": code,
            "month_label": month_label,
            "file_name": file_name,
            "original_file_name": original_name,
            "s3_key": s3_key,
            "file_url": file_url,
            "file_size_bytes": size,
            "is_final_output": bool(is_final_output),
            "dry_run": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

