"""Tender lifecycle and admin operations owned by Person 1."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.admin import deps
from app.admin.schemas import AwardIn, TenderCreateIn, TenderUpdateIn

DRAFT = "draft"
PUBLISHED = "published"
CLOSED = "closed"
AWARDED = "awarded"


class AdminError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _deadline_passed(tender: Any) -> bool:
    return datetime.now(timezone.utc) >= _as_utc(tender.deadline)


def is_open(tender: Any) -> bool:
    """P1 cross-module contract: published and strictly before the UTC deadline."""
    return tender.status == PUBLISHED and not _deadline_passed(tender)


def _log_deadline_close(db: Any, tender: Any, ip: str | None = None) -> None:
    tender.status = CLOSED
    deps.log_action(
        db,
        actor_id=None,
        action="TENDER_CLOSED",
        tender_id=tender.id,
        ip_address=ip,
        details={"reason": "deadline"},
    )


def refresh_status(db: Any, tender: Any, ip: str | None = None) -> Any:
    """P1 contract: lazily close an overdue tender; idempotent; may commit."""
    if tender.status == PUBLISHED and not is_open(tender):
        try:
            _log_deadline_close(db, tender, ip)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return tender


def refresh_all_overdue(db: Any) -> None:
    """P1 contract: close every overdue published tender and append audit events."""
    Tender = deps.get_model("Tender")
    rows = db.execute(
        select(Tender).where(Tender.status == PUBLISHED)
    ).scalars().all()
    changed = False
    try:
        for tender in rows:
            if not is_open(tender):
                _log_deadline_close(db, tender)
                changed = True
        if changed:
            db.commit()
    except Exception:
        db.rollback()
        raise


def get_tender(db: Any, tender_id: int) -> Any:
    Tender = deps.get_model("Tender")
    return db.execute(
        select(Tender).where(Tender.id == tender_id)
    ).scalar_one_or_none()


def get_tender_or_404(db: Any, tender_id: int) -> Any:
    tender = get_tender(db, tender_id)
    if tender is None:
        raise AdminError(404, "Tender not found")
    return tender


def _safe_commit(db: Any) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def list_tenders(db: Any) -> list[Any]:
    refresh_all_overdue(db)
    Tender = deps.get_model("Tender")
    return list(
        db.execute(
            select(Tender).order_by(Tender.created_at.desc(), Tender.id.desc())
        ).scalars().all()
    )


def create_tender(
    db: Any,
    payload: TenderCreateIn,
    actor_id: int,
    ip: str | None,
) -> Any:
    Tender = deps.get_model("Tender")
    values = payload.model_dump()
    values.update(created_by=actor_id, status=DRAFT)
    tender = Tender(**values)
    try:
        db.add(tender)
        db.flush()
        deps.log_action(
            db,
            actor_id=actor_id,
            action="TENDER_CREATED",
            tender_id=tender.id,
            ip_address=ip,
            details=None,
        )
        _safe_commit(db)
        db.refresh(tender)
        return tender
    except Exception:
        db.rollback()
        raise


def update_draft(
    db: Any,
    tender_id: int,
    payload: TenderUpdateIn,
    actor_id: int,
    ip: str | None,
) -> Any:
    tender = get_tender_or_404(db, tender_id)
    if tender.status != DRAFT:
        raise AdminError(409, "Tender is not open for bidding")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if changes:
        try:
            for name, value in changes.items():
                setattr(tender, name, value)
            deps.log_action(
                db,
                actor_id=actor_id,
                action="TENDER_UPDATED",
                tender_id=tender.id,
                ip_address=ip,
                details=None,
            )
            _safe_commit(db)
            db.refresh(tender)
        except Exception:
            db.rollback()
            raise
    return tender


def publish_tender(db: Any, tender_id: int, actor_id: int, ip: str | None) -> Any:
    tender = get_tender_or_404(db, tender_id)
    if tender.status != DRAFT:
        raise AdminError(409, "Tender is not open for bidding")
    try:
        tender.status = PUBLISHED
        deps.log_action(
            db,
            actor_id=actor_id,
            action="TENDER_PUBLISHED",
            tender_id=tender.id,
            ip_address=ip,
            details=None,
        )
        _safe_commit(db)
        db.refresh(tender)
        return tender
    except Exception:
        db.rollback()
        raise


def close_tender(db: Any, tender_id: int, actor_id: int, ip: str | None) -> Any:
    tender = get_tender_or_404(db, tender_id)
    if tender.status == PUBLISHED:
        tender = refresh_status(db, tender, ip)
        if tender.status == PUBLISHED:
            try:
                tender.status = CLOSED
                deps.log_action(
                    db,
                    actor_id=actor_id,
                    action="TENDER_CLOSED",
                    tender_id=tender.id,
                    ip_address=ip,
                    details={"reason": "manual"},
                )
                _safe_commit(db)
                db.refresh(tender)
            except Exception:
                db.rollback()
                raise
        return tender
    if tender.status == CLOSED:
        return tender
    raise AdminError(409, "Tender is not open for bidding")


def get_ranking(db: Any, tender_id: int, ip: str | None = None) -> dict:
    tender = get_tender_or_404(db, tender_id)
    tender = refresh_status(db, tender, ip)
    if tender.status == DRAFT:
        raise AdminError(409, "Tender is not open for bidding")
    if not _deadline_passed(tender):
        raise AdminError(409, "Bids are sealed until the deadline")
    try:
        return deps.rank_bids(db, tender_id)
    except AdminError:
        raise
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            raise
        raise AdminError(status_code, getattr(exc, "detail", str(exc))) from exc


def get_collusion_flags(db: Any, tender_id: int, ip: str | None = None) -> list[Any]:
    tender = get_tender_or_404(db, tender_id)
    tender = refresh_status(db, tender, ip)
    if tender.status == DRAFT:
        raise AdminError(409, "Tender is not open for bidding")
    if not _deadline_passed(tender):
        raise AdminError(409, "Bids are sealed until the deadline")
    CollusionFlag = deps.get_model("CollusionFlag")
    return list(
        db.execute(
            select(CollusionFlag)
            .where(CollusionFlag.tender_id == tender_id)
            .order_by(CollusionFlag.flagged_at.desc(), CollusionFlag.id.desc())
        ).scalars().all()
    )


def award_tender(
    db: Any,
    tender_id: int,
    payload: AwardIn,
    actor_id: int,
    ip: str | None,
) -> Any:
    tender = get_tender_or_404(db, tender_id)
    tender = refresh_status(db, tender, ip)
    if tender.status == DRAFT:
        raise AdminError(409, "Tender is not open for bidding")
    if not _deadline_passed(tender):
        raise AdminError(409, "Bids are sealed until the deadline")
    if tender.status != CLOSED:
        raise AdminError(409, "Tender is not open for bidding")

    ranking = get_ranking(db, tender_id, ip)
    eligible_ids = {int(row["bid_id"]) for row in ranking.get("ranking", [])}
    if payload.winning_bid_id not in eligible_ids:
        raise AdminError(404, "Tender not found")

    Award = deps.get_model("Award")
    award = Award(
        tender_id=tender.id,
        winning_bid_id=payload.winning_bid_id,
        awarded_at=datetime.now(timezone.utc),
    )
    try:
        db.add(award)
        db.flush()
        tender.status = AWARDED
        deps.log_action(
            db,
            actor_id=actor_id,
            action="TENDER_AWARDED",
            tender_id=tender.id,
            ip_address=ip,
            details={"winning_bid_id": payload.winning_bid_id},
        )
        _safe_commit(db)
        db.refresh(award)
        return award
    except Exception:
        db.rollback()
        raise
