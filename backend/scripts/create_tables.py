# scripts/create_tables.py
# Run from backend/:  python -m scripts.create_tables
from app.database import Base, engine
import app.auction.models  # noqa: F401  (importing registers the Bid table on Base)

Base.metadata.create_all(bind=engine)

columns = [c.name for c in Base.metadata.tables["bids"].columns]
print("bids table ready. Columns: " + ", ".join(columns))