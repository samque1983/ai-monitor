# agent/config.py
import os
from dotenv import load_dotenv

load_dotenv()


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
