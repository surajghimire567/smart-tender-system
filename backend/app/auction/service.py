# app/auction/service.py
# Day 3: submit a bid + check a receipt.
# Day 4: revise a bid (= INSERT a new row), revision history, current bids.
# Day 5: after the deadline, decrypt the current bids and rank them (read-only)
# Business rules live here, OUT of the router, so the API, the self-tests and
# (later) pytest all call the same code. Nothing in this file UPDATEs or DELETEs a bid.
# Day 6: collusion rules 1 + 2 - flag a vendor pair that is repeatedly only 1-2% apart, and a vendor
#   that wins an unusually high share of its tenders (both read-only); save both rules' flags
#   in collusion_flags (insert-only).
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from app.auction import collusion
from app.auction.models import Bid, CollusionFlag
from sqlalchemy.orm import Session, aliased

from app.auction import crypto, tender_rules
from app.auction.schemas import BidCreate, BidRevise
from app.audit.service import log_action as audit_log_action
from app.models import Award, Tender


class BidRejected(Exception):
    """Base class: every rejection carries the HTTP status the router should use."""
    status_code = 400


class TenderNotFound(BidRejected):
    status_code = 404


class TenderNotOpen(BidRejected):
    status_code = 409


class BidClosedError(TenderNotOpen):
    """P2 contract error: the tender stopped accepting bids."""


class TenderStillSealed(BidRejected):
    status_code = 409


class SealedError(TenderStillSealed):
    """P2 contract error: results are unavailable before the deadline."""


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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---- shared helpers (Day 3 code, moved here so revise_bid can reuse it) ----
def _check_tender_open(db: Session, tender_id: int, amount: Decimal, now: datetime) -> None:
    """Status, deadline and ceiling: the SAME rules for a first bid and a revision."""
    tender = tender_rules.get_tender(db, tender_id)
    if tender is None:
        raise TenderNotFound(f"Tender {tender_id} does not exist.")
    if tender.status != "published":
        raise BidClosedError(
            f"Tender {tender_id} is not open for bidding (status: {tender.status})."
        )
    if now >= _as_utc(tender.deadline):
        raise BidClosedError(
            f"Deadline passed at {tender.deadline.isoformat()}; late bids are rejected."
        )
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


# ---- Day 3 / P2 contract: submit an original bid or a revision. ----
def submit_bid(
    db: Session,
    tender: Tender,
    vendor_id: int,
    amount: Decimal,
    device_fingerprint: str | None,
    ip_address: str | None,
    supersedes_bid_id: int | None = None,
) -> dict:
    """Add one sealed bid row and leave commit/rollback to the caller."""
    now = datetime.now(timezone.utc)                 # ONE server-side time
    tender_id = int(tender.id)
    _check_tender_open(db, tender_id, Decimal(amount), now)

    if supersedes_bid_id is not None:
        superseded = db.get(Bid, supersedes_bid_id)
        if superseded is None or superseded.tender_id != tender_id:
            raise BidNotFound(f"Bid {supersedes_bid_id} does not exist for this tender.")
        if superseded.vendor_id != vendor_id:
            raise NotYourBid("You can only revise your own bid.")
        latest = _latest_id(db, superseded.id)
        if latest != superseded.id:
            raise NotLatestBid(
                f"Bid {superseded.id} was already revised. Revise your latest bid: {latest}."
            )

    bid = _seal(
        tender_id,
        vendor_id,
        Decimal(amount),
        now,
        ip_address=ip_address,
        device_fingerprint=device_fingerprint,
        revision_of=supersedes_bid_id,
    )
    db.add(bid)
    db.flush()                            # populate the receipt ID; caller owns transaction
    return {
        "bid_id": bid.id,
        "tender_id": bid.tender_id,
        "vendor_id": bid.vendor_id,
        "bid_hash": bid.bid_hash,
        "submitted_at": bid.submitted_at,
        "supersedes_bid_id": bid.revision_of,
    }


