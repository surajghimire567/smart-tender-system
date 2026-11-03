"""P2 auth, vendor browsing, bid, receipt, and own-result routes."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.vendor import deps, service
from app.vendor.schemas import (
    BidIn,
    BidReceipt,
    LoginIn,
    MyBidItem,
    RegisterIn,
    TokenOut,
    UserOut,
    VendorResultOut,
    VendorTenderItem,
    VendorTenderOut,
)
from app.vendor.security import (
    TOKEN_TTL_SECONDS,
    create_access_token,
    hash_password,
    make_device_fingerprint,
    verify_password,
)

router = APIRouter()


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _vendor_or_404(db: Session, tender_id: int) -> Any:
    Tender = deps.get_model("Tender")
    tender = db.get(Tender, tender_id)
    if tender is None or tender.status == "draft":
        raise HTTPException(status_code=404, detail="Tender not found")
    return tender


def _receipt(value: dict | None) -> BidReceipt | None:
    if value is None:
        return None
    return BidReceipt.model_validate(value)


def _reject_bid(
    db: Session,
    user: Any,
    tender_id: int,
    ip_address: str | None,
    reason: str,
    status_code: int,
    detail: str,
) -> None:
    deps.log_action(
        db,
        actor_id=int(user.id),
        action="BID_REJECTED",
        tender_id=tender_id,
        ip_address=ip_address,
        details={"reason": reason},
    )
    _commit(db)
    raise HTTPException(status_code=status_code, detail=detail)


# ---- Auth routes ----
@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, request: Request, db: Session = Depends(deps.get_db)):
    User = deps.get_model("User")
    email = payload.email.lower()
    existing = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        name=payload.name,
        email=email,
        password_hash=hash_password(payload.password),
        role="vendor",
        company_name=payload.company_name,
        registration_number=payload.registration_number,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    try:
        db.flush()
        deps.log_action(
            db,
            actor_id=int(user.id),
            action="USER_REGISTERED",
            ip_address=service.client_ip(request),
            details={"company_name": payload.company_name},
        )
        _commit(db)
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.execute(
            select(User).where(func.lower(User.email) == email)
        ).scalar_one_or_none()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Email already registered") from exc
        raise
    except Exception:
        db.rollback()
        raise
    return user


@router.post("/auth/login", response_model=TokenOut)
def login(
    payload: LoginIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
):
    User = deps.get_model("User")
    email = payload.email.lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    ip_address = service.client_ip(request)
    fingerprint = make_device_fingerprint(x_device_id, request.headers.get("user-agent"))

    if user is None or not verify_password(payload.password, user.password_hash):
        try:
            deps.log_action(
                db,
                actor_id=None,
                action="LOGIN_FAILED",
                ip_address=ip_address,
                details={"email": email},
            )
            _commit(db)
        except Exception:
            db.rollback()
            raise
        raise HTTPException(status_code=401, detail="Invalid email or password")

    try:
        service.log_login_anomaly(db, user, fingerprint, ip_address)
        deps.log_action(
            db,
            actor_id=int(user.id),
            action="LOGIN_SUCCESS",
            ip_address=ip_address,
            details={"device_fingerprint": fingerprint},
        )
        token = create_access_token(int(user.id), user.role, fingerprint)
        _commit(db)
    except Exception:
        db.rollback()
        raise
    return TokenOut(
        access_token=token,
        token_type="bearer",
        role=user.role,
        expires_in=TOKEN_TTL_SECONDS,
    )


@router.get("/auth/me", response_model=UserOut)
def auth_me(user: Any = Depends(deps.get_current_user)):
    return user


# ---- Vendor tender browsing ----
@router.get("/tenders", response_model=list[VendorTenderItem])
def list_tenders(
    request: Request,
    status_filter: str = Query(default="published", alias="status", pattern="^published$"),
    db: Session = Depends(deps.get_db),
    vendor: Any = Depends(deps.require_role("vendor")),
):
    del status_filter  # the vendor API intentionally exposes published tenders only
    deps.refresh_all_overdue(db, service.client_ip(request))
    Tender = deps.get_model("Tender")
    rows = db.execute(
        select(Tender)
        .where(Tender.status == "published")
        .order_by(Tender.deadline.asc(), Tender.id.asc())
    ).scalars().all()
    result = []
    for tender in rows:
        current = deps.get_current_bid(db, int(tender.id), int(vendor.id))
        result.append(
            VendorTenderItem(
                id=tender.id,
                title=tender.title,
                status="published",
                deadline=tender.deadline,
                ceiling_price=tender.ceiling_price,
                is_open=deps.is_open(tender),
                has_my_bid=current is not None,
            )
        )
    return result


@router.get("/tenders/{tender_id}", response_model=VendorTenderOut)
def get_tender(
    tender_id: int,
    request: Request,
    db: Session = Depends(deps.get_db),
    vendor: Any = Depends(deps.require_role("vendor")),
):
    tender = _vendor_or_404(db, tender_id)
    tender = deps.refresh_status(db, tender, service.client_ip(request))
    if tender.status != "published":
        # Closed/awarded tenders are reached only from My bids.
        raise HTTPException(status_code=404, detail="Tender not found")
    current = deps.get_current_bid(db, int(tender.id), int(vendor.id))
    return VendorTenderOut(
        id=tender.id,
        title=tender.title,
        description=tender.description,
        ceiling_price=tender.ceiling_price,
        deadline=tender.deadline,
        status=tender.status,
        is_open=deps.is_open(tender),
        my_current_bid=_receipt(current),
    )


# ---- Bid submission ----
@router.post(
    "/tenders/{tender_id}/bids",
    response_model=BidReceipt,
    status_code=status.HTTP_201_CREATED,
)
def place_bid(
    payload: BidIn,
    tender_id: int,
    request: Request,
    db: Session = Depends(deps.get_db),
    vendor: Any = Depends(deps.require_role("vendor")),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
):
    ip_address = service.client_ip(request)
    tender = _vendor_or_404(db, tender_id)
    tender = deps.refresh_status(db, tender, ip_address)
    if not deps.is_open(tender):
        _reject_bid(
            db, vendor, tender_id, ip_address, "not_open", 409,
            "Tender is not open for bidding",
        )
    if payload.amount > Decimal(tender.ceiling_price):
        _reject_bid(
            db, vendor, tender_id, ip_address, "over_ceiling", 400,
            "Bid exceeds the ceiling price",
        )

    current = deps.get_current_bid(db, tender_id, int(vendor.id))
    supersedes_bid_id = current["bid_id"] if current else None
    fingerprint = make_device_fingerprint(
        x_device_id, request.headers.get("user-agent")
    )
    service.check_bid_anomaly(
        db, vendor, fingerprint, ip_address, tender_id
    )

    try:
        receipt = deps.submit_bid(
            db,
            tender,
            int(vendor.id),
            payload.amount,
            fingerprint,
            ip_address,
            supersedes_bid_id=supersedes_bid_id,
        )
        deps.log_action(
            db,
            actor_id=int(vendor.id),
            action="BID_REVISED" if supersedes_bid_id is not None else "BID_SUBMITTED",
            tender_id=tender_id,
            ip_address=ip_address,
            details={
                "bid_hash": receipt["bid_hash"],
                "supersedes_bid_id": supersedes_bid_id,
            },
        )
        db.commit()
    except deps.BidClosedError:
        db.rollback()
        _reject_bid(
            db, vendor, tender_id, ip_address, "not_open", 409,
            "Tender is not open for bidding",
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Your current bid changed. Refresh and try again",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return BidReceipt.model_validate(receipt)


@router.get("/vendor/bids", response_model=list[MyBidItem])
def my_bids(
    db: Session = Depends(deps.get_db),
    vendor: Any = Depends(deps.require_role("vendor")),
):
    return [MyBidItem.model_validate(row) for row in deps.get_my_bids(db, int(vendor.id))]


@router.get("/vendor/tenders/{tender_id}/result", response_model=VendorResultOut)
def my_result(
    tender_id: int,
    request: Request,
    db: Session = Depends(deps.get_db),
    vendor: Any = Depends(deps.require_role("vendor")),
):
    tender = _vendor_or_404(db, tender_id)
    tender = deps.refresh_status(db, tender, service.client_ip(request))
    try:
        result = deps.get_vendor_result(db, tender_id, int(vendor.id))
    except deps.SealedError as exc:
        raise HTTPException(
            status_code=409,
            detail="Bids are sealed until the deadline",
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="No bid from you on this tender")
    result = VendorResultOut.model_validate(result)
    if request.headers.get("x-background-refresh", "").lower() != "true":
        deps.log_action(
            db,
            actor_id=int(vendor.id),
            action="VENDOR_RESULT_VIEWED",
            tender_id=tender_id,
            ip_address=service.client_ip(request),
            details={"my_rank": result.my_rank},
        )
        _commit(db)
    return result
