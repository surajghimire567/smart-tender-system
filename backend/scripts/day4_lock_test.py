# scripts/day4_lock_test.py
# Run from backend/:  python -m scripts.day4_lock_test
# Part A: the database refuses every insider edit (UPDATE / DELETE / TRUNCATE).
# Part B: the RIGHT way to change a bid: a revision = a new row + a new receipt.
# Any failed check raises AssertionError, so it can never end with "passed" by mistake.
import random
import threading
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.auction import service
from app.auction.crypto import decrypt_amount, encrypt_amount, make_bid_hash, verify_bid_hash
from app.auction.db_lock import lock_status
from app.auction.models import Bid, BidLockedError
from app.auction.schemas import BidRevise
from app.database import SessionLocal, engine
from app.main import app

client = TestClient(app)
TENDER = 9999                         # open demo tender (tender_rules.py)
LATE_TENDER = 9998                    # deadline in 2020
VENDOR = random.randint(1000, 999999)
HEADERS = {"X-Device-Fingerprint": "day4-test-laptop"}


def expect(label, response, status):
    assert response.status_code == status, (
        f"{label}: expected {status}, got {response.status_code} {response.text}")
    print(f"[OK] {label} -> {status}")


def no_amount(response):
    assert "amount" not in response.text, "a response leaked an amount field!"


def revise(bid_id, amount, vendor_id=VENDOR, **extra):
    return client.post(f"/auction/bids/{bid_id}/revisions",
                       json={"vendor_id": vendor_id, "amount": amount, **extra}, headers=HEADERS)


def rows(**where):
    with SessionLocal() as db:
        q = select(func.count()).select_from(Bid)
        for k, v in where.items():
            q = q.where(getattr(Bid, k) == v)
        return db.scalar(q)


# ---- 0. the lock must be installed AND enabled before we attack anything ----
with engine.connect() as conn:
    status = lock_status(conn)
assert all(s == "ON" for s in status.values()), (
    f"lock is not active: {status} -> run python -m scripts.create_tables first")
print("[OK] both triggers installed and enabled:", ", ".join(status))

# ---- setup: a first bid + one revision through the API ----
r = client.post("/auction/bids", json={"tender_id": TENDER, "vendor_id": VENDOR,
                                       "amount": "125000.50"}, headers=HEADERS)
expect("first bid", r, 201)
original = r.json()
assert original["revision_of"] is None
r1 = revise(original["bid_id"], "123000.00")
expect("revision 1", r1, 201)
rev1 = r1.json()
total_before = rows()

# =============== PART A: the insider (313-contract case) =================
ATTACKS = [
    ("UPDATE amount token", "UPDATE bids SET bid_amount_encrypted = :tok WHERE id = :orig"),
    ("UPDATE receipt hash", "UPDATE bids SET bid_hash = repeat('0', 64) WHERE id = :orig"),
    ("hide a revision link", "UPDATE bids SET revision_of = NULL WHERE id = :rev"),
    ("DELETE one bid", "DELETE FROM bids WHERE id = :rev"),
    ("DELETE every bid", "DELETE FROM bids"),
    ("TRUNCATE the table", "TRUNCATE bids"),
]
params = {"tok": encrypt_amount(1), "orig": original["bid_id"], "rev": rev1["bid_id"]}
for label, sql in ATTACKS:
    with SessionLocal() as db:
        try:
            db.execute(text(sql), params)
            db.commit()
        except IntegrityError as e:              # 23xxx class -> IntegrityError
            db.rollback()
            assert e.orig.pgcode == "23001", f"{label}: wrong error {e.orig.pgcode}"
            assert "insert-only" in str(e.orig), f"{label}: unexpected message {e.orig}"
            print(f"[OK] L2 DB blocked: {label:<22} -> SQLSTATE 23001")
        else:
            raise AssertionError(f"{label} was ALLOWED by the database!")

# Layer 1 still answers first for our own ORM code
with SessionLocal() as db:
    bid = db.get(Bid, original["bid_id"])
    try:
        bid.bid_amount_encrypted = encrypt_amount(1)
        db.commit()
    except BidLockedError:
        db.rollback()
        print("[OK] L1 ORM guard still blocks edits before any SQL is sent")
    else:
        raise AssertionError("ORM update was allowed")

# after all attacks: nothing changed
assert rows() == total_before, "a row disappeared!"
with SessionLocal() as db:
    stored = db.get(Bid, original["bid_id"])
    assert decrypt_amount(stored.bid_amount_encrypted) == Decimal("125000.50")
    assert stored.bid_hash == original["bid_hash"]
    assert db.get(Bid, rev1["bid_id"]).revision_of == original["bid_id"]
    assert service.check_receipt(db, original["bid_hash"])["integrity_ok"] is True
print("[OK] original bid still decrypts, verifies and keeps its revision link")

