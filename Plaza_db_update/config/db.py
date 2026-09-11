"""Analytics DB connection and schema helpers for Plaza_db_update."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg2 import sql

from config.excel_config import LANE_COLUMNS, LANE_LT2_COLUMNS

PLAZA_UPDATE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PLAZA_UPDATE_DIR.parent
WEBSITE_BACKEND = PROJECT_ROOT / "Website" / "backend"


def load_env_file() -> None:
    for path in (
        PLAZA_UPDATE_DIR / ".env",
        PROJECT_ROOT / ".env",
        WEBSITE_BACKEND / ".env",
    ):
        if path.is_file():
            load_dotenv(path, override=False)


def get_analytics_db_connection_kwargs() -> dict:
    load_env_file()
    host = os.getenv("DB_HOST", "").strip()
    port = os.getenv("DB_PORT", "5432").strip()
    user = os.getenv("DB_USER", "").strip()
    password = os.getenv("DB_PASSWORD", "")
    database = (
        os.getenv("NHIT_DB", "").strip()
        or os.getenv("ANALYTICS_DB_NAME", "").strip()
        or os.getenv("DB_NAME", "").strip()
    )
    missing = [
        name
        for name, value in (
            ("DB_HOST", host),
            ("DB_PORT", port),
            ("DB_USER", user),
            ("NHIT_DB / ANALYTICS_DB_NAME / DB_NAME", database),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required .env keys: {', '.join(missing)}")
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database,
    }


def fetch_existing_columns(conn, table_name: str) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        return {row[0] for row in cursor.fetchall()}


def _create_table(conn, table_name: str, column_defs: list[str]) -> None:
    create_sql = sql.SQL("CREATE TABLE IF NOT EXISTS {table} ({columns});").format(
        table=sql.Identifier(table_name),
        columns=sql.SQL(", ").join(sql.SQL(part) for part in column_defs),
    )
    with conn.cursor() as cursor:
        cursor.execute(create_sql)
        cursor.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {index_name} ON {table} (plaza_identifier)"
            ).format(
                index_name=sql.Identifier(f"ix_{table_name}_plaza_identifier"),
                table=sql.Identifier(table_name),
            )
        )
    conn.commit()
    print(f"Ensured table '{table_name}'.")


def ensure_mop_distribution_per_class_table(conn, table_name: str) -> None:
    if fetch_existing_columns(conn, table_name):
        print(f"Table '{table_name}' already exists.")
        return
    _create_table(
        conn,
        table_name,
        [
            "id BIGSERIAL PRIMARY KEY",
            "plaza_identifier TEXT NOT NULL",
            "plaza_name TEXT NOT NULL",
            "date DATE NOT NULL",
            "hour TEXT NOT NULL",
            "vehicle_class TEXT NOT NULL",
            "mop TEXT NOT NULL",
            "txn_count INTEGER NOT NULL DEFAULT 0",
            "UNIQUE (plaza_identifier, date, hour, vehicle_class, mop)",
        ],
    )


def ensure_class_distribution_per_lane_table(conn, table_name: str) -> None:
    if fetch_existing_columns(conn, table_name):
        print(f"Table '{table_name}' already exists.")
        return
    _create_table(
        conn,
        table_name,
        [
            "id BIGSERIAL PRIMARY KEY",
            "plaza_identifier TEXT NOT NULL",
            "plaza_name TEXT NOT NULL",
            "date DATE NOT NULL",
            "hour TEXT NOT NULL",
            "lane TEXT NOT NULL",
            "vehicle_class TEXT NOT NULL",
            "txn_count INTEGER NOT NULL DEFAULT 0",
            "UNIQUE (plaza_identifier, date, hour, lane, vehicle_class)",
        ],
    )


def ensure_mop_distribution_per_lane_table(conn, table_name: str) -> None:
    if fetch_existing_columns(conn, table_name):
        print(f"Table '{table_name}' already exists.")
        return
    _create_table(
        conn,
        table_name,
        [
            "id BIGSERIAL PRIMARY KEY",
            "plaza_identifier TEXT NOT NULL",
            "plaza_name TEXT NOT NULL",
            "date DATE NOT NULL",
            "hour TEXT NOT NULL",
            "lane TEXT NOT NULL",
            "mop TEXT NOT NULL",
            "txn_count INTEGER NOT NULL DEFAULT 0",
            "UNIQUE (plaza_identifier, date, hour, lane, mop)",
        ],
    )


def ensure_gap_distribution_per_lane_table(conn, table_name: str) -> None:
    existing = fetch_existing_columns(conn, table_name)
    if existing:
        print(f"Table '{table_name}' already exists.")
        return

    column_defs = [
        "id BIGSERIAL PRIMARY KEY",
        "plaza_identifier TEXT NOT NULL",
        "plaza_name TEXT NOT NULL",
        "date DATE NOT NULL",
        "hour TEXT NOT NULL",
    ]
    for column_name in LANE_COLUMNS.values():
        column_defs.append(f"{column_name} DOUBLE PRECISION")
    for column_name in LANE_LT2_COLUMNS.values():
        column_defs.append(f"{column_name} INTEGER NOT NULL DEFAULT 0")
    column_defs.append("UNIQUE (plaza_identifier, date, hour)")
    _create_table(conn, table_name, column_defs)


def ensure_all_analytics_tables(conn) -> None:
    from config.settings import (
        CLASS_DISTRIBUTION_PER_LANE_TABLE,
        GAP_DISTRIBUTION_PER_LANE_TABLE,
        MOP_DISTRIBUTION_PER_CLASS_TABLE,
        MOP_DISTRIBUTION_PER_LANE_TABLE,
    )

    ensure_mop_distribution_per_class_table(conn, MOP_DISTRIBUTION_PER_CLASS_TABLE)
    ensure_class_distribution_per_lane_table(conn, CLASS_DISTRIBUTION_PER_LANE_TABLE)
    ensure_mop_distribution_per_lane_table(conn, MOP_DISTRIBUTION_PER_LANE_TABLE)
    ensure_gap_distribution_per_lane_table(conn, GAP_DISTRIBUTION_PER_LANE_TABLE)
