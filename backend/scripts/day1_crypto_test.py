# scripts/day1_crypto_test.py
# Run from backend/:  python -m scripts.day1_crypto_test
# Proves L1 (encryption) and L2 (hash receipt) work before any DB tables exist.
from app.auction.crypto import (
    encrypt_amount, decrypt_amount, make_bid_hash, verify_bid_hash,
)

amount = 125000.5
t1 = encrypt_amount(amount)
t2 = encrypt_amount(amount)
print("Token 1:", t1[:40], "...")
print("Token 2:", t2[:40], "...")
assert t1 != t2, "Same amount should give different tokens (random IV)"
assert decrypt_amount(t1) == decrypt_amount(t2)
print("[OK] L1 decrypt ->", decrypt_amount(t1))

tampered = t1[:-5] + ("A" if t1[-5] != "A" else "B") + t1[-4:]
try:
    decrypt_amount(tampered)
    print("[FAIL] tampered token was accepted")
except ValueError as e:
    print("[OK] L1 tamper detected ->", e)

ts = "2026-10-16T10:00:00+00:00"
receipt = make_bid_hash(7, 42, amount, ts)
print("Receipt:", receipt)
assert verify_bid_hash(7, 42, amount, ts, receipt)
assert not verify_bid_hash(7, 42, 120000, ts, receipt)
print("[OK] L2 receipt matches original, fails for changed amount")
print("\nDay 1 crypto checks passed.")