def submit_bid_legacy(
    db: Session,
    data: BidCreate,
    *,
    ip_address: str | None,
    device_fingerprint: str | None,
) -> Bid:
    """Compatibility adapter for the standalone auction route, which commits itself."""
    tender = db.get(Tender, data.tender_id)
    if tender is None:
        raise TenderNotFound(f"Tender {data.tender_id} does not exist.")
    try:
        receipt = submit_bid(
            db,
            tender,
            data.vendor_id,
            data.amount,
            device_fingerprint,
            ip_address,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _constraint(exc) == "uq_bids_one_original_per_vendor":
            raise DuplicateBid(DUPLICATE_MSG) from exc
        raise
    bid = db.get(Bid, receipt["bid_id"])
    assert bid is not None
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
    _check_tender_open(db, old.tender_id, data.amount, now)

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


def _bid_receipt(bid: Bid) -> dict:
    return {
        "bid_id": bid.id,
        "tender_id": bid.tender_id,
        "vendor_id": bid.vendor_id,
        "bid_hash": bid.bid_hash,
        "submitted_at": bid.submitted_at,
        "supersedes_bid_id": bid.revision_of,
    }


def get_current_bid(db: Session, tender_id: int, vendor_id: int) -> dict | None:
    """Return the vendor's latest bid for a tender, without revealing its amount."""
    newer = aliased(Bid)
    bid = db.scalar(
        select(Bid)
        .where(
            Bid.tender_id == tender_id,
            Bid.vendor_id == vendor_id,
            ~exists().where(newer.revision_of == Bid.id),
        )
        .order_by(Bid.id.desc())
        .limit(1)
    )
    return None if bid is None else _bid_receipt(bid)


def get_my_bids(db: Session, vendor_id: int) -> list[dict]:
    """Return this vendor's bid history with tender labels and current-row markers."""
    newer = aliased(Bid)
    is_current = ~exists().where(newer.revision_of == Bid.id)
    rows = db.execute(
        select(Bid, Tender.title, Tender.status, is_current.label("is_current"))
        .join(Tender, Tender.id == Bid.tender_id)
        .where(Bid.vendor_id == vendor_id)
        .order_by(Bid.submitted_at.desc(), Bid.id.desc())
    ).all()
    return [
        {
            "bid_id": bid.id,
            "tender_id": bid.tender_id,
            "tender_title": title,
            "tender_status": tender_status,
            "bid_hash": bid.bid_hash,
            "submitted_at": bid.submitted_at,
            "is_current": bool(current),
            "supersedes_bid_id": bid.revision_of,
        }
        for bid, title, tender_status, current in rows
    ]

# ---- Day 5: open the bids after the deadline and rank them (L1) ----
EXCLUDE_TOKEN = "token cannot be decrypted (invalid or tampered)"
EXCLUDE_HASH = "receipt hash does not match the decrypted amount"
EXCLUDE_LATE = "submitted after the tender closed"
EXCLUDE_CEILING = "above the ceiling price"
CENT = Decimal("0.01")


def _check_tender_closed(db: Session, tender_id: int, now: datetime) -> tender_rules.TenderWindow:
    """The mirror of _check_tender_open: ranking waits until close or the deadline."""
    tender = tender_rules.get_tender(db, tender_id)
    if tender is None:
        raise TenderNotFound(f"Tender {tender_id} does not exist.")
    if tender.status == "draft":
        raise TenderNotOpen(f"Tender {tender_id} was never published; there are no bids to open.")
    opening_time = _as_utc(tender.closed_at or tender.deadline)
    if now < opening_time:
        raise SealedError(
            f"Bids stay sealed until the tender opening time ({opening_time.isoformat()}). "
            "Ranking opens after it.")
    return tender


def _open_bid(bid: Bid, tender: tender_rules.TenderWindow) -> tuple[Decimal | None, str | None]:
    """Decrypt ONE bid and re-check it. Returns (amount, None) or (None, reason)."""
    try:
        amount = crypto.decrypt_amount(bid.bid_amount_encrypted)        # L1
    except ValueError:
        return None, EXCLUDE_TOKEN
    if not crypto.verify_bid_hash(bid.tender_id, bid.vendor_id, amount,
                                  bid.submitted_at_iso(), bid.bid_hash):  # L2
        return None, EXCLUDE_HASH
    submitted_at = _as_utc(bid.submitted_at)
    closed_at = _as_utc(tender.closed_at) if tender.closed_at is not None else None
    deadline = _as_utc(tender.deadline)
    if closed_at is not None and closed_at < deadline:
        late = submitted_at > closed_at
    else:
        late = submitted_at >= (closed_at or deadline)
    if late:
        return None, EXCLUDE_LATE
    if amount > tender.ceiling_price:           # only possible via a direct INSERT
        return None, EXCLUDE_CEILING
    return amount, None


def rank_bids(db: Session, tender_id: int, *, now: datetime | None = None) -> dict:
    """Decrypt ONLY the current bids, drop any that fail a check, sort lowest -> highest.
    Read-only: nothing is written, so the plain amounts exist only in this response."""
    now = now or datetime.now(timezone.utc)
    tender = _check_tender_closed(db, tender_id, now)

    current = current_bids(db, tender_id)
    opened, excluded = [], []
    for bid in current:
        amount, reason = _open_bid(bid, tender)
        if reason:
            excluded.append({"bid_id": bid.id, "vendor_id": bid.vendor_id,
                             "bid_hash": bid.bid_hash, "reason": reason})
        else:
            opened.append((amount, bid))

    # lowest amount first; equal amounts -> the one sealed EARLIER wins; then bid id
    opened.sort(key=lambda pair: (pair[0], pair[1].submitted_at, pair[1].id))

    ranking, previous = [], None
    for position, (amount, bid) in enumerate(opened, start=1):
        gap = None if previous is None else ((amount - previous) / previous * 100).quantize(CENT)
        ranking.append({
            "rank": position, "bid_id": bid.id, "vendor_id": bid.vendor_id,
            "amount": amount, "bid_hash": bid.bid_hash,
            "submitted_at": bid.submitted_at_iso(), "revision_of": bid.revision_of,
            "gap_pct": gap,
        })
        previous = amount

    return {
        "tender_id": tender.tender_id,
        "status": tender.status,
        "deadline": tender.deadline.isoformat(),
        "opened_at": now.isoformat(),
        "current_bids": len(current),
        "ranked": len(ranking),
        "lowest": ranking[0] if ranking else None,
        "ranking": ranking,
        "excluded": sorted(excluded, key=lambda x: x["bid_id"]),
    }

def get_vendor_result(db: Session, tender_id: int, vendor_id: int) -> dict | None:
    """Return a vendor's ranked result after close, or None when they have no valid bid."""
    tender = tender_rules.get_tender(db, tender_id)
    if tender is None or tender.status == "draft":
        return None

    now = datetime.now(timezone.utc)
    ranking = rank_bids(db, tender_id, now=now)["ranking"]
    my_bid = next((row for row in ranking if row["vendor_id"] == vendor_id), None)
    if my_bid is None:
        return None

    award = db.scalar(select(Award).where(Award.tender_id == tender_id))
    status = "closed" if tender.status == "published" else tender.status
    outcome = "pending"
    if status == "awarded" and award is not None:
        outcome = "won" if award.winning_bid_id == my_bid["bid_id"] else "lost"

    return {
        "tender_id": tender_id,
        "status": status,
        "my_rank": my_bid["rank"],
        "my_amount": my_bid["amount"],
        "total_bids": len(ranking),
        "outcome": outcome,
    }


# ---- Day 6: collusion rule 1 - repeated 1-2% undercutting between the same pair (L10) ----
def scan_undercutting(db: Session, *, min_repeats: int = collusion.MIN_REPEATS,
                      now: datetime | None = None) -> dict:
    """Rank every tender that may be opened, look at neighbouring bids, flag repeated pairs.
    Read-only. Each ranking goes through rank_bids(), so the deadline check (L1) cannot be skipped."""
    now = now or datetime.now(timezone.utc)
    scanned, events = [], []
    for tender_id in tender_rules.openable_tender_ids(db, now):
        ranking = rank_bids(db, tender_id, now=now)["ranking"]
        scanned.append(tender_id)
        events.extend(collusion.close_neighbours(tender_id, ranking))

    flagged = collusion.flag_repeated_pairs(events, min_repeats)
    return {
        "rule": "repeated_undercutting",
        "gap_min_pct": collusion.GAP_MIN, "gap_max_pct": collusion.GAP_MAX,
        "min_repeats": min_repeats,
        "scanned_at": now.isoformat(),
        "tenders_scanned": scanned,
        "close_gaps_found": len(events),
        "pairs_flagged": len(flagged),
        "flagged": flagged,
    }


# ---- Day 6: collusion rule 2 - one vendor wins an unusually high share of its tenders (L10) ----
def scan_win_share(db: Session, *, min_share: int = collusion.WIN_SHARE_MIN,
                   min_entered: int = collusion.MIN_ENTERED, now: datetime | None = None) -> dict:
    """Rank every tender that may be opened, count entries + wins per vendor, flag high win shares.
    Read-only. Like rule 1, every ranking goes through rank_bids(), so the deadline check (L1) holds."""
    now = now or datetime.now(timezone.utc)
    rankings = {
        tender_id: rank_bids(db, tender_id, now=now)["ranking"]
        for tender_id in tender_rules.openable_tender_ids(db, now)
    }
    records = collusion.win_records(rankings)
    flagged = collusion.flag_high_win_share(records, min_share, min_entered)
    return {
        "rule": collusion.RULE_WIN_SHARE,
        "min_share_pct": min_share, "min_entered": min_entered,
        "min_bidders": collusion.MIN_BIDDERS,
        "scanned_at": now.isoformat(),
        "tenders_scanned": sorted(rankings),
        "contested_tenders": [t for t in sorted(rankings) if len(rankings[t]) >= collusion.MIN_BIDDERS],
        "vendors_judged": sum(1 for r in records.values() if len(r["entered"]) >= min_entered),
        "vendors_flagged": len(flagged),
        "flagged": flagged,
    }


# ---- Day 6: save BOTH rules' flags into collusion_flags (insert-only, never twice) ----
FLAG_INDEXES = {"uq_flags_pair", "uq_flags_single"}


def _flag_saved(db: Session, row: dict) -> bool:
    """Is this exact flag (rule + tender + vendor/pair) already in the table?"""
    return bool(db.scalar(select(exists().where(
        CollusionFlag.rule == row["rule"],
        CollusionFlag.tender_id == row["tender_id"],
        CollusionFlag.vendor_id_a == row["vendor_id_a"],
        CollusionFlag.vendor_id_b.is_not_distinct_from(row["vendor_id_b"]),   # NULL-safe "="
    ))))


def run_collusion_scan(
    db: Session,
    *,
    now: datetime | None = None,
    actor_id: int | None = None,
    ip_address: str | None = None,
) -> dict:
    """Run rule 1 + rule 2 with the OFFICIAL thresholds and INSERT every flag not saved yet.
    Bids are only read. The only writes are NEW rows in collusion_flags."""
    now = now or datetime.now(timezone.utc)
    rule1 = scan_undercutting(db, now=now)            # rule 1: 1-2% apart in >= 3 tenders
    rule2 = scan_win_share(db, now=now)               # rule 2: won >= 75% of >= 3 contested tenders
    rows = collusion.flag_rows(rule1["flagged"], rule2["flagged"])

    saved, already = [], 0
    for row in rows:
        if _flag_saved(db, row):
            already += 1                              # an earlier run saved it
            continue
        flag = CollusionFlag(**row, flagged_at=now)
        try:
            with db.begin_nested():                   # SAVEPOINT: a race undoes only this INSERT
                db.add(flag)
        except IntegrityError as e:
            if _constraint(e) not in FLAG_INDEXES:
                raise
            already += 1                              # a parallel run saved it a moment ago
            continue
        saved.append(flag)
    audit_log_action(
        db,
        actor_id=actor_id,
        action="COLLUSION_SCAN",
        ip_address=ip_address,
        details={
            "tenders_scanned": len(rule1["tenders_scanned"]),
            "flags_found": len(rows),
            "new_flags": len(saved),
            "already_saved": already,
        },
    )
    db.commit()
    for flag in saved:
        db.refresh(flag)

    return {
        "scanned_at": now.isoformat(),
        "tenders_scanned": rule1["tenders_scanned"],
        "pairs_flagged": rule1["pairs_flagged"],
        "vendors_flagged": rule2["vendors_flagged"],
        "flags_found": len(rows),
        "new_flags": len(saved),
        "already_saved": already,
        "saved": saved,
    }


def list_flags(db: Session, *, tender_id: int | None = None, vendor_id: int | None = None,
               rule: str | None = None) -> list[CollusionFlag]:
    """Saved flags, newest first. vendor_id matches either side of a pair."""
    query = select(CollusionFlag).order_by(CollusionFlag.id.desc())
    if tender_id is not None:
        query = query.where(CollusionFlag.tender_id == tender_id)
    if vendor_id is not None:
        query = query.where(or_(CollusionFlag.vendor_id_a == vendor_id,
                                CollusionFlag.vendor_id_b == vendor_id))
    if rule is not None:
        query = query.where(CollusionFlag.rule == rule)
    return list(db.scalars(query).all())
