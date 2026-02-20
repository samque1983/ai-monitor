import os
import tempfile
import yaml
import pytest
from src.config import load_config


def test_load_config_returns_all_sections():
    """Config must contain csv_url, ibkr, data, reports, schedule sections."""
    config = load_config("config.yaml")
    assert "csv_url" in config
    assert "ibkr" in config
    assert "data" in config
    assert "reports" in config
    assert "schedule" in config


def test_load_config_ibkr_defaults():
    """IBKR config must have host, port, client_id, timeout."""
    config = load_config("config.yaml")
    assert config["ibkr"]["host"] == "127.0.0.1"
    assert isinstance(config["ibkr"]["port"], int)
    assert isinstance(config["ibkr"]["client_id"], int)


def test_load_config_missing_file_raises():
    """Loading a nonexistent config file should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")


def test_load_config_custom_file():
    """Config should load from any valid YAML file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({
            "csv_url": "https://example.com/test.csv",
            "ibkr": {"host": "localhost", "port": 4002, "client_id": 2, "timeout": 10},
            "data": {"iv_history_db": "test.db", "price_period": "6mo"},
            "reports": {"output_dir": "test_reports", "log_dir": "test_logs"},
            "schedule": {"timezone": "UTC", "run_time": "12:00"},
        }, f)
        tmp_path = f.name
    try:
        config = load_config(tmp_path)
        assert config["csv_url"] == "https://example.com/test.csv"
        assert config["ibkr"]["port"] == 4002
    finally:
        os.unlink(tmp_path)
