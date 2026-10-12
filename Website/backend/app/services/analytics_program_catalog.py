"""Catalog of analytics ETL programs (separate from exception uploads)."""

from __future__ import annotations

ANALYTICS_VRN_ETC_PROGRAM = {
    "code": "analytics_vrn_etc",
    "label": "VRN + ETC analytics load",
    "description": (
        "Upload VRN and/or ETC workbooks (at least one slot required). "
        "VRN loads hourly mop/class/lane/gap insights; ETC loads "
        "revenue_distribution_per_class. Existing day/hour rows update only "
        "when the new metric is greater. S3 inputs are deleted only after a "
        "successful run; failed jobs keep files so you can fix and retry."
    ),
    "group_exception_codes": [],
    "group_exception_type_ids": [],
    "enabled": True,
    "requires_pipeline_plaza_key": False,
    "uses_entity_map": False,
    "updates_metrics": False,
    "is_analytics": True,
    # Start is allowed when any of these slots has files (neither is mandatory alone).
    "require_any_slots": ["vrn", "etc"],
    "input_slots": [
        {
            "key": "vrn",
            "label": "VRN files",
            "required": False,
            "multiple": True,
            "accept": ".xlsx,.xls,.xlsm,.csv",
        },
        {
            "key": "etc",
            "label": "ETC files",
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


def plaza_db_update_root():
    from app.services.repo_paths import plaza_db_update_root as resolve_plaza_root

    return resolve_plaza_root()
