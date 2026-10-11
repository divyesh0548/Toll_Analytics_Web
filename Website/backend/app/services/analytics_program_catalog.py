"""Catalog of analytics ETL programs (separate from exception uploads)."""

from __future__ import annotations

from pathlib import Path

ANALYTICS_VRN_ETC_PROGRAM = {
    "code": "analytics_vrn_etc",
    "label": "VRN + ETC analytics load",
    "description": (
        "Upload VRN (and optional ETC) workbooks. Loads hourly mop/class/lane/gap "
        "insights from VRN and revenue_distribution_per_class from ETC. "
        "Existing day/hour rows update only when the new metric is greater. "
        "S3 inputs are deleted only after a successful run; failed jobs keep "
        "files so you can fix and retry."
    ),
    "group_exception_codes": [],
    "group_exception_type_ids": [],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": False,
    "updates_metrics": False,
    "is_analytics": True,
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
            "label": "ETC files (optional)",
            "required": False,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
    ],
}


def list_analytics_programs() -> list[dict]:
    return [ANALYTICS_VRN_ETC_PROGRAM]


def get_analytics_program(code: str) -> dict | None:
    key = str(code or "").strip()
    for program in list_analytics_programs():
        if program["code"] == key:
            return program
    return None


def is_analytics_program_code(code: str) -> bool:
    return get_analytics_program(code) is not None


def plaza_db_update_root() -> Path:
    # Website/backend/app/services → repo root → Plaza_db_update
    return Path(__file__).resolve().parents[4] / "Plaza_db_update"
