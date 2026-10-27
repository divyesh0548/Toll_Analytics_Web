"""Flask application factory."""

from __future__ import annotations

import logging
import os

from flask import Flask
from flask_cors import CORS

from config import config_by_name
from app.extensions import db, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    env_name = config_name or os.getenv("FLASK_ENV", "development")
    app.config.from_object(config_by_name.get(env_name, config_by_name["default"]))

    # Keep terminal clean: hide default request access lines.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Browser may hit /api via nginx (same origin) or direct backend.
    # Ngrok demo origin must be listed for any cross-origin API calls.
    cors_origins = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173,"
            "https://mariah-pernickety-phraseologically.ngrok-free.dev",
        ).split(",")
        if o.strip()
    ]
    CORS(app, resources={r"/api/*": {"origins": cors_origins or "*"}})

    db.init_app(app)
    migrate.init_app(app, db)

    # Import models so Flask-Migrate can detect them.
    from app import models  # noqa: F401

    from app.routes import (
        analytics_bp,
        auth_bp,
        companies_bp,
        exception_jobs_bp,
        plazas_bp,
        spvs_bp,
    )
    from app.routes.exception_pipeline import exception_pipeline_bp
    from app.routes.mapping_config import mapping_config_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(companies_bp, url_prefix="/api/companies")
    app.register_blueprint(spvs_bp, url_prefix="/api/spvs")
    app.register_blueprint(plazas_bp, url_prefix="/api/plazas")
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
    app.register_blueprint(exception_jobs_bp, url_prefix="/api/exception-jobs")
    app.register_blueprint(exception_pipeline_bp, url_prefix="/api/exception-pipeline")
    app.register_blueprint(mapping_config_bp, url_prefix="/api/mapping-config")

    from flask import request
    from app.utils.api_log import log_api

    @app.after_request
    def _log_api_call(response):
        path = request.path or ""
        if path.startswith("/api/"):
            log_api(request.method, path, response.status_code)
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    from app.services.siteadmin_bootstrap import bootstrap_siteadmin_on_startup
    from app.services.audit_exception_bootstrap import (
        bootstrap_audit_exception_types_on_startup,
    )
    from app.services.exception_job_worker import start_exception_job_worker

    bootstrap_siteadmin_on_startup(app)
    bootstrap_audit_exception_types_on_startup(app)
    start_exception_job_worker(app)

    _register_mapping_cli(app)

    return app


def _register_mapping_cli(app: Flask) -> None:
    """Manual seed only — never runs on startup."""
    import click

    @app.cli.command("seed-shared-config")
    @click.option(
        "--replace",
        is_flag=True,
        help="Wipe existing mapping rows and load shared_config JSON again.",
    )
    def seed_shared_config_command(replace: bool) -> None:
        """Load shared_config JSON into mapping tables (does not run by itself)."""
        from app.services.mapping_config_seed import seed_shared_config

        try:
            result = seed_shared_config(replace=replace)
        except (RuntimeError, FileNotFoundError) as exc:
            raise SystemExit(str(exc)) from exc
        counts = result["counts"]
        click.echo(
            "Seeded shared config from {root}\n"
            "  canonicals: {canonicals}\n"
            "  aliases: {aliases}\n"
            "  list items: {list_items}\n"
            "  settings: {settings}".format(root=result["root"], **counts)
        )
        skipped = result.get("skipped") or []
        if skipped:
            click.echo(f"Skipped {len(skipped)} duplicate aliases:")
            for line in skipped[:40]:
                click.echo(f"  {line}")
            if len(skipped) > 40:
                click.echo(f"  … and {len(skipped) - 40} more")
