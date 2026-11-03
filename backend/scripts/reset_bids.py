# scripts/reset_bids.py
# Run from backend/:  python -m scripts.reset_bids      (then: python -m scripts.create_tables)
# DEMO ONLY. The triggers refuse DELETE and TRUNCATE on bids (Day 4) and on collusion_flags
# (Day 6), so the only way to start clean is to DROP the tables (only their OWNER may do this).
from sqlalchemy import text

from app.auction.db_lock import FLAGS_FUNCTION, FUNCTION
from app.auction.tender_rules import DEMO_TENDER_IDS, TEST_TENDER_MIN
from app.database import engine

# Day 6: tenders >= TEST_TENDER_MIN were made by a self-test (day6_collusion_test / day6_flags_test).
NOT_DEMO = "SELECT count(*) FROM {table} WHERE NOT (tender_id = ANY(:ids)) AND tender_id < :test_min"
params = {"ids": list(DEMO_TENDER_IDS), "test_min": TEST_TENDER_MIN}

with engine.begin() as conn:
    exists = conn.execute(text("SELECT to_regclass('bids') IS NOT NULL")).scalar()
    if not exists:
        raise SystemExit("No bids table. Run: python -m scripts.create_tables")
    has_flags = conn.execute(text("SELECT to_regclass('collusion_flags') IS NOT NULL")).scalar()
    real = conn.execute(text(NOT_DEMO.format(table="bids")), params).scalar()
    if has_flags:
        real += conn.execute(text(NOT_DEMO.format(table="collusion_flags")), params).scalar()
    total = conn.execute(text("SELECT count(*) FROM bids")).scalar()
    flags = conn.execute(text("SELECT count(*) FROM collusion_flags")).scalar() if has_flags else 0

if real:
    raise SystemExit(f"Refusing: {real} row(s) belong to non-demo tenders. Never reset real data.")

print(f"This DROPS the bids table ({total} demo rows), the collusion_flags table "
      f"({flags} demo rows) and their lock triggers.")
if input("Type RESET to confirm: ").strip() != "RESET":
    raise SystemExit("Cancelled. Nothing changed.")

with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS collusion_flags"))   # triggers go with the table
    conn.execute(text("DROP TABLE bids"))
    conn.execute(text(f"DROP FUNCTION IF EXISTS {FLAGS_FUNCTION}()"))
    conn.execute(text(f"DROP FUNCTION IF EXISTS {FUNCTION}()"))
print("bids + collusion_flags dropped. Now run: python -m scripts.create_tables")
