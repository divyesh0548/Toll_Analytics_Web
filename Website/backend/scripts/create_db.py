"""
Create the application database from .env (DB_NAME).

Does NOT create tables — use Flask-Migrate for that:
    flask --app run:app db upgrade

Usage (from Website/backend):
    python scripts/create_db.py

This script only prints SQL / connects and creates the empty database.
It will not drop an existing database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")


def connection_kwargs(*, database: str) -> dict:
    host = os.getenv("DB_HOST", "").strip()
    port = os.getenv("DB_PORT", "5432").strip()
    user = os.getenv("DB_USER", "").strip()
    password = os.getenv("DB_PASSWORD", "")
    if not all([host, port, user, database]):
        raise SystemExit(
            "Missing DB settings in .env. Need DB_HOST, DB_PORT, DB_USER, DB_NAME."
        )
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database,
        "connect_timeout": 15,
    }


def database_exists(conn, db_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        return cur.fetchone() is not None


def create_database(db_name: str) -> None:
    # Connect to the default maintenance DB to issue CREATE DATABASE.
    admin_db = os.getenv("DB_ADMIN_DB", "postgres").strip() or "postgres"
    kwargs = connection_kwargs(database=admin_db)
    conn = psycopg2.connect(**kwargs)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        if database_exists(conn, db_name):
            print(f"Database already exists: {db_name}")
            return
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
        print(f"Created database: {db_name}")
    finally:
        conn.close()


def smoke_connect(db_name: str) -> None:
    kwargs = connection_kwargs(database=db_name)
    conn = psycopg2.connect(**kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version();")
            name, version = cur.fetchone()
        print(f"Connected OK → database={name}")
        print(f"Server: {version.split(',')[0]}")
    finally:
        conn.close()


def main() -> None:
    db_name = os.getenv("DB_NAME", "").strip()
    if not db_name:
        raise SystemExit("DB_NAME is empty in .env (e.g. DB_NAME=toll_analytics).")

    print(f"Target DB_NAME={db_name}")
    print(f"Host={os.getenv('DB_HOST')} Port={os.getenv('DB_PORT')} User={os.getenv('DB_USER')}")
    create_database(db_name)
    smoke_connect(db_name)
    print()
    print("Next (tables via migrations):")
    print("  flask --app run:app db migrate -m \"create users table\"")
    print("  flask --app run:app db upgrade")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
