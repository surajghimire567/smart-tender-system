"""Create a repeatable viva dataset for the closed-tender collusion demo.

Run from backend/ after the database migrations:
    python -m scripts.demo_seed --admin-password '...' --vendor-password '...'

An optional --schema selects a PostgreSQL schema for isolated verification.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auction.service import _seal
from app.audit.service import log_action
from app.config import DATABASE_URL
from app.models import Tender, User
from app.vendor.security import hash_password


DEMO_TITLE_PREFIX = "VIVA Collusion Demo"
DEFAULT_ADMIN_EMAIL = "viva.admin@example.test"
DEFAULT_VENDOR_EMAILS = tuple(
    f"viva.vendor{number}@example.test" for number in range(1, 4)
)
DEMO_BIDS = (
    (Decimal("100000.00"), Decimal("101500.00"), Decimal("108000.00")),
    (Decimal("101600.00"), Decimal("100000.00"), Decimal("108000.00")),
    (Decimal("100000.00"), Decimal("101800.00"), Decimal("108000.00")),
)


def _engine_for_schema(schema: str | None):
    url = make_url(DATABASE_URL)
    connect_args = {}
    if schema:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("schema must be a lowercase PostgreSQL identifier")
        connect_args["options"] = f"-csearch_path={schema}"
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def _ensure_user(
    db: Session,
    *,
    email: str,
    role: str,
    password: str,
    name: str,
    company_name: str | None = None,
    registration_number: str | None = None,
) -> User:
    user = db.execute(
        select(User).where(User.email == email.lower())
    ).scalar_one_or_none()
    if user is not None:
        if user.role != role:
            raise ValueError(f"{email} exists with role {user.role}, expected {role}")
        return user
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=role,
        company_name=company_name,
        registration_number=registration_number,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    return user


def seed_demo_data(
    db: Session,
    *,
    admin_password: str,
    vendor_password: str,
    admin_email: str = DEFAULT_ADMIN_EMAIL,
) -> dict:
    """Insert the viva admin, three vendors, tenders, and sealed bid records."""
    admin = _ensure_user(
        db,
        email=admin_email,
        role="admin",
        password=admin_password,
        name="Viva Administrator",
    )
    vendors = [
        _ensure_user(
            db,
            email=email,
            role="vendor",
            password=vendor_password,
            name=f"Viva Vendor {index}",
            company_name=f"Viva Supplier {index}",
            registration_number=f"VIVA-DEMO-{index}",
        )
        for index, email in enumerate(DEFAULT_VENDOR_EMAILS, start=1)
    ]
    db.flush()

    existing = list(
        db.scalars(
            select(Tender)
            .where(Tender.title.like(f"{DEMO_TITLE_PREFIX}%"))
            .order_by(Tender.id)
        ).all()
    )
    if existing:
        if len(existing) != len(DEMO_BIDS):
            raise RuntimeError(
                "A partial viva seed already exists. Review those demo tenders "
                "before running the seed again."
            )
        return {
            "admin_email": admin.email,
            "vendor_emails": [vendor.email for vendor in vendors],
            "tender_ids": [tender.id for tender in existing],
            "created": False,
        }

    now = datetime.now(timezone.utc)
    tenders = []
    for index in range(len(DEMO_BIDS)):
        closed_at = now - timedelta(minutes=2 + index)
        tender = Tender(
            created_by=admin.id,
            title=f"{DEMO_TITLE_PREFIX} {index + 1}",
            description=(
                "A sealed, closed sample tender for demonstrating the "
                "repeated 1–2% undercutting rule."
            ),
            base_price=Decimal("90000.00"),
            ceiling_price=Decimal("120000.00"),
            deadline=now + timedelta(days=30),
            closed_at=closed_at,
            status="closed",
        )
        db.add(tender)
        tenders.append(tender)
    db.flush()

    for tender, amounts in zip(tenders, DEMO_BIDS):
        submitted_at = tender.closed_at - timedelta(minutes=10)
        for vendor_index, (vendor, amount) in enumerate(zip(vendors, amounts)):
            db.add(
                _seal(
                    tender.id,
                    vendor.id,
                    amount,
                    submitted_at,
                    ip_address="127.0.0.1",
                    device_fingerprint=f"viva-seed-vendor-{vendor_index + 1}",
                )
            )
    log_action(
        db,
        actor_id=admin.id,
        action="DEMO_SEED_CREATED",
        details={
            "tender_ids": [tender.id for tender in tenders],
            "vendor_ids": [vendor.id for vendor in vendors],
            "rule": "repeated_undercutting",
        },
    )
    db.commit()
    return {
        "admin_email": admin.email,
        "vendor_emails": [vendor.email for vendor in vendors],
        "tender_ids": [tender.id for tender in tenders],
        "created": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--vendor-password", required=True)
    parser.add_argument("--admin-email", default=DEFAULT_ADMIN_EMAIL)
    parser.add_argument("--schema", help="Optional existing PostgreSQL schema")
    args = parser.parse_args()

    engine = _engine_for_schema(args.schema)
    try:
        with Session(engine) as db:
            result = seed_demo_data(
                db,
                admin_password=args.admin_password,
                vendor_password=args.vendor_password,
                admin_email=args.admin_email,
            )
        state = "created" if result["created"] else "already present"
        print(f"Viva seed {state}.")
        print(f"Admin login: {result['admin_email']}")
        print("Vendor logins: " + ", ".join(result["vendor_emails"]))
        print("Tenders: " + ", ".join(str(value) for value in result["tender_ids"]))
        if result["created"]:
            print("The same vendor pair is 1.50%, 1.60%, and 1.80% apart in the three tenders.")
            print("Run an admin collusion scan to save the repeated-undercutting flags.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
