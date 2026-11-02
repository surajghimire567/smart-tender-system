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
    revision_of: int | None = None   # Day 4: set when this receipt is for a revision
    message: str


class ReceiptCheckOut(BaseModel):
    bid_id: int
    tender_id: int
    submitted_at: str
    integrity_ok: bool     # stored token + stored hash still agree
    superseded: bool       # True once a revision points at this bid (Day 4)

# ---- Day 4: input for a revision ----
class BidRevise(BaseModel):
    # No tender_id: the tender is copied from the old bid, so a revision can't jump
    # to another tender. extra="forbid" turns any such attempt into a 422.
    model_config = ConfigDict(extra="forbid")

    # TEMPORARY: Day 8 takes vendor_id from Person 2's login token instead.
    vendor_id: int = Field(..., gt=0)
    amount: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)


# ---- Day 4: revision history (receipts and times only, NO amounts) ----
class BidHistoryItem(BaseModel):
    bid_id: int
    bid_hash: str
    submitted_at: str
    revision_of: int | None
    is_current: bool       # True only for the newest row; only it counts on Day 5


class BidHistoryOut(BaseModel):
    tender_id: int
    vendor_id: int
    original_bid_id: int
    current_bid_id: int
    revisions: int         # 0 = never revised
    history: list[BidHistoryItem]   # oldest -> newest

   # ---- Day 5: ranking (the ONLY output that contains amounts, and only after the deadline) ----
class RankedBidOut(BaseModel):
    rank: int              # 1 = lowest amount = best bid
    bid_id: int
    vendor_id: int
    amount: Decimal        # decrypted in memory, never written back to the database
    bid_hash: str
    submitted_at: str
    revision_of: int | None
    gap_pct: Decimal | None   # % above the bid ranked just before it (None for rank 1). Day 6 uses it.


class ExcludedBidOut(BaseModel):
    # NO amount here: a bid that fails a check is never revealed.
    bid_id: int
    vendor_id: int
    bid_hash: str
    reason: str


class TenderRankingOut(BaseModel):
    tender_id: int
    status: str
    deadline: str
    opened_at: str            # when this ranking was computed (UTC)
    current_bids: int         # newest bid of each vendor (revisions replace older rows)
    ranked: int
    lowest: RankedBidOut | None
    ranking: list[RankedBidOut]       # lowest -> highest
    excluded: list[ExcludedBidOut]    # failed an integrity / deadline / ceiling check 

  # ---- Day 6: collusion rule 1. NO amount field anywhere: only vendor ids, ranks and % gaps. ----
class CollusionEventOut(BaseModel):
    tender_id: int
    lower_vendor_id: int       # the cheaper bid of the two neighbours
    higher_vendor_id: int
    lower_bid_id: int
    higher_bid_id: int
    gap_pct: Decimal           # how far above the cheaper one, in % (1.00 to 2.00)


class FlaggedPairOut(BaseModel):
    vendor_a: int              # the smaller vendor id of the pair
    vendor_b: int
    times: int                 # in how many different tenders they were this close
    tender_ids: list[int]
    a_cheaper_times: int
    b_cheaper_times: int
    avg_gap_pct: Decimal
    events: list[CollusionEventOut]


class CollusionScanOut(BaseModel):
    rule: str
    gap_min_pct: Decimal
    gap_max_pct: Decimal
    min_repeats: int
    scanned_at: str
    tenders_scanned: list[int]
    close_gaps_found: int      # single close gaps seen (normal competition, NOT flags)
    pairs_flagged: int
    flagged: list[FlaggedPairOut]


# ---- Day 6: collusion rule 2 (one vendor wins too often). Still NO amount field anywhere. ----
class WinShareFlagOut(BaseModel):
    vendor_id: int
    entered: int                # contested tenders (>= 2 valid bids) with a ranked bid of this vendor
    won: int                    # of those, how many it was rank 1 in
    win_share_pct: Decimal      # won / entered * 100, 2 decimals
    tender_ids_entered: list[int]
    tender_ids_won: list[int]


class WinShareScanOut(BaseModel):
    rule: str
    min_share_pct: int
    min_entered: int
    min_bidders: int
    scanned_at: str
    tenders_scanned: list[int]
    contested_tenders: list[int]   # scanned tenders with >= min_bidders valid bids
    vendors_judged: int            # vendors that entered >= min_entered contested tenders
    vendors_flagged: int
    flagged: list[WinShareFlagOut]


# ---- Day 6: the saved flags (CollusionFlags table) ----
class CollusionFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule: str                   # repeated_undercutting | high_win_share
    tender_id: int
    vendor_id_a: int
    vendor_id_b: int | None     # None for high_win_share (one vendor, no pair)
    flag_reason: str
    flagged_at: datetime


class CollusionRunOut(BaseModel):
    scanned_at: str
    tenders_scanned: list[int]
    pairs_flagged: int          # rule 1 result (pairs of vendors)
    vendors_flagged: int        # rule 2 result (single vendors)
    flags_found: int            # rows both rules produced in this run
    new_flags: int              # rows INSERTed by this run
    already_saved: int          # rows an earlier run had saved (skipped, never duplicated)
    saved: list[CollusionFlagOut]   # the NEW rows only  