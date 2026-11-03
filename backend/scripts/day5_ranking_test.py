# scripts/day5_ranking_test.py
# Run from backend/:  python -m scripts.day5_ranking_test
# Part A: BEFORE the deadline the ranking route refuses and reveals nothing (L1).
# Part B: AFTER the deadline it decrypts only current bids and ranks them lowest -> highest.
# Part C: a bid that fails a check (tampered, late, above ceiling) is excluded, never revealed.
# Any failed check raises AssertionError, so it can never end with "passed" by mistake.
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auction import service, tender_rules
from app.auction.crypto import encrypt_amount, make_bid_hash
from app.auction.models import Bid
from app.database import SessionLocal
from app.main import app
from scripts.tender_test_fixtures import seed_test_tenders

client = TestClient(app)
TB = random.randint(tender_rules.TEST_TENDER_MIN, tender_rules.TEST_TENDER_MIN + 900_000_000)
OPEN_TENDER, LATE_TENDER, DRAFT_TENDER, CLOSED, UNKNOWN_TENDER = (TB + i for i in range(5))
DEADLINE = datetime.now(timezone.utc) - timedelta(days=1)
BASE = random.randint(1000, 900000)          # fresh vendor ids for this run
A, B, C, D, LATE, HIGH, BADHASH, BADTOKEN = (BASE + i for i in range(8))

with SessionLocal() as db:
    seed_test_tenders(db, [
        (OPEN_TENDER, "published", datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
        (LATE_TENDER, "published", DEADLINE, Decimal("200000.00")),
        (DRAFT_TENDER, "draft", datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
        (CLOSED, "closed", DEADLINE, Decimal("200000.00")),
    ])


def expect(label, response, status):
    assert response.status_code == status, (
        f"{label}: expected {status}, got {response.status_code} {response.text}")
    print(f"[OK] {label} -> {status}")
    return response


def total_rows():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Bid))


def insert(vendor, amount, minutes_before_deadline, revision_of=None, *,
           token=None, hash_amount=None):
    """Bids on a CLOSED tender can't go through the API any more, so insert them
    directly with a time BEFORE the deadline (a negative value = after it).
    INSERT is the one thing the Day 4 lock allows."""
    at = DEADLINE - timedelta(minutes=minutes_before_deadline)
    bid = Bid(
        tender_id=CLOSED, vendor_id=vendor,
        bid_amount_encrypted=token or encrypt_amount(amount),
        bid_hash=make_bid_hash(CLOSED, vendor, hash_amount or amount, at.isoformat()),
        revision_of=revision_of, submitted_at=at,
    )
    with SessionLocal() as db:
        db.add(bid)
        db.commit()
        return bid.id


# =============== PART A: sealed until the deadline =======================
r = expect("ranking an OPEN tender (deadline 2099)", client.get(f"/auction/tenders/{OPEN_TENDER}/ranking"), 409)
assert "sealed" in r.text and "amount" not in r.text and "ranking" not in r.json()
expect("ranking a DRAFT tender", client.get(f"/auction/tenders/{DRAFT_TENDER}/ranking"), 409)
expect("ranking a tender that doesn't exist", client.get(f"/auction/tenders/{UNKNOWN_TENDER}/ranking"), 404)
expect("ranking tender id 0", client.get("/auction/tenders/0/ranking"), 422)
with SessionLocal() as db:   # the service itself refuses too, not only the route
    try:
        service.rank_bids(db, OPEN_TENDER)
    except service.TenderStillSealed:
        print("[OK] service.rank_bids refuses before the deadline (L1)")
    else:
        raise AssertionError("open tender was ranked before its deadline!")
    # one second before the deadline = still sealed; at the deadline = open
    try:
        service.rank_bids(db, CLOSED, now=DEADLINE - timedelta(seconds=1))
        raise AssertionError("ranked 1 second before the deadline!")
    except service.TenderStillSealed:
        pass
    service.rank_bids(db, CLOSED, now=DEADLINE)
print("[OK] boundary: 1 s before deadline -> sealed, exactly at deadline -> open")

