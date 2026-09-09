"""HTTP route blueprints."""

from app.routes.auth import auth_bp
from app.routes.companies import companies_bp

__all__ = ["auth_bp", "companies_bp"]
