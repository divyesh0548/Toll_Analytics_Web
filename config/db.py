"""Analytics database connection and schema management."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from psycopg2 import sql

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from db_config import get_db_connection_kwargs, load_env_file


def get_analytics_db_connection_kwargs() -> dict:
    """PostgreSQL connection for analytics — uses NHIT_DB from .env."""
    load_env_file()
    kwargs = get_db_connection_kwargs()
    nhit_db = os.environ.get("NHIT_DB", "").strip()
    if not nhit_db:
        raise RuntimeError("Missing NHIT_DB in project-root .env (e.g. NHIT_DB=nhit).")
    kwargs["database"] = nhit_db
    return kwargs


def get_analytics_table_name() -> str:
    load_env_file()
    table_name = os.environ.get("Analytical_DB_Table", "").strip()
    if not table_name:
        raise RuntimeError(
            "Missing Analytical_DB_Table in project-root .env "
            "(e.g. Analytical_DB_Table=nhit_analytics)."
        )
    return table_name


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


def ensure_analytics_table(conn, table_name: str, count_columns: list[str]) -> None:
    """
    Create the analytics table if missing, then add any metric columns
    that are defined in module1 but not yet present in the database.
    """
    existing = fetch_existing_columns(conn, table_name)

    if not existing:
        column_defs = [
            "id BIGSERIAL PRIMARY KEY",
            "plaza_name TEXT NOT NULL",
            "hour TEXT NOT NULL",
            "date DATE NOT NULL",
        ]
        column_defs.extend(
            f"{column_name} INTEGER NOT NULL DEFAULT 0" for column_name in count_columns
        )
        column_defs.append("UNIQUE (plaza_name, date, hour)")

        create_sql = sql.SQL(
            "CREATE TABLE IF NOT EXISTS {table} ({columns});"
        ).format(
            table=sql.Identifier(table_name),
            columns=sql.SQL(", ").join(sql.SQL(part) for part in column_defs),
        )
        with conn.cursor() as cursor:
            cursor.execute(create_sql)
        conn.commit()
        print(f"Created table '{table_name}' with {len(count_columns)} metric column(s).")
        return

    added: list[str] = []
    with conn.cursor() as cursor:
        for column_name in count_columns:
            if column_name in existing:
                continue
            alter_sql = sql.SQL(
                "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                "INTEGER NOT NULL DEFAULT 0"
            ).format(
                table=sql.Identifier(table_name),
                column=sql.Identifier(column_name),
            )
            cursor.execute(alter_sql)
            added.append(column_name)

    if added:
        conn.commit()
        print(f"Added {len(added)} column(s) to '{table_name}': {', '.join(added)}")
    else:
        print(f"All {len(count_columns)} metric columns already exist in '{table_name}'.")


def ensure_gap_distribution_table(
    conn,
    table_name: str,
    avg_lane_columns: list[str],
    lt2_lane_columns: list[str],
) -> None:
    """
    Create the gap-per-lane hourly table if missing.
    Grain: (plaza_name, date, hour) with:
      - l01…l12 = avg gap seconds
      - l01_lt2_count…l12_lt2_count = gaps < 2s per lane
    """
    existing = fetch_existing_columns(conn, table_name)

    if not existing:
        column_defs = [
            "id BIGSERIAL PRIMARY KEY",
            "plaza_name TEXT NOT NULL",
            "date DATE NOT NULL",
            "hour TEXT NOT NULL",
        ]
        for column_name in avg_lane_columns:
            column_defs.append(f"{column_name} DOUBLE PRECISION")
        for column_name in lt2_lane_columns:
            column_defs.append(f"{column_name} INTEGER NOT NULL DEFAULT 0")
        column_defs.append("UNIQUE (plaza_name, date, hour)")

        create_sql = sql.SQL(
            "CREATE TABLE IF NOT EXISTS {table} ({columns});"
        ).format(
            table=sql.Identifier(table_name),
            columns=sql.SQL(", ").join(sql.SQL(part) for part in column_defs),
        )
        with conn.cursor() as cursor:
            cursor.execute(create_sql)
        conn.commit()
        print(
            f"Created table '{table_name}' with {len(avg_lane_columns)} avg-lane "
            f"and {len(lt2_lane_columns)} lt2-lane column(s)."
        )
        return

    added: list[str] = []
    with conn.cursor() as cursor:
        for column_name in avg_lane_columns:
            if column_name in existing:
                continue
            alter_sql = sql.SQL(
                "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} DOUBLE PRECISION"
            ).format(
                table=sql.Identifier(table_name),
                column=sql.Identifier(column_name),
            )
            cursor.execute(alter_sql)
            added.append(column_name)

        for column_name in lt2_lane_columns:
            if column_name in existing:
                continue
            alter_sql = sql.SQL(
                "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                "INTEGER NOT NULL DEFAULT 0"
            ).format(
                table=sql.Identifier(table_name),
                column=sql.Identifier(column_name),
            )
            cursor.execute(alter_sql)
            added.append(column_name)

    if added:
        conn.commit()
        print(f"Added {len(added)} column(s) to '{table_name}': {', '.join(added)}")
    else:
        print(f"Gap distribution table '{table_name}' already exists.")


def ensure_exempt_distribution_table(conn, table_name: str, lane_columns: list[str]) -> None:
    """
    Create the exempt-per-lane hourly table if missing.
    Grain: (plaza_name, date, hour) with wide lane columns (l01…l12).
    """
    existing = fetch_existing_columns(conn, table_name)

    if not existing:
        column_defs = [
            "id BIGSERIAL PRIMARY KEY",
            "plaza_name TEXT NOT NULL",
            "date DATE NOT NULL",
            "hour TEXT NOT NULL",
        ]
        column_defs.extend(
            f"{column_name} INTEGER NOT NULL DEFAULT 0" for column_name in lane_columns
        )
        column_defs.append("UNIQUE (plaza_name, date, hour)")

        create_sql = sql.SQL(
            "CREATE TABLE IF NOT EXISTS {table} ({columns});"
        ).format(
            table=sql.Identifier(table_name),
            columns=sql.SQL(", ").join(sql.SQL(part) for part in column_defs),
        )
        with conn.cursor() as cursor:
            cursor.execute(create_sql)
        conn.commit()
        print(f"Created table '{table_name}' with {len(lane_columns)} lane column(s).")
        return

    added: list[str] = []
    with conn.cursor() as cursor:
        for column_name in lane_columns:
            if column_name in existing:
                continue
            alter_sql = sql.SQL(
                "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                "INTEGER NOT NULL DEFAULT 0"
            ).format(
                table=sql.Identifier(table_name),
                column=sql.Identifier(column_name),
            )
            cursor.execute(alter_sql)
            added.append(column_name)

    if added:
        conn.commit()
        print(f"Added {len(added)} column(s) to '{table_name}': {', '.join(added)}")
    else:
        print(f"Exempt distribution table '{table_name}' already exists.")