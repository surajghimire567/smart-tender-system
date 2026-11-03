
# app/auction/crypto.py
# Person 3 core tools:
#   L1 -> encrypt / decrypt bid amounts (Fernet)
#   L2 -> tamper-evident hash receipt (SHA-256)
import hashlib
from decimal import Decimal, InvalidOperation

from cryptography.fernet import Fernet, InvalidToken

from app.config import FERNET_KEY, RECEIPT_SALT

_fernet = Fernet(FERNET_KEY.encode())


def normalize_amount(amount) -> str:
    """Turn 1500, '1500.5', Decimal('1500.50') into one fixed text: '1500.50'."""
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"Not a valid amount: {amount!r}")
    if value <= 0:
        raise ValueError("Bid amount must be greater than 0")
    return str(value)


def encrypt_amount(amount) -> str:
    """Amount -> encrypted token (safe to store in the DB)."""
    plain = normalize_amount(amount)
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_amount(token: str) -> Decimal:
    """Encrypted token -> Decimal. Fails loudly if token was altered."""
    try:
        plain = _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("Bid token is invalid or was tampered with")
    return Decimal(plain)


def make_bid_hash(tender_id: int, vendor_id: int, amount, submitted_at: str) -> str:
    """SHA-256 receipt. Same inputs -> same hash. Any change -> new hash."""
    payload = f"{tender_id}|{vendor_id}|{normalize_amount(amount)}|{submitted_at}|{RECEIPT_SALT}"
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_bid_hash(tender_id, vendor_id, amount, submitted_at, receipt: str) -> bool:
    """Recompute the hash and compare with the receipt the vendor holds."""
    return make_bid_hash(tender_id, vendor_id, amount, submitted_at) == receipt