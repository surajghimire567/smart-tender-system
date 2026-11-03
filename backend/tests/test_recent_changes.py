from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as shared_models
from app.admin import service as admin_service
from app.admin.schemas import CollusionFlagOut, TenderCreateIn
from app.admin.deps import require_admin
from app.auction import crypto, service as auction_service, tender_rules
from app.auction.models import Bid, CollusionFlag
from app.auction.tender_rules import TenderWindow
from app.database import Base
from app.main import app


def test_collusion_flag_single_vendor_serializes_and_is_shared_model():
    assert shared_models.CollusionFlag is CollusionFlag
    flag = CollusionFlag(
        id=1,
        rule="high_win_share",
        tender_id=8,
        vendor_id_a=21,
        vendor_id_b=None,
        flag_reason="high share",
        flagged_at=datetime.now(timezone.utc),
    )

    result = CollusionFlagOut.model_validate(flag)

    assert result.vendor_id_b is None


def _valid_bid(bid_id: int, vendor_id: int, submitted_at: datetime) -> Bid:
    amount = Decimal("100.00")
    return Bid(
        id=bid_id,
        tender_id=77,
        vendor_id=vendor_id,
        bid_amount_encrypted=crypto.encrypt_amount(amount),
        bid_hash=crypto.make_bid_hash(77, vendor_id, amount, submitted_at.isoformat()),
        submitted_at=submitted_at,
    )


def test_early_close_timestamp_boundary_and_scheduled_deadline():
    closed_at = datetime.now(timezone.utc).replace(microsecond=123456)
    deadline = closed_at + timedelta(hours=1)
    early_close = TenderWindow(77, "closed", deadline, Decimal("200.00"), closed_at)

    amount, reason = auction_service._open_bid(
        _valid_bid(1, 11, closed_at), early_close
    )
    assert amount == Decimal("100.00")
    assert reason is None

    amount, reason = auction_service._open_bid(
        _valid_bid(2, 12, closed_at + timedelta(microseconds=1)), early_close
    )
    assert amount is None
    assert reason == auction_service.EXCLUDE_LATE

    scheduled = TenderWindow(77, "published", deadline, Decimal("200.00"), None)
    amount, reason = auction_service._open_bid(_valid_bid(3, 13, deadline), scheduled)
    assert amount is None
    assert reason == auction_service.EXCLUDE_LATE


def test_openable_tenders_use_closed_at_or_deadline():
    from app.models import Tender, User

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[User.__table__, Tender.__table__])
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        owner = User(
            name="Test admin",
            email="admin@example.invalid",
            password_hash="unused",
            role="admin",
        )
        db.add(owner)
        db.flush()
        db.add_all(
            [
                Tender(
                    id=1,
                    created_by=owner.id,
                    title="closed early",
                    description="",
                    base_price=Decimal("1.00"),
                    ceiling_price=Decimal("10.00"),
                    deadline=now + timedelta(days=1),
                    closed_at=now - timedelta(seconds=1),
                    status="closed",
                ),
                Tender(
                    id=2,
                    created_by=owner.id,
                    title="closed later",
                    description="",
                    base_price=Decimal("1.00"),
                    ceiling_price=Decimal("10.00"),
                    deadline=now - timedelta(days=1),
                    closed_at=now + timedelta(seconds=1),
                    status="closed",
                ),
                Tender(
                    id=3,
                    created_by=owner.id,
                    title="deadline passed",
                    description="",
                    base_price=Decimal("1.00"),
                    ceiling_price=Decimal("10.00"),
                    deadline=now - timedelta(seconds=1),
                    status="published",
                ),
                Tender(
                    id=4,
                    created_by=owner.id,
                    title="draft",
                    description="",
                    base_price=Decimal("1.00"),
                    ceiling_price=Decimal("10.00"),
                    deadline=now - timedelta(days=1),
                    status="draft",
                ),
            ]
        )
        db.commit()

        assert tender_rules.openable_tender_ids(db, now) == [1, 3]
    engine.dispose()


def test_tender_validation_returns_clear_price_and_deadline_errors():
    future = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(ValidationError, match="ceiling_price must be greater"):
        TenderCreateIn(
            title="Bad bounds",
            description="",
            base_price="20.00",
            ceiling_price="10.00",
            deadline=future,
        )

    with pytest.raises(ValidationError, match="deadline must be in the future"):
        TenderCreateIn(
            title="Past deadline",
            description="",
            base_price="10.00",
            ceiling_price="20.00",
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

    with pytest.raises(admin_service.AdminError, match="ceiling_price must be greater"):
        admin_service._validate_tender_values(
            Decimal("20.00"), Decimal("10.00"), future
        )


def test_manual_close_records_close_time_and_runs_collusion_scan(monkeypatch):
    deadline = datetime.now(timezone.utc) + timedelta(days=1)
    tender = SimpleNamespace(id=1, status="published", deadline=deadline, closed_at=None)
    scanned = []
    db = SimpleNamespace(refresh=lambda row: None, rollback=lambda: None)
    monkeypatch.setattr(admin_service, "get_tender_or_404", lambda *_: tender)
    monkeypatch.setattr(admin_service, "refresh_status", lambda _db, row, _ip: row)
    monkeypatch.setattr(admin_service, "_safe_commit", lambda _db: None)
    monkeypatch.setattr(admin_service.deps, "log_action", lambda *a, **k: None)
    monkeypatch.setattr(
        admin_service.deps,
        "run_collusion_scan",
        lambda *a, **k: scanned.append((a, k)),
    )

    result = admin_service.close_tender(db, 1, 5, "127.0.0.1")

    assert result.status == "closed"
    assert result.closed_at is not None
    assert result.closed_at < deadline
    assert len(scanned) == 1


def test_removed_public_routes_and_admin_only_auction_views():
    routes = [route for route in app.routes if hasattr(route, "path")]
    path_methods = {
        (method, route.path)
        for route in routes
        for method in (getattr(route, "methods", None) or set())
    }
    assert not any(path in {"/demo-encrypt", "/demo-decrypt"} for _, path in path_methods)
    assert ("POST", "/auction/bids") not in path_methods
    assert not any(path.endswith("/revisions") for _, path in path_methods)

    admin_paths = {
        "/auction/tenders/{tender_id}/sealed-bids",
        "/auction/tenders/{tender_id}/ranking",
        "/auction/collusion/scan",
        "/auction/collusion/flags",
    }
    for route in routes:
        if route.path not in admin_paths:
            continue
        assert any(dep.call is require_admin for dep in route.dependant.dependencies)
