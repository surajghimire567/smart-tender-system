"""Append-only audit event writes and admin queries."""
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action(
    db: Session,
    actor_id: int | None,
    action: str,
    tender_id: int | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an event without committing; the caller owns the transaction."""
    normalized_action = action.strip().upper()
    if not normalized_action or len(normalized_action) > 80:
        raise ValueError("action must contain 1 to 80 characters")
    if actor_id is not None and actor_id <= 0:
        raise ValueError("actor_id must be positive or None")
    if tender_id is not None and tender_id <= 0:
        raise ValueError("tender_id must be positive or None")

    entry = AuditLog(
        actor_id=actor_id,
        tender_id=tender_id,
        action=normalized_action,
        ip_address=ip_address[:45] if ip_address else None,
        details=dict(details) if details is not None else None,
    )
    db.add(entry)
    db.flush()
    return entry


def list_audit_logs(
    db: Session,
    *,
    limit: int,
    offset: int,
    tender_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = None,
) -> tuple[list[AuditLog], int]:
    filters = []
    if tender_id is not None:
        filters.append(AuditLog.tender_id == tender_id)
    if actor_id is not None:
        filters.append(AuditLog.actor_id == actor_id)
    if action:
        filters.append(AuditLog.action == action.strip().upper())

    query = select(AuditLog).where(*filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return rows, int(total)
