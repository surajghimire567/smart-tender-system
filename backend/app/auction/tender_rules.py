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


# Demo tenders so you can test every rule today.
DEMO_TENDERS = {
    9999: TenderWindow(9999, "published", datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
    9998: TenderWindow(9998, "published", datetime(2020, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
    9997: TenderWindow(9997, "draft",     datetime(2099, 1, 1, tzinfo=timezone.utc), Decimal("200000.00")),
}


def get_tender(tender_id: int) -> TenderWindow | None:
    """Return the tender's bidding window, or None if it doesn't exist."""
    return DEMO_TENDERS.get(tender_id)