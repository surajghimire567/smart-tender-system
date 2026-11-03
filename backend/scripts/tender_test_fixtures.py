"""Database fixtures for auction integration scripts."""
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tender, User


def seed_test_tenders(
    db: Session,
    tenders: list[tuple[int, str, datetime, Decimal]],
) -> None:
    """Insert test tenders into the real table for IDs/status/deadline lookups."""
    owner_id = db.scalar(select(User.id).order_by(User.id).limit(1))
    if owner_id is None:
        owner = User(
            name="Auction self-test",
            email=f"auction-self-test-{uuid4().hex}@example.invalid",
            password_hash="self-test-only-not-a-login-hash",
            role="admin",
        )
        db.add(owner)
        db.flush()
        owner_id = owner.id

    for tender_id, status, deadline, ceiling_price in tenders:
        if db.get(Tender, tender_id) is not None:
            raise RuntimeError(f"Self-test tender ID collision: {tender_id}")
        db.add(Tender(
            id=tender_id,
            created_by=owner_id,
            title=f"SELF-TEST ONLY: auction tender {tender_id}",
            description="Temporary database row used by an auction integration script.",
            base_price=Decimal("1.00"),
            ceiling_price=ceiling_price,
            deadline=deadline,
            status=status,
        ))
    db.commit()
