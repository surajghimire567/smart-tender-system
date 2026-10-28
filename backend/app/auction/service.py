# app/auction/service.py
# Day 3: submit a bid + check a receipt.
# Day 4: revise a bid (= INSERT a new row), revision history, current bids.
# Business rules live here, OUT of the router, so the API, the self-tests and
# (later) pytest all call the same code. Nothing in this file UPDATEs or DELETEs a bid.
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.auction import crypto, tender_rules
from app.auction.models import Bid
from app.auction.schemas import BidCreate, BidRevise


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


# ---- Day 4 ----
class BidNotFound(BidRejected):
    status_code = 404


class NotYourBid(BidRejected):
    status_code = 403


class NotLatestBid(BidRejected):
    status_code = 409


DUPLICATE_MSG = "You already bid on this tender. Submit a revision instead."


# ---- shared helpers (Day 3 code, moved here so revise_bid can reuse it) ----
def _check_tender_open(tender_id: int, amount: Decimal, now: datetime) -> None:
    """Status, deadline and ceiling: the SAME rules for a first bid and a revision."""
    tender = tender_rules.get_tender(tender_id)
    if tender is None:
        raise TenderNotFound(f"Tender {tender_id} does not exist.")
    if tender.status != "published":
        raise TenderNotOpen(f"Tender {tender_id} is not open for bidding (status: {tender.status}).")
    if now >= tender.deadline:
        raise TenderNotOpen(f"Deadline passed at {tender.deadline.isoformat()}; late bids are rejected.")
    if amount > tender.ceiling_price:
        raise AboveCeiling(f"Bid is above the ceiling price of {tender.ceiling_price}.")


def _seal(tender_id: int, vendor_id: int, amount: Decimal, now: datetime, *,
          ip_address: str | None, device_fingerprint: str | None,
          revision_of: int | None = None) -> Bid:
    """Encrypt (L1) + hash (L2) into a NEW Bid object. float() = the type Day 1-3 used."""
    value = float(amount)
    return Bid(
        tender_id=tender_id,
        vendor_id=vendor_id,
        bid_amount_encrypted=crypto.encrypt_amount(value),                        # L1
        bid_hash=crypto.make_bid_hash(tender_id, vendor_id, value, now.isoformat()),  # L2
        device_fingerprint=device_fingerprint,                                    # L9 (Person 2)
        ip_address=ip_address,
        revision_of=revision_of,
        submitted_at=now,
    )


def _constraint(e: IntegrityError) -> str | None:
    """Name of the database constraint that stopped the INSERT (psycopg2 sets diag)."""
    diag = getattr(e.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _latest_id(db: Session, bid_id: int) -> int:
    """Follow revision_of forward until no newer row exists."""
    while True:
        newer = db.scalar(select(Bid.id).where(Bid.revision_of == bid_id))
        if newer is None:
            return bid_id
        bid_id = newer


# ---- Day 3: first bid ----
def submit_bid(db: Session, data: BidCreate, *, ip_address: str | None,
               device_fingerprint: str | None) -> Bid:
    """Check the rules, then encrypt (L1), hash (L2) and INSERT one new row."""
    now = datetime.now(timezone.utc)                 # ONE server-side time
    _check_tender_open(data.tender_id, data.amount, now)

    already = db.scalar(select(exists().where(
        Bid.tender_id == data.tender_id,
        Bid.vendor_id == data.vendor_id,
        Bid.revision_of.is_(None),
    )))
    if already:
        raise DuplicateBid(DUPLICATE_MSG)

    bid = _seal(data.tender_id, data.vendor_id, data.amount, now,
                ip_address=ip_address, device_fingerprint=device_fingerprint)
    db.add(bid)
    try:
        db.commit()
    except IntegrityError as e:          # two requests raced past the check above
        db.rollback()
        if _constraint(e) == "uq_bids_one_original_per_vendor":
            raise DuplicateBid(DUPLICATE_MSG)
        raise
    db.refresh(bid)
    return bid


# ---- Day 4: revise = INSERT a new row that points at the old one ----
def revise_bid(db: Session, old_bid_id: int, data: BidRevise, *, ip_address: str | None,
               device_fingerprint: str | None) -> Bid:
    now = datetime.now(timezone.utc)

    # 1. the bid being revised must exist
    old = db.get(Bid, old_bid_id)
    if old is None:
        raise BidNotFound(f"Bid {old_bid_id} does not exist.")

    # 2. only its own vendor may revise it (Day 8: vendor_id comes from the login token)
    if old.vendor_id != data.vendor_id:
        raise NotYourBid("You can only revise your own bid.")

    # 3. same deadline / status / ceiling rules as a first bid
    _check_tender_open(old.tender_id, data.amount, now)

    # 4. only the LATEST bid in the chain may be revised (history = one straight line)
    latest = _latest_id(db, old.id)
    if latest != old.id:
        raise NotLatestBid(f"Bid {old.id} was already revised. Revise your latest bid: {latest}.")

    # 5. seal and INSERT. tender_id + vendor_id are copied from the old row.
    bid = _seal(old.tender_id, old.vendor_id, data.amount, now, ip_address=ip_address,
                device_fingerprint=device_fingerprint, revision_of=old.id)
    db.add(bid)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        name = _constraint(e)
        if name == "uq_bids_revision_of":            # another request revised it first
            raise NotLatestBid(f"Bid {old.id} was just revised by another request. "
                               "Reload your history and revise the latest bid.")
        if name == "fk_bids_revision_same_owner":    # can't happen via step 2, DB double-checks
            raise NotYourBid("You can only revise your own bid.")
        raise
    db.refresh(bid)
    return bid


# ---- Day 3: receipt check ----
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


# ---- Day 4: history of one chain (receipts and times only) ----
def bid_history(db: Session, bid_id: int) -> dict:
    """Same answer from ANY id in the chain: walk back to the original, then forward."""
    bid = db.get(Bid, bid_id)
    if bid is None:
        raise BidNotFound(f"Bid {bid_id} does not exist.")

    while bid.revision_of is not None:                      # back to the original
        bid = db.get(Bid, bid.revision_of)
    chain = [bid]
    while True:                                             # forward to the newest
        newer = db.scalar(select(Bid).where(Bid.revision_of == chain[-1].id))
        if newer is None:
            break
        chain.append(newer)

    return {
        "tender_id": chain[0].tender_id,
        "vendor_id": chain[0].vendor_id,
        "original_bid_id": chain[0].id,
        "current_bid_id": chain[-1].id,
        "revisions": len(chain) - 1,
        "history": [
            {"bid_id": b.id, "bid_hash": b.bid_hash, "submitted_at": b.submitted_at_iso(),
             "revision_of": b.revision_of, "is_current": b is chain[-1]}
            for b in chain
        ],
    }


# ---- Day 4: the bids that count (Day 5 decrypts and ranks only these) ----
def current_bids(db: Session, tender_id: int) -> list[Bid]:
    """Rows no other row points at = the newest bid of each vendor."""
    newer = aliased(Bid)
    query = (
        select(Bid)
        .where(Bid.tender_id == tender_id)
        .where(~exists().where(newer.revision_of == Bid.id))
        .order_by(Bid.vendor_id)
    )
    return list(db.execute(query).scalars().all())