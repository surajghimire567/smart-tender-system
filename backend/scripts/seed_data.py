"""Idempotently seed local demo users and a draft tender.

Set SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD, SEED_VENDOR_EMAIL, and
SEED_VENDOR_PASSWORD in the local environment before running this script.
Passwords are never accepted as command-line arguments or printed.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select

from app.audit.service import log_action
from app.database import SessionLocal
from app.models import Tender, User


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before running seed_data.py")
    return value


def _password_hash(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) < 12:
        raise RuntimeError("Seed passwords must be at least 12 bytes")
    if len(encoded) > 72:
        raise RuntimeError("bcrypt seed passwords must not exceed 72 bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def _get_or_create_user(
    db,
    *,
    email: str,
    password: str,
    name: str,
    role: str,
    company_name: str | None = None,
    registration_number: str | None = None,
) -> tuple[User, bool]:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is not None:
        if user.role != role:
            raise RuntimeError(f"{normalized_email} already exists with a different role")
        return user, False

    user = User(
        email=normalized_email,
        password_hash=_password_hash(password),
        name=name,
        role=role,
        company_name=company_name,
        registration_number=registration_number,
    )
    db.add(user)
    db.flush()
    return user, True


def seed() -> None:
    admin_email = _required("SEED_ADMIN_EMAIL")
    admin_password = _required("SEED_ADMIN_PASSWORD")
    vendor_email = _required("SEED_VENDOR_EMAIL")
    vendor_password = _required("SEED_VENDOR_PASSWORD")
    db = SessionLocal()
    try:
        admin, admin_created = _get_or_create_user(
            db,
            email=admin_email,
            password=admin_password,
            name=os.getenv("SEED_ADMIN_NAME", "Demo Administrator").strip(),
            role="admin",
        )
        vendor, vendor_created = _get_or_create_user(
            db,
            email=vendor_email,
            password=vendor_password,
            name=os.getenv("SEED_VENDOR_NAME", "Demo Vendor").strip(),
            role="vendor",
            company_name=os.getenv("SEED_VENDOR_COMPANY", "Demo Company").strip(),
            registration_number=os.getenv(
                "SEED_VENDOR_REGISTRATION", "DEMO-VENDOR-001"
            ).strip(),
        )

        tender_created = False
        tender = None
        if os.getenv("SEED_DEMO_TENDER", "1").strip().lower() not in {"0", "false", "no"}:
            title = "DEMO ONLY: Road maintenance supplies"
            tender = db.scalar(
                select(Tender).where(Tender.created_by == admin.id, Tender.title == title)
            )
            if tender is None:
                tender = Tender(
                    created_by=admin.id,
                    title=title,
                    description="Seed record for local development. Not a real procurement notice.",
                    base_price=100000,
                    ceiling_price=150000,
                    deadline=datetime.now(timezone.utc) + timedelta(days=7),
                    status="draft",
                )
                db.add(tender)
                db.flush()
                tender_created = True

        if admin_created or vendor_created or tender_created:
            log_action(
                db,
                actor_id=admin.id,
                action="DEMO_DATA_SEEDED",
                tender_id=tender.id if tender_created and tender is not None else None,
                details={
                    "admin_created": admin_created,
                    "vendor_created": vendor_created,
                    "demo_tender_created": tender_created,
                },
            )
        db.commit()
        print(
            "Seed complete: "
            f"admin_id={admin.id}, vendor_id={vendor.id}, "
            f"demo_tender={'created' if tender_created else 'unchanged'}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
