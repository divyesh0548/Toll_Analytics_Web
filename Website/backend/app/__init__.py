"""Flask application factory."""

from __future__ import annotations

import os

from flask import Flask
from flask_cors import CORS

from config import config_by_name
from app.extensions import db, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    env_name = config_name or os.getenv("FLASK_ENV", "development")
    app.config.from_object(config_by_name.get(env_name, config_by_name["default"]))

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    db.init_app(app)
    migrate.init_app(app, db)

    # Import models so Flask-Migrate can detect them.
    from app import models  # noqa: F401

    from app.routes import auth_bp, companies_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(companies_bp, url_prefix="/api/companies")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
