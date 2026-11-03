"""Run the Week 6 API path and security edge cases in a disposable PostgreSQL schema.

Run from backend/ with the configured PostgreSQL connection:
    python -m scripts.week6_e2e

The script creates a temporary schema, runs the authenticated API flow, then drops
that schema. The configured public schema is not modified.
"""
from __future__ import annotations

import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app import database
from app.auction import crypto
from app.auction.service import run_collusion_scan
from app.auction.models import Bid
from app.audit import middleware as audit_middleware
from app.config import DATABASE_URL
from app.main import app
from app.models import AuditLog, Base, Tender, User
from app.vendor import router as vendor_router
from app.vendor.security import hash_password
from scripts.demo_seed import seed_demo_data


ADMIN_EMAIL = "week6.admin@example.test"
ADMIN_PASSWORD = "Admin-Viva-2026!"
VENDOR_PASSWORD = "Vendor-Viva-2026!"
VENDOR_EMAILS = tuple(f"week6.vendor{index}@example.test" for index in range(1, 4))
VENDOR_DEVICE_IDS = ("week6-device-a", "week6-device-b", "week6-device-c")
PRICE_SETS = (
    ("100000.00", "101500.00", "108000.00"),
    ("101600.00", "100000.00", "108000.00"),
    ("100000.00", "101800.00", "108000.00"),
)


def expect(response, status: int, label: str):
    assert response.status_code == status, (
        f"{label}: expected {status}, got {response.status_code}: {response.text}"
    )
    print(f"[OK] {label}: HTTP {status}")
    return response


