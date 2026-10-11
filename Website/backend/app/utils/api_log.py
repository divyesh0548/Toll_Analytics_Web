"""Short, plain API event logs for the terminal."""

from __future__ import annotations

from datetime import datetime


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_ok(message: str) -> None:
    print(f"{_ts()}  OK  {message}", flush=True)


def log_fail(message: str) -> None:
    print(f"{_ts()}  ERR {message}", flush=True)


def log_api(method: str, path: str, status: int) -> None:
    print(f"{_ts()}  API {method} {path} → {status}", flush=True)
