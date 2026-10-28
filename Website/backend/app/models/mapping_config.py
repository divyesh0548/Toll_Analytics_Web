"""Editable shared mappings (vehicle class, MOP, column aliases, keywords).

Seeded on demand from Exeption Programs/common/shared_config — not on startup.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MappingDomain(db.Model):
    __tablename__ = "mapping_domains"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    label = db.Column(db.String(128), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    canonicals = db.relationship(
        "MappingCanonical",
        back_populates="domain",
        cascade="all, delete-orphan",
    )


class MappingCanonical(db.Model):
    __tablename__ = "mapping_canonicals"
    __table_args__ = (
        db.UniqueConstraint(
            "domain_id", "canonical_key", name="uq_mapping_canonicals_domain_key"
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    domain_id = db.Column(
        db.BigInteger,
        db.ForeignKey("mapping_domains.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_key = db.Column(db.String(128), nullable=False)
    db_column = db.Column(db.String(128), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    domain = db.relationship("MappingDomain", back_populates="canonicals")
    aliases = db.relationship(
        "MappingAlias",
        back_populates="canonical",
        cascade="all, delete-orphan",
    )


class MappingAlias(db.Model):
    __tablename__ = "mapping_aliases"
    __table_args__ = (
        db.UniqueConstraint(
            "canonical_id",
            "alias_normalized",
            name="uq_mapping_aliases_canonical_norm",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    domain_id = db.Column(
        db.BigInteger,
        db.ForeignKey("mapping_domains.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_id = db.Column(
        db.BigInteger,
        db.ForeignKey("mapping_canonicals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias = db.Column(db.String(512), nullable=False)
    alias_normalized = db.Column(db.String(512), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)

    canonical = db.relationship("MappingCanonical", back_populates="aliases")


class MappingListItem(db.Model):
    """Domain-level lists such as vehicle-class exclude and MOP ignore."""

    __tablename__ = "mapping_list_items"
    __table_args__ = (
        db.UniqueConstraint(
            "domain_id",
            "list_key",
            "value_normalized",
            name="uq_mapping_list_items_domain_key_norm",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    domain_id = db.Column(
        db.BigInteger,
        db.ForeignKey("mapping_domains.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    list_key = db.Column(db.String(64), nullable=False)
    value = db.Column(db.String(512), nullable=False)
    value_normalized = db.Column(db.String(512), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)


class MappingSetting(db.Model):
    """Scalar shared settings (header scan defaults and source overrides)."""

    __tablename__ = "mapping_settings"

    key = db.Column(db.String(128), primary_key=True)
    value_json = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )
    updated_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class MappingAudit(db.Model):
    __tablename__ = "mapping_audit"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    domain_code = db.Column(db.String(64), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    before_json = db.Column(db.JSON, nullable=True)
    after_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
