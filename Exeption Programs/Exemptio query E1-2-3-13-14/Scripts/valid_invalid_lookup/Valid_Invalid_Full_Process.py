import os
from pathlib import Path
import json
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

PORTAL_ROOT = Path(__file__).resolve().parents[2]
# Exeption Programs/ (sibling of E4/, Exemptio query…/)
EXCEPTION_PROGRAMS_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
E4_DIR = EXCEPTION_PROGRAMS_ROOT / "E4"
# Prefer E4/plaza_rates.py (canonical). Do not use Scripts/plaza_rates.py.
if str(E4_DIR) not in sys.path:
    sys.path.insert(0, str(E4_DIR))
if str(PORTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTAL_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

load_dotenv(EXCEPTION_PROGRAMS_ROOT / ".env")
load_dotenv(
    EXCEPTION_PROGRAMS_ROOT.parent / "Website" / "backend" / ".env",
    override=False,
)

from Header_Mapping.header_mapping import VALID_INVALID_LOOKUP_HEADER_MAPPING
from header_matching import normalize_header_match
from plaza_rates import (  # noqa: E402  — E4/plaza_rates.py
    APR26_RATES_START_DATE,
    get_all_plaza_names,
    normalize_plaza_rate_key,
    resolve_plaza_rates_dict,
)

from valid_invalid_config import (
    ACCEPTED_STATUS_VALUES,
    BUS_VEHICLE_CLASSES,
    CRANE_MOUNTED_VEHICLE_CLASS,
    DISCOUNT_PASS_JOURNEY_TYPES,
    HEAVY_SPECIAL_VEHICLE_CLASSES,
    INVALID_EXCLUDED_VEHICLE_CLASSES,
    JOURNEY_TYPES_TO_DROP,
    LIFECYCLE_EXCLUDED_VEHICLE_CLASSES,
    RATE_SHEET_ID_COLUMN_ALIASES,
    RATE_SHEET_JOURNEY_COLUMN_RENAMES,
    STATUS_COLUMN_CANDIDATES,
    UPDATED_JOURNEY_TYPE_CONT,
    UPDATED_JOURNEY_TYPE_LOCAL,
    UPDATED_JOURNEY_TYPE_SINGLE,
    ZERO_SETTLEMENT_REMOVE_JOURNEY_TYPES,
    map_npci_to_tc_class,
    normalize_journey_type,
)


def normalize_vehicle_class(value) -> str:
    """Strip + casefold so ' BUS' / 'BUS' / 'bus' compare equal."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip().casefold()


def normalized_vehicle_class_set(values) -> set:
    return {normalize_vehicle_class(v) for v in values if normalize_vehicle_class(v)}


def vehicle_class_isin(series: pd.Series, values) -> pd.Series:
    targets = normalized_vehicle_class_set(values)
    return series.map(normalize_vehicle_class).isin(targets)


def vehicle_class_eq(series: pd.Series, value) -> pd.Series:
    target = normalize_vehicle_class(value)
    if not target:
        return pd.Series(False, index=series.index)
    return series.map(normalize_vehicle_class) == target


# -----------------------------
# Input/Output Paths
# -----------------------------
OUTPUT_DIR = os.environ.get("VALID_INVALID_OUTPUT_DIR")
output_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else Path(__file__).resolve().parent / "veeravalli valid invalid output"
output_dir.mkdir(parents=True, exist_ok=True)
output_invalid_path = output_dir / "invalid_table.csv"
output_valid_path = output_dir / "valid_table.csv"

# -----------------------------
# RDS Connection Details
# -----------------------------
DB_HOST = os.environ.get("RDS_HOST")
DB_PORT = os.environ.get("RDS_PORT", "5432")
DB_NAME = os.environ.get("RDS_DB_NAME")
DB_USER = os.environ.get("RDS_USER")
DB_PASSWORD = os.environ.get("RDS_PASSWORD")
TABLE_NAME = os.environ.get("RDS_TABLE_NAME", "checkpostmaster")

# -----------------------------
# Plaza rates (from plaza_rates.py) + lifecycle input
# -----------------------------
PLAZA_NAME = os.environ.get("VALID_INVALID_PLAZA_NAME", "").strip()
LIFECYCLE_INPUT_PATH = os.environ.get("VALID_INVALID_LIFECYCLE_PATH", r"merged_output.csv")
USER_HEADER_MAPPING = json.loads(os.environ.get("VALID_INVALID_HEADER_MAPPING", "{}"))

# Index 1-6 in plaza_rates maps to these TC Class / Weight bands (and bus seating bands).
_PLAZA_RATE_CLASS_ROWS = (
    (1, "Car", "LMV/CJV/VC20", "<=7500 Kgs"),
    (2, "LCV", "LCV", ">7500 Kgs but <=12,000 Kgs"),
    (3, "Trk 2 Axle", "TRUCK 2 Axle", "> 12,000 Kgs but <= 18,500 Kgs"),
    (3, "Bus", "BUS", "More than 32 seating capacity"),
    (4, "Truck 3 axle", "3AXLE", "> 18,500 Kgs but <= 28,000 Kgs"),
    (5, "MAV", "MAV (4 to 6 Axle)", "> 28,000 Kgs but <= 60,000 Kgs"),
    (6, "OSV", "OSV (7 Axle)", ">60,000 Kgs"),
    (1, "Car", "LMV/CJV/VC20", "Less than equal to 12 seating capacity"),
    (2, "LCV", "LCV", "exceeds 12 but less than equal to 32"),
)

_DATE_COLUMN_CANDIDATES = (
    "Reader Read Time",
    "Date & Time",
    "Date Time",
    "Transaction Date Time",
    "Transaction Date",
    "Txn Date",
    "Txn Date Time",
    "DATETIME",
    "Date",
)

_HEADER_SCAN_ROWS = 50
_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _lifecycle_header_candidates():
    candidates = []
    for aliases in VALID_INVALID_LOOKUP_HEADER_MAPPING.values():
        candidates.extend(aliases)
    candidates.extend(_DATE_COLUMN_CANDIDATES)
    candidates.extend(
        (
            "Agency Txn Id",
            "Plaza ID",
            "Lane ID",
            "Settlement Amount",
            "Settlement Type",
            "Vehicle Reg. No.",
        )
    )
    return candidates


def _detect_header_row_index(df_raw: pd.DataFrame, header_keywords, min_matches: int = 2):
    """Return the first row that matches enough header keywords, else None."""
    target = {normalize_header_match(k) for k in header_keywords if normalize_header_match(k)}
    best_idx = None
    best_matches = 0
    for idx in range(len(df_raw)):
        row_values = {
            normalize_header_match(v)
            for v in df_raw.iloc[idx].tolist()
            if normalize_header_match(v)
        }
        match_count = len(target.intersection(row_values))
        if match_count > best_matches:
            best_matches = match_count
            best_idx = idx
        if match_count >= min_matches:
            return idx
    if best_idx is not None and best_matches >= min_matches:
        return best_idx
    return None


def _read_csv_with_encoding(path: Path, **kwargs) -> pd.DataFrame:
    last_error = None
    for encoding in _CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return pd.read_csv(path, **kwargs)


def load_lifecycle_dataframe(lifecycle_path, nrows=None) -> pd.DataFrame:
    """
    Load a lifecycle/ETC file as CSV or Excel.

    Detects a title/metadata header row the same way the portal header-mapping
    preview does, so a raw plaza Excel upload works without Life Cycle Merge.
    """
    path = Path(lifecycle_path)
    if not path.is_file():
        raise FileNotFoundError(f"Lifecycle file not found: {path}")

    suffix = path.suffix.lower()
    header_candidates = _lifecycle_header_candidates()

    if suffix == ".csv":
        sample = _read_csv_with_encoding(
            path, header=None, dtype=str, nrows=_HEADER_SCAN_ROWS, low_memory=False
        )
        header_row_index = _detect_header_row_index(sample, header_candidates, min_matches=2)
        if header_row_index is None:
            header_row_index = 0
        read_kwargs = {"skiprows": header_row_index, "low_memory": False}
        if nrows is not None:
            read_kwargs["nrows"] = nrows
        df = _read_csv_with_encoding(path, **read_kwargs)
        print(
            f"Valid/Invalid Lookup: loaded CSV '{path.name}' "
            f"(header row index={header_row_index}, rows={len(df)})."
        )
        return df

    if suffix in {".xlsx", ".xls"}:
        excel_file = pd.ExcelFile(path)
        for sheet_name in excel_file.sheet_names:
            sample = pd.read_excel(
                excel_file,
                sheet_name=sheet_name,
                header=None,
                dtype=str,
                nrows=_HEADER_SCAN_ROWS,
            )
            if sample.empty:
                continue
            header_row_index = _detect_header_row_index(
                sample, header_candidates, min_matches=2
            )
            if header_row_index is None:
                continue
            read_kwargs = {
                "sheet_name": sheet_name,
                "skiprows": header_row_index,
            }
            if nrows is not None:
                read_kwargs["nrows"] = nrows
            df = pd.read_excel(excel_file, **read_kwargs)
            if df.empty and nrows is None:
                continue
            print(
                f"Valid/Invalid Lookup: loaded Excel '{path.name}' sheet '{sheet_name}' "
                f"(header row index={header_row_index}, rows={len(df)})."
            )
            return df
        raise ValueError(
            f"Header keyword not found in Excel file '{path.name}'. "
            "Expected columns such as Journey Type, Vehicle Reg. No., NPCI Class Desc. "
            "Job stopped — no column mapping is applied."
        )

    raise ValueError(
        f"Unsupported lifecycle file type '{suffix}' for {path.name}. "
        "Use .csv, .xlsx, or .xls."
    )


def _detect_lifecycle_as_of_date(lifecycle_path) -> date | None:
    """Return the latest parseable transaction date from the lifecycle/ETC file."""
    try:
        sample = load_lifecycle_dataframe(lifecycle_path, nrows=5000)
    except Exception as exc:
        print(f"Valid/Invalid Lookup: could not sample lifecycle dates ({exc}). Using base rates.")
        return None

    sample.columns = sample.columns.astype(str).str.strip()
    normalized = {normalize_header_match(col): col for col in sample.columns}
    date_col = None
    for candidate in _DATE_COLUMN_CANDIDATES:
        key = normalize_header_match(candidate)
        if key in normalized:
            date_col = normalized[key]
            break
    if date_col is None:
        # Fallback: first column whose name looks like a date/time field.
        for col in sample.columns:
            lowered = str(col).casefold()
            if "date" in lowered or "time" in lowered:
                date_col = col
                break
    if date_col is None:
        print("Valid/Invalid Lookup: no date column found in lifecycle file. Using base rates.")
        return None

    parsed = pd.to_datetime(sample[date_col], errors="coerce", format="mixed")
    if parsed.isna().all():
        parsed = pd.to_datetime(sample[date_col], errors="coerce", dayfirst=True)
    valid = parsed.dropna()
    if valid.empty:
        print(f"Valid/Invalid Lookup: column '{date_col}' has no parseable dates. Using base rates.")
        return None
    as_of = valid.max()
    print(
        f"Valid/Invalid Lookup: lifecycle date column '{date_col}' "
        f"-> as_of={as_of.date() if hasattr(as_of, 'date') else as_of}."
    )
    if isinstance(as_of, datetime):
        return as_of.date()
    if hasattr(as_of, "date"):
        return as_of.date()
    return None


def build_rates_df_from_plaza(plaza_name: str, as_of_date: date | None = None) -> pd.DataFrame:
    """
    Build the melted rates DataFrame that Valid/Invalid expects, from plaza_rates.py.

    Attributes use canonical names already:
      Single Journey / Cont. Journey / Local Conti/Single
    """
    plaza_data, source = resolve_plaza_rates_dict(plaza_name, as_of_date=as_of_date)
    if plaza_data is None:
        available = ", ".join(sorted(get_all_plaza_names()))
        raise KeyError(
            f"No rates configured for plaza '{plaza_name}'. "
            f"Available plazas: {available}"
        )

    section_to_attribute = {
        "single": UPDATED_JOURNEY_TYPE_SINGLE,
        "return": UPDATED_JOURNEY_TYPE_CONT,
        "local": UPDATED_JOURNEY_TYPE_LOCAL,
    }
    rows = []
    for index, tc_class, vehicle_class, weight_capacity in _PLAZA_RATE_CLASS_ROWS:
        for section, attribute in section_to_attribute.items():
            section_rates = plaza_data.get(section) or {}
            value = section_rates.get(index)
            if value is None:
                continue
            rows.append(
                {
                    "TC Class": tc_class,
                    "Vehicle Class": vehicle_class,
                    "Weight/Capacity": weight_capacity,
                    "Attribute": attribute,
                    "value": value,
                }
            )

    if not rows:
        raise ValueError(f"Plaza '{plaza_name}' rate table is empty (source={source}).")

    print(
        f"Valid/Invalid Lookup: using plaza_rates for '{normalize_plaza_rate_key(plaza_name)}' "
        f"(source={source}, as_of={as_of_date}, cutoff={APR26_RATES_START_DATE})."
    )
    return pd.DataFrame(rows)


def process_vehicle(lifecycle_input_path):
    missing_db_config = [
        key
        for key, value in {
            "RDS_HOST": DB_HOST,
            "RDS_DB_NAME": DB_NAME,
            "RDS_USER": DB_USER,
            "RDS_PASSWORD": DB_PASSWORD,
        }.items()
        if not value
    ]
    if missing_db_config:
        raise EnvironmentError(
            "Missing required database configuration in .env: "
            + ", ".join(missing_db_config)
        )

    df_l = load_lifecycle_dataframe(lifecycle_input_path)

    engine = create_engine(
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    query = f'SELECT * FROM "{TABLE_NAME}"'

    chunk_frames = []
    for chunk in pd.read_sql_query(query, con=engine, chunksize=100000):
        chunk_frames.append(chunk)

    if not chunk_frames:
        raise ValueError(f"No data found in table: {TABLE_NAME}")

    df_c = pd.concat(chunk_frames, ignore_index=True)
    engine.dispose()

    def normalize_column_name(name):
        return normalize_header_match(name)

    normalized_to_original = {normalize_column_name(col): col for col in df_c.columns}
    required_map = {
        "Unique Vehicle Number": ["uniquevehiclenumber", "vehicleregno", "vrn"],
        "vehicle class": ["vehicleclass", "npciclassdesc", "class"],
        "weight": ["weight", "seatingcapacity", "capacity"],
    }

    rename_columns = {}
    for expected_col, candidates in required_map.items():
        for candidate in candidates:
            if candidate in normalized_to_original:
                rename_columns[normalized_to_original[candidate]] = expected_col
                break

    df_c = df_c.rename(columns=rename_columns)

    missing_required = [
        col for col in ["Unique Vehicle Number", "vehicle class", "weight"] if col not in df_c.columns
    ]
    if missing_required:
        raise KeyError(
            f"Missing required checkpostmaster columns: {missing_required}. "
            f"Available columns: {list(df_c.columns)}"
        )

    df_c["Unique Vehicle Number"] = df_c["Unique Vehicle Number"].astype(str).str.replace(".", "", regex=False)
    df_c["weight"] = df_c["weight"].apply(lambda x: str(x) if pd.notnull(x) else None)

    df_c = df_c[
        ~df_c["vehicle class"].isin(
            [
                "---Select Vehicle Class---",
                "THREE WHEE! ER{PASSENGER)",
                "THREE WHEELER(GOODS)",
                "THREE WHEELER(PASSENGER)",
                "THREE WHEELER{GOODS)",
                "—Select Vehicle Class—",
                "--Select Vehicle Class--",
                "----Select Vehicle Class----",
                "---Select Vehicle Class---",
                "----Select Vehicle Class----",
            ]
        )
        & (df_c["Unique Vehicle Number"] != "PB11U4131")
        & (df_c["Unique Vehicle Number"] != "MH04DT4250")
        & (df_c["Unique Vehicle Number"] != "MP13WA9975")
        & (df_c["Unique Vehicle Number"] != "MP13WA9928")
    ]

    df_c = df_c[~((df_c["vehicle class"].isnull()) & (df_c["weight"].isnull()))]
    df_c = df_c.drop_duplicates()
    df_c = df_c.drop_duplicates(subset="Unique Vehicle Number")

    df_l.columns = df_l.columns.str.strip()

    rename_map = {
        canonical: [candidate for candidate in candidates if candidate != canonical]
        for canonical, candidates in VALID_INVALID_LOOKUP_HEADER_MAPPING.items()
    }

    user_renames = {}
    for target, selected_source in USER_HEADER_MAPPING.items():
        if (
            target in VALID_INVALID_LOOKUP_HEADER_MAPPING
            and selected_source
            and selected_source in df_l.columns
            and selected_source != target
        ):
            user_renames[selected_source] = target

    if user_renames:
        df_l = df_l.rename(columns=user_renames)

    normalized_columns = {normalize_header_match(col): col for col in df_l.columns}

    for target, alternatives in rename_map.items():
        if target not in df_l.columns:
            for alt in alternatives:
                normalized_alt = normalize_header_match(alt)
                if normalized_alt in normalized_columns:
                    df_l = df_l.rename(columns={normalized_columns[normalized_alt]: target})
                    break

    if "Journey Type" in df_l.columns:
        df_l = df_l[~df_l["Journey Type"].isin(JOURNEY_TYPES_TO_DROP)]

    status_col = next(
        (col for col in STATUS_COLUMN_CANDIDATES if col in df_l.columns),
        None,
    )
    if status_col:
        df_l = df_l[df_l[status_col].isin(ACCEPTED_STATUS_VALUES)]

    df_l["Veh Reg No."] = df_l["Veh Reg No."].str.upper().str.strip()
    df_c["Unique Vehicle Number"] = df_c["Unique Vehicle Number"].str.upper().str.strip()

    df_merged = df_l.merge(
        df_c,
        left_on="Veh Reg No.",
        right_on="Unique Vehicle Number",
        how="left",
    ).drop(columns=["Unique Vehicle Number"])

    df_merged["updated journey type"] = df_merged["Journey Type"].apply(normalize_journey_type)

    df_final = df_merged[
        (df_merged["Veh Reg No."].str.len() <= 12)
        & ((df_merged["vehicle class"].notna()) | (df_merged["weight"].notna() & (df_merged["weight"] != "nan")))
    ]

    df_final["weight"] = pd.to_numeric(df_final["weight"], errors="coerce").astype("Int64")
    return df_final


def _resolve_rates_id_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename rates-sheet identity columns to canonical TC Class / Weight/Capacity / Vehicle Class."""
    aliases = RATE_SHEET_ID_COLUMN_ALIASES or {}
    canonical_names = ("TC Class", "Weight/Capacity", "Vehicle Class")
    norm_to_col = {normalize_header_match(col): col for col in df.columns}
    rename: dict = {}
    missing = []

    for canonical in canonical_names:
        candidates = [canonical] + list(aliases.get(canonical, []))
        found = None
        for candidate in candidates:
            key = normalize_header_match(candidate)
            if key in norm_to_col:
                found = norm_to_col[key]
                break
        if found is None:
            missing.append(canonical)
            continue
        if found != canonical:
            rename[found] = canonical

    if missing:
        raise KeyError(
            "Rates sheet is missing required identity column(s): "
            f"{missing}. Tried aliases from RATE_SHEET_ID_COLUMN_ALIASES. "
            f"Available columns: {list(df.columns)}"
        )
    return df.rename(columns=rename) if rename else df


def _resolve_rates_journey_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename journey-rate columns using RATE_SHEET_JOURNEY_COLUMN_RENAMES (normalized match)."""
    id_cols = {"TC Class", "Weight/Capacity", "Vehicle Class"}
    # source_norm → canonical Attribute name
    rename_lookup = {
        normalize_header_match(src): dest
        for src, dest in (RATE_SHEET_JOURNEY_COLUMN_RENAMES or {}).items()
        if src and dest
    }
    rename: dict = {}
    for col in df.columns:
        if col in id_cols:
            continue
        dest = rename_lookup.get(normalize_header_match(col))
        if dest and dest != col:
            rename[col] = dest
    return df.rename(columns=rename) if rename else df


def rates(df):
    df = _resolve_rates_id_columns(df)
    df = _resolve_rates_journey_columns(df)
    return df.melt(id_vars=["TC Class", "Weight/Capacity", "Vehicle Class"], var_name="Attribute")


def get_rate_from_rates(tc_class, journey_type, rates_df):
    row = rates_df.loc[
        (rates_df["TC Class"] == tc_class) & (rates_df["Attribute"] == journey_type),
        "value",
    ]
    return row.values[0] if not row.empty else 0


def vehicle_lifecycle(df_result, rates_df):
    df_result = df_result[~vehicle_class_isin(df_result["vehicle class"], LIFECYCLE_EXCLUDED_VEHICLE_CLASSES)]

    conditions = [
        vehicle_class_isin(df_result["vehicle class"], HEAVY_SPECIAL_VEHICLE_CLASSES)
        & (df_result["updated journey type"] == UPDATED_JOURNEY_TYPE_SINGLE),
        vehicle_class_isin(df_result["vehicle class"], HEAVY_SPECIAL_VEHICLE_CLASSES)
        & (df_result["updated journey type"] == UPDATED_JOURNEY_TYPE_CONT),
        vehicle_class_isin(df_result["vehicle class"], HEAVY_SPECIAL_VEHICLE_CLASSES)
        & (df_result["updated journey type"] == UPDATED_JOURNEY_TYPE_LOCAL),
        vehicle_class_eq(df_result["vehicle class"], CRANE_MOUNTED_VEHICLE_CLASS)
        & (df_result["updated journey type"] == UPDATED_JOURNEY_TYPE_SINGLE),
        vehicle_class_eq(df_result["vehicle class"], CRANE_MOUNTED_VEHICLE_CLASS)
        & (df_result["updated journey type"] == UPDATED_JOURNEY_TYPE_CONT),
        vehicle_class_eq(df_result["vehicle class"], CRANE_MOUNTED_VEHICLE_CLASS)
        & (df_result["updated journey type"] == UPDATED_JOURNEY_TYPE_LOCAL),
    ]

    values = [
        get_rate_from_rates("MAV", UPDATED_JOURNEY_TYPE_SINGLE, rates_df),
        get_rate_from_rates("MAV", UPDATED_JOURNEY_TYPE_CONT, rates_df),
        get_rate_from_rates("MAV", UPDATED_JOURNEY_TYPE_LOCAL, rates_df),
        get_rate_from_rates("LCV", UPDATED_JOURNEY_TYPE_SINGLE, rates_df),
        get_rate_from_rates("LCV", UPDATED_JOURNEY_TYPE_CONT, rates_df),
        get_rate_from_rates("LCV", UPDATED_JOURNEY_TYPE_LOCAL, rates_df),
    ]

    df_result["Rate 1"] = np.select(conditions, values, default=None)

    def classify_weight(weight):
        if pd.isna(weight):
            return None
        if weight <= 7500:
            return "<=7500 Kgs"
        if weight <= 12000:
            return ">7500 Kgs but <=12,000 Kgs"
        if weight <= 18500:
            return "> 12,000 Kgs but <= 18,500 Kgs"
        if weight <= 28000:
            return "> 18,500 Kgs but <= 28,000 Kgs"
        if weight <= 60000:
            return "> 28,000 Kgs but <= 60,000 Kgs"
        return ">60,000 Kgs"

    df_result["Custom.1"] = df_result["weight"].apply(classify_weight)
    return df_result


def vehicle_bus(df_result):
    df_result = df_result[vehicle_class_isin(df_result["vehicle class"], BUS_VEHICLE_CLASSES)]
    df_result = df_result.dropna(subset=["weight"])

    def classify_weight(row):
        weight = row["weight"]
        if weight > 32:
            return "More than 32 seating capacity"
        if 12 < weight <= 32:
            return "exceeds 12 but less than equal to 32"
        return "Less than equal to 12 seating capacity"

    df_result["Custom.1"] = df_result.apply(classify_weight, axis=1)
    return df_result


def get_rate(df, rates_df, is_bus=False):
    df = df.merge(
        rates_df[["Attribute", "Weight/Capacity", "value"]],
        left_on=["updated journey type", "Custom.1"],
        right_on=["Attribute", "Weight/Capacity"],
        how="left",
    ).drop(columns=["Attribute", "Weight/Capacity"])

    df["value"] = df["value"].fillna(0).astype(int)

    if is_bus:
        df.rename(columns={"value": "Rate"}, inplace=True)
    else:
        df["Rate 1"] = df["Rate 1"].fillna(0).astype(int)
        df["Rate"] = df["Rate 1"] + df["value"]

    settlement_candidates = [
        "Net Settlement Amt",
        "Net Settlement Amount",
        "SETTLED Amount (Rs.)",
        "Settled Amount (Rs.)",
        "settled amount",
        "Settlement Amount",
    ]
    normalized_df_cols = {normalize_header_match(col): col for col in df.columns}
    settlement_col = None
    for candidate in settlement_candidates:
        normalized_candidate = normalize_header_match(candidate)
        if normalized_candidate in normalized_df_cols:
            settlement_col = normalized_df_cols[normalized_candidate]
            break

    if not settlement_col:
        raise KeyError(
            "Settlement amount column not found. Expected one of: "
            f"{settlement_candidates}. Available columns: {list(df.columns)}"
        )

    if settlement_col != "Net Settlement Amt":
        df.rename(columns={settlement_col: "Net Settlement Amt"}, inplace=True)
    df["Net Settlement Amt"] = pd.to_numeric(df["Net Settlement Amt"], errors="coerce").fillna(0)
    df["Custom.4"] = np.where(df["Net Settlement Amt"] < df["Rate"], "Invalid", "Valid")
    return df


def map_npci_to_tc(npci):
    return map_npci_to_tc_class(npci)

def process_vehicle_classification(df):
    df = df.copy()
    df["weight"] = df["weight"].replace(0, None)

    def correct_vehicle_class(weight):
        if pd.isna(weight) or weight == "":
            return "MAV"
        if weight <= 7500:
            return "LMV"
        if weight <= 12000:
            return "LCV"
        if weight <= 18500:
            return "Truck 2 axle"
        if weight <= 28000:
            return "Truck 3 axle"
        if 28000 < weight <= 60000:
            return "MAV"
        return "Truck 7 axle"

    df["Correct Vehicle Class"] = df["weight"].apply(correct_vehicle_class)

    def classify_custom_2(row):
        if row["Custom.1"] == "Less than equal to 12 seating capacity":
            return "LMV"
        if row["Custom.1"] == "More than 32 seating capacity":
            return "BUS"
        if row["Custom.1"] == "exceeds 12 but less than equal to 32":
            return "LCV"
        return row["Correct Vehicle Class"]

    df["Custom.2"] = df.apply(classify_custom_2, axis=1)
    df.drop(columns=["Correct Vehicle Class"], inplace=True)
    df.rename(columns={"Custom.2": "Correct Vehicle Class"}, inplace=True)
    return df


def main():
    print("Valid/Invalid Lookup: loading input data and plaza rates.")
    plaza_name = PLAZA_NAME
    if not plaza_name:
        raise ValueError(
            "VALID_INVALID_PLAZA_NAME is required. Select a plaza on the Valid/Invalid Lookup form."
        )

    as_of_date = _detect_lifecycle_as_of_date(LIFECYCLE_INPUT_PATH)
    rates_df = build_rates_df_from_plaza(plaza_name, as_of_date=as_of_date)

    df_result = process_vehicle(LIFECYCLE_INPUT_PATH)
    df_final_1 = vehicle_lifecycle(df_result, rates_df)
    df_bus = vehicle_bus(df_result)

    df_final_1 = get_rate(df_final_1, rates_df, is_bus=False)
    df_bus = get_rate(df_bus, rates_df, is_bus=True)
    df_combined = pd.concat([df_final_1, df_bus], ignore_index=True).drop(columns=["Rate 1", "value"], errors="ignore")

    single_rates = rates_df[rates_df["Attribute"] == UPDATED_JOURNEY_TYPE_SINGLE]
    rate_lookup = dict(zip(single_rates["TC Class"], single_rates["value"]))

    df_invalid = df_combined[df_combined["Custom.4"] == "Invalid"]
    df_invalid = process_vehicle_classification(df_invalid)

    df_valid = df_combined[df_combined["Custom.4"] == "Valid"]
    df_valid = process_vehicle_classification(df_valid)
    print(f"Valid/Invalid Lookup: split data -> invalid={len(df_invalid)}, valid={len(df_valid)}")

    df_invalid["Custom.2"] = df_invalid.apply(
        lambda row: "Remove"
        if row["Net Settlement Amt"] == 0
        and row["Journey Type"] in ZERO_SETTLEMENT_REMOVE_JOURNEY_TYPES
        else "Keep",
        axis=1,
    )
    df_invalid = df_invalid[df_invalid["Custom.2"] != "Remove"]
    df_invalid.drop(columns=["Custom.2"], inplace=True)

    def update_net_settlement(row):
        if row["Journey Type"] in DISCOUNT_PASS_JOURNEY_TYPES:
            tc_class = map_npci_to_tc(row["NPCI Class Desc"])
            if tc_class and tc_class in rate_lookup:
                return rate_lookup[tc_class]
        return row["Net Settlement Amt"]

    df_invalid["updated net settlement amount"] = df_invalid.apply(update_net_settlement, axis=1)
    df_invalid.drop_duplicates(inplace=True)
    df_invalid["Impact"] = df_invalid["Rate"] - df_invalid["updated net settlement amount"]
    df_invalid = df_invalid[(df_invalid["Impact"] != 0) & (df_invalid["Impact"] > 0)]

    df_invalid = df_invalid[
        ~vehicle_class_isin(df_invalid["vehicle class"], INVALID_EXCLUDED_VEHICLE_CLASSES)
    ]

    df_valid = df_valid[df_valid["Rate"] != 0]
    print(f"Valid/Invalid Lookup: final invalid rows={len(df_invalid)}, final valid rows={len(df_valid)}")

    df_invalid.to_csv(output_invalid_path, index=False)
    df_valid.to_csv(output_valid_path, index=False)
    print(f"Valid/Invalid Lookup: exported invalid -> {output_invalid_path}")
    print(f"Valid/Invalid Lookup: exported valid -> {output_valid_path}")


if __name__ == "__main__":
    main()
