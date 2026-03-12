# tests/test_dashboard_routes.py
import pytest
from fastapi.testclient import TestClient


def test_templates_dir_exists():
    """Jinja2 templates directory must exist."""
    import os
    assert os.path.isdir("agent/templates"), "agent/templates/ not found"


def test_jinja2_importable():
    """jinja2 must be installed."""
    import jinja2  # noqa: F401
