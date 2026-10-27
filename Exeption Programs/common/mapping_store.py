"""Read shared mapping tables (vehicle class, MOP, headers, indexes).

Exception programs and plaza ETL use this instead of the JSON files under
common/shared_config. Those JSON files remain the seed source only.
"""

from __future__ import annotations

import os
from pathlib import Path

_SNAPSHOT: dict | None = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_CANDIDATES = (
    _REPO_ROOT / "Website" / "backend" / ".env",
)

# Program config key -> column_alias canonical key in mapping_canonicals.
_COLUMN_KEYS = {
    "pass_type_column_names": "pass_type",
    "pass_chassis_column_names": "pass_chassis",
    "pass_start_date_column_names": "pass_start_date",
    "pass_end_date_column_names": "pass_end_date",
    "issuance_fee_column_names": "issuance_fee",
    "trips_taken_column_names": "trips_taken",
    "mapper_vehicle_class_column_names": "npci_class",
    "tc_class_column_aliases": "tc_class",
    "journey_type_column_aliases": "journey_type",
    "vehicle_column_aliases": "vehicle_reg_no",
    "datetime_column_aliases": "read_datetime",
}


def _load_dotenv_files() -> None:
    if os.getenv("DB_HOST", "").strip():
        return
    for path in _ENV_CANDIDATES:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        if os.getenv("DB_HOST", "").strip():
            return


def _connect():
    _load_dotenv_files()
    host = os.getenv("DB_HOST", "").strip()
    # Exception jobs overwrite DB_NAME with the submissions database.
    # Mapping tables live on the website analytics database.
    name = (
        os.getenv("Toll_Analytics_DB", "").strip()
        or os.getenv("DB_NAME", "").strip()
    )
    user = os.getenv("DB_USER", "").strip()
    if not host or not name or not user:
        raise RuntimeError(
            "DB_HOST, DB_USER, and Toll_Analytics_DB (or DB_NAME) are required "
            "to load mapping config."
        )
    import psycopg2

    return psycopg2.connect(
        host=host,
        port=os.getenv("DB_PORT", "5432").strip() or "5432",
        user=user,
        password=os.getenv("DB_PASSWORD", ""),
        dbname=name,
    )


