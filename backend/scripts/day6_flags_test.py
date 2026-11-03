# scripts/day6_flags_test.py
# Run from backend/:  python -m scripts.day6_flags_test
# Part A: rule 2 itself, no database: sole bidders, the 75% edge, too few tenders, exact test, rows.
# Part B: GET /auction/collusion/win-share on real bids: who is flagged, thresholds, 422s, read-only.
# Part C: POST /auction/collusion/scan saves both rules' flags ONCE; GET /auction/collusion/flags filters.
# Part D: collusion_flags is insert-only (ORM + trigger), no amounts, nothing saved before a deadline.
# Any failed check raises AssertionError, so it can never end with "passed" by mistake.
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.auction import collusion, tender_rules
from app.auction.crypto import encrypt_amount, make_bid_hash
from app.auction.models import Bid, CollusionFlag, FlagLockedError
from app.database import SessionLocal
from app.main import app
from scripts.tender_test_fixtures import seed_test_tenders

client = TestClient(app)
WIN, SCAN, FLAGS = "/auction/collusion/win-share", "/auction/collusion/scan", "/auction/collusion/flags"
DEADLINE = datetime(2024, 6, 1, tzinfo=timezone.utc)
BASE = random.randint(1000, 900000)          # fresh vendor ids for this run
TB = random.randint(tender_rules.TEST_TENDER_MIN, tender_rules.TEST_TENDER_MIN + 900_000_000)
W, X, Y, Z, V = (BASE + i for i in range(5))
T = [TB + i for i in range(9)]               # 9 brand-new closed tenders: T[0] .. T[8]
OPEN_TENDER, DRAFT_TENDER = TB + 9, TB + 10
MINE = set(T)


def expect(label, response, status):
    assert response.status_code == status, (
        f"{label}: expected {status}, got {response.status_code} {response.text}")
    print(f"[OK] {label} -> {status}")
    return response


def count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def insert(tender_id, vendor, amount, minutes_before_deadline):
    """Direct INSERT (allowed by the Day 4 lock) with a time BEFORE the tender's deadline."""
    with SessionLocal() as db:
        tender = tender_rules.get_tender(db, tender_id)
        assert tender is not None
        at = tender.deadline - timedelta(minutes=minutes_before_deadline)
        db.add(Bid(tender_id=tender_id, vendor_id=vendor,
                   bid_amount_encrypted=encrypt_amount(amount),
                   bid_hash=make_bid_hash(tender_id, vendor, amount, at.isoformat()),
                   revision_of=None, submitted_at=at))
        db.commit()


def rk(*vendors):
    """A tiny ranking with the one key rule 2 reads: vendor ids, rank 1 first."""
    return [{"rank": i + 1, "vendor_id": v} for i, v in enumerate(vendors)]


def find(data, vendor):
    return next((f for f in data["flagged"] if f["vendor_id"] == vendor), None)


def key(flag):
    return (flag["rule"], flag["tender_id"], flag["vendor_id_a"], flag["vendor_id_b"])


with SessionLocal() as db:
    if not db.scalar(text("SELECT to_regclass('collusion_flags') IS NOT NULL")):
        raise SystemExit("No collusion_flags table. Run: python -m scripts.create_tables")

# =============== PART A: rule 2, no database ==============================
rec = collusion.win_records({1: rk(10, 20), 2: rk(10, 30), 3: rk(20, 10), 4: rk(10, 20), 5: rk(30)})
assert rec[10] == {"entered": [1, 2, 3, 4], "won": [1, 2, 4]}
assert rec[30] == {"entered": [2], "won": []}, "a sole-bidder tender was counted"
print("[OK] entries + wins counted per vendor; a sole-bidder tender counts for nobody")

flags = collusion.flag_high_win_share(rec)
assert [f["vendor_id"] for f in flags] == [10] and flags[0]["win_share_pct"] == Decimal("75.00")
assert flags[0]["tender_ids_won"] == [1, 2, 4]
assert collusion.flag_high_win_share(rec, min_share=76) == []
print("[OK] 3 of 4 = 75.00% is flagged (the edge counts); at 76% it is not")

two = collusion.win_records({1: rk(40, 20), 2: rk(40, 20)})
assert collusion.flag_high_win_share(two) == []                      # 2 of 2, but only 2 tenders
assert collusion.flag_high_win_share(two, min_entered=2)[0]["win_share_pct"] == Decimal("100.00")
print("[OK] 2 wins out of 2 is not judged at min_entered 3, flagged at min_entered 2")

thirds = collusion.win_records({1: rk(50, 60), 2: rk(50, 60), 3: rk(60, 50)})
assert [f["vendor_id"] for f in collusion.flag_high_win_share(thirds, min_share=66)] == [50]
assert collusion.flag_high_win_share(thirds, min_share=67) == []
print("[OK] 2 of 3 = 66.67%: flagged at 66, not at 67 (exact whole-number test, no rounding)")

