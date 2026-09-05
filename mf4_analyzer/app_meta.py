"""Single source of truth for app identity, release URL, and asset paths."""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "TraceLab"
APP_VERSION = "v8.2.2"
WINDOW_TITLE = f"{APP_NAME} {APP_VERSION}"
APP_CREDIT = "GC02689"

# Feishu release/download page opened by the status-bar update icon.
RELEASE_URL = "https://jcnubq178nzc.feishu.cn/wiki/LkfAwEotfiSO6GktmPvcYPRznhd"


def asset_path(*parts: str) -> Path:
    """Resolve a bundled asset path. PyInstaller exposes the bundle root via
    ``sys._MEIPASS``; in dev fall back to the repo root (parent of this
    package). Mirrors ``mf4_analyzer/app.py:_load_app_icon``."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base is not None else Path(__file__).resolve().parent.parent
    return root.joinpath("assets", *parts)
