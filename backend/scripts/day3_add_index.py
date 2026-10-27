from app.database import engine
from app.auction.models import Bid

for index in Bid.__table__.indexes:
    index.create(bind=engine, checkfirst=True)

print("bids indexes ready: " + ", ".join(sorted(i.name for i in Bid.__table__.indexes)))