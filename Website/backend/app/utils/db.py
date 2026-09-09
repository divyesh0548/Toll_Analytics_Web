"""Shared DB connection helpers for Flask app and analytics queries."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")


def get_db_connection_kwargs(database: str | None = None) -> dict:
    """psycopg2 kwargs from Website/backend/.env."""
    host = os.getenv("DB_HOST", "").strip()
    port = os.getenv("DB_PORT", "5432").strip()
    user = os.getenv("DB_USER", "").strip()
    password = os.getenv("DB_PASSWORD", "")
    db_name = (database or os.getenv("DB_NAME", "")).strip()

    missing = [
        name
        for name, value in (
            ("DB_HOST", host),
            ("DB_PORT", port),
            ("DB_USER", user),
            ("DB_NAME", db_name),
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
        "database": db_name,
    }


def sqlalchemy_database_uri(database: str | None = None) -> str:
    kwargs = get_db_connection_kwargs(database=database)
    return (
        f"postgresql+psycopg2://{kwargs['user']}:{kwargs['password']}"
        f"@{kwargs['host']}:{kwargs['port']}/{kwargs['database']}"
    )
