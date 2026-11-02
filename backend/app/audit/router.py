"""Admin-only, paginated audit log view."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit import service
from app.audit.schemas import AuditLogPageOut
from app.database import get_db

try:
    # Person 1's dependency delegates to Person 2's authenticated admin role.
    from app.admin.deps import require_admin
except (ImportError, AttributeError):
    def require_admin() -> None:
        raise HTTPException(
            status_code=503,
            detail="Admin authentication integration is pending",
        )


router = APIRouter(prefix="/admin", tags=["Audit"])


@router.get("/audit-logs", response_model=AuditLogPageOut)
def get_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tender_id: int | None = Query(default=None, gt=0),
    actor_id: int | None = Query(default=None, gt=0),
    action: str | None = Query(default=None, min_length=1, max_length=80),
    db: Session = Depends(get_db),
    admin: Any = Depends(require_admin),
) -> AuditLogPageOut:
    """List audit events newest first; log the view itself after reading."""
    rows, total = service.list_audit_logs(
        db,
        limit=limit,
        offset=offset,
        tender_id=tender_id,
        actor_id=actor_id,
        action=action,
    )
    admin_id = getattr(admin, "id", None)
    try:
        service.log_action(
            db,
            actor_id=int(admin_id) if admin_id is not None else None,
            action="AUDIT_LOG_VIEWED",
            details={
                "limit": limit,
                "offset": offset,
                "tender_id": tender_id,
                "actor_id_filter": actor_id,
                "action_filter": action,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return AuditLogPageOut(items=rows, total=total, limit=limit, offset=offset)
