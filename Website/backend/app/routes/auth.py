"""Authentication and user-management API routes."""

from __future__ import annotations

import secrets
import string

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.user import CREATABLE_ROLES, ROLES, SITEADMIN_ROLE, User
from app.services.auth_tokens import (
    get_current_user,
    issue_token,
    login_required,
    roles_required,
)
from app.utils.api_log import log_fail, log_ok

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
        log_fail("login failed: missing credentials")
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        log_fail(f"login failed: {email or 'unknown'}")
        return jsonify({"error": "Invalid email or password"}), 401
    if not user.is_active:
        log_fail(f"login blocked inactive: {email}")
        return jsonify({"error": "Your Account is inactive."}), 403

    token = issue_token(user)
    log_ok(f"{email} logged in")
    return jsonify({"token": token, "user": user.to_dict()})


@auth_bp.get("/me")
@login_required
def me():
    user = get_current_user()
    log_ok(f"session ok: {user.email}")
    return jsonify({"user": user.to_dict()})


@auth_bp.post("/change-password")
@login_required
def change_password():
    user = get_current_user()
    if user.role == SITEADMIN_ROLE:
        log_fail(f"password change blocked for siteadmin: {user.email}")
        return jsonify({"error": "Site admin password cannot be changed here"}), 403

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not current_password or not new_password:
        log_fail(f"password change failed: missing fields ({user.email})")
        return jsonify({"error": "current_password and new_password are required"}), 400
    if len(new_password) < 8:
        log_fail(f"password change failed: too short ({user.email})")
        return jsonify({"error": "New password must be at least 8 characters"}), 400
    if not user.check_password(current_password):
        log_fail(f"password change failed: bad current ({user.email})")
        return jsonify({"error": "Current password is incorrect"}), 401
    if current_password == new_password:
        log_fail(f"password change failed: unchanged ({user.email})")
        return jsonify({"error": "New password must be different from the current password"}), 400

    user.set_password(new_password, temporary=False)
    db.session.commit()
    log_ok(f"{user.email} password updated")
    return jsonify({"user": user.to_dict()})


@auth_bp.get("/users")
@roles_required("siteadmin")
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    log_ok(f"listed {len(users)} users")
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
        log_fail(f"user create failed: {exc}")
        return jsonify({"error": str(exc)}), 400

    if not email:
        log_fail("user create failed: email required")
        return jsonify({"error": "email is required"}), 400
    if User.query.filter_by(email=email).first():
        log_fail(f"user create failed: {email} exists")
        return jsonify({"error": "A user with this email already exists"}), 409

    temp_password = (data.get("password") or "").strip() or _generate_temp_password()
    user = User(email=email, full_name=full_name, role=role, is_active=True)
    user.set_password(temp_password, temporary=True)
    db.session.add(user)
    db.session.commit()
    log_ok(f"{email} created successfully")
    return jsonify({"user": user.to_dict()}), 201


@auth_bp.get("/roles")
@roles_required("siteadmin")
def creatable_roles():
    return jsonify({"roles": list(CREATABLE_ROLES), "all_roles": list(ROLES)})