pair = {"vendor_a": 10, "vendor_b": 20, "times": 3, "events": [
    {"tender_id": 7, "lower_vendor_id": 20, "higher_vendor_id": 10,
     "lower_bid_id": 1, "higher_bid_id": 2, "gap_pct": Decimal("1.50")}]}
rows = collusion.flag_rows([pair], flags)
assert [key(r) for r in rows] == [("high_win_share", 1, 10, None), ("high_win_share", 2, 10, None),
                                  ("high_win_share", 4, 10, None), ("repeated_undercutting", 7, 10, 20)]
assert all("amount" not in r["flag_reason"] for r in rows)
print("[OK] flag rows: one per tender of evidence; pair sorted (a < b); one vendor -> vendor_id_b None")

# =============== setup: 9 brand-new closed tenders ========================
# W wins 3 of the 4 contested tenders it enters (exactly 75%), and X sits 1.50% next to W in
# three of them (cover bids -> rule 1 as well). Y wins two tenders ALONE (no competition) and
# 1 of 2 contested ones. V wins 2 of 2 (too few to judge at 3). Z never wins. Other gaps >= 10%.
PLAN = {
    T[0]: [(W, "100000.00"), (X, "101500.00"), (Y, "120000.00")],
    T[1]: [(W, "90000.00"), (Z, "99000.00")],
    T[2]: [(X, "80000.00"), (W, "81200.00"), (Z, "90000.00")],
    T[3]: [(W, "70000.00"), (X, "71050.00")],
    T[4]: [(Y, "50000.00")],                                  # sole bidder
    T[5]: [(Y, "60000.00")],                                  # sole bidder
    T[6]: [(Y, "40000.00"), (Z, "44000.00")],
    T[7]: [(V, "30000.00"), (Z, "33000.00")],
    T[8]: [(V, "20000.00"), (Z, "22000.00")],
}
with SessionLocal() as db:
    seed_test_tenders(db, [
        (t, "closed", DEADLINE + timedelta(days=i), Decimal("200000.00"))
        for i, t in enumerate(T)
    ] + [
        (OPEN_TENDER, "published", datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
        (DRAFT_TENDER, "draft", datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
    ])
for tender, bids in PLAN.items():
    for slot, (vendor, amount) in enumerate(bids):
        insert(tender, vendor, amount, 180 - 30 * slot)
bids_before, flags_before = count(Bid), count(CollusionFlag)
print(f"[OK] sealed {sum(map(len, PLAN.values()))} bids in 9 closed tenders {T[0]}..{T[-1]} "
      f"(vendors {W}..{V})")

# =============== PART B: GET win-share on real bids =======================
data = expect("win-share scan, default thresholds (75%, 3 tenders)", client.get(WIN), 200).json()
assert data["rule"] == "high_win_share" and (data["min_share_pct"], data["min_entered"]) == (75, 3)
assert MINE <= set(data["tenders_scanned"])
assert OPEN_TENDER not in data["tenders_scanned"] and DRAFT_TENDER not in data["tenders_scanned"]
assert {T[0], T[1], T[2], T[3], T[6], T[7], T[8]} <= set(data["contested_tenders"])
assert T[4] not in data["contested_tenders"] and T[5] not in data["contested_tenders"]
print("[OK] closed tenders scanned (open + draft are not); sole-bidder tenders are not contested")

w = find(data, W)
assert w is not None, "the vendor that won 3 of 4 contested tenders was not flagged"
assert (w["entered"], w["won"], Decimal(w["win_share_pct"])) == (4, 3, Decimal("75.00"))
assert w["tender_ids_won"] == [T[0], T[1], T[3]] and w["tender_ids_entered"] == T[:4]
assert all(find(data, v) is None for v in (X, Y, Z, V))
print(f"[OK] vendor {W} flagged: won 3 of 4 = 75.00%; {Y}'s two solo wins did not count")

assert find(client.get(WIN, params={"min_share": 76}).json(), W) is None
low = expect("win-share scan with min_entered 2", client.get(WIN, params={"min_entered": 2}), 200).json()
v = find(low, V)
assert v is not None and (v["entered"], v["won"], Decimal(v["win_share_pct"])) == (2, 2, Decimal("100.00"))
assert find(low, Y) is None                      # 1 of 2 contested = 50%
print(f"[OK] min_share 76 drops {W}; min_entered 2 flags {V} (2 of 2) but not {Y} (1 of 2)")
expect("min_share 49 is refused", client.get(WIN, params={"min_share": 49}), 422)
expect("min_entered 1 is refused", client.get(WIN, params={"min_entered": 1}), 422)
assert (count(Bid), count(CollusionFlag)) == (bids_before, flags_before), "a GET scan wrote rows!"
print("[OK] the GET scans wrote nothing (read-only)")

# =============== PART C: POST scan saves, GET flags lists =================
r = expect("POST scan: both rules, official thresholds", client.post(SCAN), 200)
run, run_text = r.json(), r.text
mine = [f for f in run["saved"] if f["tender_id"] in MINE]
assert {key(f) for f in mine} == {
    ("repeated_undercutting", T[0], W, X), ("repeated_undercutting", T[2], W, X),
    ("repeated_undercutting", T[3], W, X), ("high_win_share", T[0], W, None),
    ("high_win_share", T[1], W, None), ("high_win_share", T[3], W, None)}, mine
assert run["new_flags"] == len(run["saved"])
assert run["flags_found"] == run["new_flags"] + run["already_saved"]
assert count(CollusionFlag) == flags_before + run["new_flags"]
assert count(Bid) == bids_before, "the scan wrote to the bids table!"
print(f"[OK] 6 flags saved: rule 1 pair ({W}, {X}) x3 + rule 2 vendor {W} x3; {V} not saved "
      "(official 3-tender bar); bids untouched")

again = expect("POST scan again", client.post(SCAN), 200).json()
assert again["new_flags"] == 0 and again["already_saved"] == again["flags_found"] >= 6
assert count(CollusionFlag) == flags_before + run["new_flags"]
print("[OK] second run saves nothing new: every flag exists exactly once")

on_t0 = expect("GET flags for one tender", client.get(FLAGS, params={"tender_id": T[0]}), 200).json()
assert {key(f) for f in on_t0} == {("repeated_undercutting", T[0], W, X), ("high_win_share", T[0], W, None)}
x_flags = [f for f in client.get(FLAGS, params={"vendor_id": X}).json() if f["tender_id"] in MINE]
assert len(x_flags) == 3 and all(f["vendor_id_b"] == X for f in x_flags)
w_rule2 = [f for f in client.get(FLAGS, params={"vendor_id": W, "rule": "high_win_share"}).json()
           if f["tender_id"] in MINE]
assert sorted(f["tender_id"] for f in w_rule2) == [T[0], T[1], T[3]]
assert "won 3 of the 4 contested tenders" in w_rule2[0]["flag_reason"]
assert client.get(FLAGS, params={"tender_id": T[4]}).json() == []
ids = [f["id"] for f in client.get(FLAGS).json()]
assert ids == sorted(ids, reverse=True), "flags are not newest first"
print("[OK] filters: by tender, by vendor (either side of a pair), by rule; newest first")
expect("unknown rule is refused", client.get(FLAGS, params={"rule": "bogus"}), 422)
expect("tender_id 0 is refused", client.get(FLAGS, params={"tender_id": 0}), 422)

# =============== PART D: insert-only, no amounts, nothing before deadline ==
target = mine[0]
with SessionLocal() as db:
    db.get(CollusionFlag, target["id"]).flag_reason = "nothing to see here"
    try:
        db.commit()
        raise AssertionError("the ORM edited a saved flag!")
    except FlagLockedError:
        db.rollback()
print("[OK] ORM edit of a saved flag -> FlagLockedError (layer 1)")

for sql in (f"UPDATE collusion_flags SET flag_reason = 'x' WHERE id = {target['id']}",
            f"DELETE FROM collusion_flags WHERE id = {target['id']}",
            "TRUNCATE collusion_flags"):
    with SessionLocal() as db:
        try:
            db.execute(text(sql))
            db.commit()
            raise AssertionError(f"the database allowed: {sql}")
        except IntegrityError as e:
            db.rollback()
            assert "insert-only" in str(e.orig), str(e.orig)
    print(f"[OK] raw SQL {sql.split()[0]} on collusion_flags -> refused by the trigger (layer 2)")
with SessionLocal() as db:
    assert db.get(CollusionFlag, target["id"]).flag_reason == target["flag_reason"]
assert count(CollusionFlag) == flags_before + run["new_flags"]
print("[OK] the flag is unchanged and no flag disappeared")

for body in (run_text, client.get(FLAGS).text, client.get(WIN).text):
    assert "amount" not in body, "a collusion output leaked an amount!"
print("[OK] no amount in the win-share, scan or flags output (L1)")

with SessionLocal() as db:
    openable = set(tender_rules.openable_tender_ids(db, now=DEADLINE - timedelta(seconds=1)))
assert MINE.isdisjoint(openable)
print("[OK] before the test tenders' deadlines, none of them is openable (L1)")

print("\nDay 6 win-share + flags checks passed.")
