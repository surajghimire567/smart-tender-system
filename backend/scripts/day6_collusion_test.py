# scripts/day6_collusion_test.py
# Run from backend/:  python -m scripts.day6_collusion_test
# Part A: the rule itself, no database: window edges, neighbours only, pair order, repeat count.
# Part B: the scan on real bids: a pair that is close in 3 tenders is flagged, decoys are not.
# Part C: the scan is read-only, repeatable, shows no amount (L1) and never opens a sealed tender.
# Any failed check raises AssertionError, so it can never end with "passed" by mistake.
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auction import collusion, service, tender_rules
from app.auction.crypto import encrypt_amount, make_bid_hash
from app.auction.models import Bid
from app.auction.tender_rules import TenderWindow
from app.database import SessionLocal
from app.main import app

client = TestClient(app)
SCAN = "/auction/collusion/undercutting"
OPEN_TENDER, DRAFT_TENDER = 9999, 9997
DEADLINE = datetime(2025, 2, 1, tzinfo=timezone.utc)
BASE = random.randint(1000, 900000)          # fresh vendor ids for this run
TB = random.randint(tender_rules.TEST_TENDER_MIN, tender_rules.TEST_TENDER_MIN + 900_000_000)  # fresh tender ids
A, B, C, D, E = (BASE + i for i in range(5))
T1, T2, T3 = TB, TB + 1, TB + 2


def expect(label, response, status):
    assert response.status_code == status, (
        f"{label}: expected {status}, got {response.status_code} {response.text}")
    print(f"[OK] {label} -> {status}")
    return response


def total_rows():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Bid))


def insert(tender_id, vendor, amount, minutes_before_deadline):
    """Direct INSERT (allowed by the Day 4 lock) with a time BEFORE the tender's deadline."""
    at = tender_rules.get_tender(tender_id).deadline - timedelta(minutes=minutes_before_deadline)
    bid = Bid(tender_id=tender_id, vendor_id=vendor,
              bid_amount_encrypted=encrypt_amount(amount),
              bid_hash=make_bid_hash(tender_id, vendor, amount, at.isoformat()),
              revision_of=None, submitted_at=at)
    with SessionLocal() as db:
        db.add(bid)
        db.commit()
        return bid.id


def ranked(rank, vendor, gap):
    """A tiny ranking row with the same keys service.rank_bids() returns."""
    return {"rank": rank, "bid_id": 1000 + rank, "vendor_id": vendor,
            "gap_pct": None if gap is None else Decimal(gap)}


def events_for(*gaps):
    """Vendors 1, 2, 3 ... ranked in order; gaps[i] = gap between rank i+1 and rank i+2."""
    rows = [ranked(1, 1, None)] + [ranked(i + 2, i + 2, g) for i, g in enumerate(gaps)]
    return collusion.close_neighbours(7, rows)


def event(tender, lower, higher, gap="1.50"):
    return {"tender_id": tender, "lower_vendor_id": lower, "higher_vendor_id": higher,
            "lower_bid_id": 1, "higher_bid_id": 2, "gap_pct": Decimal(gap)}


def find_pair(data, x, y):
    lo, hi = sorted((x, y))
    return next((p for p in data["flagged"] if (p["vendor_a"], p["vendor_b"]) == (lo, hi)), None)


# =============== PART A: the rule, no database ===========================
assert [len(events_for(g)) for g in ("0.99", "1.00", "2.00", "2.01", "0.00")] == [0, 1, 1, 0, 0]
print("[OK] window edges: 0.99 no, 1.00 yes, 2.00 yes, 2.01 no, 0.00 (a tie) no")

# only NEIGHBOURS are compared: rank 1 and rank 3 are never paired with each other
ev = collusion.close_neighbours(7, [ranked(1, 1, None), ranked(2, 2, "5.00"), ranked(3, 3, "1.50")])
assert [(e["lower_vendor_id"], e["higher_vendor_id"]) for e in ev] == [(2, 3)]
print("[OK] only neighbouring ranks are compared")

assert collusion.close_neighbours(7, [ranked(1, 5, None), ranked(2, 5, "1.50")]) == []
print("[OK] a vendor is never paired with itself")

evs = [event(1, 10, 20), event(2, 20, 10), event(3, 10, 20)]       # cheaper vendor swaps
flagged = collusion.flag_repeated_pairs(evs, 3)
assert len(flagged) == 1 and (flagged[0]["vendor_a"], flagged[0]["vendor_b"]) == (10, 20)
assert flagged[0]["times"] == 3 and flagged[0]["tender_ids"] == [1, 2, 3]
assert (flagged[0]["a_cheaper_times"], flagged[0]["b_cheaper_times"]) == (2, 1)
assert collusion.flag_repeated_pairs(evs[:2], 3) == []             # twice is not "repeatedly"
assert len(collusion.flag_repeated_pairs(evs[:2], 2)) == 1         # unless you lower the bar
print("[OK] same pair whoever is cheaper; needs the threshold number of DIFFERENT tenders")

