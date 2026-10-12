"""Shared monthly input slots and which exception programs they unlock.

Batch UI uploads these slots once; checkboxes enable only when required slots
are present for that plaza + year + month.
"""

from __future__ import annotations

# Slots shown on the Monthly Exceptions page (upload once per plaza/month).
MONTHLY_INPUT_SLOTS: list[dict] = [
    {
        "key": "vrn",
        "label": "VRN files",
        "description": "Plaza VRN transaction files for the month.",
        "required_hint": "Full Exempt, E06, E10",
        "multiple": True,
        "accept": ".xlsx,.xls,.xlsm,.csv",
        "user_upload": True,
    },
    {
        "key": "etc",
        "label": "ETC / Lifecycle files",
        "description": "ETC or lifecycle extracts (same files often work for E05 lifecycle).",
        "required_hint": "Full Exempt, E05, E06, E09, E10",
        "multiple": True,
        "accept": ".xlsx,.xls,.xlsm,.csv",
        "user_upload": True,
    },
    {
        "key": "pass",
        "label": "Pass reports",
        "description": "Local / commercial pass issuance reports.",
        "required_hint": "Full Exempt, E04, E07",
        "multiple": True,
        "accept": ".xlsx,.xls,.xlsm,.csv",
        "user_upload": True,
    },
    {
        "key": "concessionaire",
        "label": "Concessionaire file(s)",
        "description": "Required for Full Exempt pipeline.",
        "required_hint": "Full Exempt",
        "multiple": True,
        "accept": ".xlsx,.xls,.xlsm,.csv",
        "user_upload": True,
    },
    {
        "key": "scraped",
        "label": "Scraped vehicle / permit files (optional)",
        "description": (
            "IHMCL scrape for E05 and/or national-permit files for E06. "
            "Optional — without scrape E05 stays disabled; E06 can still run "
            "and live-scrape if Selenium is configured."
        ),
        "required_hint": "Enables E05; optional for E06",
        "multiple": True,
        "accept": ".xlsx,.xls,.xlsm,.csv",
        "user_upload": True,
    },
    {
        "key": "to_plaza_vrn",
        "label": "To-plaza VRN (subsequent plaza)",
        "description": (
            "VRN of the subsequent plaza for E15. Separate from this plaza's VRN."
        ),
        "required_hint": "E15",
        "multiple": True,
        "accept": ".xlsx,.xls,.xlsm,.csv",
        "user_upload": True,
    },
    {
        "key": "full_exempt_final",
        "label": "Full Exempt final workbook",
        "description": (
            "Produced by Full Exempt for this plaza+month "
            "(e.g. *_final.xlsx). Auto-fed into E15 as From-plaza exempt."
        ),
        "required_hint": "Produced by Full Exempt → required by E15",
        "multiple": False,
        "accept": ".xlsx,.xls,.xlsm",
        "user_upload": False,  # system-produced; not a primary upload slot
    },
]

