import os
import yaml


def load_config(path: str) -> dict:
    """Load configuration from a YAML file.

    Raises FileNotFoundError if the file does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r") as f:
        return yaml.safe_load(f)
