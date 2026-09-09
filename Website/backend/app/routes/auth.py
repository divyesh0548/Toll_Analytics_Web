"""Authentication and user-management API routes."""

from __future__ import annotations

import secrets
import string

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.user import CREATABLE_ROLES, ROLES, User
from app.services.auth_tokens import (
    get_current_user,
    issue_token,
    login_required,
    roles_required,
)

auth_bp = Blueprint("auth", __name__)


def _generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@auth_bp.get("/health")
def auth_health():
    return jsonify({"status": "ok", "service": "auth"})


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401
    if not user.is_active:
        return jsonify({"error": "Your Account is inactive."}), 403

    token = issue_token(user)
    return jsonify({"token": token, "user": user.to_dict()})


@auth_bp.get("/me")
@login_required
def me():
    return jsonify({"user": get_current_user().to_dict()})


@auth_bp.get("/users")
@roles_required("siteadmin")
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({"users": [u.to_dict() for u in users]})


@auth_bp.post("/users")
@roles_required("siteadmin")
def create_user():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    full_name = (data.get("full_name") or "").strip() or None
    try:
        role = User.normalize_role(data.get("role"), allowed=CREATABLE_ROLES)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not email:
        return jsonify({"error": "email is required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "A user with this email already exists"}), 409

    temp_password = (data.get("password") or "").strip() or _generate_temp_password()
    user = User(email=email, full_name=full_name, role=role, is_active=True)
    user.set_password(temp_password, temporary=True)
    db.session.add(user)
    db.session.commit()
    return jsonify({"user": user.to_dict()}), 201


@auth_bp.get("/roles")
@roles_required("siteadmin")
def creatable_roles():
    return jsonify({"roles": list(CREATABLE_ROLES), "all_roles": list(ROLES)})
