# scripts/create_tables.py
# Run from backend/:  python -m scripts.create_tables
# Creates missing tables AND installs the Day 4 insert-only lock on bids.
# Safe to run again and again (idempotent).
from app.auction.db_lock import LOCK_TRIGGERS, install_bid_lock, lock_status
from app.database import Base, engine
import app.auction.models  # noqa: F401  (importing registers the Bid table on Base)

with engine.begin() as conn:          # ONE transaction: commit at the end, rollback on error
    Base.metadata.create_all(bind=conn)   # new table -> after_create locks it
    install_bid_lock(conn)                # table from Day 2 already existed -> lock it now
    status = lock_status(conn)

columns = [c.name for c in Base.metadata.tables["bids"].columns]
print("bids table ready. Columns: " + ", ".join(columns))
print("Insert-only lock (L2, database layer):")
for name, state in status.items():
    print(f"  {name:<26} {LOCK_TRIGGERS[name].split(' ON ')[0]:<26} {state}")

if any(state != "ON" for state in status.values()):
    raise SystemExit("Lock is NOT fully active - fix this before continuing.")