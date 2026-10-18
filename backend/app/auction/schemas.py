# app/auction/schemas.py
# What the API is ALLOWED to send back. Note: no amount field at all (L1).
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SealedBidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    vendor_id: int
    bid_hash: str
    token_preview: str
    revision_of: int | None
    submitted_at: datetime