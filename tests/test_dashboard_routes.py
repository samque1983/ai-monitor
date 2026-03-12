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


def test_nav_partial_exists():
    import os
    assert os.path.isfile("agent/templates/_nav.html")

def test_nav_partial_has_all_pages():
    content = open("agent/templates/_nav.html").read()
    assert "/dashboard" in content
    assert "/risk-report" in content
    assert "/chat" in content
    assert "/watchlist" in content

def test_nav_partial_active_variable():
    """_nav.html must use active_page variable for highlighting."""
    content = open("agent/templates/_nav.html").read()
    assert "active_page" in content
