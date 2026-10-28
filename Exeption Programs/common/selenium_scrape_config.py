"""
Shared Selenium / web-scrape settings for E5, E6, and future scrapers.

Source of truth: Website/backend/.env (also injected by Docker Compose).

Common keys (all scrape programs):
  SCRAPE_ENABLED          — 1 = use Chrome; 0 = off / legacy path
  SCRAPE_USE_GRID         — 1 = Selenium Grid; 0 = local Chrome in this process
  SCRAPE_GRID_URL         — Grid hub URL (when USE_GRID=1)
  SCRAPE_MAX_NODES        — Chrome node containers to auto-start (when auto-manage)
  SCRAPE_MAX_CONCURRENCY  — browser sessions on each node
                            total scrape sessions = nodes × concurrency
  SCRAPE_MAX_SESSIONS     — legacy alias for CONCURRENCY (also fills NODES if unset)
  SCRAPE_AUTO_MANAGE_NODES— 1 = spawn chrome nodes against existing hub; 0 = use
                            already-registered nodes only
  SCRAPE_HEADLESS         — headless Chrome

Older names (EXCEPTION_USE_SELENIUM, SELENIUM_*, E5_/E6_USE_SELENIUM_GRID)
still work as fallbacks if SCRAPE_* is unset.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

COMMON_DIR = Path(__file__).resolve().parent
REPO_ROOT = COMMON_DIR.parent.parent
WEBSITE_BACKEND_ENV = REPO_ROOT / "Website" / "backend" / ".env"

_DEFAULTS: dict[str, Any] = {
    "use_selenium": True,
    "use_grid": False,
    "selenium_remote_url": "http://localhost:4444/wd/hub",
    "max_nodes": 3,
    "max_concurrency": 3,
    "headless": True,
    "auto_manage_nodes": False,
    "selenium_network": "selenium-grid",
    "selenium_hub_container": "selenium-hub",
    "selenium_node_image": "selenium/node-chrome:latest",
    "mobile_number": "9999999999",
    "plaza_name": "Phulwaria Toll Plaza",
}

_env_loaded = False


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _first_set(*names: str) -> str | None:
    for name in names:
        if name in os.environ and str(os.environ.get(name, "")).strip() != "":
            return name
    return None


def ensure_website_env_loaded(*, override: bool = False) -> Path | None:
    """
    Load Website/backend/.env when present on disk.
    Docker Compose already injects the same file into the process; load is a no-op
    when the file is absent inside the image.
    """
    global _env_loaded
    if _env_loaded and not override:
        return WEBSITE_BACKEND_ENV if WEBSITE_BACKEND_ENV.is_file() else None
    if WEBSITE_BACKEND_ENV.is_file():
        load_dotenv(WEBSITE_BACKEND_ENV, override=override)
        _env_loaded = True
        return WEBSITE_BACKEND_ENV
    _env_loaded = True
    return None


def load_selenium_scrape_config(
    program_defaults: dict | None = None,
    *,
    program: str | None = None,
) -> dict[str, Any]:
    """
    Merge optional program JSON scrape defaults with Website/backend/.env.

    Returns a dict suitable for E5/E6 scrape helpers:
      use_selenium, use_grid, selenium_remote_url, max_nodes, max_concurrency,
      headless, auto_manage_nodes, selenium_network, selenium_hub_container,
      selenium_node_image, mobile_number, plaza_name
    """
    ensure_website_env_loaded(override=False)

    cfg: dict[str, Any] = dict(_DEFAULTS)
    if program_defaults:
        for key, value in program_defaults.items():
            if value is None:
                continue
            if key in cfg or key in {
                "selenium_remote_url",
                "max_nodes",
                "max_concurrency",
                "headless",
                "auto_manage_nodes",
                "mobile_number",
                "plaza_name",
            }:
                cfg[key] = value

    # Enable Chrome scrape
    enabled_key = _first_set("SCRAPE_ENABLED", "EXCEPTION_USE_SELENIUM", "IHMCL_USE_SELENIUM")
    if enabled_key:
        cfg["use_selenium"] = _env_flag(enabled_key, cfg["use_selenium"])

    # Grid vs local Chrome (common key only — no per-program overrides in .env)
    grid_key = _first_set("SCRAPE_USE_GRID", "SELENIUM_USE_GRID", "E6_USE_SELENIUM_GRID", "E5_USE_SELENIUM_GRID")
    if grid_key:
        cfg["use_grid"] = _env_flag(grid_key, bool(cfg.get("use_grid", False)))
    else:
        cfg["use_grid"] = bool(cfg.get("use_grid", False))

    url_key = _first_set("SCRAPE_GRID_URL", "SELENIUM_REMOTE_URL")
    if url_key:
        cfg["selenium_remote_url"] = os.environ[url_key].strip()

    # Chrome node containers (auto-manage) vs parallel scrape workers
    nodes_key = _first_set("SCRAPE_MAX_NODES", "SELENIUM_MAX_NODES")
    conc_key = _first_set(
        "SCRAPE_MAX_CONCURRENCY",
        "SCRAPE_MAX_SESSIONS",
        "SELENIUM_MAX_SESSIONS",
    )
    if nodes_key:
        cfg["max_nodes"] = max(1, _env_int(nodes_key, int(cfg.get("max_nodes") or 3)))
    if conc_key:
        cfg["max_concurrency"] = max(
            1, _env_int(conc_key, int(cfg.get("max_concurrency") or 3))
        )
    # Legacy: SCRAPE_MAX_SESSIONS / SELENIUM_MAX_NODES alone used to mean both
    if nodes_key is None and conc_key is not None:
        cfg["max_nodes"] = int(cfg["max_concurrency"])
    if conc_key is None and nodes_key is not None:
        cfg["max_concurrency"] = int(cfg["max_nodes"])
    # Very old single key SELENIUM_MAX_NODES when used as the only sessions knob
    if nodes_key == "SELENIUM_MAX_NODES" and conc_key is None:
        cfg["max_concurrency"] = int(cfg["max_nodes"])

    headless_key = _first_set("SCRAPE_HEADLESS", "SELENIUM_HEADLESS")
    if headless_key:
        cfg["headless"] = _env_flag(headless_key, bool(cfg.get("headless", True)))

    auto_key = _first_set("SCRAPE_AUTO_MANAGE_NODES", "SELENIUM_AUTO_MANAGE_NODES")
    if auto_key:
        cfg["auto_manage_nodes"] = _env_flag(
            auto_key, bool(cfg.get("auto_manage_nodes", False))
        )

    if os.environ.get("SELENIUM_NETWORK", "").strip():
        cfg["selenium_network"] = os.environ["SELENIUM_NETWORK"].strip()
    if os.environ.get("SELENIUM_HUB_CONTAINER", "").strip():
        cfg["selenium_hub_container"] = os.environ["SELENIUM_HUB_CONTAINER"].strip()
    if os.environ.get("SELENIUM_NODE_IMAGE", "").strip():
        cfg["selenium_node_image"] = os.environ["SELENIUM_NODE_IMAGE"].strip()

    # E5 site defaults may still come from program JSON (e5_config.json)
    if os.environ.get("IHMCL_MOBILE_NUMBER", "").strip():
        cfg["mobile_number"] = os.environ["IHMCL_MOBILE_NUMBER"].strip()
    if os.environ.get("IHMCL_PLAZA_NAME", "").strip():
        cfg["plaza_name"] = os.environ["IHMCL_PLAZA_NAME"].strip()

    return cfg
