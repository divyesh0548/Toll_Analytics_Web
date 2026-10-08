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
            "label": "Rates override (optional)",
            "required": False,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm",
        },
        {
            "key": "approved_exemption",
            "label": "Approved exemption override (optional)",
            "required": False,
            "multiple": False,
            "accept": ".xlsx,.xls,.xlsm",
        },
    ],
}

# Placeholders for other exception programs (wired later).
_PLACEHOLDER_PROGRAMS = [
    {
        "code": "e04",
        "label": "E04 — Local passes to commercial vehicles",
        "description": "Coming soon.",
        "group_exception_codes": ["E04"],
        "group_exception_type_ids": [4],
        "enabled": False,
        "input_slots": [],
    },
    {
        "code": "e05",
        "label": "E05 — Incorrect FASTag issuance",
        "description": "Coming soon.",
        "group_exception_codes": ["E05"],
        "group_exception_type_ids": [5],
        "enabled": False,
        "input_slots": [],
    },
    {
        "code": "e06",
        "label": "E06 — Discounted passes / national permit",
        "description": "Coming soon.",
        "group_exception_codes": ["E06"],
        "group_exception_type_ids": [6],
        "enabled": False,
        "input_slots": [],
    },
    {
        "code": "e07",
        "label": "E07 — Local passes at lower or zero charge",
        "description": "Coming soon.",
        "group_exception_codes": ["E07"],
        "group_exception_type_ids": [7],
        "enabled": False,
        "input_slots": [],
    },
    {
        "code": "e09",
        "label": "E09 — Unsettled transactions",
        "description": "Coming soon.",
        "group_exception_codes": ["E09"],
        "group_exception_type_ids": [9],
        "enabled": False,
        "input_slots": [],
    },
    {
        "code": "e10",
        "label": "E10 — Overloading penalty (incl. E10-A/B/C)",
        "description": "Coming soon.",
        "group_exception_codes": ["E10", "E10-A", "E10-B", "E10-C"],
        "group_exception_type_ids": [10],
        "enabled": False,
        "input_slots": [],
    },
    {
        "code": "e15",
        "label": "E15 — Exempt vs subsequent plaza",
        "description": "Coming soon.",
        "group_exception_codes": ["E15"],
        "group_exception_type_ids": [15],
        "enabled": False,
        "input_slots": [],
    },
]


def list_programs() -> list[dict]:
    return [FULL_EXEMPT_PROGRAM, *_PLACEHOLDER_PROGRAMS]


def get_program(code: str) -> dict | None:
    key = str(code or "").strip()
    for program in list_programs():
        if program["code"] == key:
            return program
    return None


def exempt_portal_root() -> Path:
    """Path to the copied Exempt Query portal."""
    # Website/backend/app/services → repo root → Exeption Programs/...
    here = Path(__file__).resolve()
    repo_root = here.parents[4]
    return (
        repo_root
        / "Exeption Programs"
        / "Exemptio query E1-2-3-13-14"
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
