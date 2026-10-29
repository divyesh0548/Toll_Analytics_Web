"""Catalog of exception programs available for upload/run jobs."""

from __future__ import annotations

from pathlib import Path

# Group shown as one card on the Exceptions Upload page.
FULL_EXEMPT_PROGRAM = {
    "code": "full_exempt_e1_e2_e3_e13_e14",
    "label": "Exempt Query — Full Process",
    "description": (
        "One run produces annexure workbooks and updates audit metrics for "
        "E01, E02, E03, E13, and E14."
    ),
    "group_exception_codes": ["E01", "E02", "E03", "E13", "E14"],
    "group_exception_type_ids": [1, 2, 3, 13, 14],
    "enabled": True,
    # Needs codes_dump / annexure plaza key in addition to Website plaza.
    "requires_pipeline_plaza_key": True,
    "uses_entity_map": False,
    "input_slots": [
        {
            "key": "lc_etc",
            "label": "LC / ETC files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "vrn",
            "label": "VRN files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "pass",
            "label": "Pass reports",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "concessionaire",
            "label": "Concessionaire file(s)",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "rates",
            "label": "Rates (optional)",
            "required": False,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm",
            "server_default": True,
        },
        {
            "key": "approved_exemption",
            "label": "Approved exemption",
            "required": False,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm",
            "server_default": True,
        },
    ],
}

# Placeholders for other exception programs (wired later).
# uses_entity_map=True → Website only asks for plaza; entity_name comes from
# Exeption Programs/common/plaza_entity_map.json.
_PLACEHOLDER_DEFAULTS = {
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "input_slots": [],
}

