"""User account model."""

from __future__ import annotations

from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

ROLES = ("siteadmin", "snt", "viewer")
CREATABLE_ROLES = ("snt", "viewer")
DEFAULT_ROLE = "viewer"
SITEADMIN_ROLE = "siteadmin"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default=DEFAULT_ROLE)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    temp_login = db.Column(db.Boolean, nullable=False, default=False)
    temp_pass = db.Column(db.String(255), nullable=True)
    login_email_sent = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    def set_password(self, password: str, *, temporary: bool = False) -> None:
        self.password_hash = generate_password_hash(password)
        if temporary:
            self.temp_pass = password
            self.temp_login = True
            self.login_email_sent = False
        else:
            self.temp_pass = None
            self.temp_login = False

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def normalize_role(role: str | None, *, allowed: tuple[str, ...] | None = None) -> str:
        allowed_roles = allowed or ROLES
        value = (role or DEFAULT_ROLE).strip().lower()
        if value not in allowed_roles:
            raise ValueError(
                f"Invalid role '{role}'. Allowed: {', '.join(allowed_roles)}"
            )
        return value

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "temp_login": self.temp_login,
            "login_email_sent": self.login_email_sent,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<User {self.email}>"
