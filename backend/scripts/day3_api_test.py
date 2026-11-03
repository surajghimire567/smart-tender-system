# scripts/day3_api_test.py
# Run from backend/:  python -m scripts.day3_api_test
# Calls the REAL FastAPI app (no server needed) and checks every Day 3 rule.
# Any failed check raises AssertionError, so it can never end with "passed" by mistake.
import random
import threading
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.auction import service
from app.auction.crypto import decrypt_amount, encrypt_amount, verify_bid_hash
from app.auction.models import Bid
from app.auction.schemas import BidCreate
from app.database import SessionLocal
from app.main import app

client = TestClient(app)
TENDER = 9999                       # open demo tender (tender_rules.py)
VENDOR = random.randint(1000, 999999)
AMOUNT = "125000.50"                # sent as a string -> exact Decimal, no float rounding


def post_bid(**overrides):
    body = {"tender_id": TENDER, "vendor_id": VENDOR, "amount": AMOUNT}
    body.update(overrides)
    return client.post("/auction/bids", json=body,
                       headers={"X-Device-Fingerprint": "day3-test-laptop"})


def expect(label, response, status):
    assert response.status_code == status, (
        f"{label}: expected {status}, got {response.status_code} {response.text}")
    print(f"[OK] {label} -> {status}")


def rows_for(vendor_id):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Bid).where(Bid.vendor_id == vendor_id))


# ---- 1. a valid bid ----
r = post_bid()
expect("valid bid accepted", r, 201)
receipt = r.json()
assert len(receipt["bid_hash"]) == 64, "receipt is not a SHA-256 hex string"
assert receipt["submitted_at"].endswith("+00:00"), "receipt time is not UTC"
assert "125000" not in r.text and "amount" not in receipt, "response leaked the amount!"
print(f"     receipt={receipt['bid_hash'][:12]}...  bid_id={receipt['bid_id']}")

# ---- 2. L1: the raw table holds only a token ----
with SessionLocal() as db:
    row = db.execute(text(
        "SELECT bid_amount_encrypted, ip_address, device_fingerprint FROM bids WHERE id = :i"),
        {"i": receipt["bid_id"]}).one()
assert "125000" not in row.bid_amount_encrypted, "plain amount stored in the database!"
assert decrypt_amount(row.bid_amount_encrypted) == Decimal(AMOUNT)
assert row.device_fingerprint == "day3-test-laptop" and row.ip_address
print("[OK] L1 DB holds only a token:", row.bid_amount_encrypted[:25], "...")

# ---- 3. L2: the VENDOR can check the receipt with what they already know ----
assert verify_bid_hash(TENDER, VENDOR, float(AMOUNT), receipt["submitted_at"], receipt["bid_hash"])
assert not verify_bid_hash(TENDER, VENDOR, 120000.00, receipt["submitted_at"], receipt["bid_hash"])
print("[OK] L2 receipt matches the amount sent, and NOT any other amount")

# ---- 4. receipt lookup: proves integrity, shows no amount ----
r = client.get(f"/auction/receipts/{receipt['bid_hash']}")
expect("receipt lookup", r, 200)
assert r.json()["integrity_ok"] is True and r.json()["superseded"] is False
assert "125000" not in r.text and "amount" not in r.json()
r = client.get(f"/auction/tenders/{TENDER}/sealed-bids")
assert any(b["id"] == receipt["bid_id"] for b in r.json()) and "125000" not in r.text
print("[OK] receipt + sealed-bids show the bid, never the amount")

# ---- 5. bad requests: each MUST be refused, and nothing may be saved ----
expect("second bid, same vendor + tender", post_bid(amount="119000"), 409)
expect("tender past its deadline (9998)", post_bid(tender_id=9998), 409)
expect("tender still a draft (9997)", post_bid(tender_id=9997), 409)
expect("tender that doesn't exist", post_bid(tender_id=123456), 404)
expect("above ceiling price", post_bid(vendor_id=VENDOR + 1, amount="250000"), 422)
for bad in ["0", "-5", "100.123", "abc", None]:
    expect(f"invalid amount {bad!r}", post_bid(vendor_id=VENDOR + 1, amount=bad), 422)
expect("client-chosen submitted_at",
       post_bid(vendor_id=VENDOR + 1, submitted_at="2020-01-01T00:00:00+00:00"), 422)
expect("client-chosen bid_hash", post_bid(vendor_id=VENDOR + 1, bid_hash="0" * 64), 422)
expect("unknown receipt", client.get("/auction/receipts/" + "0" * 64), 404)
expect("malformed receipt", client.get("/auction/receipts/not-a-hash"), 422)
assert rows_for(VENDOR) == 1 and rows_for(VENDOR + 1) == 0, "a rejected bid was saved!"
print("[OK] nothing was saved for any rejected request")

# ---- 6. race: the same vendor double-clicks "Submit" ----
racer = VENDOR + 2
barrier = threading.Barrier(2)
results = []


def race(amount):
    with SessionLocal() as db:
        barrier.wait()                 # both threads start at the same moment
        try:
            service.submit_bid(db, BidCreate(tender_id=TENDER, vendor_id=racer, amount=amount),
                               ip_address="127.0.0.1", device_fingerprint=None)
            results.append("saved")
        except service.DuplicateBid:
            results.append("duplicate")


threads = [threading.Thread(target=race, args=(a,)) for a in ("150000", "149000")]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert sorted(results) == ["duplicate", "saved"], f"race result: {results}"
assert rows_for(racer) == 1
print("[OK] two simultaneous bids -> exactly one saved, one refused")

# ---- 7. the 313-contract attack: an insider swaps the token in raw SQL ----
with SessionLocal() as db:
    try:
        db.execute(text("UPDATE bids SET bid_amount_encrypted = :t WHERE id = :i"),
                   {"t": encrypt_amount(1), "i": receipt["bid_id"]})
    except DBAPIError:                  # from Day 4 the trigger refuses this
        db.rollback()
        print("[OK] raw UPDATE blocked by the database trigger (Day 4+)")
    else:
        assert service.check_receipt(db, receipt["bid_hash"])["integrity_ok"] is False
        db.rollback()                   # undo the attack, nothing is committed
        print("[OK] tampered token detected: integrity_ok = False (change rolled back)")
with SessionLocal() as db:
    assert service.check_receipt(db, receipt["bid_hash"])["integrity_ok"] is True

print("\nDay 3 submit-bid checks passed.")