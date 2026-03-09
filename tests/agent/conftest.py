import os
import tempfile
import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Give each test its own fresh SQLite database."""
    tmp = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("AGENT_DB_PATH", tmp)

    # Reset the deps singleton so _get_db() re-initializes with the temp path
    import agent.deps as deps_module
    original_db = deps_module._db
    original_path = deps_module._db_path
    deps_module._db = None
    deps_module._db_path = None

    yield

    # Teardown: close and discard temp db
    if deps_module._db is not None:
        try:
            deps_module._db.close()
        except Exception:
            pass
    deps_module._db = original_db
    deps_module._db_path = original_path
    if os.path.exists(tmp):
        os.unlink(tmp)
