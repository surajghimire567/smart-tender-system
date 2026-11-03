"""Person 1's /admin routes. All state changes and audit events share a transaction."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from app.admin import deps, service
from app.admin.schemas import (
    AwardIn,
    AwardOut,
    CollusionFlagOut,
    TenderCreateIn,
    TenderOut,
    TenderUpdateIn,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


def _ip(request: Request) -> str | None:
    # The project blueprint specifies request.client.host; do not trust forwarded headers.
    return request.client.host if request.client else None


def _actor_id(user: Any) -> int:
    actor_id = getattr(user, "id", None)
    if actor_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return int(actor_id)


def _tender_out(tender: Any) -> dict[str, Any]:
    return {
        "id": tender.id,
        "created_by": tender.created_by,
        "title": tender.title,
        "description": tender.description,
        "base_price": tender.base_price,
        "ceiling_price": tender.ceiling_price,
        "deadline": tender.deadline,
        "status": tender.status,
        "created_at": tender.created_at,
        "is_open": service.is_open(tender),
    }


def _admin_error(db: Session, exc: Exception) -> None:
    db.rollback()
    if isinstance(exc, service.AdminError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if isinstance(exc, HTTPException):
        raise exc
    raise exc


@router.get("/tenders", response_model=list[TenderOut])
def list_admin_tenders(
    db: Session = Depends(deps.get_db),
    _admin: Any = Depends(deps.require_admin),
):
    """Admin dashboard tender list; overdue published tenders are lazily closed."""
    try:
        tenders = service.list_tenders(db)
        return [_tender_out(tender) for tender in tenders]
    except Exception as exc:
        _admin_error(db, exc)


@router.post("/tenders", response_model=TenderOut, status_code=status.HTTP_201_CREATED)
def create_tender(
    payload: TenderCreateIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    admin: Any = Depends(deps.require_admin),
):
    try:
        tender = service.create_tender(
            db, payload, _actor_id(admin), _ip(request)
        )
        return _tender_out(tender)
    except Exception as exc:
        _admin_error(db, exc)


@router.get("/tenders/{tender_id}", response_model=TenderOut)
def get_admin_tender(
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(deps.get_db),
    _admin: Any = Depends(deps.require_admin),
):
    try:
        tender = service.get_tender_or_404(db, tender_id)
        tender = service.refresh_status(db, tender, _ip(request))
        return _tender_out(tender)
    except Exception as exc:
        _admin_error(db, exc)


@router.patch("/tenders/{tender_id}", response_model=TenderOut)
def edit_draft_tender(
    payload: TenderUpdateIn,
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(deps.get_db),
    admin: Any = Depends(deps.require_admin),
):
    try:
        tender = service.update_draft(
            db, tender_id, payload, _actor_id(admin), _ip(request)
        )
        return _tender_out(tender)
    except Exception as exc:
        _admin_error(db, exc)


@router.post("/tenders/{tender_id}/publish", response_model=TenderOut)
def publish_tender(
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(deps.get_db),
    admin: Any = Depends(deps.require_admin),
):
    try:
        tender = service.publish_tender(
            db, tender_id, _actor_id(admin), _ip(request)
        )
        return _tender_out(tender)
    except Exception as exc:
        _admin_error(db, exc)


@router.post("/tenders/{tender_id}/close", response_model=TenderOut)
def close_tender(
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(deps.get_db),
    admin: Any = Depends(deps.require_admin),
):
    try:
        tender = service.close_tender(
            db, tender_id, _actor_id(admin), _ip(request)
        )
        return _tender_out(tender)
    except Exception as exc:
        _admin_error(db, exc)


@router.get("/tenders/{tender_id}/ranking")
def get_tender_ranking(
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(deps.get_db),
    _admin: Any = Depends(deps.require_admin),
):
    """The P3 ranking service is called only after the server-side deadline check."""
    try:
        return service.get_ranking(
            db, tender_id, _ip(request)
        )
    except Exception as exc:
        _admin_error(db, exc)


@router.get("/tenders/{tender_id}/flags", response_model=list[CollusionFlagOut])
def get_tender_flags(
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(deps.get_db),
    _admin: Any = Depends(deps.require_admin),
):
    try:
        flags = service.get_collusion_flags(
            db, tender_id, _ip(request)
        )
        return [CollusionFlagOut.model_validate(flag) for flag in flags]
    except Exception as exc:
        _admin_error(db, exc)


@router.post(
    "/tenders/{tender_id}/award",
    response_model=AwardOut,
    status_code=status.HTTP_201_CREATED,
)
def award_tender(
    payload: AwardIn,
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(deps.get_db),
    admin: Any = Depends(deps.require_admin),
):
    try:
        award = service.award_tender(
            db, tender_id, payload, _actor_id(admin), _ip(request)
        )
        return award
    except Exception as exc:
        _admin_error(db, exc)
