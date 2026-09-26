"""
E4 — Download VRN files from submissions DB and merge Veh Reg No + TC Class.

Uses column vrn_file_url. Keywords / aliases live in vrn_merge_config.json.

  python vrn-download-merge.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "vrn_merge_config.json"

ENTITY_NAME = "odhaki_paipkhar"
FROM_DATE = "2026-01-01"
TO_DATE = "2026-04-30"

DOWNLOAD_FOLDER = BASE_DIR / "vrn_downloads"
MERGED_OUTPUT_DIR = BASE_DIR / "output"

DOWNLOAD_TIMEOUT_SECONDS = 180
SKIP_EXISTING = True
DOWNLOAD_ONLY = False
EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}


def load_env() -> None:
    if not ENV_FILE.is_file():
        raise FileNotFoundError(f"Env file not found: {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name} (in {ENV_FILE})")
    return value


def connection_kwargs() -> dict:
    return {
        "host": require_env("DB_HOST"),
        "port": int(require_env("DB_PORT") or "5432"),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": require_env("DB_NAME"),
    }


def table_name() -> str:
    return (
        os.getenv("Table_NAME", "").strip()
        or os.getenv("TABLE_NAME", "").strip()
        or "submissions"
    )


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


_DATE_ORDERS = {"dd/mm/yyyy", "mm/dd/yyyy", "dd-mmm-yyyy"}
_BLANK_DATE = {"", "na", "n/a", "null", "none", "nat", "nan", "-"}
_DAY_FIRST_FORMATS = (
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p",
    "%d/%m/%Y %I:%M %p",
    "%d-%m-%Y %I:%M:%S %p",
    "%d-%m-%Y %I:%M %p",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y",
    "%d/%m/%Y",
)
_MONTH_FIRST_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m-%d-%Y %I:%M:%S %p",
    "%m-%d-%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m-%d-%Y %H:%M:%S",
    "%m-%d-%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y",
)
# 27-Apr-2026 08:01:54 AM — month name, so day/month order is not ambiguous.
_NAMED_MONTH_FORMATS = (
    "%d-%b-%Y %I:%M:%S %p",
    "%d-%b-%Y %I:%M %p",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y",
)
_PLAIN_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
) + _NAMED_MONTH_FORMATS


def date_order_for(entity_name: str, config: dict) -> str:
    """VRN files only. dd/mm/yyyy, mm/dd/yyyy, or dd-mmm-yyyy."""
    key = str(entity_name or "").strip().casefold()
    for row in config.get("entities") or []:
        name = str(row.get("entity_name") or "").strip().casefold()
        if name != key:
            continue
        order = str(row.get("date_format") or "").strip().casefold()
        if order not in _DATE_ORDERS:
            raise RuntimeError(
                f"Set date_format for {entity_name!r} in vrn_merge_config.json "
                "to dd/mm/yyyy, mm/dd/yyyy, or dd-mmm-yyyy "
                "(example 27-Apr-2026 08:01:54 AM is dd-mmm-yyyy)."
            )
        return order
    raise RuntimeError(
        f"Add {entity_name!r} to the entities list in vrn_merge_config.json "
        "and set date_format to dd/mm/yyyy, mm/dd/yyyy, or dd-mmm-yyyy."
    )


def parse_vrn_date(value, date_order: str) -> datetime | None:
    text = _normalize_header_cell(value)
    if text.casefold() in _BLANK_DATE:
        return None
    if date_order == "dd-mmm-yyyy":
        formats = _NAMED_MONTH_FORMATS + _PLAIN_FORMATS
        dayfirst = True
    elif date_order == "mm/dd/yyyy":
        formats = _MONTH_FIRST_FORMATS + _PLAIN_FORMATS
        dayfirst = False
    else:
        formats = _DAY_FIRST_FORMATS + _PLAIN_FORMATS
        dayfirst = True
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    parsed = pd.to_datetime(text, dayfirst=dayfirst, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def parse_iso_date(value: str, label: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError(f"Set {label} (YYYY-MM-DD).")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(f"{label} must be YYYY-MM-DD, got {value!r}.") from exc


def validate_interval(from_date: str, to_date: str) -> tuple[date, date]:
    start = parse_iso_date(from_date, "FROM_DATE")
    end = parse_iso_date(to_date, "TO_DATE")
    if end < start:
        raise RuntimeError("TO_DATE must be on or after FROM_DATE.")
    return start, end


def fetch_vrn_records(conn, *, entity_name: str, start: date, end: date) -> list[dict]:
    query = sql.SQL(
        """
        SELECT id, entity_name, date, vrn_file_url
        FROM {table}
        WHERE entity_name = %s
          AND date::date >= %s
          AND date::date <= %s
          AND vrn_file_url IS NOT NULL
          AND TRIM(vrn_file_url::text) <> ''
        ORDER BY date, id
        """
    ).format(table=sql.Identifier(table_name()))
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query, (entity_name, start.isoformat(), end.isoformat()))
        return [dict(row) for row in cursor.fetchall()]


def filename_from_url(url: str, record_id: int) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name:
        return name
    return f"vrn_{record_id}.xlsx"


def safe_part(value) -> str:
    text = str(value).strip() if value not in (None, "") else "unknown"
    return re.sub(r"[\\/:*?\"<>|]+", "-", text)


def build_local_path(
    output_folder: Path,
    entity_name: str,
    record_date,
    filename: str,
) -> Path:
    if hasattr(record_date, "strftime"):
        date_str = record_date.strftime("%Y-%m-%d")
    else:
        date_str = str(record_date)[:10]
    return output_folder / safe_part(entity_name) / date_str / filename


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    destination.write_bytes(response.content)


def download_vrn_files(
    conn,
    *,
    entity_name: str,
    start: date,
    end: date,
    output_folder: Path,
    skip_existing: bool = SKIP_EXISTING,
) -> tuple[list[Path], dict[str, int]]:
    records = fetch_vrn_records(conn, entity_name=entity_name, start=start, end=end)
    stats = {"found": len(records), "downloaded": 0, "skipped": 0, "failed": 0}
    local_paths: list[Path] = []

    print(f"Entity: {entity_name}")
    print(f"Date range: {start.isoformat()} → {end.isoformat()}")
    print(f"Table: {table_name()}")
    print(f"Download folder: {output_folder.resolve()}")
    print(f"Records with vrn_file_url: {len(records)}\n")

    for index, record in enumerate(records, start=1):
        record_id = record["id"]
        url = str(record["vrn_file_url"]).strip()
        filename = filename_from_url(url, record_id)
        local_path = build_local_path(
            output_folder, record["entity_name"], record["date"], filename
        )
        prefix = f"[{index}/{len(records)}] id={record_id} date={record['date']}"

        if skip_existing and local_path.is_file() and local_path.stat().st_size > 0:
            print(f"{prefix} SKIP (exists): {local_path}")
            stats["skipped"] += 1
            local_paths.append(local_path)
            continue

        try:
            print(f"{prefix} DOWNLOAD → {local_path}")
            download_file(url, local_path)
            stats["downloaded"] += 1
            local_paths.append(local_path)
        except requests.RequestException as exc:
            print(f"{prefix} FAILED: {exc}")
            stats["failed"] += 1

    print("\nDownload summary")
    print(f"  Found:      {stats['found']}")
    print(f"  Downloaded: {stats['downloaded']}")
    print(f"  Skipped:    {stats['skipped']}")
    print(f"  Failed:     {stats['failed']}")
    return local_paths, stats


def _normalize_header_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return " ".join(text.split())


def _normalize_header_key(value) -> str:
    return _normalize_header_cell(value).casefold()


def detect_header_row(
    df_raw: pd.DataFrame,
    keywords: list[str],
    *,
    scan_rows: int,
    min_matches: int,
) -> int:
    keyword_keys = {_normalize_header_key(k) for k in keywords if str(k).strip()}
    if not keyword_keys:
        raise ValueError("header_keywords is empty in vrn_merge_config.json")

    limit = min(int(scan_rows), len(df_raw))
    best_idx = None
    best_score = -1
    for row_idx in range(limit):
        cells = {_normalize_header_key(v) for v in df_raw.iloc[row_idx].tolist()}
        cells.discard("")
        score = sum(1 for key in keyword_keys if key in cells)
        if score > best_score:
            best_score = score
            best_idx = row_idx

    if best_idx is None or best_score < int(min_matches):
        raise ValueError(
            f"Header row not detected (need >= {min_matches} keyword matches; "
            f"best score={best_score})."
        )
    return best_idx


def read_first_sheet_raw(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    return pd.read_excel(path, sheet_name=0, header=None, dtype=str)


def dataframe_from_header(
    df_raw: pd.DataFrame, header_idx: int
) -> tuple[list[str], pd.DataFrame]:
    headers = [_normalize_header_cell(v) for v in df_raw.iloc[header_idx].tolist()]
    while headers and headers[-1] == "":
        headers.pop()
    if not any(headers):
        raise ValueError("Detected header row is empty")
    body = df_raw.iloc[header_idx + 1 :, : len(headers)].copy()
    body.columns = headers
    body = body.dropna(how="all").reset_index(drop=True)
    return headers, body


def resolve_column(headers: list[str], aliases: list[str]) -> str | None:
    by_key = {_normalize_header_key(h): h for h in headers if _normalize_header_cell(h)}
    for alias in aliases or []:
        key = _normalize_header_key(alias)
        if key in by_key:
            return by_key[key]
    return None


def extract_merge_frame(
    path: Path,
    *,
    keywords: list[str],
    scan_rows: int,
    min_matches: int,
    merge_columns: dict[str, list[str]],
    date_order: str,
) -> pd.DataFrame:
    print(f"Reading: {path}")
    df_raw = read_first_sheet_raw(path)
    if df_raw.empty:
        raise ValueError(f"File is empty: {path.name}")

    header_idx = detect_header_row(
        df_raw, keywords, scan_rows=scan_rows, min_matches=min_matches
    )
    headers, df = dataframe_from_header(df_raw, header_idx)
    print(f"  Header at row {header_idx + 1} ({len(headers)} cols, {len(df)} rows)")

    out = pd.DataFrame(index=df.index)
    missing: list[str] = []
    for canonical, aliases in merge_columns.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        source = resolve_column(headers, [str(a) for a in alias_list])
        if source is None:
            missing.append(canonical)
            out[canonical] = ""
        else:
            values = df[source].astype(str)
            if "date" in canonical.casefold():
                parsed = [
                    parse_vrn_date(value, date_order) for value in values.tolist()
                ]
                values = [
                    stamp.strftime("%Y-%m-%d %H:%M:%S") if stamp is not None else ""
                    for stamp in parsed
                ]
            out[canonical] = values
            print(f"  {canonical} ← {source!r}")

    if missing:
        print(f"  WARNING missing columns (left blank): {', '.join(missing)}")
    return out


def list_local_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        p
        for p in folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in EXCEL_EXTENSIONS
        and not p.name.startswith("~$")
    )


def merge_vrn_files(
    paths: list[Path],
    config: dict,
    output_path: Path,
    date_order: str,
) -> Path:
    keywords = config.get("header_keywords") or []
    scan_rows = int(config.get("header_scan_rows") or 25)
    min_matches = int(config.get("min_header_matches") or 2)
    merge_columns = config.get("merge_columns") or {}
    if not paths:
        raise FileNotFoundError("No VRN files to merge.")

    print("\n" + "=" * 60)
    print(f"Merging {len(paths)} VRN file(s)…")
    frames: list[pd.DataFrame] = []
    errors: list[str] = []

    for path in paths:
        try:
            frames.append(
                extract_merge_frame(
                    path,
                    keywords=keywords,
                    scan_rows=scan_rows,
                    min_matches=min_matches,
                    merge_columns=merge_columns,
                    date_order=date_order,
                )
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"{path}: {exc}"
            print(f"  ERROR {msg}")
            errors.append(msg)

    if not frames:
        raise RuntimeError("No VRN files could be parsed.\n" + "\n".join(errors))

    merged = pd.concat(frames, ignore_index=True)
    data_cols = [c for c in merge_columns.keys() if c in merged.columns]
    if data_cols:
        blank = merged[data_cols].apply(
            lambda col: col.astype(str).str.strip().eq("") | col.isna()
        )
        merged = merged.loc[~blank.all(axis=1)].reset_index(drop=True)

    output_path = Path(output_path)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() != ".csv":
        output_path = output_path.with_suffix(".csv")
    merged.to_csv(output_path, index=False, encoding="utf-8-sig")

    print("=" * 60)
    print(f"Merged rows: {len(merged)} from {len(frames)} file(s)")
    if errors:
        print(f"Skipped / failed files: {len(errors)}")
    print(f"Wrote: {output_path}")
    return output_path


def delete_downloaded_files(paths: list[Path], download_folder: Path) -> int:
    deleted = 0
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                deleted += 1
        except OSError as exc:
            print(f"WARNING could not delete {path}: {exc}")

    root = download_folder.resolve()
    if root.is_dir():
        for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
            folder = Path(dirpath)
            if folder == root:
                continue
            try:
                if not any(folder.iterdir()):
                    folder.rmdir()
            except OSError:
                pass

    print(f"Deleted {deleted} downloaded VRN file(s).")
    return deleted


def run_vrn_download_merge(
    entity_name: str,
    from_date: str,
    to_date: str,
    *,
    download_folder: Path | None = None,
    merged_output_dir: Path | None = None,
    skip_existing: bool = SKIP_EXISTING,
    download_only: bool = DOWNLOAD_ONLY,
    delete_downloads: bool = True,
) -> Path | None:
    name = str(entity_name or "").strip()
    if not name:
        raise RuntimeError("entity_name is required")

    start, end = validate_interval(from_date, to_date)
    out_download = Path(download_folder or DOWNLOAD_FOLDER)
    if not out_download.is_absolute():
        out_download = BASE_DIR / out_download
    out_download.mkdir(parents=True, exist_ok=True)

    load_env()
    config = load_config()
    date_order = date_order_for(name, config)
    print(f"VRN date order for {name}: {date_order}")

    print("Connecting to DB for VRN…")
    with psycopg2.connect(**connection_kwargs()) as conn:
        local_paths, _stats = download_vrn_files(
            conn,
            entity_name=name,
            start=start,
            end=end,
            output_folder=out_download,
            skip_existing=skip_existing,
        )

    if download_only:
        print("\nDOWNLOAD_ONLY=True — VRN merge skipped.")
        return None

    paths = local_paths or list_local_files(out_download / safe_part(name))
    if not paths:
        paths = list_local_files(out_download)
    if not paths:
        raise FileNotFoundError(
            f"No VRN files downloaded for entity={name!r} "
            f"range {start.isoformat()} → {end.isoformat()}"
        )

    merged_name = (
        f"{safe_part(name)}_{start.isoformat()}_{end.isoformat()}_merged_vrn.csv"
    )
    output_dir = Path(merged_output_dir or MERGED_OUTPUT_DIR)
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir
    merged_path = merge_vrn_files(paths, config, output_dir / merged_name, date_order)
    if delete_downloads:
        delete_downloaded_files(paths, out_download)
    else:
        print(f"Keeping {len(paths)} downloaded VRN file(s) in {out_download}")
    return merged_path


def main() -> int:
    run_vrn_download_merge(ENTITY_NAME, FROM_DATE, TO_DATE)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
