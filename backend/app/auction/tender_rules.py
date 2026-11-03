# app/auction/tender_rules.py
# Day 3: a TEMPORARY stand-in for Person 1's Tenders table.
# The auction engine only needs 3 facts about a tender: status, deadline, ceiling price.
# Day 8: replace the body of get_tender() with a query on the real Tender model.
# Keep the same return shape and nothing else in the engine has to change.
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class TenderWindow:
    tender_id: int
    status: str              # draft / published / closed / awarded (Roadmap §5)
    deadline: datetime       # always UTC
    ceiling_price: Decimal   # a bid above this is rejected


DEMO_TENDERS = {
    9999: TenderWindow(9999, "published", datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
    9998: TenderWindow(9998, "published", datetime(2020, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
    9997: TenderWindow(9997, "draft",     datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
    # Day 5: a tender that CLOSED normally -> its bids may be opened and ranked.
    9996: TenderWindow(9996, "closed",    datetime(2025, 6, 1, tzinfo=timezone.utc), Decimal("200000.00")),
    # Day 6: more CLOSED tenders, used as demo data for the collusion scan.
    9995: TenderWindow(9995, "closed",    datetime(2025, 5, 15, tzinfo=timezone.utc), Decimal("200000.00")),
    9994: TenderWindow(9994, "closed",    datetime(2025, 4, 20, tzinfo=timezone.utc), Decimal("200000.00")),
    9993: TenderWindow(9993, "closed",    datetime(2025, 3, 10, tzinfo=timezone.utc), Decimal("200000.00")),
    # Day 6: closed tenders for the rule-2 (win share) demo: vendor 505 wins all 3, always 3% under 506.
    9992: TenderWindow(9992, "closed",    datetime(2025, 2, 15, tzinfo=timezone.utc), Decimal("200000.00")),
    9991: TenderWindow(9991, "closed",    datetime(2025, 1, 20, tzinfo=timezone.utc), Decimal("200000.00")),
    9990: TenderWindow(9990, "closed",    datetime(2024, 12, 10, tzinfo=timezone.utc), Decimal("200000.00")),
}

# Day 6: self-tests create throw-away closed tenders at runtime with ids from here up.
# They are not in DEMO_TENDERS on disk, so reset_bids uses this to know they are test data.
TEST_TENDER_MIN = 1_000_000_000


def get_tender(tender_id: int) -> TenderWindow | None:
    """Return the tender's bidding window, or None if it doesn't exist."""
    return DEMO_TENDERS.get(tender_id)

# ---- Day 6: which tenders may be opened right now? ----
def openable_tender_ids(now: datetime | None = None) -> list[int]:
    """Not a draft AND deadline reached: the same two conditions as service._check_tender_closed."""
    now = now or datetime.now(timezone.utc)
    return sorted(t.tender_id for t in DEMO_TENDERS.values()
                  if t.status != "draft" and now >= t.deadline)