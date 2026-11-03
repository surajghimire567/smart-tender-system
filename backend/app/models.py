"""Shared relational models owned by the database module.

Bid rows are owned by the auction module. Award.winning_bid_id deliberately
stays an integer here so this package can be migrated before that module is
integrated; the award service verifies the bid belongs to the tender.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric,
    String, Text, UniqueConstraint, event, func,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, validates

from app.auction.models import CollusionFlag
from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'vendor')", name="ck_users_role"),
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("registration_number", name="uq_users_registration_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(200))
    registration_number: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @validates("email")
    def normalize_email(self, key: str, value: str) -> str:
        return value.strip().lower()


class Tender(Base):
    __tablename__ = "tenders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'closed', 'awarded')",
            name="ck_tenders_status",
        ),
        CheckConstraint(
            "base_price > 0 AND ceiling_price >= base_price",
            name="ck_tenders_price_bounds",
        ),
        Index("ix_tenders_status_deadline", "status", "deadline"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    ceiling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Award(Base):
    __tablename__ = "awards"
    __table_args__ = (
        UniqueConstraint("tender_id", name="uq_awards_tender"),
        CheckConstraint("winning_bid_id > 0", name="ck_awards_winning_bid_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    winning_bid_id: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class AuditLog(Base):
    """Append-only record of application actions and request metadata."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("length(trim(action)) > 0", name="ck_audit_logs_action_nonempty"),
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_action_timestamp", "action", "timestamp"),
        Index("ix_audit_logs_tender_timestamp", "tender_id", "timestamp"),
        Index("ix_audit_logs_actor_timestamp", "actor_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenders.id", ondelete="RESTRICT"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    details: Mapped[dict | None] = mapped_column(JSON)


class AuditLogMutationError(RuntimeError):
    """Raised if application code attempts to change or delete an audit event."""


@event.listens_for(AuditLog, "before_update")
def _reject_audit_update(mapper, connection, target) -> None:
    raise AuditLogMutationError("Audit logs are append-only.")


@event.listens_for(AuditLog, "before_delete")
def _reject_audit_delete(mapper, connection, target) -> None:
    raise AuditLogMutationError("Audit logs are append-only.")


@event.listens_for(Session, "do_orm_execute")
def _reject_audit_bulk_mutation(state) -> None:
    if (state.is_update or state.is_delete) and any(
        mapper.class_ is AuditLog for mapper in state.all_mappers
    ):
        raise AuditLogMutationError("Bulk UPDATE/DELETE on audit logs is not allowed.")
