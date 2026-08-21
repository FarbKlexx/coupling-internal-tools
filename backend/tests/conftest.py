import pytest

from app.core.kanban_db import init_schema


@pytest.fixture
def kanban_db(tmp_path, monkeypatch):
    """Point the kanban database at a fresh file for one test.

    Works because `kanban_db.db_path()` reads the environment on every call
    instead of capturing it at import time.
    """
    monkeypatch.setenv("KANBAN_DB_PATH", str(tmp_path / "kanban.db"))
    init_schema()
    return tmp_path / "kanban.db"
