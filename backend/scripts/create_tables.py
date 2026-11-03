# scripts/create_tables.py
# Run from backend/:  python -m scripts.create_tables
# Creates missing tables AND installs the insert-only locks:
#   Day 4: bids        Day 6: collusion_flags
# Safe to run again and again (idempotent).
from app.auction.db_lock import (
    FLAGS_TRIGGERS, LOCK_TRIGGERS, flags_lock_status, install_bid_lock, install_flags_lock,
    lock_status,
)
from app.database import Base, engine
import app.auction.models  # noqa: F401  (importing registers Bid + CollusionFlag on Base)

with engine.begin() as conn:          # ONE transaction: commit at the end, rollback on error
    Base.metadata.create_all(bind=conn)   # new table -> its after_create event locks it
    install_bid_lock(conn)                # tables that already existed -> lock them now
    install_flags_lock(conn)
    status = {**lock_status(conn), **flags_lock_status(conn)}

for table in ("bids", "collusion_flags"):
    columns = [c.name for c in Base.metadata.tables[table].columns]
    print(f"{table} table ready. Columns: " + ", ".join(columns))
print("Insert-only locks (database layer):")
when = {**LOCK_TRIGGERS, **FLAGS_TRIGGERS}
for name, state in status.items():
    print(f"  {name:<26} {when[name].split(' ON ')[0]:<26} {state}")

if any(state != "ON" for state in status.values()):
    raise SystemExit("Lock is NOT fully active - fix this before continuing.")