"""Plaza calendar event CRUD and file upload parsing."""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

import pandas as pd
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.calendar_event import (
    EVENT_SOURCES,
    EVENT_TYPES,
    PlazaCalendarEvent,
)

_START_ALIASES = {"start_date", "date", "start"}
_END_ALIASES = {"end_date", "end"}
_LABEL_ALIASES = {"label", "name", "event"}
_TYPE_ALIASES = {"event_type", "type"}

_TYPE_ALIASES_MAP = {
    "national_holiday": "national_holiday",
    "national": "national_holiday",
    "national holiday": "national_holiday",
    "regional_holiday": "regional_holiday",
    "regional": "regional_holiday",
    "regional holiday": "regional_holiday",
    "bank_holiday": "bank_holiday",
    "bank": "bank_holiday",
    "bank holiday": "bank_holiday",
    "govt_holiday": "govt_holiday",
    "govt": "govt_holiday",
    "govt holiday": "govt_holiday",
    "government": "govt_holiday",
    "government holiday": "govt_holiday",
    "election_day": "election_day",
    "election": "election_day",
    "election day": "election_day",
    "mela_window": "mela_window",
    "mela": "mela_window",
    "mela window": "mela_window",
}


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    # Excel serial numbers sometimes arrive as floats
    try:
        as_float = float(text)
        if as_float > 20000:
            return pd.to_datetime(as_float, unit="D", origin="1899-12-30").date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        parsed = pd.to_datetime(text, dayfirst=False, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"Invalid date: {value}") from None
        return parsed.date()


def _normalize_event_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = " ".join(text.split())
    mapped = _TYPE_ALIASES_MAP.get(text) or _TYPE_ALIASES_MAP.get(text.replace(" ", "_"))
    if not mapped:
        raise ValueError(
            f"Invalid event_type '{value}'. Expected one of: {', '.join(EVENT_TYPES)}"
        )
    return mapped


def _normalize_source(value: Any, *, default: str = "manual") -> str:
    text = str(value or default).strip().lower()
    if text not in EVENT_SOURCES:
        raise ValueError(f"Invalid source '{value}'. Expected one of: {', '.join(EVENT_SOURCES)}")
    return text