def run() -> None:
    schema = "week6_test_" + uuid4().hex[:12]
    url = make_url(DATABASE_URL)
    admin_engine = create_engine(url, pool_pre_ping=True)
    test_engine = None
    client = None
    original_db_factory = database.SessionLocal
    original_audit_factory = audit_middleware.SessionLocal
    original_current_bid = vendor_router.deps.get_current_bid
    app.dependency_overrides.clear()

    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        test_engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        TestSessionLocal = sessionmaker(
            bind=test_engine, autoflush=False, autocommit=False
        )
        database.SessionLocal = TestSessionLocal
        audit_middleware.SessionLocal = TestSessionLocal

        with Session(test_engine) as db:
            admin = User(
                name="Week 6 Administrator",
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                role="admin",
            )
            db.add(admin)
            db.commit()

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            client = TestClient(app)

        admin_login = expect(
            client.post(
                "/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                headers={"X-Device-Id": "week6-admin-device"},
            ),
            200,
            "admin login",
        ).json()
        admin_headers = {
            "Authorization": f"Bearer {admin_login['access_token']}",
            "X-Device-Id": "week6-admin-device",
        }

        deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        tenders = []
        first_tender = expect(
            client.post(
                "/admin/tenders",
                json={
                    "title": "Week 6 Collusion Tender 1",
                    "description": "Authenticated end-to-end verification tender.",
                    "base_price": "90000.00",
                    "ceiling_price": "120000.00",
                    "deadline": deadline,
                },
                headers=admin_headers,
            ),
            201,
            "create tender 1",
        ).json()
        expect(
            client.post(
                f"/admin/tenders/{first_tender['id']}/publish",
                headers=admin_headers,
            ),
            200,
            "publish tender 1",
        )
        tenders.append(first_tender)

        vendors = []
        vendor_tokens = []
        for index, email in enumerate(VENDOR_EMAILS, start=1):
            registered = expect(
                client.post(
                    "/auth/register",
                    json={
                        "name": f"Week 6 Vendor {index}",
                        "email": email,
                        "password": VENDOR_PASSWORD,
                        "company_name": f"Week 6 Supplier {index}",
                        "registration_number": f"WEEK6-{index}",
                    },
                ),
                201,
                f"vendor {index} registration",
            ).json()
            login = expect(
                client.post(
                    "/auth/login",
                    json={"email": email, "password": VENDOR_PASSWORD},
                    headers={"X-Device-Id": VENDOR_DEVICE_IDS[index - 1]},
                ),
                200,
                f"vendor {index} login",
            ).json()
            vendors.append(registered)
            vendor_tokens.append(login["access_token"])

        for index in range(1, 3):
            created = expect(
                client.post(
                    "/admin/tenders",
                    json={
                        "title": f"Week 6 Collusion Tender {index + 1}",
                        "description": "Authenticated end-to-end verification tender.",
                        "base_price": "90000.00",
                        "ceiling_price": "120000.00",
                        "deadline": deadline,
                    },
                    headers=admin_headers,
                ),
                201,
                f"create tender {index + 1}",
            ).json()
            expect(
                client.post(
                    f"/admin/tenders/{created['id']}/publish",
                    headers=admin_headers,
                ),
                200,
                f"publish tender {index + 1}",
            )
            tenders.append(created)

        first_bid = None
        for tender_index, tender in enumerate(tenders):
            for vendor_index, price in enumerate(PRICE_SETS[tender_index]):
                headers = {
                    "Authorization": f"Bearer {vendor_tokens[vendor_index]}",
                    "X-Device-Id": VENDOR_DEVICE_IDS[vendor_index],
                }
                if tender_index == 0 and vendor_index == 0:
                    headers["X-Device-Id"] = "week6-device-changed"
                response = expect(
                    client.post(
                        f"/tenders/{tender['id']}/bids",
                        json={"amount": price},
                        headers=headers,
                    ),
                    201,
                    f"vendor {vendor_index + 1} bid on tender {tender_index + 1}",
                )
                receipt = response.json()
                assert "amount" not in receipt
                assert len(receipt["bid_hash"]) == 64
                if tender_index == 0 and vendor_index == 0:
                    first_bid = receipt

        bid_audit = expect(
            client.get("/admin/audit-logs?limit=200", headers=admin_headers),
            200,
            "audit submitted bids",
        ).json()
        submitted_events = [
            row for row in bid_audit["items"] if row["action"] == "BID_SUBMITTED"
        ]
        assert len(submitted_events) >= 9
        assert all(
            "bid_hash" in (row["details"] or {})
            and "amount" not in (row["details"] or {})
            for row in submitted_events
        )
        print("[OK] submitted bids are audited by receipt hash, without amounts")

        # The vendor API checks the ceiling before it inserts or revises a bid.
        over_ceiling = client.post(
            f"/tenders/{tenders[0]['id']}/bids",
            json={"amount": "120000.01"},
            headers={
                "Authorization": f"Bearer {vendor_tokens[2]}",
                "X-Device-Id": VENDOR_DEVICE_IDS[2],
            },
        )
        expect(over_ceiling, 400, "over-ceiling bid rejected")

        # Two requests that both observed no current bid race to insert an original.
        duplicate_tender = expect(
            client.post(
                "/admin/tenders",
                json={
                    "title": "Week 6 Duplicate Race",
                    "description": "Concurrency boundary verification.",
                    "base_price": "1.00",
                    "ceiling_price": "100.00",
                    "deadline": deadline,
                },
                headers=admin_headers,
            ),
            201,
            "create duplicate-race tender",
        ).json()
        expect(
            client.post(
                f"/admin/tenders/{duplicate_tender['id']}/publish",
                headers=admin_headers,
            ),
            200,
            "publish duplicate-race tender",
        )
        original_get_current = vendor_router.deps.get_current_bid
        race_barrier = threading.Barrier(2)

        def synchronized_current_bid(db, tender_id, vendor_id):
            current = original_get_current(db, tender_id, vendor_id)
            if tender_id == duplicate_tender["id"] and vendor_id == vendors[0]["id"]:
                race_barrier.wait(timeout=10)
            return current

        vendor_router.deps.get_current_bid = synchronized_current_bid
        race_headers = {
            "Authorization": f"Bearer {vendor_tokens[0]}",
            "X-Device-Id": VENDOR_DEVICE_IDS[0],
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    client.post,
                    f"/tenders/{duplicate_tender['id']}/bids",
                    json={"amount": "50.00"},
                    headers=race_headers,
                )
                for _ in range(2)
            ]
            race_responses = [future.result(timeout=20) for future in futures]
        vendor_router.deps.get_current_bid = original_get_current
        assert sorted(response.status_code for response in race_responses) == [201, 409], [
            (response.status_code, response.text) for response in race_responses
        ]
        print("[OK] concurrent duplicate first bids: one accepted, one rejected")

        # A deadline-past published tender is closed lazily and refuses a late bid.
        late_tender = expect(
            client.post(
                "/admin/tenders",
                json={
                    "title": "Week 6 Late Bid",
                    "description": "Deadline edge verification.",
                    "base_price": "1.00",
                    "ceiling_price": "100.00",
                    "deadline": deadline,
                },
                headers=admin_headers,
            ),
            201,
            "create late-bid tender",
        ).json()
        expect(
            client.post(
                f"/admin/tenders/{late_tender['id']}/publish",
                headers=admin_headers,
            ),
            200,
            "publish late-bid tender",
        )
        with Session(test_engine) as db:
            row = db.get(Tender, late_tender["id"])
            row.deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        late_response = client.post(
            f"/tenders/{late_tender['id']}/bids",
            json={"amount": "50.00"},
            headers={
                "Authorization": f"Bearer {vendor_tokens[1]}",
                "X-Device-Id": VENDOR_DEVICE_IDS[1],
            },
        )
        expect(late_response, 409, "late bid rejected")

        # The PostgreSQL insert-only trigger blocks a direct edit of the encrypted bid.
        with Session(test_engine) as db:
            try:
                db.execute(
                    text(
                        "UPDATE bids SET bid_amount_encrypted = :token WHERE id = :bid_id"
                    ),
                    {"token": crypto.encrypt_amount("1.00"), "bid_id": first_bid["bid_id"]},
                )
                db.commit()
                raise AssertionError("The bid edit trigger allowed an UPDATE")
            except DBAPIError as exc:
                db.rollback()
                assert "insert-only" in str(exc).lower()
        print("[OK] direct bid edit blocked by PostgreSQL trigger")

        for index, tender in enumerate(tenders, start=1):
            expect(
                client.post(
                    f"/admin/tenders/{tender['id']}/close",
                    headers=admin_headers,
                ),
                200,
                f"close tender {index}",
            )
        with Session(test_engine) as db:
            closed = db.get(Tender, tenders[0]["id"])
            assert closed.closed_at is not None
            assert closed.closed_at < closed.deadline
            assert db.scalar(select(Bid.id).where(Bid.tender_id == tenders[0]["id"])) is not None
        print("[OK] early close timestamp is stored before the scheduled deadline")

        flags = expect(
            client.get("/auction/collusion/flags", headers=admin_headers),
            200,
            "read saved collusion flags",
        ).json()
        pair_flags = [
            flag
            for flag in flags
            if flag["rule"] == "repeated_undercutting"
            and {flag["vendor_id_a"], flag["vendor_id_b"]}
            == {vendors[0]["id"], vendors[1]["id"]}
        ]
        assert len(pair_flags) >= 3, pair_flags
        print("[OK] repeated 1–2% vendor pair flagged across all three closed tenders")

        scan = expect(
            client.post("/auction/collusion/scan", headers=admin_headers),
            200,
            "run both collusion rules",
        ).json()
        assert scan["pairs_flagged"] >= 1

        ranking = expect(
            client.get(
                f"/admin/tenders/{tenders[0]['id']}/ranking",
                headers=admin_headers,
            ),
            200,
            "view opened ranking",
        ).json()
        assert ranking["ranked"] == 3
        winning_bid_id = ranking["ranking"][0]["bid_id"]
        award = expect(
            client.post(
                f"/admin/tenders/{tenders[0]['id']}/award",
                json={"winning_bid_id": winning_bid_id},
                headers=admin_headers,
            ),
            201,
            "award the lowest eligible bid",
        ).json()
        assert award["winning_bid_id"] == winning_bid_id

        # Verify bid audit records retain receipts, never plaintext amounts.
        with Session(test_engine) as db:
            logs = list(
                db.scalars(
                    select(AuditLog).where(AuditLog.action.in_(
                        ["BID_SUBMITTED", "BID_REVISED", "DEVICE_ANOMALY",
                         "TENDER_CLOSED", "COLLUSION_SCAN", "RANKING_VIEWED",
                         "TENDER_AWARDED"]
                    ))
                ).all()
            )
        actions = {row.action for row in logs}
        expected_actions = {
            "BID_SUBMITTED",
            "DEVICE_ANOMALY",
            "TENDER_CLOSED",
            "COLLUSION_SCAN",
            "RANKING_VIEWED",
            "TENDER_AWARDED",
        }
        assert expected_actions.issubset(actions), expected_actions - actions
        bid_logs = [row for row in logs if row.action == "BID_SUBMITTED"]
        assert bid_logs and all(
            "bid_hash" in (row.details or {})
            and "amount" not in (row.details or {})
            for row in bid_logs
        )
        audit_page = expect(
            client.get("/admin/audit-logs?limit=200", headers=admin_headers),
            200,
            "view audit trail",
        ).json()
        assert audit_page["total"] >= len(logs)
        print("[OK] audit trail includes receipt hashes, device warning, close, scan, ranking, and award")

        # Verify the reusable viva seed is repeatable and produces saved pair flags.
        with Session(test_engine) as db:
            seed_once = seed_demo_data(
                db,
                admin_password="Viva-Seed-Admin!",
                vendor_password="Viva-Seed-Vendor!",
            )
            seed_twice = seed_demo_data(
                db,
                admin_password="Viva-Seed-Admin!",
                vendor_password="Viva-Seed-Vendor!",
            )
            assert seed_once["created"] is True
            assert seed_twice["created"] is False
            assert seed_once["tender_ids"] == seed_twice["tender_ids"]
            scan_seed = run_collusion_scan(
                db,
                actor_id=None,
                now=datetime.now(timezone.utc),
            )
            assert scan_seed["pairs_flagged"] >= 1
            assert scan_seed["new_flags"] >= 3
        print("[OK] viva seed is idempotent and its real closed tenders produce pair flags")
        print("WEEK6_E2E_PASS")

    finally:
        vendor_router.deps.get_current_bid = original_current_bid
        database.SessionLocal = original_db_factory
        audit_middleware.SessionLocal = original_audit_factory
        app.dependency_overrides.clear()
        if client is not None:
            client.close()
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin_engine.dispose()


if __name__ == "__main__":
    run()
