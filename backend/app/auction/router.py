from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auction import crypto, service
from app.auction.collusion import MIN_ENTERED, MIN_REPEATS, WIN_SHARE_MIN
from app.auction.models import Bid
from app.auction.schemas import (
    BidCreate, BidHistoryOut, BidReceiptOut, BidRevise, CollusionFlagOut, CollusionRunOut,
    CollusionScanOut, ReceiptCheckOut, SealedBidOut, TenderRankingOut, WinShareScanOut,
)
from app.database import get_db

router = APIRouter(prefix="/auction", tags=["Auction Engine"])


class DemoBid(BaseModel):
    tender_id: int = Field(..., gt=0)
    vendor_id: int = Field(..., gt=0)
    amount: float = Field(..., gt=0)


@router.post("/demo-encrypt")
def demo_encrypt(bid: DemoBid):
    """Show what the DB would store vs what only the server can see."""
    submitted_at = datetime.now(timezone.utc).isoformat()
    token = crypto.encrypt_amount(bid.amount)
    receipt = crypto.make_bid_hash(bid.tender_id, bid.vendor_id, bid.amount, submitted_at)
    return {
        "stored_in_db": {"bid_amount_encrypted": token, "bid_hash": receipt,
                         "submitted_at": submitted_at},
        "server_can_decrypt": str(crypto.decrypt_amount(token)),
        "receipt_valid": crypto.verify_bid_hash(
            bid.tender_id, bid.vendor_id, bid.amount, submitted_at, receipt),
    }


class DemoDecrypt(BaseModel):
    token: str


# WARNING: /demo-decrypt decrypts ANY valid token for ANYONE, which defeats L1 for
# real bids. Delete both /demo-* routes before Day 8 integration / any deployment.
@router.post("/demo-decrypt")
def demo_decrypt(body: DemoDecrypt):
    """Try pasting an edited token here -> you get a 400 error (tamper detected)."""
    try:
        return {"amount": str(crypto.decrypt_amount(body.token))}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- Day 2: read-only sealed bids (receipts only, NO amounts) ----
@router.get("/tenders/{tender_id}/sealed-bids", response_model=list[SealedBidOut])
def sealed_bids(tender_id: int, db: Session = Depends(get_db)):
    """List bids for a tender without revealing any amount (L1)."""
    query = select(Bid).where(Bid.tender_id == tender_id).order_by(Bid.id)
    return db.execute(query).scalars().all()


# ---- Day 3: submit a sealed bid (L1 + L2) ----
@router.post("/bids", response_model=BidReceiptOut, status_code=201)
def submit_bid(
    body: BidCreate,
    request: Request,
    db: Session = Depends(get_db),
    x_device_fingerprint: str | None = Header(default=None, max_length=255),
):
    """Encrypt the amount, hash a receipt, INSERT one row, return the receipt."""
    try:
        bid = service.submit_bid(
            db, body,
            ip_address=request.client.host if request.client else None,
            device_fingerprint=x_device_fingerprint,
        )
    except service.BidRejected as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return BidReceiptOut(
        bid_id=bid.id,
        tender_id=bid.tender_id,
        vendor_id=bid.vendor_id,
        bid_hash=bid.bid_hash,
        submitted_at=bid.submitted_at_iso(),
        message="Bid sealed. Save this receipt; the amount stays encrypted until the deadline.",
    )


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
    # ---- Day 4: revise a bid = INSERT a new row (there is NO PUT / PATCH / DELETE) ----
@router.post("/bids/{bid_id}/revisions", response_model=BidReceiptOut, status_code=201)
def revise_bid(
    body: BidRevise,
    request: Request,
    bid_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    x_device_fingerprint: str | None = Header(default=None, max_length=255),
):
    """Seal a NEW amount as a new row pointing at bid_id. The old row is never touched."""
    try:
        bid = service.revise_bid(
            db, bid_id, body,
            ip_address=request.client.host if request.client else None,
            device_fingerprint=x_device_fingerprint,
        )
    except service.BidRejected as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return BidReceiptOut(
        bid_id=bid.id,
        tender_id=bid.tender_id,
        vendor_id=bid.vendor_id,
        bid_hash=bid.bid_hash,
        submitted_at=bid.submitted_at_iso(),
        revision_of=bid.revision_of,
        message="Revision sealed as a new bid. Save this NEW receipt; only your latest bid counts.",
    )


# ---- Day 4: revision history (receipts and times, NO amounts) ----
@router.get("/bids/{bid_id}/history", response_model=BidHistoryOut)
def bid_history(bid_id: int = Path(..., gt=0), db: Session = Depends(get_db)):
    """Original -> every revision -> current, from any bid id in the chain."""
    try:
        return service.bid_history(db, bid_id)
    except service.BidRejected as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

 # ---- Day 5: open + rank the bids, ONLY after the deadline (L1) ----
@router.get("/tenders/{tender_id}/ranking", response_model=TenderRankingOut)
def tender_ranking(tender_id: int = Path(..., gt=0), db: Session = Depends(get_db)):
    """Before the deadline: 409, nothing decrypted. After: current bids, lowest -> highest."""
    try:
        return service.rank_bids(db, tender_id)
    except service.BidRejected as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))   

    # ---- Day 6: collusion rule 1 - repeated 1-2% undercutting between the same vendor pair (L10) ----
@router.get("/collusion/undercutting", response_model=CollusionScanOut)
def collusion_undercutting(min_repeats: int = Query(MIN_REPEATS, ge=2, le=20),
                           db: Session = Depends(get_db)):
    """Scans every tender whose deadline has passed. Sealed tenders are never opened."""
    return service.scan_undercutting(db, min_repeats=min_repeats)


# ---- Day 6: collusion rule 2 - one vendor wins an unusually high share (read-only, like rule 1) ----
@router.get("/collusion/win-share", response_model=WinShareScanOut)
def collusion_win_share(min_share: int = Query(WIN_SHARE_MIN, ge=50, le=100),
                        min_entered: int = Query(MIN_ENTERED, ge=2, le=50),
                        db: Session = Depends(get_db)):
    """Wins / contested tenders entered, per vendor, over every tender whose deadline has passed."""
    return service.scan_win_share(db, min_share=min_share, min_entered=min_entered)


# ---- Day 6: run BOTH rules and SAVE the flags (the only collusion route that writes) ----
@router.post("/collusion/scan", response_model=CollusionRunOut)
def collusion_scan(db: Session = Depends(get_db)):
    """Official thresholds only. New flags are INSERTed; flags saved earlier are never touched."""
    return service.run_collusion_scan(db)


# ---- Day 6: the saved flags (Person 1's dashboard reads this on Day 8) ----
@router.get("/collusion/flags", response_model=list[CollusionFlagOut])
def collusion_flags(tender_id: int | None = Query(None, gt=0),
                    vendor_id: int | None = Query(None, gt=0),
                    rule: Literal["repeated_undercutting", "high_win_share"] | None = Query(None),
                    db: Session = Depends(get_db)):
    """Newest first. Filter by tender, by vendor (either side of a pair) or by rule."""
    return service.list_flags(db, tender_id=tender_id, vendor_id=vendor_id, rule=rule)