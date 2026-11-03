"""Single swap point for Person 2, Person 3, and Person 4 contracts.

The fallback implementations are integration stubs only. Replace the imports here
when the corresponding teammate module is merged; do not implement their modules
inside Person 1's branch.
"""
from typing import Any

from fastapi import HTTPException

from app.database import get_db

# Person 2 owns auth. The contract is require_role(role) -> FastAPI dependency.
try:
    from app.vendor.deps import require_role as _require_role

    require_admin = _require_role("admin")
except (ImportError, AttributeError):
    def require_admin() -> None:
        """TODO: replace with Person 2's require_role('admin') dependency."""
        raise HTTPException(
            status_code=503,
            detail="Admin authentication integration is pending",
        )


def _load_models() -> dict[str, Any]:
    """Load Person 4's shared models lazily so the router can import before P4 merges."""
    try:
        from app.models import Award, CollusionFlag, Tender
    except (ImportError, AttributeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Shared database models are not integrated",
        ) from exc
    return {"Tender": Tender, "Award": Award, "CollusionFlag": CollusionFlag}


def get_model(name: str) -> Any:
    return _load_models()[name]


# Person 4 owns log_action. Prefer the package export; permit the service-module
# export as a one-file adapter if P4 chooses that layout.
try:
    from app.audit import log_action as _log_action
except (ImportError, AttributeError):
    try:
        from app.audit.service import log_action as _log_action
    except (ImportError, AttributeError):
        _log_action = None


def log_action(
    db: Any,
    actor_id: int | None,
    action: str,
    tender_id: int | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    """P4 contract: append an audit event; the caller owns the transaction."""
    if _log_action is None:
        raise HTTPException(
            status_code=503,
            detail="Audit integration is pending",
        )
    _log_action(
        db,
        actor_id=actor_id,
        action=action,
        tender_id=tender_id,
        ip_address=ip_address,
        details=details,
    )


# Person 3's repository branch currently exports rank_bids(db, tender_id).
try:
    from app.auction.service import rank_bids as _rank_bids
except (ImportError, AttributeError):
    _rank_bids = None


def rank_bids(db: Any, tender_id: int) -> dict:
    """TODO fallback to Person 3's real rank_bids implementation at integration."""
    if _rank_bids is None:
        raise HTTPException(
            status_code=503,
            detail="Auction ranking integration is pending",
        )
    return _rank_bids(db, tender_id)


def run_collusion_scan(
    db: Any,
    *,
    actor_id: int | None = None,
    ip_address: str | None = None,
) -> dict:
    """Run Person 3's idempotent flag scan using the caller's database session."""
    try:
        from app.auction.service import run_collusion_scan as scan
    except (ImportError, AttributeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Auction collusion integration is pending",
        ) from exc
    return scan(db, actor_id=actor_id, ip_address=ip_address)
