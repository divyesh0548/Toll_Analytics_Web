"""Auth token helpers and route guards."""

from __future__ import annotations

from functools import wraps

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.models.user import User


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="toll-analytics-auth",
    )


def issue_token(user: User) -> str:
    return _serializer().dumps({"uid": user.id, "role": user.role})


def user_from_token(token: str, *, max_age_seconds: int = 60 * 60 * 12) -> User | None:
    try:
        payload = _serializer().loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, payload.get("uid"))
    if not user or not user.is_active:
        return None
    return user


def get_bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def get_current_user() -> User | None:
    if hasattr(g, "current_user"):
        return g.current_user
    token = get_bearer_token()
    user = user_from_token(token) if token else None
    g.current_user = user
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if user.role not in roles:
                return jsonify({"error": "Forbidden"}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator
