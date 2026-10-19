# app/database.py
# Creates the DB connection. Models (Day 2) will inherit from Base.
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """FastAPI dependency: one DB session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_connection() -> bool:
    """Runs SELECT 1. True means the database is reachable."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1