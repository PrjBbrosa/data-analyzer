"""QSettings-backed recent files / projects store.

Window-free: this module must not import ``ui.main_window`` or ``ui_kit``.
The production factory is ``QSettings("MF4Analyzer", "DataAnalyzer")``; tests
inject ``settings_factory`` (and MainWindow passes the isolatable Inspector
factory so UI tests never touch the live store).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QSettings


logger = logging.getLogger(__name__)

SETTINGS_ORG = "MF4Analyzer"
SETTINGS_APP = "DataAnalyzer"
KEY_RECENT_V1 = "files/recent_v1"

KIND_FILE = "file"
KIND_PROJECT = "project"
_KINDS = frozenset({KIND_FILE, KIND_PROJECT})

_SEP = "  ·  "
_FILENAME_MAX = 40
_MISSING_SUFFIX = "  （未找到）"


@dataclass(frozen=True)
class RecentEntry:
    path: str
    kind: str
    opened_at: str


def _default_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def normalize_recent_path(path) -> str:
    text = os.fspath(path).strip()
    if not text:
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(text)))


def _path_identity(path: str) -> str:
    return os.path.normcase(path)


def _ellipsis_middle(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len == 1:
        return "…"
    inner = max_len - 1
    left = inner // 2
    right = inner - left
    if right <= 0:
        return text[:left] + "…"
    return text[:left] + "…" + text[-right:]


def _fold_home(parent: str, home: str) -> str:
    home = os.path.normpath(os.fspath(home))
    parent_norm = os.path.normpath(parent)
    home_key = os.path.normcase(home)
    parent_key = os.path.normcase(parent_norm)
    if parent_key == home_key:
        return "~"
    prefix = home.rstrip("\\/") + os.sep
    if parent_key.startswith(os.path.normcase(prefix)):
        return "~" + parent_norm[len(home):]
    return parent


def format_recent_label(path, *, max_chars: int = 56, home=None) -> str:
    """``filename  ·  parent_dir`` with ``~`` folding and middle ellipsis."""
    raw = os.fspath(path)
    p = Path(raw)
    filename = p.name or raw
    parent = str(p.parent)
    if home is None:
        home = str(Path.home())
    parent = _fold_home(parent, home)
    if len(filename) > _FILENAME_MAX:
        filename = _ellipsis_middle(filename, _FILENAME_MAX)
    label = f"{filename}{_SEP}{parent}"
    if len(label) <= max_chars:
        return label
    budget = max_chars - len(filename) - len(_SEP)
    parent = _ellipsis_middle(parent, max(0, budget))
    return f"{filename}{_SEP}{parent}"


def format_opened_at(opened_at: str) -> str:
    try:
        dt = datetime.fromisoformat(opened_at)
    except (TypeError, ValueError):
        return str(opened_at)
    return dt.strftime("%Y-%m-%d %H:%M")


def format_recent_tooltip(entry: RecentEntry) -> str:
    return f"{entry.path}\n最近打开 {format_opened_at(entry.opened_at)}"


def missing_recent_label(label: str) -> str:
    return f"{label}{_MISSING_SUFFIX}"


class RecentFilesStore:
    """Owns ``files/recent_v1`` in one ``QSettings`` backend."""

    def __init__(self, settings_factory=None, *, max_files: int = 8, max_projects: int = 4):
        self._settings_factory = settings_factory
        self._settings_obj = None
        self._max_files = int(max_files)
        self._max_projects = int(max_projects)
        self._corrupt_warned = False

    def _settings(self) -> QSettings:
        if self._settings_obj is None:
            factory = self._settings_factory
            if factory is None:
                self._settings_obj = _default_settings()
            elif callable(factory):
                self._settings_obj = factory()
            else:
                self._settings_obj = factory
        return self._settings_obj

    @staticmethod
    def exists(entry: RecentEntry) -> bool:
        try:
            return Path(entry.path).exists()
        except OSError:
            return False

    def record_file(self, path) -> None:
        self._record(path, KIND_FILE)

    def record_project(self, path) -> None:
        self._record(path, KIND_PROJECT)

    def entries(self, kind: str) -> tuple[RecentEntry, ...]:
        return tuple(entry for entry in self._load() if entry.kind == kind)

    def remove(self, path) -> None:
        identity = _path_identity(normalize_recent_path(path))
        if not identity:
            return
        kept = [
            entry for entry in self._load()
            if _path_identity(entry.path) != identity
        ]
        self._save(kept)

    def clear(self) -> None:
        self._save([])

    def _record(self, path, kind: str) -> None:
        normalized = normalize_recent_path(path)
        if not normalized or kind not in _KINDS:
            return
        identity = _path_identity(normalized)
        now = datetime.now().astimezone().replace(microsecond=0).isoformat()
        entries = [
            entry for entry in self._load()
            if _path_identity(entry.path) != identity
        ]
        entries.insert(0, RecentEntry(path=normalized, kind=kind, opened_at=now))
        self._save(self._evict(entries))

    def _evict(self, entries: list[RecentEntry]) -> list[RecentEntry]:
        n_files = 0
        n_projects = 0
        kept: list[RecentEntry] = []
        for entry in entries:
            if entry.kind == KIND_FILE:
                if n_files >= self._max_files:
                    continue
                n_files += 1
            elif entry.kind == KIND_PROJECT:
                if n_projects >= self._max_projects:
                    continue
                n_projects += 1
            else:
                continue
            kept.append(entry)
        return kept

    def _load(self) -> list[RecentEntry]:
        try:
            raw = self._settings().value(KEY_RECENT_V1, "")
        except Exception:
            self._warn_corrupt("failed to read %s", KEY_RECENT_V1)
            return []
        if raw in (None, ""):
            return []
        if not isinstance(raw, str):
            self._warn_corrupt("recent files payload is not a JSON string")
            return []
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            self._warn_corrupt("recent files JSON is corrupt")
            return []
        if not isinstance(data, list):
            self._warn_corrupt("recent files payload is not a list")
            return []
        parsed: list[RecentEntry] = []
        for item in data:
            entry = self._parse_item(item)
            if entry is None:
                self._warn_corrupt("recent files entry missing fields")
                return []
            parsed.append(entry)
        return parsed

    def _parse_item(self, item) -> RecentEntry | None:
        if not isinstance(item, dict):
            return None
        path = item.get("path")
        kind = item.get("kind")
        opened_at = item.get("opened_at")
        if not isinstance(path, str) or not path.strip():
            return None
        if kind not in _KINDS:
            return None
        if not isinstance(opened_at, str) or not opened_at.strip():
            return None
        return RecentEntry(path=path, kind=kind, opened_at=opened_at)

    def _save(self, entries: list[RecentEntry]) -> None:
        payload = [
            {"path": entry.path, "kind": entry.kind, "opened_at": entry.opened_at}
            for entry in entries
        ]
        self._settings().setValue(
            KEY_RECENT_V1, json.dumps(payload, ensure_ascii=False),
        )
        self._corrupt_warned = False

    def _warn_corrupt(self, message: str, *args) -> None:
        if self._corrupt_warned:
            return
        self._corrupt_warned = True
        logger.warning(message, *args)
