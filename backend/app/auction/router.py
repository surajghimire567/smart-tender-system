# app/auction/router.py
# Day 1 demo routes for the auction engine (replaced by real routes Day 3+).
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auction import crypto

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


@router.post("/demo-decrypt")
def demo_decrypt(body: DemoDecrypt):
    """Try pasting an edited token here -> you get a 400 error (tamper detected)."""
    try:
        return {"amount": str(crypto.decrypt_amount(body.token))}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))