def load_snapshot(*, refresh: bool = False) -> dict:
    """Process-wide snapshot of active mapping rows."""
    global _SNAPSHOT
    if _SNAPSHOT is not None and not refresh:
        return _SNAPSHOT

    groups: dict[str, dict[str, dict]] = {}
    alias_lists: dict[str, dict[str, list[str]]] = {}
    lists: dict[str, dict[str, list[str]]] = {}
    settings: dict[str, object] = {}

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.code, c.canonical_key, c.db_column, c.sort_order, a.alias
                FROM mapping_domains d
                JOIN mapping_canonicals c
                  ON c.domain_id = d.id AND c.is_active
                LEFT JOIN mapping_aliases a
                  ON a.canonical_id = c.id AND a.is_active
                ORDER BY d.code, c.sort_order, c.canonical_key, a.alias
                """
            )
            rows = cur.fetchall()
            cur.execute(
                """
                SELECT d.code, i.list_key, i.value
                FROM mapping_list_items i
                JOIN mapping_domains d ON d.id = i.domain_id
                WHERE i.is_active
                ORDER BY d.code, i.list_key, i.value
                """
            )
            list_rows = cur.fetchall()
            cur.execute("SELECT key, value_json FROM mapping_settings")
            setting_rows = cur.fetchall()
    finally:
        conn.close()

    if not rows and not list_rows and not setting_rows:
        raise RuntimeError(
            "Mapping tables are empty. From Website/backend run: "
            "flask --app run:app seed-shared-config"
        )

    order: dict[str, list[str]] = {}
    for code, canonical_key, db_column, _sort, alias in rows:
        groups.setdefault(code, {})
        bucket = groups[code].setdefault(
            canonical_key,
            {"db_column": db_column, "aliases": []},
        )
        if db_column and not bucket["db_column"]:
            bucket["db_column"] = db_column
        order.setdefault(code, [])
        if canonical_key not in order[code]:
            order[code].append(canonical_key)
        if alias:
            bucket["aliases"].append(alias)
            alias_lists.setdefault(code, {}).setdefault(canonical_key, []).append(alias)

    for code, list_key, value in list_rows:
        lists.setdefault(code, {}).setdefault(list_key, []).append(value)

    for key, value in setting_rows:
        settings[str(key)] = value

    _SNAPSHOT = {
        "groups": groups,
        "alias_lists": alias_lists,
        "lists": lists,
        "settings": settings,
        "order": order,
    }
    return _SNAPSHOT


def vehicle_class_mappings() -> dict[str, tuple[str, list[str]]]:
    """canonical -> (db_column, aliases), same shape as plaza mappings.load_mappings."""
    snap = load_snapshot()
    mappings: dict[str, tuple[str, list[str]]] = {}
    for key in snap["order"].get("vehicle_class", []):
        entry = snap["groups"]["vehicle_class"][key]
        db_column = entry.get("db_column")
        if not db_column:
            raise RuntimeError(f"Vehicle class {key} has no database column.")
        mappings[key] = (str(db_column), list(entry.get("aliases") or []))
    if not mappings:
        raise RuntimeError("No vehicle class mappings are stored.")
    return mappings


def mop_mappings() -> dict[str, tuple[str, list[str]]]:
    snap = load_snapshot()
    mappings: dict[str, tuple[str, list[str]]] = {}
    for key in snap["order"].get("mop", []):
        entry = snap["groups"]["mop"][key]
        db_column = entry.get("db_column")
        if not db_column:
            raise RuntimeError(f"Mode of payment {key} has no database column.")
        mappings[key] = (str(db_column), list(entry.get("aliases") or []))
    if not mappings:
        raise RuntimeError("No mode-of-payment mappings are stored.")
    return mappings


def list_values(domain: str, list_key: str) -> list[str]:
    snap = load_snapshot()
    return list((snap["lists"].get(domain) or {}).get(list_key) or [])


def alias_list(domain: str, canonical_key: str) -> list[str]:
    snap = load_snapshot()
    return list((snap["alias_lists"].get(domain) or {}).get(canonical_key) or [])


def canonical_keys(domain: str) -> list[str]:
    snap = load_snapshot()
    return list(snap["order"].get(domain) or [])


def _match_minimum(settings: dict, source: str | None, fallback):
    overrides = settings.get("overrides_by_source") or {}
    if source and isinstance(overrides, dict) and source in overrides:
        raw = overrides[source]
        if isinstance(raw, dict):
            raw = raw.get("min_header_matches", fallback)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return fallback
    if "min_header_matches" in settings:
        try:
            return int(settings["min_header_matches"])
        except (TypeError, ValueError):
            return fallback
    return fallback


def overlay_shared_config(
    config: dict,
    *,
    header_source: str | None = None,
    match_source: str | None = None,
) -> dict:
    """Replace shared keys on a program config with mapping-table values.

    Keys the program does not already have are left unset. Program-only rules
    (weights, scrape, rate cutover, plaza filters) stay in the local JSON.
    """
    if not isinstance(config, dict):
        return config
    snap = load_snapshot()
    settings = snap["settings"]

    if "tc_class_index_map" in config:
        tc = snap["alias_lists"].get("tc_index") or {}
        if tc:
            config["tc_class_index_map"] = {key: list(values) for key, values in tc.items()}

    if "journey_type_map" in config:
        journey = snap["alias_lists"].get("journey_type") or {}
        if journey:
            config["journey_type_map"] = {
                key: list(values) for key, values in journey.items()
            }

    pass_lists = snap["alias_lists"].get("pass_type") or {}
    if "mp_pass_type_values" in config and pass_lists.get("mp_pass_type_values"):
        config["mp_pass_type_values"] = list(pass_lists["mp_pass_type_values"])
    if "lt_pass_type_values" in config and pass_lists.get("lt_pass_type_values"):
        config["lt_pass_type_values"] = list(pass_lists["lt_pass_type_values"])

    columns = snap["alias_lists"].get("column_alias") or {}
    for config_key, canonical in _COLUMN_KEYS.items():
        values = columns.get(canonical) or []
        if config_key in config and values:
            config[config_key] = list(values)

    if header_source and "header_keywords" in config:
        keywords = alias_list("header_keyword", header_source)
        if keywords:
            from common.header_match import normalize_header_match

            merged = [str(item) for item in (config.get("header_keywords") or [])]
            seen = {normalize_header_match(item) for item in merged}
            seen.discard("")
            for item in keywords:
                token = normalize_header_match(item)
                if token and token not in seen:
                    merged.append(str(item))
                    seen.add(token)
            config["header_keywords"] = merged

    if "header_scan_rows" in config and settings.get("header_scan_rows") is not None:
        try:
            config["header_scan_rows"] = int(settings["header_scan_rows"])
        except (TypeError, ValueError):
            pass

    if "min_header_matches" in config:
        config["min_header_matches"] = _match_minimum(
            settings,
            match_source or header_source,
            config.get("min_header_matches"),
        )

    return config
