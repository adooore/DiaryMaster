from __future__ import annotations

import os
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = DEMO_ROOT / "workspace"
WEB_DIR = DEMO_ROOT / "web"

ENV_API_KEY = "DEEPSEEK_API_KEY"
HOST = os.environ.get("DIARYMASTER_HOST") or os.environ.get("DEEPNOTE_HOST", "127.0.0.1")
PORT = int(os.environ.get("DIARYMASTER_PORT") or os.environ.get("DEEPNOTE_PORT", "8765"))


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(DEMO_ROOT / ".env")
    load_dotenv(DEMO_ROOT.parent / "DeepNote" / ".env")


def get_api_key() -> str:
    load_dotenv_if_available()
    return os.environ.get(ENV_API_KEY, "").strip()
