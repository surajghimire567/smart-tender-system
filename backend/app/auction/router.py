from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auction import service
from app.auction.collusion import MIN_ENTERED, MIN_REPEATS, WIN_SHARE_MIN
from app.auction.models import Bid
from app.auction.schemas import (
    BidHistoryOut,
    CollusionFlagOut,
    CollusionRunOut,
    CollusionScanOut,
    ReceiptCheckOut,
    SealedBidOut,
    TenderRankingOut,
    WinShareScanOut,
)
from app.admin.deps import require_admin
from app.audit.service import log_action as audit_log_action
from app.database import get_db

router = APIRouter(prefix="/auction", tags=["Auction Engine"])


# ---- Day 2: read-only sealed bids (receipts only, NO amounts) ----
@router.get(
    "/tenders/{tender_id}/sealed-bids",
    response_model=list[SealedBidOut],
    dependencies=[Depends(require_admin)],
)
def sealed_bids(tender_id: int, db: Session = Depends(get_db)):
    """List bids for a tender without revealing any amount (L1)."""
    query = select(Bid).where(Bid.tender_id == tender_id).order_by(Bid.id)
    return db.execute(query).scalars().all()


# ---- Day 3: check a receipt (no amount in, no amount out) ----
@router.get("/receipts/{bid_hash}", response_model=ReceiptCheckOut)
def check_receipt(
    bid_hash: str = Path(..., pattern="^[0-9a-f]{64}$"),
    db: Session = Depends(get_db),
):
    """Is my bid stored, and are its token and hash still consistent?"""
    try:
        return service.check_receipt(db, bid_hash)
    except service.ReceiptNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
# ---- Day 4: revision history (receipts and times, NO amounts) ----
@router.get("/bids/{bid_id}/history", response_model=BidHistoryOut)
def bid_history(bid_id: int = Path(..., gt=0), db: Session = Depends(get_db)):
    """Original -> every revision -> current, from any bid id in the chain."""
    try:
        return service.bid_history(db, bid_id)
    except service.BidRejected as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

# ---- Day 5: open + rank the bids, ONLY after the deadline (L1) ----
@router.get(
    "/tenders/{tender_id}/ranking",
    response_model=TenderRankingOut,
)
def tender_ranking(
    request: Request,
    tender_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    admin: Any = Depends(require_admin),
):
    """Before the deadline: 409, nothing decrypted. After: current bids, lowest -> highest."""
    try:
        result = service.rank_bids(db, tender_id)
        audit_log_action(
            db,
            actor_id=int(admin.id),
            action="RANKING_VIEWED",
            tender_id=tender_id,
            ip_address=request.client.host if request.client else None,
            details={
                "ranked_bids": result.get("ranked", 0),
                "excluded_bids": len(result.get("excluded", [])),
            },
        )
        db.commit()
        return result
    except service.BidRejected as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

# ---- Day 6: collusion rule 1 - repeated 1-2% undercutting between the same vendor pair (L10) ----
@router.get(
    "/collusion/undercutting",
    response_model=CollusionScanOut,
)
def collusion_undercutting(
    request: Request,
    min_repeats: int = Query(MIN_REPEATS, ge=2, le=20),
    db: Session = Depends(get_db),
    admin: Any = Depends(require_admin),
):
    """Scans every tender whose deadline has passed. Sealed tenders are never opened."""
    result = service.scan_undercutting(db, min_repeats=min_repeats)
    audit_log_action(
        db,
        actor_id=int(admin.id),
        action="COLLUSION_SCAN",
        ip_address=request.client.host if request.client else None,
        details={
            "rule": result["rule"],
            "tenders_scanned": len(result["tenders_scanned"]),
            "flags_found": result["pairs_flagged"],
        },
    )
    db.commit()
    return result


# ---- Day 6: collusion rule 2 - one vendor wins an unusually high share (read-only, like rule 1) ----
@router.get(
    "/collusion/win-share",
    response_model=WinShareScanOut,
)
def collusion_win_share(
    request: Request,
    min_share: int = Query(WIN_SHARE_MIN, ge=50, le=100),
    min_entered: int = Query(MIN_ENTERED, ge=2, le=50),
    db: Session = Depends(get_db),
    admin: Any = Depends(require_admin),
):
    """Wins / contested tenders entered, per vendor, over every tender whose deadline has passed."""
    result = service.scan_win_share(db, min_share=min_share, min_entered=min_entered)
    audit_log_action(
        db,
        actor_id=int(admin.id),
        action="COLLUSION_SCAN",
        ip_address=request.client.host if request.client else None,
        details={
            "rule": result["rule"],
            "tenders_scanned": len(result["tenders_scanned"]),
            "flags_found": result["vendors_flagged"],
        },
    )
    db.commit()
    return result


# ---- Day 6: run BOTH rules and SAVE the flags (the only collusion route that writes) ----
@router.post(
    "/collusion/scan",
    response_model=CollusionRunOut,
)
def collusion_scan(
    request: Request,
    db: Session = Depends(get_db),
    admin: Any = Depends(require_admin),
):
    """Official thresholds only. New flags are INSERTed; flags saved earlier are never touched."""
    return service.run_collusion_scan(
        db,
        actor_id=int(admin.id),
        ip_address=request.client.host if request.client else None,
    )


# ---- Day 6: the saved flags (Person 1's dashboard reads this on Day 8) ----
@router.get(
    "/collusion/flags",
    response_model=list[CollusionFlagOut],
)
def collusion_flags(
    request: Request,
    tender_id: int | None = Query(None, gt=0),
    vendor_id: int | None = Query(None, gt=0),
    rule: Literal["repeated_undercutting", "high_win_share"] | None = Query(None),
    db: Session = Depends(get_db),
    admin: Any = Depends(require_admin),
):
    """Newest first. Filter by tender, by vendor (either side of a pair) or by rule."""
    flags = service.list_flags(db, tender_id=tender_id, vendor_id=vendor_id, rule=rule)
    audit_log_action(
        db,
        actor_id=int(admin.id),
        action="COLLUSION_FLAGS_VIEWED",
        tender_id=tender_id,
        ip_address=request.client.host if request.client else None,
        details={"flag_count": len(flags)},
    )
    db.commit()
    return flags
