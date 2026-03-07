import os
import tempfile
import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Give each test its own fresh SQLite database."""
    tmp = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("AGENT_DB_PATH", tmp)

    # Reset the module-level db singleton so _get_db() re-initializes with the temp path
    import agent.main as main_module
    original_db = main_module.db
    main_module.db = None

    yield

    # Teardown: close and discard temp db
    if main_module.db is not None:
        try:
            main_module.db.close()
        except Exception:
            pass
    main_module.db = original_db
    if os.path.exists(tmp):
        os.unlink(tmp)
