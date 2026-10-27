# app/auction/service.py
# Day 3: the business rules for submitting a bid, kept OUT of the router so
# the same code can be called by the API, the self-test and (later) pytest.
from datetime import datetime, timezone

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auction import crypto, tender_rules
from app.auction.models import Bid
from app.auction.schemas import BidCreate


class BidRejected(Exception):
    """Base class: every rejection carries the HTTP status the router should use."""
    status_code = 400


class TenderNotFound(BidRejected):
    status_code = 404


class TenderNotOpen(BidRejected):
    status_code = 409


class AboveCeiling(BidRejected):
    status_code = 422


class DuplicateBid(BidRejected):
    status_code = 409


class ReceiptNotFound(BidRejected):
    status_code = 404


def submit_bid(db: Session, data: BidCreate, *, ip_address: str | None,
               device_fingerprint: str | None) -> Bid:
    """Check the rules, then encrypt (L1), hash (L2) and INSERT one new row."""
    # 1. ONE server-side time. The client never chooses it.
    now = datetime.now(timezone.utc)

    # 2. Tender rules
    tender = tender_rules.get_tender(data.tender_id)
    if tender is None:
        raise TenderNotFound(f"Tender {data.tender_id} does not exist.")
    if tender.status != "published":
        raise TenderNotOpen(f"Tender {data.tender_id} is not open for bidding (status: {tender.status}).")
    if now >= tender.deadline:
        raise TenderNotOpen(f"Deadline passed at {tender.deadline.isoformat()}; late bids are rejected.")
    if data.amount > tender.ceiling_price:
        raise AboveCeiling(f"Bid is above the ceiling price of {tender.ceiling_price}.")

    # 3. One original bid per vendor per tender (changes = revision, Day 4)
    already = db.scalar(select(exists().where(
        Bid.tender_id == data.tender_id,
        Bid.vendor_id == data.vendor_id,
        Bid.revision_of.is_(None),
    )))
    if already:
        raise DuplicateBid("You already bid on this tender. Submit a revision instead (Day 4).")

    # 4. Seal it. float() = the same type Day 1 and Day 2 passed to crypto.
    amount = float(data.amount)
    bid = Bid(
        tender_id=data.tender_id,
        vendor_id=data.vendor_id,
        bid_amount_encrypted=crypto.encrypt_amount(amount),                      # L1
        bid_hash=crypto.make_bid_hash(data.tender_id, data.vendor_id, amount,    # L2
                                      now.isoformat()),
        device_fingerprint=device_fingerprint,                                   # L9 (Person 2)
        ip_address=ip_address,
        submitted_at=now,
    )

    # 5. INSERT. If two requests raced past step 3, the database index stops the second.
    db.add(bid)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        diag = getattr(e.orig, "diag", None)          # psycopg2 (requirements.txt) sets this
        if getattr(diag, "constraint_name", None) == "uq_bids_one_original_per_vendor":
            raise DuplicateBid("You already bid on this tender. Submit a revision instead (Day 4).")
        raise
    db.refresh(bid)
    return bid


def check_receipt(db: Session, bid_hash: str) -> dict:
    """Prove a receipt's bid is stored and untouched WITHOUT revealing the amount."""
    bid = db.scalar(select(Bid).where(Bid.bid_hash == bid_hash))
    if bid is None:
        raise ReceiptNotFound("No bid with this receipt.")

    # Decrypt INSIDE the server only to recompute the hash; the amount never leaves.
    try:
        amount = float(crypto.decrypt_amount(bid.bid_amount_encrypted))
        integrity_ok = crypto.verify_bid_hash(
            bid.tender_id, bid.vendor_id, amount, bid.submitted_at_iso(), bid.bid_hash)
    except ValueError:            # token edited -> Fernet refuses it
        integrity_ok = False

    superseded = db.scalar(select(exists().where(Bid.revision_of == bid.id)))
    return {
        "bid_id": bid.id,
        "tender_id": bid.tender_id,
        "submitted_at": bid.submitted_at_iso(),
        "integrity_ok": integrity_ok,
        "superseded": bool(superseded),
    }