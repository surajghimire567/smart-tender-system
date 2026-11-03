"""Request metadata auditing without storing request bodies or query values."""
import logging
import time
from typing import Any

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.audit.service import log_action
from app.database import SessionLocal

logger = logging.getLogger(__name__)
_SKIP_PATHS = {"/", "/db-check", "/admin/audit-logs"}
_SKIP_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/favicon.ico")


def _actor_id(request: Request) -> int | None:
    state_user = getattr(request.state, "user", None)
    state_id = getattr(state_user, "id", None) or getattr(request.state, "actor_id", None)
    if state_id is not None:
        try:
            return int(state_id)
        except (TypeError, ValueError):
            return None

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        # Person 2 owns token verification; this import exists after module integration.
        from app.vendor.security import decode_access_token

        claims = decode_access_token(token)
        if claims.get("role") not in {"admin", "vendor"}:
            return None
        actor_id = int(claims["sub"])
        return actor_id if actor_id > 0 else None
    except Exception:
        return None


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "<unmatched-route>"


def _route_tender_id(request: Request) -> int | None:
    params = request.scope.get("path_params") or {}
    try:
        tender_id = int(params.get("tender_id"))
    except (TypeError, ValueError):
        return None
    return tender_id if tender_id > 0 else None


def _persist_event(
    *,
    actor_id: int | None,
    tender_id: int | None,
    ip_address: str | None,
    details: dict[str, Any],
) -> None:
    db = SessionLocal()
    try:
        log_action(
            db,
            actor_id=actor_id,
            action="HTTP_REQUEST",
            tender_id=tender_id,
            ip_address=ip_address,
            details=details,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Could not persist request audit event (%s).", type(exc).__name__)
    finally:
        db.close()


class AuditMiddleware(BaseHTTPMiddleware):
    """Record request method, route, status, duration, actor, and client IP only."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS or path.startswith(_SKIP_PREFIXES):
            return await call_next(request)

        started = time.perf_counter()
        actor_id = _actor_id(request)
        ip_address = request.client.host if request.client else None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            await run_in_threadpool(
                _persist_event,
                actor_id=actor_id,
                tender_id=_route_tender_id(request),
                ip_address=ip_address,
                details={
                    "method": request.method,
                    "path": _route_path(request),
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise

        await run_in_threadpool(
            _persist_event,
            actor_id=actor_id,
            tender_id=_route_tender_id(request),
            ip_address=ip_address,
            details={
                "method": request.method,
                "path": _route_path(request),
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response