# =============== PART B: revisions done the right way ====================
r2 = revise(rev1["bid_id"], "121500.00")
expect("revision 2", r2, 201)
rev2 = r2.json()
no_amount(r1); no_amount(r2)
assert rev1["revision_of"] == original["bid_id"] and rev2["revision_of"] == rev1["bid_id"]
receipts = {original["bid_hash"], rev1["bid_hash"], rev2["bid_hash"]}
assert len(receipts) == 3, "two bids share a receipt!"
assert verify_bid_hash(TENDER, VENDOR, 121500.00, rev2["submitted_at"], rev2["bid_hash"])
assert not verify_bid_hash(TENDER, VENDOR, 125000.50, rev2["submitted_at"], rev2["bid_hash"])
print("[OK] every revision has its own receipt for its own amount")

# history: the same answer from ANY id in the chain, oldest -> newest
answers = []
for start in (original["bid_id"], rev1["bid_id"], rev2["bid_id"]):
    h = client.get(f"/auction/bids/{start}/history")
    expect(f"history from bid {start}", h, 200)
    no_amount(h)
    answers.append(h.json())
assert answers[0] == answers[1] == answers[2]
hist = answers[0]
assert [x["bid_id"] for x in hist["history"]] == [original["bid_id"], rev1["bid_id"], rev2["bid_id"]]
assert [x["is_current"] for x in hist["history"]] == [False, False, True]
assert hist["revisions"] == 2 and hist["current_bid_id"] == rev2["bid_id"]
print("[OK] history: 3 rows, oldest -> newest, only the newest is current")

# receipts: old ones still valid but superseded
for receipt, superseded in [(original, True), (rev1, True), (rev2, False)]:
    c = client.get(f"/auction/receipts/{receipt['bid_hash']}").json()
    assert c["integrity_ok"] is True and c["superseded"] is superseded
print("[OK] old receipts still verify and say superseded=True; newest says False")

# current_bids: exactly one row per vendor = the newest
with SessionLocal() as db:
    current = [b for b in service.current_bids(db, TENDER) if b.vendor_id == VENDOR]
assert [b.id for b in current] == [rev2["bid_id"]]
print("[OK] current_bids() returns only the latest revision (input for Day 5)")

# ---- bad revisions: each MUST be refused, and nothing may be saved ----
mine = rows(vendor_id=VENDOR)
other = VENDOR + 1
expect("revise an OLD bid (already revised)", revise(original["bid_id"], "120000"), 409)
expect("revise someone else's bid", revise(rev2["bid_id"], "120000", vendor_id=other), 403)
expect("revise a bid that doesn't exist", revise(999999999, "120000"), 404)
expect("revise bid id 0", revise(0, "120000"), 422)
expect("revision above ceiling", revise(rev2["bid_id"], "250000"), 422)
for bad in ["0", "-5", "100.123", "abc", None]:
    expect(f"invalid amount {bad!r}", revise(rev2["bid_id"], bad), 422)
expect("sneak in another tender_id", revise(rev2["bid_id"], "120000", tender_id=9997), 422)

# a bid on the late tender (inserted directly: the API would refuse it today)
late_vendor = VENDOR + 3
with SessionLocal() as db:
    now = datetime.now(timezone.utc)
    late = Bid(tender_id=LATE_TENDER, vendor_id=late_vendor,
               bid_amount_encrypted=encrypt_amount(100000.0),
               bid_hash=make_bid_hash(LATE_TENDER, late_vendor, 100000.0, now.isoformat()),
               submitted_at=now)
    db.add(late)
    db.commit()
    late_id = late.id
expect("revise after the deadline", revise(late_id, "90000", vendor_id=late_vendor), 409)
assert rows(vendor_id=VENDOR) == mine and rows(vendor_id=late_vendor) == 1
assert rows(vendor_id=other) == 0
print("[OK] nothing was saved for any rejected revision")

# ---- no route can edit or delete a bid ----
for route in app.routes:
    if getattr(route, "path", "").startswith("/auction/bids"):
        assert not ({"PUT", "PATCH", "DELETE"} & route.methods), f"{route.path} {route.methods}"
print("[OK] no PUT / PATCH / DELETE route exists for bids")

# ---- race: two revisions of the SAME bid at the same moment ----
racer = VENDOR + 2
r = client.post("/auction/bids", json={"tender_id": TENDER, "vendor_id": racer,
                                       "amount": "150000"})
expect("racer's first bid", r, 201)
race_bid = r.json()["bid_id"]
barrier = threading.Barrier(2)
results = []


def race(amount):
    with SessionLocal() as db:
        barrier.wait()                 # both threads start at the same moment
        try:
            service.revise_bid(db, race_bid, BidRevise(vendor_id=racer, amount=amount),
                               ip_address="127.0.0.1", device_fingerprint=None)
            results.append("saved")
        except service.NotLatestBid:
            results.append("refused")


threads = [threading.Thread(target=race, args=(a,)) for a in ("149000", "148000")]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert sorted(results) == ["refused", "saved"], f"race result: {results}"
assert rows(vendor_id=racer) == 2       # original + exactly ONE revision
print("[OK] two simultaneous revisions -> exactly one saved, one refused")

print("\nDay 4 lock + revision checks passed.")