# =============== setup: 3 brand-new closed tenders with 13 sealed bids ===
for i, t in enumerate((T1, T2, T3)):
    tender_rules.DEMO_TENDERS[t] = TenderWindow(
        t, "closed", DEADLINE + timedelta(days=i), Decimal("200000.00"))
    assert tender_rules.get_tender(t) is not None, "get_tender() does not read DEMO_TENDERS"

# A and B are 1.50% / 2.00% / 1.50% apart (the cheaper vendor changes). C and D are only
# close in T1 (1.00%) and T2 (1.50%). E is far from everybody. No other neighbours are within 2%.
PLAN = {
    T1: [(A, "100000.00"), (B, "101500.00"), (C, "130000.00"), (D, "131300.00"), (E, "160000.00")],
    T2: [(B, "90000.00"), (A, "91800.00"), (C, "120000.00"), (D, "121800.00")],
    T3: [(A, "80000.00"), (B, "81200.00"), (E, "95000.00"), (C, "110000.00")],
}
for tender, bids in PLAN.items():
    for slot, (vendor, amount) in enumerate(bids):
        insert(tender, vendor, amount, 180 - 30 * slot)
rows_before = total_rows()
print(f"[OK] sealed 13 bids in 3 closed tenders {T1}..{T3} (vendors {A}..{E})")

# =============== PART B: the scan on real bids ===========================
r = expect("scan with the default threshold (3)", client.get(SCAN), 200)
data = r.json()
assert data["rule"] == "repeated_undercutting" and data["min_repeats"] == 3
assert {T1, T2, T3} <= set(data["tenders_scanned"])
assert OPEN_TENDER not in data["tenders_scanned"] and DRAFT_TENDER not in data["tenders_scanned"]
assert data["pairs_flagged"] == len(data["flagged"])
print("[OK] closed tenders are scanned; the open (2099) and draft tenders are not")

p = find_pair(data, A, B)
assert p is not None, "the pair that is close in 3 tenders was not flagged"
assert p["times"] == 3 and p["tender_ids"] == [T1, T2, T3]
assert (p["a_cheaper_times"], p["b_cheaper_times"]) == (2, 1)      # A cheaper in T1, T3; B in T2
assert Decimal(p["avg_gap_pct"]) == Decimal("1.67")
assert [Decimal(e["gap_pct"]) for e in p["events"]] == [Decimal("1.50"), Decimal("2.00"), Decimal("1.50")]
print(f"[OK] pair ({A}, {B}) flagged: 3 tenders, avg gap 1.67%, edge gap 2.00% counted")

assert find_pair(data, C, D) is None, "a pair that is close only twice was flagged at threshold 3"
assert all(E not in (x["vendor_a"], x["vendor_b"]) for x in data["flagged"])
print(f"[OK] pair ({C}, {D}) close in only 2 tenders -> NOT flagged at threshold 3; vendor {E} never flagged")

r = expect("scan with threshold 2", client.get(SCAN, params={"min_repeats": 2}), 200)
low = r.json()
cd = find_pair(low, C, D)
assert cd is not None and cd["times"] == 2 and cd["tender_ids"] == [T1, T2]
assert (cd["a_cheaper_times"], cd["b_cheaper_times"]) == (2, 0)
assert Decimal(cd["avg_gap_pct"]) == Decimal("1.25")               # 1.00 edge counted too
assert find_pair(low, A, B) is not None
print(f"[OK] threshold 2 flags ({C}, {D}) as well: edge gap 1.00% counted")

expect("threshold 1 is refused", client.get(SCAN, params={"min_repeats": 1}), 422)
expect("threshold 0 is refused", client.get(SCAN, params={"min_repeats": 0}), 422)

# =============== PART C: read-only, repeatable, no amounts, no sealed tenders
assert "amount" not in r.text and "amount" not in client.get(SCAN).text, "the scan leaked an amount!"
print("[OK] the scan output contains no amount (L1)")

again = client.get(SCAN).json()
assert again["flagged"] == data["flagged"] and again["tenders_scanned"] == data["tenders_scanned"]
assert total_rows() == rows_before, "the scan wrote to the bids table!"
print("[OK] same answer twice, and the scan wrote nothing (read-only)")

with SessionLocal() as db:      # before every deadline nothing may be opened, so nothing is scanned
    out = service.scan_undercutting(db, now=datetime(2000, 1, 1, tzinfo=timezone.utc))
assert out["tenders_scanned"] == [] and out["flagged"] == [] and out["close_gaps_found"] == 0
print("[OK] with the clock set before every deadline, no tender is opened (L1)")

print("\nDay 6 collusion checks passed.")