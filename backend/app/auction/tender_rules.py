# app/auction/tender_rules.py
"""Tender-window lookups shared by bidding, ranking, and collusion scans."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Tender


@dataclass(frozen=True)
class TenderWindow:
    tender_id: int
    status: str              # draft / published / closed / awarded
    deadline: datetime
    ceiling_price: Decimal
    closed_at: datetime | None = None


# Fixed IDs reserved by the local demo scripts. They are identifiers only; tender data is
# always loaded from the shared database table.
DEMO_TENDER_IDS = frozenset({9990, 9991, 9992, 9993, 9994, 9995, 9996, 9997, 9998, 9999})

# Self-tests create throw-away tenders with IDs at or above this boundary. reset_bids uses
# it to distinguish test data from ordinary low-ID records before offering a table reset.
TEST_TENDER_MIN = 1_000_000_000


def get_tender(db: Session, tender_id: int) -> TenderWindow | None:
    """Return the stored tender's bidding window, or None if the ID is unknown."""
    tender = db.get(Tender, tender_id)
    if tender is None:
        return None
    return TenderWindow(
        tender_id=tender.id,
        status=tender.status,
        deadline=tender.deadline,
        closed_at=tender.closed_at,
        ceiling_price=tender.ceiling_price,
    )


def openable_tender_ids(db: Session, now: datetime | None = None) -> list[int]:
    """IDs of non-draft tenders whose close/deadline opening time has passed."""
    now = now or datetime.now(timezone.utc)
    opening_time_passed = or_(
        Tender.closed_at <= now,
        and_(Tender.closed_at.is_(None), Tender.deadline <= now),
    )
    query = (
        select(Tender.id)
        .where(Tender.status != "draft", opening_time_passed)
        .order_by(Tender.id)
    )
    return list(db.scalars(query).all())
