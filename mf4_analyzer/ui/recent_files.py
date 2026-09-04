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
import unicodedata
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

    def __init__(self, settings_factory=None, *, max_files: int = 40, max_projects: int = 10):
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

    def all_entries(self) -> tuple[RecentEntry, ...]:
        """Return the persisted global MRU sequence across kinds."""
        return tuple(self._load())

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


# Match quality, lower is better. These integers are the ranking contract.
_TIER_FILENAME_EXACT = 0
_TIER_FILENAME_PREFIX = 1
_TIER_FILENAME_SUBSTRING = 2
_TIER_FILENAME_SUBSEQUENCE = 3
_TIER_DIR_SEGMENT_PREFIX = 4
_TIER_PATH_SUBSTRING = 5
_TIER_PATH_SUBSEQUENCE = 6


@dataclass(frozen=True)
class RecentMatch:
    """Immutable search projection for one recent entry."""

    entry: RecentEntry
    filename: str
    display_parent: str
    name_spans: tuple[tuple[int, int], ...]
    path_spans: tuple[tuple[int, int], ...]
    rank: tuple


def _display_parent(path: str, home: str) -> str:
    parent = str(Path(path).parent)
    return _fold_home(parent, home)


def _normalize_mapped(text: str) -> tuple[str, tuple[int, ...]]:
    """NFKC + casefold + slash-unify, mapping each output char to a source index."""
    out: list[str] = []
    index_map: list[int] = []
    for src_i, char in enumerate(text):
        if char in "\\/":
            folded = "/"
        else:
            folded = unicodedata.normalize("NFKC", char).casefold()
        for out_ch in folded:
            out.append(out_ch)
            index_map.append(src_i)
    return "".join(out), tuple(index_map)


def _source_span(norm_start: int, norm_end: int, index_map: tuple[int, ...]) -> tuple[int, int]:
    if norm_end <= norm_start or not index_map:
        return (0, 0)
    src_start = index_map[norm_start]
    src_end = index_map[norm_end - 1] + 1
    if src_end < src_start:
        src_end = src_start + 1
    return (src_start, src_end)