# program_code → required monthly slots + mapping into exception_job file slots.
# optional_slots: present → better UX / skip scrape; not required to enable checkbox
#   except where noted in enable_requires_optional.
PIPELINE_PROGRAMS: list[dict] = [
    {
        "code": "full_exempt_e1_e2_e3_e13_e14",
        "label": "Exempt Query — Full Pipeline",
        "sort_order": 10,
        "requires_pipeline_plaza_key": True,
        "required_slots": ["vrn", "etc", "pass", "concessionaire"],
        "optional_slots": [],
        "slot_map": {
            "vrn": "vrn",
            "etc": "lc_etc",
            "pass": "pass",
            "concessionaire": "concessionaire",
        },
        "produces_slots": ["full_exempt_final"],
    },
    {
        "code": "e04",
        "label": "E04 — Local passes to commercial vehicles",
        "sort_order": 20,
        "requires_pipeline_plaza_key": False,
        "required_slots": ["pass"],
        "optional_slots": [],
        "slot_map": {"pass": "pass"},
        "produces_slots": [],
    },
    {
        "code": "e07",
        "label": "E07 — Local passes at lower or zero charge",
        "sort_order": 30,
        "requires_pipeline_plaza_key": False,
        "required_slots": ["pass"],
        "optional_slots": [],
        "slot_map": {"pass": "pass"},
        "produces_slots": [],
    },
    {
        "code": "e09",
        "label": "E09 — Unsettled transactions",
        "sort_order": 40,
        "requires_pipeline_plaza_key": False,
        "required_slots": ["etc"],
        "optional_slots": [],
        "slot_map": {"etc": "etc"},
        "produces_slots": [],
    },
    {
        "code": "e06",
        "label": "E06 — Discounted passes / national permit",
        "sort_order": 50,
        "requires_pipeline_plaza_key": False,
        "required_slots": ["etc", "vrn"],
        "optional_slots": ["scraped"],
        "slot_map": {
            "etc": "etc",
            "vrn": "vrn",
            "scraped": "permit",
        },
        "produces_slots": [],
    },
    {
        "code": "e05",
        "label": "E05 — Incorrect FASTag issuance",
        "sort_order": 60,
        "requires_pipeline_plaza_key": False,
        # Scraped is required to enable E05 in the batch UI (no live scrape).
        "required_slots": ["etc", "scraped"],
        "optional_slots": [],
        "slot_map": {
            "etc": "lifecycle",
            "scraped": "ihmcl",
        },
        "produces_slots": [],
    },
    {
        "code": "e10",
        "label": "E10 — Overloading (E10-A/B/C)",
        "sort_order": 70,
        "requires_pipeline_plaza_key": False,
        "required_slots": ["vrn", "etc"],
        "optional_slots": [],
        "slot_map": {"vrn": "vrn", "etc": "etc"},
        "produces_slots": [],
    },
    {
        "code": "e15",
        "label": "E15 — Exempt vs subsequent plaza",
        "sort_order": 80,
        "requires_pipeline_plaza_key": False,
        # full_exempt_final auto-fed from same plaza+month after Full Exempt.
        "required_slots": ["full_exempt_final", "to_plaza_vrn"],
        "optional_slots": [],
        "slot_map": {
            "full_exempt_final": "from_plaza",
            "to_plaza_vrn": "vrn",
        },
        "produces_slots": [],
    },
]

PIPELINE_METRICS_TABLE = "pipeline_audit_exception_metrics"
PIPELINE_OUTPUT_FILES_TABLE = "pipeline_audit_exception_output_files"


def list_monthly_input_slots(*, include_system: bool = False) -> list[dict]:
    if include_system:
        return list(MONTHLY_INPUT_SLOTS)
    return [s for s in MONTHLY_INPUT_SLOTS if s.get("user_upload")]


def list_pipeline_programs() -> list[dict]:
    return sorted(PIPELINE_PROGRAMS, key=lambda p: int(p.get("sort_order") or 0))


def get_pipeline_program(code: str) -> dict | None:
    key = str(code or "").strip()
    for program in PIPELINE_PROGRAMS:
        if program["code"] == key:
            return program
    return None


def program_enabled_for_slots(program: dict, present_slots: set[str]) -> bool:
    required = set(program.get("required_slots") or [])
    return required.issubset(present_slots)


def evaluate_program_availability(present_slots: set[str]) -> list[dict]:
    """Return programs with enabled flag + missing required slots."""
    out: list[dict] = []
    for program in list_pipeline_programs():
        required = list(program.get("required_slots") or [])
        missing = [s for s in required if s not in present_slots]
        out.append(
            {
                "code": program["code"],
                "label": program["label"],
                "sort_order": program.get("sort_order"),
                "requires_pipeline_plaza_key": bool(
                    program.get("requires_pipeline_plaza_key")
                ),
                "required_slots": required,
                "optional_slots": list(program.get("optional_slots") or []),
                "missing_slots": missing,
                "enabled": len(missing) == 0,
                "produces_slots": list(program.get("produces_slots") or []),
            }
        )
    return out