E04_PROGRAM = {
    "code": "e04",
    "label": "E04 — Local passes to commercial vehicles",
    "description": (
        "Upload pass files; ETC/VRN are downloaded automatically when needed. "
        "Updates E04 metrics and uploads merged output to S3. "
        "Plaza only — entity_name from plaza_entity_map.json."
    ),
    "group_exception_codes": ["E04"],
    "group_exception_type_ids": [4],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    "input_slots": [
        {
            "key": "pass",
            "label": "Pass files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

# Single E05 job: lifecycle → Valid/Invalid (internal) → E05.
# IHMCL scrape file optional: live scrape, or export VRNs for offline scrape.
E05_PROGRAM = {
    "code": "e05",
    "label": "E05 — Incorrect FASTag issuance",
    "description": (
        "Upload lifecycle/ETC. Optionally upload a scraped IHMCL vehicle file. "
        "If omitted, Start asks: live IHMCL scrape, or download vehicles to scrape "
        "offline (job stops so you can attach the scrape later). "
        "Plaza only — entity_name from plaza_entity_map.json."
    ),
    "group_exception_codes": ["E05"],
    "group_exception_type_ids": [5],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    "produces_staging_invalid": False,
    "allows_staging_invalid_pick": False,
    "may_live_scrape": True,
    "scrape_slot": "ihmcl",
    # Include legacy prep jobs in the Recent list on this card.
    "job_program_codes": ["e05", "valid_invalid_lookup"],
    "input_slots": [
        {
            "key": "lifecycle",
            "label": "Lifecycle / ETC file",
            "required": True,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "ihmcl",
            "label": "Scraped vehicle data (IHMCL) — optional",
            "required": False,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

# Legacy aliases (old queued jobs / worker imports).
E05_MAIN_PROCESS = E05_PROGRAM
VALID_INVALID_PROGRAM = {
    "code": "valid_invalid_lookup",
    "label": "Valid / Invalid Lookup (legacy)",
    "enabled": False,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": False,
    "input_slots": [
        {
            "key": "lifecycle",
            "label": "Lifecycle / ETC file",
            "required": True,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

E06_PROGRAM = {
    "code": "e06",
    "label": "E06 — Discounted passes / national permit",
    "description": (
        "Upload ETC and VRN for the period. Optionally upload permit files. "
        "If omitted, Start asks: live Parivahan scrape, or download vehicles to "
        "scrape offline (job stops so you can attach permits later). "
        "Updates E06 metrics and uploads enriched output to S3. "
        "Plaza only — entity_name from plaza_entity_map.json."
    ),
    "group_exception_codes": ["E06"],
    "group_exception_type_ids": [6],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    "may_live_scrape": True,
    "scrape_slot": "permit",
    "input_slots": [
        {
            "key": "etc",
            "label": "ETC files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "vrn",
            "label": "VRN files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "permit",
            "label": "Permit files (optional — skips live scrape)",
            "required": False,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

E07_PROGRAM = {
    "code": "e07",
    "label": "E07 — Local passes at lower or zero charge",
    "description": (
        "Upload pass files. Keeps VC4 rows, drops IHMCL_Exemption, computes "
        "Loss from months × rate vs issuance fees. Updates E07 metrics "
        "(existing months neglected) and uploads output CSV to S3. Plaza only."
    ),
    "group_exception_codes": ["E07"],
    "group_exception_type_ids": [7],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": False,
    "updates_metrics": True,
    "input_slots": [
        {
            "key": "pass",
            "label": "Pass files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

E09_PROGRAM = {
    "code": "e09",
    "label": "E09 — Unsettled transactions",
    "description": (
        "Upload ETC files. Keeps UNSETTLED settlement rows, totals Amount by "
        "Reader Read Time month, updates E09 metrics, and uploads unsettled "
        "CSV to S3. Plaza only."
    ),
    "group_exception_codes": ["E09"],
    "group_exception_type_ids": [9],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": False,
    "updates_metrics": True,
    "input_slots": [
        {
            "key": "etc",
            "label": "ETC files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

E11_PROGRAM = {
    "code": "e11",
    "label": "E11 — AVC class consistency",
    "description": (
        "Upload VRN files. Builds monthly AVC pivot by vehicle, stores the "
        "right-class percentage for E11 metrics, and uploads monthly_right_avc.csv "
        "to S3. Plaza only — entity_name from plaza_entity_map.json."
    ),
    "group_exception_codes": ["E11"],
    "group_exception_type_ids": [11],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    "input_slots": [
        {
            "key": "vrn",
            "label": "VRN files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

E10_PROGRAM = {
    "code": "e10",
    "label": "E10 — Overloading penalty (incl. E10-A/B/C)",
    "description": (
        "Upload VRN and ETC for the same period. Attaches checkpost weight, "
        "computes overweight segments E10-A/B/C, updates metrics for E10 and "
        "segments, and uploads three segment CSVs to S3 (not one combined file). "
        "Plaza only — entity_name from plaza_entity_map.json."
    ),
    "group_exception_codes": ["E10", "E10-A", "E10-B", "E10-C"],
    "group_exception_type_ids": [10],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    "input_slots": [
        {
            "key": "vrn",
            "label": "VRN files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "etc",
            "label": "ETC files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

E15_PROGRAM = {
    "code": "e15",
    "label": "E15 — Exempt vs subsequent plaza",
    "description": (
        "Upload From-plaza exempt files and To-plaza VRN. Merges on vehicle + "
        "side, keeps MATCH=Yes and non-EXEMPT payment, applies To-plaza rates, "
        "updates E15 metrics, and uploads from_to_combined.xlsx to S3 "
        "(month from Date & Time). Plaza only — entity_name from plaza_entity_map. "
        "From-plaza can reuse a Full Exempt *_final.xlsx already generated for this plaza."
    ),
    "group_exception_codes": ["E15"],
    "group_exception_type_ids": [15],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    # Reuse Full Exempt finals registered as plaza_monthly_exception_inputs
    # (slot=full_exempt_final) after Exempt Query — Full Process succeeds.
    "allows_exempt_final_pick": True,
    "input_slots": [
        {
            "key": "from_plaza",
            "label": "From-plaza exempt files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
            "or_exempt_final_pick": True,
        },
        {
            "key": "vrn",
            "label": "To-plaza VRN files",
            "required": True,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

_PLACEHOLDER_PROGRAMS: list[dict] = []


def list_programs() -> list[dict]:
    """Top-level cards on the Exceptions upload page (groups expand in-page)."""
    return [
        FULL_EXEMPT_PROGRAM,
        E04_PROGRAM,
        E05_PROGRAM,
        E06_PROGRAM,
        E07_PROGRAM,
        E09_PROGRAM,
        E10_PROGRAM,
        E11_PROGRAM,
        E15_PROGRAM,
        *_PLACEHOLDER_PROGRAMS,
    ]


def iter_runnable_programs() -> list[dict]:
    """Flat list of programs/processes that can be queued as jobs."""
    out: list[dict] = []
    for program in list_programs():
        if program.get("is_process_group") and program.get("processes"):
            out.extend(program["processes"])
        else:
            out.append(program)
    return out


def get_program(code: str) -> dict | None:
    """Resolve a runnable process/program code (not the group card alone)."""
    key = str(code or "").strip()
    for program in iter_runnable_programs():
        if program["code"] == key:
            return program
    # Allow looking up the group wrapper (UI only — not queueable).
    for program in list_programs():
        if program["code"] == key:
            return program
    # Analytics ETL programs share the same job table / worker.
    from app.services.analytics_program_catalog import get_analytics_program

    return get_analytics_program(key)


def job_list_codes_for_program(code: str) -> list[str]:
    """Codes to filter recent jobs when a catalog card (or process) is selected."""
    key = str(code or "").strip()
    if not key:
        return []
    for program in list_programs():
        if program["code"] == key:
            if program.get("job_program_codes"):
                return list(program["job_program_codes"])
            if program.get("is_process_group") and program.get("processes"):
                return [p["code"] for p in program["processes"]]
            return [key]
    # Direct process code
    if get_program(key):
        return [key]
    return [key]


def _repo_root() -> Path:
    from app.services.repo_paths import repo_root

    return repo_root()


def _exception_programs_root() -> Path:
    from app.services.repo_paths import exception_programs_root

    return exception_programs_root()


def exempt_portal_root() -> Path:
    """Path to the copied Exempt Query portal."""
    return _exception_programs_root() / "Exemptio query E1-2-3-13-14"


def e4_program_root() -> Path:
    """Path to the E4 exception program folder."""
    return _exception_programs_root() / "E4"


def e5_program_root() -> Path:
    """Path to the E5 exception program folder."""
    return _exception_programs_root() / "E5"


def e6_program_root() -> Path:
    """Path to the E6 exception program folder."""
    return _exception_programs_root() / "E6"


def e7_program_root() -> Path:
    """Path to the E7 exception program folder."""
    return _exception_programs_root() / "E7"


def e9_program_root() -> Path:
    """Path to the E9 exception program folder."""
    return _exception_programs_root() / "E9"


def e10_program_root() -> Path:
    """Path to the E10 exception program folder."""
    return _exception_programs_root() / "E10"


def e11_program_root() -> Path:
    """Path to the E11 exception program folder."""
    return _exception_programs_root() / "E11"


def e15_program_root() -> Path:
    """Path to the E15 exception program folder."""
    return _exception_programs_root() / "E15"


def valid_invalid_script_dir() -> Path:
    """Path to Valid/Invalid Lookup scripts."""
    return (
        exempt_portal_root()
        / "Scripts"
        / "valid_invalid_lookup"
    )


def load_pipeline_plaza_keys() -> list[str]:
    """Plaza keys from Full Exempt codes_dump.json (BASSI, ODAKHI, …)."""
    codes_path = (
        exempt_portal_root()
        / "Scripts"
        / "Excempy_Query"
        / "Final_7_scripts"
        / "codes_dump.json"
    )
    if not codes_path.is_file():
        return []
    import json

    data = json.loads(codes_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return sorted(str(k).strip().upper() for k in data.keys() if str(k).strip())
    return []


def load_plaza_identifier_to_pipeline_key() -> dict[str, str]:
    """
    plaza_identifier UUID → Full Exempt plaza key (BASSI, ODAKHI, …).
    Sourced from annexure_plaza_config.json plaza_identifiers (non-empty only).
    """
    import sys

    final_dir = (
        exempt_portal_root()
        / "Scripts"
        / "Excempy_Query"
        / "Final_7_scripts"
    )
    if str(final_dir) not in sys.path:
        sys.path.insert(0, str(final_dir))
    try:
        from annexure_plaza_config import get_plaza_identifier_map  # noqa: WPS433
    except Exception:  # noqa: BLE001
        return {}
    return {
        str(identifier).strip(): str(plaza_key).strip().upper()
        for plaza_key, identifier in get_plaza_identifier_map().items()
        if str(identifier).strip() and str(plaza_key).strip()
    }


def resolve_pipeline_plaza_key(plaza_identifier: str) -> str | None:
    """Map plazas.plaza_identifier → Full Exempt codes_dump key."""
    key = str(plaza_identifier or "").strip()
    if not key:
        return None
    return load_plaza_identifier_to_pipeline_key().get(key)


def _file_cover_payload(row) -> dict:
    if row is None:
        return {
            "file_name": None,
            "exists": False,
            "valid_from": None,
            "valid_to": None,
        }
    return {
        "file_name": row.original_file_name,
        "exists": True,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
    }


def load_annexure_server_defaults(
    pipeline_plaza_key: str,
    plaza_identifier: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """
    Uploaded rates and approved-exemption workbooks that cover the period.
    Website runs do not use the local Excel folders.
    """
    from datetime import date

    from app.services.plaza_reference_files import (
        find_covering,
        month_bounds,
        plaza_requires_approved_exemption,
        python_rates_available,
    )

    key = str(pipeline_plaza_key or "").strip().upper()
    identifier = str(plaza_identifier or "").strip()
    if not identifier and key:
        for plaza_id, plaza_key in load_plaza_identifier_to_pipeline_key().items():
            if plaza_key == key:
                identifier = plaza_id
                break

    if year and month:
        start, end = month_bounds(int(year), int(month))
    else:
        today = date.today()
        start, end = today, today

    uses_approved = plaza_requires_approved_exemption(key) if key else False
    rates = find_covering(identifier, "rates", start, end) if identifier else None
    approved = (
        find_covering(identifier, "approved_exemption", start, end)
        if identifier
        else None
    )
    rates_payload = _file_cover_payload(rates)
    rates_payload["python_fallback"] = python_rates_available(key)
    approved_payload = _file_cover_payload(approved)
    approved_payload["uses_approved_script"] = uses_approved
    approved_payload["blocks_run"] = bool(uses_approved and approved is None)
    return {
        "pipeline_plaza_key": key,
        "plaza_identifier": identifier or None,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "rates": rates_payload,
        "approved_exemption": approved_payload,
    }
