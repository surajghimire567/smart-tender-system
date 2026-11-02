"""P2-owned device anomaly checks and 30-minute login history lookup."""
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.vendor import deps


def client_ip(request: Any) -> str | None:
    return request.client.host if request.client else None


def previous_login(db: Session, user_id: int) -> Any | None:
    AuditLog = deps.get_model("AuditLog")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    return db.execute(
        select(AuditLog)
        .where(
            AuditLog.actor_id == user_id,
            AuditLog.action == "LOGIN_SUCCESS",
            AuditLog.timestamp >= cutoff,
        )
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def log_login_anomaly(
    db: Session,
    user: Any,
    fingerprint: str,
    ip_address: str | None,
) -> None:
    previous = previous_login(db, int(user.id))
    if previous is None:
        return
    previous_details = previous.details or {}
    previous_fp = previous_details.get("device_fingerprint")
    if previous_fp and previous_fp != fingerprint:
        deps.log_action(
            db,
            actor_id=int(user.id),
            action="DEVICE_ANOMALY",
            ip_address=ip_address,
            details={
                "reason": "login_device_change",
                "previous": str(previous_fp)[:12],
                "current": fingerprint[:12],
            },
        )
    elif previous_fp == fingerprint and previous.ip_address != ip_address:
        deps.log_action(
            db,
            actor_id=int(user.id),
            action="DEVICE_ANOMALY",
            ip_address=ip_address,
            details={
                "reason": "login_ip_change",
                "previous": (previous.ip_address or "")[:12],
                "current": (ip_address or "")[:12],
            },
        )


def check_bid_anomaly(
    db: Session,
    user: Any,
    fingerprint: str,
    ip_address: str | None,
    tender_id: int,
) -> None:
    """Flag a fingerprint mismatch; never reject a bid because of the mismatch."""
    token_fingerprint = getattr(user, "token_dfp", None)
    if token_fingerprint != fingerprint:
        deps.log_action(
            db,
            actor_id=int(user.id),
            action="DEVICE_ANOMALY",
            tender_id=tender_id,
            ip_address=ip_address,
            details={
                "reason": "bid_device_mismatch",
                "token": str(token_fingerprint or "")[:12],
                "current": fingerprint[:12],
            },
        )
