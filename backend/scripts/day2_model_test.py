# scripts/day2_model_test.py
# Run from backend/:  python -m scripts.day2_model_test
# Proves the Bid table stores only encrypted data and refuses edits/deletes.
# Any failed check raises AssertionError, so the script can never end with
# "passed" after a guard failed.
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.auction.crypto import decrypt_amount, encrypt_amount, make_bid_hash, verify_bid_hash
from app.auction.models import Bid, BidLockedError
from app.database import SessionLocal

TENDER_ID = 9999
VENDOR_ID = random.randint(1000, 999999)   # random -> a fresh receipt every run
AMOUNT = 125000.50

db = SessionLocal()


def make_bid(amount, *, tender_id=TENDER_ID, vendor_id=VENDOR_ID, revision_of=None):
    """Build a Bid the way Day 3's route will: ONE time value feeds the row and the receipt."""
    ts = datetime.now(timezone.utc)
    return Bid(
        tender_id=tender_id,
        vendor_id=vendor_id,
        bid_amount_encrypted=encrypt_amount(amount),
        bid_hash=make_bid_hash(tender_id, vendor_id, amount, ts.isoformat()),
        revision_of=revision_of,
        submitted_at=ts,
    )


def expect_db_reject(label, bid, pgcode, constraint=None):
    """Insert must fail with this PostgreSQL error (23505 unique, 23514 check, 23503 foreign key)."""
    try:
        db.add(bid)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        assert e.orig.pgcode == pgcode, f"{label}: wrong error {e.orig.pgcode}"
        if constraint:
            assert e.orig.diag.constraint_name == constraint, (
                f"{label}: stopped by {e.orig.diag.constraint_name}, expected {constraint}"
            )
        print(f"[OK] DB rejected: {label}")
    else:
        raise AssertionError(f"{label} was accepted")


# ---- 1. insert a bid the way Day 3's route will ----
bid = make_bid(AMOUNT)
db.add(bid)
db.commit()
db.refresh(bid)
bid_id = bid.id
print(f"[OK] inserted bid id={bid_id}, receipt={bid.bid_hash[:12]}...")

# ---- 2. L1: what a person reading the raw table would see ----
raw = db.execute(
    text("SELECT bid_amount_encrypted FROM bids WHERE id = :i"), {"i": bid_id}
).scalar()
assert "125000" not in raw, "plain amount leaked into the database!"
assert decrypt_amount(raw) == Decimal("125000.50")
print("[OK] L1 DB holds only a token:", raw[:25], "...")

# ---- 3. L2: receipt still verifies after a round trip through PostgreSQL ----
assert verify_bid_hash(TENDER_ID, VENDOR_ID, AMOUNT, bid.submitted_at_iso(), bid.bid_hash)
print("[OK] L2 receipt verifies against the stored row")

# ---- 4. try to cheat three ways: each MUST be blocked ----
try:
    bid.bid_amount_encrypted = encrypt_amount(1)
    db.commit()
except BidLockedError as e:
    db.rollback()
    print("[OK] L2 update blocked ->", e)
else:
    raise AssertionError("update was allowed")

try:
    db.execute(update(Bid).where(Bid.id == bid_id).values(tender_id=1))
    db.commit()
except BidLockedError as e:
    db.rollback()
    print("[OK] L2 bulk update blocked ->", e)
else:
    raise AssertionError("bulk update was allowed")

try:
    db.delete(db.get(Bid, bid_id))
    db.commit()
except BidLockedError as e:
    db.rollback()
    print("[OK] L2 delete blocked ->", e)
else:
    raise AssertionError("delete was allowed")

# ---- 5. the RIGHT way to change a bid: a new row that points to the old one ----
revision = make_bid(120000, revision_of=bid_id)
db.add(revision)
db.commit()
db.refresh(revision)
print(f"[OK] revision saved as NEW row id={revision.id} (revision_of={revision.revision_of})")

# ---- 6. the original is untouched ----
original = db.execute(select(Bid).where(Bid.id == bid_id)).scalar_one()
assert decrypt_amount(original.bid_amount_encrypted) == Decimal("125000.50")
assert original.revision_of is None
chain = db.execute(
    select(Bid).where((Bid.id == bid_id) | (Bid.revision_of == bid_id))
).scalars().all()
assert len(chain) == 2   # the original + its one revision, both still there
print("[OK] original bid is unchanged")

# ---- 7. the database itself refuses bad rows (nothing here is saved) ----
expect_db_reject("duplicate receipt", Bid(
    tender_id=TENDER_ID, vendor_id=VENDOR_ID + 1, bid_amount_encrypted=encrypt_amount(5),
    bid_hash=bid.bid_hash, submitted_at=datetime.now(timezone.utc)), "23505")
expect_db_reject("receipt that is not 64 chars", Bid(
    tender_id=TENDER_ID, vendor_id=VENDOR_ID + 1, bid_amount_encrypted=encrypt_amount(5),
    bid_hash="abc", submitted_at=datetime.now(timezone.utc)), "23514", "ck_bids_hash_len")
# `revision` has not been revised yet, so only the same-owner rule can stop these two
expect_db_reject("revision of ANOTHER vendor's bid",
                 make_bid(1, vendor_id=VENDOR_ID + 1, revision_of=revision.id),
                 "23503", "fk_bids_revision_same_owner")
expect_db_reject("revision pointing at a DIFFERENT tender's bid",
                 make_bid(1, tender_id=TENDER_ID + 1, revision_of=revision.id),
                 "23503", "fk_bids_revision_same_owner")
expect_db_reject("second revision of an already-revised bid (fork)",
                 make_bid(1, revision_of=bid_id), "23505", "uq_bids_revision_of")

# ---- 8. receipts need a UTC time: reject anything else before it reaches the DB ----
for label, bad_time in [
    ("naive datetime (no timezone)", datetime(2026, 10, 18, 10, 0, 0)),
    ("non-UTC datetime (+05:45)", datetime.now(timezone(timedelta(hours=5, minutes=45)))),
]:
    try:
        Bid(tender_id=TENDER_ID, vendor_id=VENDOR_ID, bid_amount_encrypted="x",
            bid_hash="0" * 64, submitted_at=bad_time)
    except ValueError:
        print(f"[OK] rejected: {label}")
    else:
        raise AssertionError(f"{label} was accepted")

db.close()
print("\nDay 2 model checks passed.")