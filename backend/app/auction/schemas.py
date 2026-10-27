# app/auction/schemas.py
# What the API ACCEPTS (BidCreate) and what it is ALLOWED to send back.
# None of the output schemas has an amount field (L1).
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---- Day 2 ----
class SealedBidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    vendor_id: int
    bid_hash: str
    token_preview: str
    revision_of: int | None
    submitted_at: datetime


# ---- Day 3: input ----
class BidCreate(BaseModel):
    # extra="forbid": the client can't sneak in submitted_at, bid_hash, revision_of ...
    model_config = ConfigDict(extra="forbid")

    tender_id: int = Field(..., gt=0)
    # TEMPORARY: Day 8 takes vendor_id from Person 2's login token instead.
    vendor_id: int = Field(..., gt=0)
    # Money as Decimal: > 0, at most 2 decimal places, at most 12 digits before the point.
    amount: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)


# ---- Day 3: output ----
class BidReceiptOut(BaseModel):
    bid_id: int
    tender_id: int
    vendor_id: int
    bid_hash: str
    submitted_at: str      # the EXACT UTC string that went into the hash
    message: str


class ReceiptCheckOut(BaseModel):
    bid_id: int
    tender_id: int
    submitted_at: str
    integrity_ok: bool     # stored token + stored hash still agree
    superseded: bool       # True once a revision points at this bid (Day 4)