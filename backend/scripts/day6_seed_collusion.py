# scripts/day6_seed_collusion.py
# Run from backend/:  python -m scripts.day6_seed_collusion
# Requires real closed tender rows with IDs 9995 through 9990 in the tenders table.
# DEMO ONLY. Rule 1: bids on closed tenders 9995, 9994 and 9993 so that vendors 501 and 503 are
# only 1-2% apart in every one of them (9996 from Day 5 already has them 1.06% apart).
# Vendors 502 and 504 are a decoy pair: close ONCE, which is normal competition.
# Rule 2: closed tenders 9992, 9991 and 9990. Vendor 505 wins all three, always exactly 3% under
# vendor 506 - too far apart for rule 1 (1-2%), but rule 2 (win share) catches it.
# Safe to run again: a vendor that already bid in a tender is skipped.
from datetime import timedelta

from sqlalchemy import exists, select

from app.auction.crypto import encrypt_amount, make_bid_hash
from app.auction.models import Bid
from app.auction.tender_rules import get_tender
from app.database import SessionLocal

# tender -> [(vendor, amount), ...]; sealed 180, 150, 120 ... minutes before the deadline
DEMO = {
    # rule 1 demo
    9995: [(501, "100000.00"), (503, "101500.00"), (502, "125000.00"), (504, "130000.00")],
    9994: [(503, "87000.00"), (501, "88200.00"), (502, "95000.00"), (504, "96400.00")],
    9993: [(501, "150000.00"), (503, "152700.00"), (504, "170000.00")],
    # rule 2 demo: 505 always wins, always 3.00% under 506
    9992: [(505, "120000.00"), (506, "123600.00"), (507, "140000.00")],
    9991: [(505, "95000.00"), (506, "97850.00"), (507, "110000.00")],
    9990: [(505, "60000.00"), (506, "61800.00"), (507, "70000.00")],
}


def seal(tender, vendor, amount, minutes, deadline):
    at = deadline - timedelta(minutes=minutes)
    return Bid(tender_id=tender, vendor_id=vendor,
               bid_amount_encrypted=encrypt_amount(amount),
               bid_hash=make_bid_hash(tender, vendor, amount, at.isoformat()),
               revision_of=None, submitted_at=at)


with SessionLocal() as db:
    for tender, bids in DEMO.items():
        window = get_tender(db, tender)
        if window is None:
            raise SystemExit(f"Tender {tender} is not present in the tenders table.")
        for slot, (vendor, amount) in enumerate(bids):
            if db.scalar(select(exists().where(Bid.tender_id == tender, Bid.vendor_id == vendor))):
                print(f"tender {tender} vendor {vendor}: already seeded, skipped")
                continue
            bid = seal(tender, vendor, amount, 180 - 30 * slot, window.deadline)
            db.add(bid)
            db.commit()                      # one INSERT per bid; the lock allows INSERT
            print(f"tender {tender} vendor {vendor}: bid sealed, id {bid.id}")

print("Done. In /docs: GET /auction/collusion/undercutting, GET /auction/collusion/win-share, then POST /auction/collusion/scan.")
