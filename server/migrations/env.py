"""Alembic environment cho OGK Server."""
from alembic import context
from sqlalchemy import pool

import server.models  # noqa: F401  (đăng ký toàn bộ model vào metadata)
from server.models.base import Base
from server.models.database import DATABASE_URL, create_ogk_engine

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.attributes.get("url") or DATABASE_URL
    engine = create_ogk_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)  # SQLite cần batch cho ALTER
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