def _merge_spans(spans: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    if not spans:
        return ()
    ordered = sorted(span for span in spans if span[1] > span[0])
    if not ordered:
        return ()
    merged: list[list[int]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        last = merged[-1]
        if start <= last[1]:
            if end > last[1]:
                last[1] = end
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def _spans_from_positions(
    positions: list[int], index_map: tuple[int, ...]
) -> tuple[tuple[int, int], ...]:
    if not positions:
        return ()
    spans: list[tuple[int, int]] = []
    run_start = positions[0]
    prev = positions[0]
    for pos in positions[1:]:
        if pos == prev + 1:
            prev = pos
            continue
        spans.append(_source_span(run_start, prev + 1, index_map))
        run_start = pos
        prev = pos
    spans.append(_source_span(run_start, prev + 1, index_map))
    return _merge_spans(spans)


def _substring_hit(haystack: str, token: str) -> tuple[int, int] | None:
    if not token or not haystack:
        return None
    start = haystack.find(token)
    if start < 0:
        return None
    return (start, 0)


def _subsequence_hit(haystack: str, token: str) -> tuple[int, int, list[int]] | None:
    if not token or not haystack:
        return None
    positions: list[int] = []
    cursor = 0
    for char in token:
        found = haystack.find(char, cursor)
        if found < 0:
            return None
        positions.append(found)
        cursor = found + 1
    start = positions[0]
    gap = positions[-1] - positions[0] - (len(token) - 1)
    return (start, gap, positions)


def _dir_segment_prefix_hit(haystack: str, token: str) -> int | None:
    if not token or not haystack:
        return None
    offset = 0
    length = len(haystack)
    while offset <= length:
        if offset == length:
            return None
        end = haystack.find("/", offset)
        if end < 0:
            end = length
        segment = haystack[offset:end]
        if segment.startswith(token):
            return offset
        if end == length:
            return None
        offset = end + 1
    return None


def _better_hit(left, right) -> bool:
    if right is None:
        return False
    if left is None:
        return True
    return (right[0], right[1], right[2]) < (left[0], left[1], left[2])


def _field_best(
    haystack: str,
    token: str,
    *,
    filename: bool,
) -> tuple[int, int, int, list[int]] | None:
    """Return ``(tier, start, gap, norm_positions)`` for one field, or None."""
    if filename:
        if haystack == token:
            return (_TIER_FILENAME_EXACT, 0, 0, list(range(len(token))))
        if haystack.startswith(token):
            return (_TIER_FILENAME_PREFIX, 0, 0, list(range(len(token))))
        sub = _substring_hit(haystack, token)
        if sub is not None:
            start, gap = sub
            return (
                _TIER_FILENAME_SUBSTRING,
                start,
                gap,
                list(range(start, start + len(token))),
            )
        seq = _subsequence_hit(haystack, token)
        if seq is not None:
            start, gap, positions = seq
            return (_TIER_FILENAME_SUBSEQUENCE, start, gap, positions)
        return None

    best: tuple[int, int, int, list[int]] | None = None
    segment_at = _dir_segment_prefix_hit(haystack, token)
    if segment_at is not None:
        best = (
            _TIER_DIR_SEGMENT_PREFIX,
            segment_at,
            0,
            list(range(segment_at, segment_at + len(token))),
        )
    sub = _substring_hit(haystack, token)
    if sub is not None:
        start, gap = sub
        candidate = (
            _TIER_PATH_SUBSTRING,
            start,
            gap,
            list(range(start, start + len(token))),
        )
        if _better_hit(best, candidate):
            best = candidate
    seq = _subsequence_hit(haystack, token)
    if seq is not None:
        start, gap, positions = seq
        candidate = (_TIER_PATH_SUBSEQUENCE, start, gap, positions)
        if _better_hit(best, candidate):
            best = candidate
    return best


def _visible_highlight(
    haystack: str,
    index_map: tuple[int, ...],
    token: str,
) -> tuple[tuple[int, int], ...]:
    sub = _substring_hit(haystack, token)
    if sub is not None:
        start, _gap = sub
        return (_source_span(start, start + len(token), index_map),)
    seq = _subsequence_hit(haystack, token)
    if seq is None:
        return ()
    _start, _gap, positions = seq
    return _spans_from_positions(positions, index_map)


def match_recent_entries(
    entries: tuple[RecentEntry, ...],
    query: str,
    *,
    home: str | None = None,
) -> tuple[RecentMatch, ...]:
    """Pure in-memory matcher. No QSettings, Path.exists, icons, or widgets."""
    if home is None:
        home = str(Path.home())
    prepared = []
    for index, entry in enumerate(entries):
        filename = Path(entry.path).name or entry.path
        display_parent = _display_parent(entry.path, home)
        filename_norm, filename_map = _normalize_mapped(filename)
        parent_norm, parent_map = _normalize_mapped(display_parent)
        raw_norm, raw_map = _normalize_mapped(entry.path)
        prepared.append(
            (
                index,
                entry,
                filename,
                display_parent,
                filename_norm,
                filename_map,
                parent_norm,
                parent_map,
                raw_norm,
                raw_map,
            )
        )

    tokens = [
        _normalize_mapped(part)[0]
        for part in query.split()
        if part
    ]
    tokens = [token for token in tokens if token]
    if not tokens:
        return tuple(
            RecentMatch(
                entry=entry,
                filename=filename,
                display_parent=display_parent,
                name_spans=(),
                path_spans=(),
                rank=(index,),
            )
            for index, entry, filename, display_parent, *_rest in prepared
        )

    matches: list[RecentMatch] = []
    for (
        index,
        entry,
        filename,
        display_parent,
        filename_norm,
        filename_map,
        parent_norm,
        parent_map,
        raw_norm,
        raw_map,
    ) in prepared:
        token_keys: list[tuple[int, int, int]] = []
        name_spans: list[tuple[int, int]] = []
        path_spans: list[tuple[int, int]] = []
        rejected = False
        for token in tokens:
            filename_hit = _field_best(filename_norm, token, filename=True)
            parent_hit = _field_best(parent_norm, token, filename=False)
            raw_hit = _field_best(raw_norm, token, filename=False)
            best = None
            for hit in (filename_hit, parent_hit, raw_hit):
                if hit is None:
                    continue
                key = (hit[0], hit[1], hit[2])
                if best is None or key < best[0]:
                    best = (key, hit)
            if best is None:
                rejected = True
                break
            token_keys.append(best[0])
            name_spans.extend(_visible_highlight(filename_norm, filename_map, token))
            path_spans.extend(_visible_highlight(parent_norm, parent_map, token))
        if rejected:
            continue
        min_tier = min(key[0] for key in token_keys)
        max_tier = max(key[0] for key in token_keys)
        start_sum = sum(key[1] for key in token_keys)
        gap_sum = sum(key[2] for key in token_keys)
        matches.append(
            RecentMatch(
                entry=entry,
                filename=filename,
                display_parent=display_parent,
                name_spans=_merge_spans(name_spans),
                path_spans=_merge_spans(path_spans),
                rank=(min_tier, max_tier, start_sum, gap_sum, index),
            )
        )
    matches.sort(key=lambda item: item.rank)
    return tuple(matches)
