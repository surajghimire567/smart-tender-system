# app/auction/router.py
# Day 1 demo routes + Day 2 sealed-bids route + Day 3 submit-bid & receipt routes.
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auction import crypto, service
from app.auction.models import Bid
from app.auction.schemas import BidCreate, BidReceiptOut, ReceiptCheckOut, SealedBidOut
from app.database import get_db
from app.auction.schemas import (
    BidCreate, BidHistoryOut, BidReceiptOut, BidRevise, ReceiptCheckOut, SealedBidOut,
)

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