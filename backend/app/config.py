# app/config.py
# One place that reads secrets from .env, so no other file touches os.environ.
import os
from dotenv import load_dotenv

load_dotenv()  # reads backend/.env into environment variables


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name} in .env - see .env.example")
    return value


DATABASE_URL = _required("DATABASE_URL")
FERNET_KEY = _required("FERNET_KEY")
RECEIPT_SALT = _required("RECEIPT_SALT")