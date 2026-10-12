"""Resolve repo / program roots for local runs and Docker.

Prefer env (set in Website/backend/.env or Compose):

  TOLL_REPO_ROOT=/app

Default: parents of this file → Toll Analytics Dashboard repo root
(Website/backend/app/services → … → repo).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def repo_root() -> Path:
    override = os.environ.get("TOLL_REPO_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # …/Website/backend/app/services/repo_paths.py → repo root
    return Path(__file__).resolve().parents[4]


def exception_programs_root() -> Path:
    override = os.environ.get("EXCEPTION_PROGRAMS_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / "Exeption Programs"


def plaza_db_update_root() -> Path:
    override = os.environ.get("PLAZA_DB_UPDATE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / "Plaza_db_update"


def backend_root() -> Path:
    """Website/backend (where .env lives)."""
    override = os.environ.get("WEBSITE_BACKEND_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def backend_env_path() -> Path:
    return backend_root() / ".env"
