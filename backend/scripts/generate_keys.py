# scripts/generate_keys.py
# Run ONCE:  python scripts/generate_keys.py
# Copy the printed lines into backend/.env (never commit .env).
import secrets
from cryptography.fernet import Fernet

print("FERNET_KEY=" + Fernet.generate_key().decode())
print("RECEIPT_SALT=" + secrets.token_hex(16))