def _resolve_columns(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for col in columns:
        key = str(col).strip().lower()
        if key in _START_ALIASES and "start_date" not in mapping:
            mapping["start_date"] = col
        elif key in _END_ALIASES and "end_date" not in mapping:
            mapping["end_date"] = col
        elif key in _LABEL_ALIASES and "label" not in mapping:
            mapping["label"] = col
        elif key in _TYPE_ALIASES and "event_type" not in mapping:
            mapping["event_type"] = col
    missing = [name for name in ("start_date", "label", "event_type") if name not in mapping]
    if missing:
        raise ValueError(
            "Upload is missing required columns: "
            + ", ".join(missing)
            + ". Accepted headers: start_date|date|start, end_date|end, "
            "label|name|event, event_type|type"
        )
    return mapping


def validate_event_fields(
    *,
    label: Any,
    event_type: Any,
    start_date: Any,
    end_date: Any = None,
    source: Any = "manual",
) -> dict:
    label_text = str(label or "").strip()
    if not label_text:
        raise ValueError("label is required")
    if len(label_text) > 255:
        raise ValueError("label must be at most 255 characters")

    start = _parse_date(start_date)
    if start is None:
        raise ValueError("start_date is required")
    end = _parse_date(end_date) if end_date not in (None, "") else start
    if end is None:
        end = start
    if end < start:
        raise ValueError("end_date must be on or after start_date")

    return {
        "label": label_text,
        "event_type": _normalize_event_type(event_type),
        "start_date": start,
        "end_date": end,
        "source": _normalize_source(source),
    }


def list_events(
    plaza_identifier: str,
    *,
    start: date | None = None,
    end: date | None = None,
    event_types: list[str] | None = None,
) -> list[PlazaCalendarEvent]:
    query = PlazaCalendarEvent.query.filter_by(plaza_identifier=plaza_identifier)
    if start is not None:
        query = query.filter(PlazaCalendarEvent.end_date >= start)
    if end is not None:
        query = query.filter(PlazaCalendarEvent.start_date <= end)
    if event_types:
        normalized = [_normalize_event_type(t) for t in event_types if str(t).strip()]
        if normalized:
            query = query.filter(PlazaCalendarEvent.event_type.in_(normalized))
    return query.order_by(
        PlazaCalendarEvent.start_date.asc(),
        PlazaCalendarEvent.label.asc(),
        PlazaCalendarEvent.id.asc(),
    ).all()


def create_event(plaza_identifier: str, data: dict) -> PlazaCalendarEvent:
    fields = validate_event_fields(
        label=data.get("label"),
        event_type=data.get("event_type"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        source=data.get("source") or "manual",
    )
    event = PlazaCalendarEvent(plaza_identifier=plaza_identifier, **fields)
    db.session.add(event)
    db.session.commit()
    return event


def update_event(event: PlazaCalendarEvent, data: dict) -> PlazaCalendarEvent:
    fields = validate_event_fields(
        label=data.get("label", event.label),
        event_type=data.get("event_type", event.event_type),
        start_date=data.get("start_date", event.start_date),
        end_date=data.get("end_date", event.end_date),
        source=data.get("source", event.source),
    )
    event.label = fields["label"]
    event.event_type = fields["event_type"]
    event.start_date = fields["start_date"]
    event.end_date = fields["end_date"]
    if "source" in data:
        event.source = fields["source"]
    db.session.commit()
    return event


def delete_event(event: PlazaCalendarEvent) -> None:
    db.session.delete(event)
    db.session.commit()


def parse_upload(file_storage: FileStorage) -> tuple[list[dict], list[dict]]:
    """Parse xlsx/csv upload into validated rows and per-row errors."""
    if file_storage is None or not file_storage.filename:
        raise ValueError("file is required")

    filename = file_storage.filename.lower()
    raw = file_storage.read()
    if not raw:
        raise ValueError("uploaded file is empty")

    buffer = io.BytesIO(raw)
    if filename.endswith(".csv"):
        df = pd.read_csv(buffer)
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        df = pd.read_excel(buffer)
    else:
        raise ValueError("Unsupported file type. Upload a .xlsx or .csv file")

    if df.empty:
        raise ValueError("uploaded file has no data rows")

    columns = [str(c) for c in df.columns]
    colmap = _resolve_columns(columns)

    rows: list[dict] = []
    errors: list[dict] = []
    for idx, series in df.iterrows():
        row_number = int(idx) + 2  # header is row 1
        try:
            start_raw = series.get(colmap["start_date"])
            end_raw = series.get(colmap["end_date"]) if "end_date" in colmap else None
            label_raw = series.get(colmap["label"])
            type_raw = series.get(colmap["event_type"])
            # Skip fully blank rows
            if (
                (pd.isna(start_raw) if not isinstance(start_raw, str) else not start_raw.strip())
                and (pd.isna(label_raw) if not isinstance(label_raw, str) else not label_raw.strip())
                and (pd.isna(type_raw) if not isinstance(type_raw, str) else not type_raw.strip())
            ):
                continue
            fields = validate_event_fields(
                label=label_raw,
                event_type=type_raw,
                start_date=start_raw,
                end_date=end_raw,
                source="upload",
            )
            rows.append(fields)
        except ValueError as exc:
            errors.append({"row": row_number, "error": str(exc)})
    return rows, errors


def bulk_upsert_from_upload(
    plaza_identifier: str,
    rows: list[dict],
) -> dict:
    """Insert rows; skip exact duplicates on plaza+dates+type+label."""
    created = 0
    skipped = 0
    for fields in rows:
        exists = (
            PlazaCalendarEvent.query.filter_by(
                plaza_identifier=plaza_identifier,
                start_date=fields["start_date"],
                end_date=fields["end_date"],
                event_type=fields["event_type"],
                label=fields["label"],
            )
            .limit(1)
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.session.add(
            PlazaCalendarEvent(
                plaza_identifier=plaza_identifier,
                label=fields["label"],
                event_type=fields["event_type"],
                start_date=fields["start_date"],
                end_date=fields["end_date"],
                source="upload",
            )
        )
        created += 1
    db.session.commit()
    return {"created": created, "skipped": skipped}
