"""P2 password, JWT, and device-fingerprint helpers."""
import hashlib
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

JWT_ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 3600


def hash_password(password: str) -> str:
    """Hash a password with bcrypt; plaintext is never persisted."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def make_device_fingerprint(device_id: str | None, user_agent: str | None) -> str:
    stable_id = device_id if device_id else "unknown"
    agent = user_agent or ""
    return hashlib.sha256(f"{stable_id}|{agent}".encode("utf-8")).hexdigest()


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("Missing JWT_SECRET in .env")
    return secret


def create_access_token(
    user_id: int,
    role: str,
    dfp: str,
    *,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(timezone.utc)
    issued_ts = int(issued.timestamp())
    claims = {
        "sub": str(user_id),
        "role": role,
        "dfp": dfp,
        "iat": issued_ts,
        "exp": issued_ts + TOKEN_TTL_SECONDS,
    }
    return jwt.encode(claims, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "role", "dfp", "iat", "exp"]},
    )
