"""Catalog of exception programs available for upload/run jobs."""

from __future__ import annotations

from pathlib import Path

# Group shown as one card on the Exceptions Upload page.
FULL_EXEMPT_PROGRAM = {
    "code": "full_exempt_e1_e2_e3_e13_e14",
    "label": "Exempt Query — Full Pipeline",
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
            "label": "Rates (optional override)",
            "required": False,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm",
            # Plaza default already exists on the Exempt portal server.
            "server_default": True,
        },
        {
            "key": "approved_exemption",
            "label": "Approved exemption (optional override)",
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

# Process A — produces staging invalid_table for E05 (no metrics).
VALID_INVALID_PROCESS = {
    "code": "valid_invalid_lookup",
    "label": "1. Valid / Invalid Lookup",
    "description": (
        "Upload lifecycle/ETC; builds invalid_table and stores it on S3 as "
        "staging (not shown in Audit downloads). Does not update metrics. "
        "Requires checkpostmaster (RDS). Rates from E4 plaza_rates via "
        "plaza_entity_map."
    ),
    "group_exception_codes": ["E05"],
    "group_exception_type_ids": [5],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": False,
    "produces_staging_invalid": True,
    "allows_staging_invalid_pick": False,
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

# Process B — Incorrect FASTag issuance (metrics + final S3).
E05_MAIN_PROCESS = {
    "code": "e05",
    "label": "2. Incorrect FASTag issuance",
    "description": (
        "Choose an invalid table from Valid/Invalid (step 1) or upload one. "
        "Optionally upload an IHMCL scrape file, or live-scrape "
        "(EXCEPTION_USE_SELENIUM in .env). Updates E05 metrics and uploads "
        "final output to S3."
    ),
    "group_exception_codes": ["E05"],
    "group_exception_type_ids": [5],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    "produces_staging_invalid": False,
    "allows_staging_invalid_pick": True,
    "input_slots": [
        {
            "key": "invalid_table",
            "label": "Invalid table",
            "required": True,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm,.csv",
            "or_staging_pick": True,
        },
        {
            "key": "ihmcl",
            "label": "IHMCL output (optional — skips live scrape)",
            "required": False,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}

# One catalog card / page for both E05 processes (not separate links).
E05_PROGRAM = {
    "code": "e05_group",
    "label": "E05 — Incorrect FASTag issuance",
    "description": (
        "Two steps on one page: Valid/Invalid Lookup (staging invalid table), "
        "then Incorrect FASTag issuance (metrics + final S3). "
        "Plaza only — entity_name from plaza_entity_map.json."
    ),
    "group_exception_codes": ["E05"],
    "group_exception_type_ids": [5],
    "enabled": True,
    "is_process_group": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": True,
    "updates_metrics": True,
    "input_slots": [],
    "processes": [VALID_INVALID_PROCESS, E05_MAIN_PROCESS],
    # Job list for this page includes both process codes.
    "job_program_codes": ["valid_invalid_lookup", "e05"],
}

# Keep aliases for worker imports.
VALID_INVALID_PROGRAM = VALID_INVALID_PROCESS

_PLACEHOLDER_PROGRAMS = [
    {
        "code": "e06",
        "label": "E06 — Discounted passes / national permit",
        "description": "Coming soon.",
        "group_exception_codes": ["E06"],
        "group_exception_type_ids": [6],
        "enabled": False,
        **_PLACEHOLDER_DEFAULTS,
    },
    {
        "code": "e07",
        "label": "E07 — Local passes at lower or zero charge",
        "description": "Coming soon.",
        "group_exception_codes": ["E07"],
        "group_exception_type_ids": [7],
        "enabled": False,
        **_PLACEHOLDER_DEFAULTS,
    },
    {
        "code": "e09",
        "label": "E09 — Unsettled transactions",
        "description": "Coming soon.",
        "group_exception_codes": ["E09"],
        "group_exception_type_ids": [9],
        "enabled": False,
        **_PLACEHOLDER_DEFAULTS,
    },
    {
        "code": "e10",
        "label": "E10 — Overloading penalty (incl. E10-A/B/C)",
        "description": "Coming soon.",
        "group_exception_codes": ["E10", "E10-A", "E10-B", "E10-C"],
        "group_exception_type_ids": [10],
        "enabled": False,
        **_PLACEHOLDER_DEFAULTS,
    },
    {
        "code": "e15",
        "label": "E15 — Exempt vs subsequent plaza",
        "description": "Coming soon.",
        "group_exception_codes": ["E15"],
        "group_exception_type_ids": [15],
        "enabled": False,
        **_PLACEHOLDER_DEFAULTS,
    },
]


def list_programs() -> list[dict]:
    """Top-level cards on the Exceptions upload page (groups expand in-page)."""
    return [
        FULL_EXEMPT_PROGRAM,
        E04_PROGRAM,
        E05_PROGRAM,
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
    return None


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
    # Website/backend/app/services → repo root
    return Path(__file__).resolve().parents[4]


def exempt_portal_root() -> Path:
    """Path to the copied Exempt Query portal."""
    return (
        _repo_root()
        / "Exeption Programs"
        / "Exemptio query E1-2-3-13-14"
    )


def e4_program_root() -> Path:
    """Path to the E4 exception program folder."""
    return _repo_root() / "Exeption Programs" / "E4"


def e5_program_root() -> Path:
    """Path to the E5 exception program folder."""
    return _repo_root() / "Exeption Programs" / "E5"


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


def load_annexure_server_defaults(pipeline_plaza_key: str) -> dict:
    """
    Default rates / approved-exemption files already on the Exempt portal server
    for this plaza key (from annexure_plaza_config.json). Upload is optional override.
    """
    key = str(pipeline_plaza_key or "").strip().upper()
    empty = {
        "pipeline_plaza_key": key,
        "rates": {"file_name": None, "exists": False},
        "approved_exemption": {
            "file_name": None,
            "exists": False,
            "uses_approved_script": False,
        },
    }
    if not key:
        return empty

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
        from annexure_plaza_config import (  # noqa: WPS433
            resolve_approved_exemption_file,
            resolve_rates_file,
            uses_approved_exemption_script,
        )
    except Exception:  # noqa: BLE001
        return empty

    rates_path = resolve_rates_file(key)
    approved_path = resolve_approved_exemption_file(key)
    return {
        "pipeline_plaza_key": key,
        "rates": {
            "file_name": rates_path.name if rates_path else None,
            "exists": bool(rates_path and rates_path.is_file()),
        },
        "approved_exemption": {
            "file_name": approved_path.name if approved_path else None,
            "exists": bool(approved_path and approved_path.is_file()),
            "uses_approved_script": bool(uses_approved_exemption_script(key)),
        },
    }
