# scripts/reset_bids.py
# Run from backend/:  python -m scripts.reset_bids      (then: python -m scripts.create_tables)
# DEMO ONLY. Since Day 4 the trigger refuses DELETE and TRUNCATE on bids, so the only
# way to start clean is to DROP the whole table (only its OWNER may do this).
from sqlalchemy import text

from app.auction.db_lock import FUNCTION
from app.auction.tender_rules import DEMO_TENDERS
from app.database import engine

with engine.begin() as conn:
    exists = conn.execute(text("SELECT to_regclass('bids') IS NOT NULL")).scalar()
    if not exists:
        raise SystemExit("No bids table. Run: python -m scripts.create_tables")
    demo_ids = list(DEMO_TENDERS)
    real = conn.execute(
        text("SELECT count(*) FROM bids WHERE NOT (tender_id = ANY(:ids))"), {"ids": demo_ids}
    ).scalar()
    total = conn.execute(text("SELECT count(*) FROM bids")).scalar()

if real:
    raise SystemExit(f"Refusing: {real} bid(s) belong to non-demo tenders. Never reset real bids.")

print(f"This DROPS the bids table ({total} demo rows) and its lock triggers.")
if input("Type RESET to confirm: ").strip() != "RESET":
    raise SystemExit("Cancelled. Nothing changed.")

with engine.begin() as conn:
    conn.execute(text("DROP TABLE bids"))                    # triggers go with the table
    conn.execute(text(f"DROP FUNCTION IF EXISTS {FUNCTION}()"))
print("bids table dropped. Now run: python -m scripts.create_tables")