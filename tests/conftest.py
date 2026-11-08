from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session
from app.db import make_engine

ROOT = Path(__file__).resolve().parents[1]

def migration_config(url):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    return config

@pytest.fixture
def database(tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.sqlite').as_posix()}"
    config = migration_config(url)
    command.upgrade(config, "head")
    engine = make_engine(url)
    yield engine, config
    engine.dispose()

@pytest.fixture
def session(database):
    with Session(database[0]) as session:
        yield session
