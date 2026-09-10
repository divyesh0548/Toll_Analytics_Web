"""Short, plain API event logs for the terminal."""

from __future__ import annotations


def log_ok(message: str) -> None:
    print(f"OK  {message}", flush=True)


def log_fail(message: str) -> None:
    print(f"ERR {message}", flush=True)