# =============== setup: bids sealed before the CLOSED tender's deadline ==
a_old = insert(A, "150000.00", 120)
a_new = insert(A, "120000.00", 60, revision_of=a_old)   # revision -> only THIS counts
c_id = insert(C, "125000.50", 90)
b_id = insert(B, "130000.00", 80)                      # tie with D, but sealed EARLIER
d_id = insert(D, "130000.00", 30)
late_id = insert(LATE, "100000.00", -5)                # 5 min AFTER the deadline
high_id = insert(HIGH, "250000.00", 50)                # above the 200000 ceiling
badhash_id = insert(BADHASH, "110000.00", 40, hash_amount="140000.00")   # hash for another amount
badtoken_id = insert(BADTOKEN, "1", 40, token="gAAAAA-this-is-not-a-real-fernet-token")
rows_before = total_rows()
print(f"[OK] inserted 9 test bids for tender {CLOSED} (vendors {A}..{BADTOKEN})")

# =============== PART B: open + rank =====================================
r = expect("ranking the CLOSED tender", client.get(f"/auction/tenders/{CLOSED}/ranking"), 200)
data = r.json()
ranking = data["ranking"]
assert data["tender_id"] == CLOSED and data["ranked"] == len(ranking)
assert data["current_bids"] == data["ranked"] + len(data["excluded"])

# whole list: ranks 1..n, amounts never go down, lowest = rank 1
amounts = [Decimal(x["amount"]) for x in ranking]
assert [x["rank"] for x in ranking] == list(range(1, len(ranking) + 1))
assert amounts == sorted(amounts), "ranking is not lowest -> highest!"
assert data["lowest"] == ranking[0]
print(f"[OK] {len(ranking)} bids ranked 1..n, lowest -> highest, lowest = rank 1")

# our vendors, in order: A (revised to 120000) < C < B = D (B sealed earlier)
mine = [x for x in ranking if x["vendor_id"] in (A, B, C, D)]
assert [x["vendor_id"] for x in mine] == [A, C, B, D], [x["vendor_id"] for x in mine]
assert [x["amount"] for x in mine] == ["120000.00", "125000.50", "130000.00", "130000.00"]
assert mine[0]["bid_id"] == a_new and mine[0]["revision_of"] == a_old
assert a_old not in {x["bid_id"] for x in ranking}, "a superseded bid was ranked!"
print("[OK] only the latest revision counts; tie -> the earlier sealed bid ranks first")

# gap_pct = % above the previous bid (input for Day 6 collusion rule)
assert ranking[0]["gap_pct"] is None
for prev, cur in zip(ranking, ranking[1:]):
    p, c = Decimal(prev["amount"]), Decimal(cur["amount"])
    assert Decimal(cur["gap_pct"]) == ((c - p) / p * 100).quantize(Decimal("0.01"))
print("[OK] gap_pct is correct for every pair")

# every ranked bid's receipt still verifies
for x in mine:
    check = client.get(f"/auction/receipts/{x['bid_hash']}").json()
    assert check["integrity_ok"] is True and check["superseded"] is False
print("[OK] every ranked bid's receipt still verifies")

# =============== PART C: excluded bids ===================================
reasons = {x["bid_id"]: x["reason"] for x in data["excluded"]}
assert reasons.get(late_id) == service.EXCLUDE_LATE
assert reasons.get(high_id) == service.EXCLUDE_CEILING
assert reasons.get(badhash_id) == service.EXCLUDE_HASH
assert reasons.get(badtoken_id) == service.EXCLUDE_TOKEN
ranked_vendors = {x["vendor_id"] for x in ranking}
assert not ranked_vendors & {LATE, HIGH, BADHASH, BADTOKEN}
assert all("amount" not in x for x in data["excluded"]), "an excluded bid leaked its amount!"
print("[OK] late / above-ceiling / bad-hash / bad-token bids excluded, amounts NOT shown")

# =============== read-only + repeatable ==================================
again = client.get(f"/auction/tenders/{CLOSED}/ranking").json()
assert again["ranking"] == ranking and again["excluded"] == data["excluded"]
assert total_rows() == rows_before, "ranking wrote to the bids table!"
print("[OK] same answer twice, and ranking wrote nothing (read-only)")

# the other routes still hide amounts, even for a closed tender
for path in (f"/auction/tenders/{CLOSED}/sealed-bids", f"/auction/bids/{a_new}/history"):
    assert "amount" not in client.get(path).text, f"{path} leaked an amount!"
print("[OK] sealed-bids and history still contain no amounts")

# a revision can't be submitted on a closed tender
r = client.post(f"/auction/bids/{a_new}/revisions", json={"vendor_id": A, "amount": "1000"})
expect("revise after the tender closed", r, 409)

print("\nDay 5 ranking checks passed.")
