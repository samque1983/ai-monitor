# agent/deps.py
"""Shared FastAPI dependencies."""
import os

from agent.db import AgentDB

_db: AgentDB | None = None
_db_path: str | None = None


def get_db() -> AgentDB:
    """Lazy singleton that respects AGENT_DB_PATH env var (supports test reloads)."""
    global _db, _db_path
    current_path = os.environ.get("AGENT_DB_PATH", "data/agent.db")
    if _db is None or current_path != _db_path:
        os.makedirs(os.path.dirname(current_path) if "/" in current_path else ".", exist_ok=True)
        _db = AgentDB(current_path)
        _db_path = current_path
    return _db
