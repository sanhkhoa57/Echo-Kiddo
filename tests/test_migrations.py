"""Alembic: migration đầu tiên phải tạo đủ schema và khớp với model hiện tại."""
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from server.models.base import Base
from server.models.database import create_ogk_engine

INI = Path(__file__).resolve().parent.parent / "server" / "alembic.ini"


def _cfg(engine):
    cfg = Config(str(INI))
    cfg.attributes["url"] = str(engine.url)
    return cfg


def test_migration_upgrade_matches_models_and_downgrades(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    engine = create_ogk_engine(url)
    cfg = _cfg(engine)

    command.upgrade(cfg, "head")
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Model lệch so với migration: {diff}"

    command.downgrade(cfg, "base")
    assert set(Base.metadata.tables).isdisjoint(inspect(engine).get_table_names())
