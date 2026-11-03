# scripts/day5_seed_closed.py
# Run from backend/:  python -m scripts.day5_seed_closed
# DEMO ONLY: puts 4 fixed vendors' bids on closed tender 9996 so you can try the
# ranking in /docs. Safe to run again: vendors that already bid are skipped.
from datetime import timedelta

from sqlalchemy import exists, select

from app.auction.crypto import encrypt_amount, make_bid_hash
from app.auction.models import Bid
from app.auction.tender_rules import get_tender
from app.database import SessionLocal

TENDER = 9996
DEADLINE = get_tender(TENDER).deadline
# vendor -> list of (amount, minutes before the deadline); 2nd item = a revision
DEMO = {
    501: [("158000.00", 300), ("141500.00", 90)],
    502: [("145200.00", 240)],
    503: [("143000.00", 200)],
    504: [("189999.99", 150)],
}


def seal(vendor, amount, minutes, revision_of):
    at = DEADLINE - timedelta(minutes=minutes)
    return Bid(tender_id=TENDER, vendor_id=vendor,
               bid_amount_encrypted=encrypt_amount(amount),
               bid_hash=make_bid_hash(TENDER, vendor, amount, at.isoformat()),
               revision_of=revision_of, submitted_at=at)


with SessionLocal() as db:
    for vendor, bids in DEMO.items():
        if db.scalar(select(exists().where(Bid.tender_id == TENDER, Bid.vendor_id == vendor))):
            print(f"vendor {vendor}: already seeded, skipped")
            continue
        previous = None
        for amount, minutes in bids:
            bid = seal(vendor, amount, minutes, previous)
            db.add(bid)
            db.commit()                      # one INSERT per bid; the lock allows INSERT
            previous = bid.id
        print(f"vendor {vendor}: {len(bids)} bid(s) sealed, latest id {previous}")

print(f"Done. Open GET /auction/tenders/{TENDER}/ranking in /docs.")