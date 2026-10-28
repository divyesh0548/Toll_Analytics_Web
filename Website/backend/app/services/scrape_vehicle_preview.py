"""Count vehicles E05 and E06 will scrape, from the month's uploaded ETC files."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Same vehicle headers E05 and E06 accept.
_VEHICLE_ALIASES = (
    "Licence Plate No",
    "Licence Plate No.",
    "Veh Reg No.",
    "Veh Reg No",
    "Vehicle Number",
    "Vehicle No",
    "Vehicle Reg No",
    "Vehicle Reg No.",
    "Vehicle Reg. No.",
    "Veh Reg Num",
    "VRN",
    "vehicle_reg_no",
    "Reg No",
    "NPCI VRN",
    "Registration Number",
)
# E05 scrapes the "2-axel and above" sheet: every charged class except these.
_CHARGED_ALIASES = (
    "Charged Vehicle Class",
    "Charged Class",
    "Charged VC",
)
_UPTO_LCV = {"VC20", "VC4", "VC5", "VC9"}
_CACHE: dict[tuple, dict] = {}


def _header_key(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().casefold()
    if text in {"", "nan", "none", "nat"}:
        return ""
    return "".join(ch for ch in text if ch.isalnum())


def _vehicle_key(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NAT"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def _find_column(columns, aliases: tuple[str, ...]) -> str | None:
    lookup = {_header_key(col): col for col in columns if _header_key(col)}
    for name in aliases:
        hit = lookup.get(_header_key(name))
        if hit is not None:
            return hit
    return None


def _header_row_index(sample) -> int:
    targets = {_header_key(name) for name in _VEHICLE_ALIASES}
    targets.discard("")
    for idx in range(len(sample)):
        cells = {_header_key(v) for v in sample.iloc[idx].tolist()}
        if cells & targets:
            return idx
    return 0


def _csv_header_index(path: Path, encoding: str) -> int:
    import csv

    with path.open(encoding=encoding, newline="") as handle:
        reader = csv.reader(handle)
        for idx, row in enumerate(reader):
            if idx >= 40:
                break
            cells = {_header_key(cell) for cell in row}
            if cells & {_header_key(name) for name in _VEHICLE_ALIASES}:
                return idx
    return 0


def _read_table(path: Path):
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix == ".csv":
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                header_idx = _csv_header_index(path, encoding)
                return pd.read_csv(
                    path,
                    header=header_idx,
                    dtype=str,
                    encoding=encoding,
                    low_memory=False,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError(f"Could not read {path.name}: {last_error}")

    sample = pd.read_excel(path, header=None, dtype=str, nrows=40)
    header_idx = _header_row_index(sample)
    return pd.read_excel(path, header=header_idx, dtype=str)


def _keys_from_frame(frame) -> tuple[set[str], set[str], str]:
    vehicle_col = _find_column(frame.columns, _VEHICLE_ALIASES)
    if vehicle_col is None:
        raise KeyError(f"No vehicle column in {list(frame.columns)}")
    keys = frame[vehicle_col].map(_vehicle_key)
    all_keys = {key for key in keys.tolist() if key}
    charged_col = _find_column(frame.columns, _CHARGED_ALIASES)
    if charged_col is None:
        return all_keys, set(all_keys), "all_unique"
    charged = frame[charged_col].map(_vehicle_key)
    two_axle = {
        key
        for key, klass in zip(keys.tolist(), charged.tolist())
        if key and klass not in _UPTO_LCV
    }
    return all_keys, two_axle, "two_axle"


def _permit_programs_on_path() -> None:
    import sys

    from app.services.repo_paths import exception_programs_root

    root = str(exception_programs_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def _permit_db_stamp() -> str:
    """Changes when a new permit row is saved, so the preview count stays current."""
    try:
        _permit_programs_on_path()
        from common.permit_scrape_store import _connect

        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT max(scraped_at) FROM permit_scrape_cache")
                row = cur.fetchone()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        logger.warning("Permit database stamp failed", exc_info=True)
        return ""
    if not row or row[0] is None:
        return ""
    return row[0].isoformat()


def _db_permit_keys(vehicles: set[str]) -> set[str]:
    if not vehicles:
        return set()
    try:
        _permit_programs_on_path()
        from common.permit_scrape_store import cached_vehicle_keys

        return cached_vehicle_keys(vehicles)
    except Exception:  # noqa: BLE001
        logger.warning("Permit database lookup for preview failed", exc_info=True)
        return set()


def _local_copy(s3_key: str, original_name: str) -> Path:
    from app.services.exception_job_s3 import download_to_path
    from app.services.repo_paths import backend_root

    suffix = Path(original_name or "").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xlsm", ".xls"}:
        suffix = ".xlsx"
    digest = hashlib.sha256(s3_key.encode("utf-8")).hexdigest()[:20]
    dest = backend_root() / "var" / "scrape-preview" / f"{digest}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    return download_to_path(s3_key, dest)


def preview_scrape_vehicles(files: list) -> dict:
    """
    files: monthly input rows or dicts with slot, s3_key, original_file_name.

    E06 count is unique ETC vehicles still missing from permit_scrape_cache.
    Stored rows are kept permanently and are shared across plazas.
    E05 count is unique vehicles E05 would send to IHMCL when the file already
    has a charged-class column; otherwise it is every unique vehicle in the file.
    A scraped upload means neither program scrapes live.
    """
    rows = []
    for item in files or []:
        if hasattr(item, "slot"):
            rows.append(
                {
                    "slot": item.slot,
                    "s3_key": item.s3_key,
                    "name": item.original_file_name,
                    "size": item.file_size_bytes,
                }
            )
        else:
            rows.append(
                {
                    "slot": item.get("slot"),
                    "s3_key": item.get("s3_key"),
                    "name": item.get("original_file_name"),
                    "size": item.get("file_size_bytes"),
                }
            )

    has_scrape_upload = any(row["slot"] == "scraped" and row["s3_key"] for row in rows)
    if has_scrape_upload:
        idle = {"live": False, "vehicles": 0}
        return {"e05": dict(idle), "e06": dict(idle)}

    etc_rows = [row for row in rows if row["slot"] == "etc" and row["s3_key"]]
    if not etc_rows:
        return {}

    cache_key = (
        tuple((row["s3_key"], row["size"]) for row in etc_rows),
        _permit_db_stamp(),
    )
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    all_keys: set[str] = set()
    two_axle: set[str] = set()
    saw_two_axle = False
    saw_all = False
    read_error = ""
    for row in etc_rows:
        try:
            path = _local_copy(str(row["s3_key"]), str(row["name"] or ""))
            frame = _read_table(path)
            file_all, file_two, basis = _keys_from_frame(frame)
        except Exception as exc:  # noqa: BLE001
            read_error = str(exc)
            logger.warning(
                "Scrape preview skipped %s", row.get("name") or row["s3_key"],
                exc_info=True,
            )
            continue
        all_keys |= file_all
        if basis == "two_axle":
            saw_two_axle = True
            two_axle |= file_two
        else:
            saw_all = True
            two_axle |= file_all

    if not all_keys and not two_axle:
        message = read_error or "Could not read a vehicle column from the ETC file."
        failed = {"live": True, "vehicles": None, "error": message}
        return {"e05": dict(failed), "e06": dict(failed)}

    cache_keys = _db_permit_keys(all_keys)
    hits = all_keys & cache_keys
    e05_keys = two_axle if saw_two_axle and not saw_all else all_keys
    result = {
        "e05": {
            "live": True,
            "vehicles": len(e05_keys),
            "basis": "two_axle" if saw_two_axle and not saw_all else "all_unique",
        },
        "e06": {
            "live": True,
            "vehicles": len(all_keys - cache_keys),
            "unique": len(all_keys),
            "cache_hits": len(hits),
        },
    }
    logger.info(
        "Scrape preview E05=%s E06=%s",
        result["e05"]["vehicles"],
        result["e06"]["vehicles"],
    )
    _CACHE[cache_key] = result
    return result
