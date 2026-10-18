# app/auction/router.py
# Day 1 demo routes + Day 2 read-only sealed-bids route.
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auction import crypto
from app.auction.models import Bid
from app.auction.schemas import SealedBidOut
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