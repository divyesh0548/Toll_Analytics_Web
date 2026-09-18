"""
E10 — VRN download/merge → drop excluded TC Class → attach checkpost Weight.

1) Download/merge VRN files for entity_name + date range (E4 vrn-download-merge)
2) Drop rows whose TC Class is in the exclude list (e10_config.json)
3) Lookup weight from Checkpost_DB (checkpostmaster) by Unique Vehicle Number
4) Drop rows with null / empty / "0" / "N/A" Weight
5) Write enriched VRN CSV

Runtime inputs are set below (not in config).
DB credentials / Checkpost_* come from Exeption Programs/E4/.env

Run:
  1. Set ENTITY_NAME, FROM_DATE, TO_DATE
  2. python Main_E10.py
     or: python Main_E10.py odhaki_paipkhar 2026-01-01 2026-04-30
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

BASE_DIR = Path(__file__).resolve().parent
E4_DIR = BASE_DIR.parent / "E4"
CONFIG_PATH = BASE_DIR / "e10_config.json"
ENV_FILE = E4_DIR / ".env"
VRN_DOWNLOAD_MERGE_PATH = E4_DIR / "vrn-download-merge.py"
OUTPUT_DIR = BASE_DIR / "output"

# --- Runtime inputs (edit these; not in config) ---
ENTITY_NAME = "odhaki_paipkhar"
FROM_DATE = "2026-01-01"
TO_DATE = "2026-02-30"
MERGED_OUTPUT_FILE = OUTPUT_DIR / "e10_vrn_with_weight.csv"


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_env() -> None:
    if not ENV_FILE.is_file():
        raise FileNotFoundError(f"Env file not found: {ENV_FILE}")
    load_dotenv(ENV_FILE, override=True)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name} (in {ENV_FILE})")
    return value


def checkpost_connection_kwargs() -> dict:
    return {
        "host": require_env("DB_HOST"),
        "port": int(os.getenv("DB_PORT") or "5432"),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": require_env("Checkpost_DB_NAME"),
    }


def checkpost_table_name() -> str:
    return (
        os.getenv("Checkpost_Table_NAME", "").strip()
        or os.getenv("CHECKPOST_TABLE_NAME", "").strip()
        or "checkpostmaster"
    )


def _normalize_header_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return " ".join(text.split())


def _normalize_header_key(value) -> str:
    return _normalize_header_cell(value).casefold()


def normalize_vehicle_number(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NAT"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_tc_class_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def resolve_column(headers: list[str], aliases: list[str]) -> str | None:
    by_key = {_normalize_header_key(h): h for h in headers if _normalize_header_cell(h)}
    for alias in aliases or []:
        key = _normalize_header_key(alias)
        if key in by_key:
            return by_key[key]
    return None


def resolve_entity_and_dates() -> tuple[str, str, str]:
    entity = ENTITY_NAME
    from_date = FROM_DATE
    to_date = TO_DATE
    if len(sys.argv) >= 2 and str(sys.argv[1]).strip():
        entity = str(sys.argv[1]).strip()
    if len(sys.argv) >= 3 and str(sys.argv[2]).strip():
        from_date = str(sys.argv[2]).strip()
    if len(sys.argv) >= 4 and str(sys.argv[3]).strip():
        to_date = str(sys.argv[3]).strip()

    entity = str(entity or "").strip()
    from_date = str(from_date or "").strip()
    to_date = str(to_date or "").strip()
    if not entity:
        entity = input("Enter entity_name: ").strip()
    if not from_date:
        from_date = input("Enter FROM_DATE (YYYY-MM-DD): ").strip()
    if not to_date:
        to_date = input("Enter TO_DATE (YYYY-MM-DD): ").strip()
    if not entity or not from_date or not to_date:
        raise RuntimeError("entity_name, FROM_DATE and TO_DATE are required.")
    return entity, from_date, to_date


def load_vrn_download_merge_module():
    path = VRN_DOWNLOAD_MERGE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"VRN download script not found: {path}")
    spec = importlib.util.spec_from_file_location("e4_vrn_download_merge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def drop_excluded_tc_class_rows(vrn_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    headers = [str(c) for c in vrn_df.columns]
    tc_col = resolve_column(headers, config.get("tc_class_column_aliases") or [])
    if not tc_col:
        raise RuntimeError(
            "TC Class column not found on merged VRN. "
            f"Available: {list(vrn_df.columns)}"
        )

    exclude = {
        normalize_tc_class_key(v)
        for v in (config.get("tc_class_exclude") or [])
        if normalize_tc_class_key(v)
    }
    if not exclude:
        print("tc_class_exclude is empty — no TC Class rows dropped.")
        return vrn_df

    keys = vrn_df[tc_col].map(normalize_tc_class_key)
    keep = ~keys.isin(exclude)
    dropped = int((~keep).sum())
    out = vrn_df.loc[keep].reset_index(drop=True)
    print(
        f"Dropped {dropped} rows with TC Class in {sorted(exclude)} "
        f"({len(out)} remaining)"
    )
    return out


def fetch_checkpost_weight_lookup(
    vehicle_numbers: list[str],
    config: dict,
) -> dict[str, str]:
    """Map normalized Unique Vehicle Number → weight (as stored text)."""
    unique_vehs = sorted({v for v in vehicle_numbers if v})
    if not unique_vehs:
        return {}

    load_env()
    table = checkpost_table_name()
    veh_col = str(
        config.get("checkpost_vehicle_column") or "Unique Vehicle Number"
    ).strip()
    weight_col = str(config.get("checkpost_weight_column") or "weight").strip()
    batch_size = int(config.get("checkpost_fetch_batch_size") or 1000)

    query = sql.SQL(
        """
        SELECT {veh} AS vehicle_no, {weight} AS weight
        FROM {table}
        WHERE regexp_replace(upper(COALESCE({veh}, '')), '[^A-Z0-9]', '', 'g') = ANY(%s)
        """
    ).format(
        table=sql.Identifier(table),
        veh=sql.Identifier(veh_col),
        weight=sql.Identifier(weight_col),
    )

    lookup: dict[str, str] = {}
    print(
        f"Fetching checkpost weights from {require_env('Checkpost_DB_NAME')}.{table} "
        f"for {len(unique_vehs):,} unique vehicles…"
    )
    with psycopg2.connect(**checkpost_connection_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            for start in range(0, len(unique_vehs), batch_size):
                batch = unique_vehs[start : start + batch_size]
                # Match both raw and normalized forms: query with batch as-is;
                # also try uppercase variants already normalized.
                cursor.execute(query, (batch,))
                rows = cursor.fetchall()
                for row in rows:
                    veh = normalize_vehicle_number(row.get("vehicle_no"))
                    if not veh or veh in lookup:
                        continue
                    weight_raw = row.get("weight")
                    if weight_raw is None or (
                        isinstance(weight_raw, float) and pd.isna(weight_raw)
                    ):
                        continue
                    weight_text = str(weight_raw).strip()
                    if weight_text == "" or weight_text.lower() in {"nan", "none"}:
                        continue
                    lookup[veh] = weight_text

    print(f"  Checkpost weight hits: {len(lookup):,}/{len(unique_vehs):,}")
    return lookup


def attach_weight_from_checkpost(
    vrn_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    headers = [str(c) for c in vrn_df.columns]
    veh_col = resolve_column(headers, config.get("vehicle_column_aliases") or [])
    if not veh_col:
        raise RuntimeError(
            "Vehicle column not found on merged VRN. "
            f"Available: {list(vrn_df.columns)}"
        )

    out_col = str(config.get("weight_output_column") or "Weight").strip() or "Weight"
    vehs = vrn_df[veh_col].map(normalize_vehicle_number)
    # Checkpost stores plates without separators; query with normalized values.
    lookup = fetch_checkpost_weight_lookup(vehs.tolist(), config)

    weights = [lookup.get(v, "") for v in vehs.tolist()]
    result = vrn_df.copy()
    result[out_col] = weights
    matched = sum(1 for w in weights if w != "")
    print(
        f"Weight attached via checkpost on {veh_col!r} → {out_col!r}: "
        f"{matched}/{len(result)} rows matched"
    )
    return result


def drop_invalid_weight_rows(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    headers = [str(c) for c in df.columns]
    weight_col = resolve_column(
        headers,
        [
            str(config.get("weight_output_column") or "Weight"),
            "Weight",
            "weight",
        ],
    )
    if not weight_col:
        raise RuntimeError(
            "Weight column not found after checkpost lookup. "
            f"Available: {list(df.columns)}"
        )

    invalid = {
        str(v).strip().casefold()
        for v in (config.get("weight_invalid_values") or [])
    }
    # Always treat blank / null-like as invalid
    invalid.update({"", "0", "0.0", "n/a", "na", "null", "none", "nan", "nat"})

    def is_valid(value) -> bool:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return False
        text = str(value).strip()
        if text.casefold() in invalid:
            return False
        # Numeric zero (e.g. 0.00)
        try:
            if float(text.replace(",", "")) == 0.0:
                return False
        except ValueError:
            pass
        return True

    keep = df[weight_col].map(is_valid)
    dropped = int((~keep).sum())
    out = df.loc[keep].reset_index(drop=True)
    print(
        f"Dropped {dropped} rows with null/invalid Weight "
        f"(kept {len(out)})"
    )
    return out


def save_output(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".xlsx":
        df.to_excel(path, index=False)
    else:
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Wrote: {path}")
    return path


def main() -> int:
    print("=" * 60)
    print("E10 — VRN + checkpost Weight")
    print("=" * 60)

    config = load_config()
    entity_name, from_date, to_date = resolve_entity_and_dates()
    print(f"entity_name: {entity_name}")
    print(f"date range: {from_date} → {to_date}")

    print("-" * 60)
    print("Downloading / merging VRN…")
    vrn_mod = load_vrn_download_merge_module()
    vrn_path = vrn_mod.run_vrn_download_merge(
        entity_name,
        from_date,
        to_date,
        merged_output_dir=OUTPUT_DIR,
    )
    if vrn_path is None:
        raise RuntimeError("VRN download finished without a merged file path.")
    print(f"Merged VRN: {vrn_path}")

    vrn_df = pd.read_csv(vrn_path, dtype=str, keep_default_na=False)
    print(f"Merged VRN rows: {len(vrn_df)}")

    print("-" * 60)
    filtered = drop_excluded_tc_class_rows(vrn_df, config)

    print("-" * 60)
    with_weight = attach_weight_from_checkpost(filtered, config)
    with_weight = drop_invalid_weight_rows(with_weight, config)

    out_path = save_output(with_weight, Path(MERGED_OUTPUT_FILE))
    print(f"Rows: {len(with_weight)} | Columns: {list(with_weight.columns)}")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
