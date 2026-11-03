from __future__ import annotations

import importlib.util
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from app.database import Base
from app import models  # noqa: F401 - registers shared tables on Base.metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("Missing DATABASE_URL in .env; see the repository .env.example")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# Register auction-owned models when that module is present in an integrated tree.
try:
    auction_models = importlib.util.find_spec("app.auction.models")
except ModuleNotFoundError:
    auction_models = None
if auction_models is not None:
    from app.auction import models as auction_models_module  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
