"""P2 swap point for shared auth, P1 tender rules, P3 engine, and P4 data/audit.

The Person 2 module owns these wrappers. Missing teammate contracts fail clearly
with 503 until the corresponding branch is integrated; no teammate's module is
reimplemented here.
"""
from importlib import import_module
from inspect import signature
from typing import Any, Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.vendor.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def _pending(message: str) -> HTTPException:
    return HTTPException(status_code=503, detail=message)


def get_model(name: str) -> Any:
    try:
        module = import_module("app.models")
        return getattr(module, name)
    except (ImportError, AttributeError) as exc:
        raise _pending("Shared database models are not integrated") from exc


def _audit_writer() -> Callable[..., Any] | None:
    for module_name in ("app.audit", "app.audit.service"):
        try:
            module = import_module(module_name)
            writer = getattr(module, "log_action", None)
            if callable(writer):
                return writer
        except ImportError:
            continue
    return None


def log_action(
    db: Session,
    actor_id: int | None,
    action: str,
    tender_id: int | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    writer = _audit_writer()
    if writer is None:
        raise _pending("Audit integration is pending")
    writer(
        db,
        actor_id=actor_id,
        action=action,
        tender_id=tender_id,
        ip_address=ip_address,
        details=details,
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Any:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        claims = decode_access_token(creds.credentials)
        if claims.get("role") not in ("admin", "vendor"):
            raise ValueError("invalid role")
        user_id = int(claims["sub"])
        dfp = claims["dfp"]
        if not isinstance(dfp, str):
            raise ValueError("invalid fingerprint")
    except Exception as exc:
        # A missing/invalid/expired token must not leak JWT parser details.
        raise HTTPException(status_code=401, detail="Not authenticated") from exc

    User = get_model("User")
    user = db.get(User, user_id)
    if user is None or user.role != claims["role"]:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user.token_dfp = dfp
    return user


def require_role(role: str):
    def role_dependency(user: Any = Depends(get_current_user)) -> Any:
        if user.role != role:
            raise HTTPException(
                status_code=403,
                detail=f"{role.capitalize()} role required",
            )
        return user

    return role_dependency


def _p1_function(name: str) -> Callable[..., Any]:
    try:
        module = import_module("app.admin.service")
        return getattr(module, name)
    except (ImportError, AttributeError) as exc:
        raise _pending("Tender lifecycle integration is pending") from exc


def is_open(tender: Any) -> bool:
    return _p1_function("is_open")(tender)


def refresh_status(db: Session, tender: Any, ip: str | None = None) -> Any:
    return _p1_function("refresh_status")(db, tender, ip)


def refresh_all_overdue(db: Session) -> None:
    _p1_function("refresh_all_overdue")(db)


def _engine_function(name: str) -> Callable[..., Any] | None:
    # The final contract is preferred. The repository's current auction branch is
    # still a standalone prototype and does not yet export these P2 signatures.
    required_parameters = {
        "submit_bid": {
            "db", "tender", "vendor_id", "amount",
            "device_fingerprint", "ip_address", "supersedes_bid_id",
        },
        "get_current_bid": {"db", "tender_id", "vendor_id"},
        "get_my_bids": {"db", "vendor_id"},
        "get_vendor_result": {"db", "tender_id", "vendor_id"},
    }.get(name, set())
    for module_name in ("app.engine.service", "app.auction.service"):
        try:
            candidate = getattr(import_module(module_name), name, None)
            if callable(candidate) and required_parameters.issubset(
                signature(candidate).parameters
            ):
                return candidate
        except ImportError:
            continue
    return None


class BidClosedError(Exception):
    """P3 contract exception: the tender closed during bid submission."""


class SealedError(Exception):
    """P3 contract exception: results are not available before close."""


def _call_engine(name: str, *args: Any, **kwargs: Any) -> Any:
    function = _engine_function(name)
    if function is None:
        raise _pending("Auction engine integration is pending")
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        # Normalize by contract name without taking ownership of P3 exceptions.
        if exc.__class__.__name__ == "BidClosedError":
            raise BidClosedError() from exc
        if exc.__class__.__name__ == "SealedError":
            raise SealedError() from exc
        raise


def submit_bid(
    db: Session,
    tender: Any,
    vendor_id: int,
    amount: Any,
    device_fingerprint: str,
    ip_address: str | None,
    supersedes_bid_id: int | None = None,
) -> dict:
    return _call_engine(
        "submit_bid", db, tender, vendor_id, amount, device_fingerprint,
        ip_address, supersedes_bid_id=supersedes_bid_id,
    )


def get_current_bid(db: Session, tender_id: int, vendor_id: int) -> dict | None:
    return _call_engine("get_current_bid", db, tender_id, vendor_id)


def get_my_bids(db: Session, vendor_id: int) -> list[dict]:
    return _call_engine("get_my_bids", db, vendor_id)


def get_vendor_result(db: Session, tender_id: int, vendor_id: int) -> dict | None:
    return _call_engine("get_vendor_result", db, tender_id, vendor_id)
