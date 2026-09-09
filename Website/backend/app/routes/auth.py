"""Authentication API routes (stubs for now)."""

from flask import Blueprint, jsonify

auth_bp = Blueprint("auth", __name__)


@auth_bp.get("/health")
def auth_health():
    return jsonify({"status": "ok", "service": "auth"})
