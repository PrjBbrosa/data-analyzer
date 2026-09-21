"""Qt chart font resolution shared by foreground and batch renderers.

This module intentionally sits outside :mod:`mf4_analyzer.ui`: the batch
renderer may construct pyqtgraph scenes, but importing it must not construct
or import the application's main-window graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import os
from pathlib import Path
import sys

import numpy as np
from PyQt5.QtCore import QRect, QStandardPaths, QThread, Qt
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter,
    QRawFont,
)
from PyQt5.QtWidgets import QApplication


CHART_FONT_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "Segoe UI",
    "PingFang SC",
    "Noto Sans CJK SC",
)
# Interactive chart axis / tick measurement point size. Render defaults and
# QFontMetrics fitters must reference this symbol — not a parallel ``9`` literal.
CHART_FONT_PT = 9.0
CJK_CONTRACT_TEXT = "单帧振动加速度"
ASCII_CONTRACT_TEXT = "TraceLab"
CJK_FONT_CANDIDATES = CHART_FONT_FAMILIES
# Keyed by the exact requested size: the batch report's font scale produces
# fractional point sizes, and truncating the key would hand 12.6pt callers a
# cached 12.0pt font.
_CHART_FONT_CACHE: dict[float, QFont] = {}
_FONT_SUFFIXES = {".ttf", ".ttc", ".otf", ".otc"}
# Filename tokens for CJK-capable faces. Not a drive letter, user, or one file.
_CJK_FILE_TOKEN_RANKS: tuple[tuple[str, int], ...] = (
    ("msyh", 0),
    ("yahei", 0),
    ("pingfang", 0),
    ("notosanscjk", 0),
    ("notosanssc", 1),
    ("sourcehan", 1),
    ("simhei", 2),
    ("simsun", 2),
    ("simkai", 2),
    ("dengxian", 2),
    ("stheiti", 2),
    ("hiraginosansgb", 2),
    ("songti", 2),
    ("wqymicrohei", 3),
    ("wqyzenhei", 3),
    ("arialunicode", 3),
    ("nisc18030", 3),
)
_MAX_FONT_FILES_TO_TRY = 12
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrawableCjkFontState:
    family: str
    source: str
    path: str
    font_ids: tuple[int, ...]


_DRAWABLE_STATE: DrawableCjkFontState | None = None


def supports_contract_text(font: QFont, text: str = CJK_CONTRACT_TEXT) -> bool:
    raw = QRawFont.fromFont(font)
    if raw.isValid():
        return all(bool(raw.supportsCharacter(character)) for character in text)
    metrics = QFontMetrics(font)
    return all(bool(metrics.inFontUcs4(ord(character))) for character in text)


def _installed_families() -> set[str]:
    try:
        return set(QFontDatabase().families())
    except (RuntimeError, TypeError, ValueError):
        return set()


def _is_drawable_contract_font(font: QFont) -> bool:
    cjk_proof = header_ink_proof(font, CJK_CONTRACT_TEXT)
    if not cjk_proof["pass"]:
        return False
    ascii_proof = header_ink_proof(font, ASCII_CONTRACT_TEXT)
    return bool(ascii_proof["pass"])


def _first_drawable_chart_family() -> QFont | None:
    installed = _installed_families()
    for family in CHART_FONT_FAMILIES:
        if family not in installed:
            continue
        font = QFont(family, 12)
        if _is_drawable_contract_font(font):
            return font
    return None


def _windows_fonts_directory() -> Path | None:
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if not windir:
        return None
    path = Path(windir) / "Fonts"
    return path if path.is_dir() else None


def _add_font_directory(found: list[Path], seen: set[Path], path: Path) -> None:
    try:
        if not path.is_dir():
            return
        resolved = path.resolve()
    except OSError:
        return
    if resolved in seen:
        return
    seen.add(resolved)
    found.append(path)


def system_font_directories() -> tuple[Path, ...]:
    """Return existing font directories from the current machine, not a fixed path."""
    found: list[Path] = []
    seen: set[Path] = set()
    for raw in QStandardPaths.standardLocations(QStandardPaths.FontsLocation):
        _add_font_directory(found, seen, Path(raw))
    windir_fonts = _windows_fonts_directory()
    if windir_fonts is not None:
        _add_font_directory(found, seen, windir_fonts)
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        _add_font_directory(
            found, seen, Path(local_app) / "Microsoft" / "Windows" / "Fonts",
        )
    home = Path.home()
    if sys.platform == "darwin":
        _add_font_directory(found, seen, Path("/System/Library/Fonts"))
        _add_font_directory(found, seen, Path("/System/Library/Fonts/Supplemental"))
        _add_font_directory(found, seen, Path("/Library/Fonts"))
        _add_font_directory(found, seen, home / "Library" / "Fonts")
    elif sys.platform.startswith("linux"):
        _add_font_directory(found, seen, Path("/usr/share/fonts"))
        _add_font_directory(found, seen, Path("/usr/local/share/fonts"))
        _add_font_directory(found, seen, home / ".fonts")
        _add_font_directory(found, seen, home / ".local" / "share" / "fonts")
    return tuple(found)


def _windows_registry_font_files() -> tuple[Path, ...]:
    if sys.platform != "win32":
        return ()
    try:
        import winreg
    except ImportError:
        return ()
    fonts_dir = _windows_fonts_directory()
    wanted = tuple(family.casefold() for family in CHART_FONT_FAMILIES)
    found: list[Path] = []
    seen: set[Path] = set()
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    for hive, subkey in roots:
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            continue
        try:
            index = 0
            while True:
                try:
                    name, value, _reg_type = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                label = str(name).split("(")[0].strip().casefold()
                if not any(family in label or label in family for family in wanted):
                    continue
                raw = str(value).strip().strip('"')
                if not raw:
                    continue
                path = Path(raw)
                if not path.is_absolute():
                    if fonts_dir is None:
                        continue
                    path = fonts_dir / raw
                try:
                    if not path.is_file() or not os.access(path, os.R_OK):
                        continue
                    resolved = path.resolve()
                except OSError:
                    continue
                if resolved in seen or path.suffix.lower() not in _FONT_SUFFIXES:
                    continue
                seen.add(resolved)
                found.append(path)
        finally:
            winreg.CloseKey(key)
    return tuple(found)


def _normalized_font_token(path: Path) -> str:
    return (
        path.name.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
    )


def _font_file_rank(path: Path) -> int | None:
    token = _normalized_font_token(path)
    matched: int | None = None
    for needle, rank in _CJK_FILE_TOKEN_RANKS:
        if needle in token and (matched is None or rank < matched):
            matched = rank
    return matched


def _iter_directory_font_files(directory: Path):
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    subdirs: list[Path] = []
    for entry in entries:
        try:
            if entry.is_file() and entry.suffix.lower() in _FONT_SUFFIXES:
                yield entry
            elif entry.is_dir():
                subdirs.append(entry)
        except OSError:
            continue
    for subdir in subdirs:
        try:
            children = list(subdir.iterdir())
        except OSError:
            continue
        for entry in children:
            try:
                if entry.is_file() and entry.suffix.lower() in _FONT_SUFFIXES:
                    yield entry
            except OSError:
                continue


def discover_cjk_font_files() -> tuple[Path, ...]:
    """Return readable CJK font files from this machine's font locations."""
    ranked: list[tuple[int, str, Path]] = []
    seen: set[Path] = set()
    for path in _windows_registry_font_files():
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        ranked.append((-1, path.name.lower(), path))
    for directory in system_font_directories():
        for path in _iter_directory_font_files(directory):
            rank = _font_file_rank(path)
            if rank is None:
                continue
            try:
                if not os.access(path, os.R_OK):
                    continue
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            ranked.append((rank, path.name.lower(), path))
    ranked.sort()
    return tuple(path for _rank, _name, path in ranked)


def _font_from_application_id(font_id: int) -> QFont | None:
    if font_id == -1:
        return None
    families = tuple(QFontDatabase.applicationFontFamilies(font_id))
    for family in families:
        if not family or family.startswith("."):
            continue
        font = QFont(family, 12)
        if _is_drawable_contract_font(font):
            return font
    for family in families:
        if not family:
            continue
        font = QFont(family, 12)
        if _is_drawable_contract_font(font):
            return font
    return None


def _set_drawable_state(state: DrawableCjkFontState) -> DrawableCjkFontState:
    global _DRAWABLE_STATE
    _DRAWABLE_STATE = state
    resolve_cjk_font.cache_clear()
    _CHART_FONT_CACHE.clear()
    return state


def drawable_cjk_font_state() -> DrawableCjkFontState | None:
    return _DRAWABLE_STATE


def reset_drawable_cjk_font_cache() -> None:
    """Test helper: allow a later ``ensure_drawable_cjk_fonts`` to run again."""
    global _DRAWABLE_STATE
    _DRAWABLE_STATE = None
    resolve_cjk_font.cache_clear()
    _CHART_FONT_CACHE.clear()


def ensure_drawable_cjk_fonts() -> DrawableCjkFontState:
    """Register a drawable CJK face once on the GUI thread and cache the result.

    Family names and ``supportsCharacter`` are not enough: Qt offscreen can
    report both while painting zero ink until a readable font file is loaded
    with ``QFontDatabase.addApplicationFont``.
    """
    if _DRAWABLE_STATE is not None:
        return _DRAWABLE_STATE
    app = QApplication.instance()
    if app is None:
        raise RuntimeError(
            "drawable CJK fonts require QApplication; call ensure_app first"
        )
    if QThread.currentThread() is not app.thread():
        raise RuntimeError(
            "QFontDatabase.addApplicationFont must run on the Qt GUI thread"
        )
    named = _first_drawable_chart_family()
    if named is not None:
        return _set_drawable_state(
            DrawableCjkFontState(
                family=named.family(),
                source="family",
                path="",
                font_ids=(),
            )
        )
    font_ids: list[int] = []
    for path in discover_cjk_font_files()[:_MAX_FONT_FILES_TO_TRY]:
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            continue
        font_ids.append(font_id)
        loaded = _font_from_application_id(font_id)
        if loaded is None:
            continue
        return _set_drawable_state(
            DrawableCjkFontState(
                family=loaded.family(),
                source="file",
                path=str(path),
                font_ids=tuple(font_ids),
            )
        )
    logger.warning(
        "No drawable CJK font family or file produced ink for %s",
        CJK_CONTRACT_TEXT,
    )
    return _set_drawable_state(
        DrawableCjkFontState(family="", source="none", path="", font_ids=tuple(font_ids))
    )


@lru_cache(maxsize=1)
def resolve_cjk_font() -> QFont | None:
    """Return a chart face that covers the CJK contract *and* actually draws ink."""
    state = _DRAWABLE_STATE
    if state is not None:
        if not state.family:
            return None
        return QFont(state.family, 12)
    return _first_drawable_chart_family()


def chart_font(point_size: float = CHART_FONT_PT) -> QFont:
    """Return the resolved explicit font for pyqtgraph text and axis items."""
    cache_key = round(float(point_size), 2)
    cached = _CHART_FONT_CACHE.get(cache_key)
    if cached is not None:
        return QFont(cached)
    resolved = resolve_cjk_font()
    if resolved is not None:
        font = QFont(resolved)
        font.setPointSizeF(float(point_size))
    else:
        app = QApplication.instance()
        font = QFont(app.font() if app is not None else QFont())
        font.setPointSizeF(float(point_size))
    _CHART_FONT_CACHE[cache_key] = QFont(font)
    return font


def apply_axis_font(axis, point_size: float = CHART_FONT_PT) -> None:
    if axis is None:
        return
    font = chart_font(point_size)
    axis.setStyle(tickFont=font)
    label = getattr(axis, "label", None)
    if label is not None:
        label.setFont(font)


def apply_text_item_font(item, point_size: float = CHART_FONT_PT) -> None:
    if item is None:
        return
    target = getattr(item, "textItem", item)
    target.setFont(chart_font(point_size))


def _ink_pixels(image: QImage, background: QColor) -> int:
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    pixels = np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.width(), 4,
    )
    reference = np.array(
        [background.red(), background.green(), background.blue(), background.alpha()],
        dtype=np.uint8,
    )
    return int(np.count_nonzero(np.any(pixels != reference, axis=2)))


def _render_header(font: QFont, text: str) -> QImage:
    image = QImage(640, 72, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    painter.setPen(QColor("#273449"))
    painter.setFont(font)
    painter.drawText(QRect(12, 4, 616, 60), Qt.AlignLeft | Qt.AlignVCenter, text)
    painter.end()
    return image


def header_ink_proof(font: QFont, text: str = CJK_CONTRACT_TEXT) -> dict[str, object]:
    background = QColor("#ffffff")
    rendered = _render_header(font, text)
    empty = _render_header(font, "")
    ink_pixels = _ink_pixels(rendered, background)
    empty_ink_pixels = _ink_pixels(empty, background)
    return {
        "font": font.family(),
        "supports": supports_contract_text(font, text),
        "ink_pixels": ink_pixels,
        "empty_ink_pixels": empty_ink_pixels,
        "pass": bool(
            supports_contract_text(font, text)
            and ink_pixels > empty_ink_pixels + 120
        ),
    }


__all__ = [
    "ASCII_CONTRACT_TEXT",
    "CHART_FONT_FAMILIES",
    "CHART_FONT_PT",
    "CJK_CONTRACT_TEXT",
    "CJK_FONT_CANDIDATES",
    "DrawableCjkFontState",
    "apply_axis_font",
    "apply_text_item_font",
    "chart_font",
    "discover_cjk_font_files",
    "drawable_cjk_font_state",
    "ensure_drawable_cjk_fonts",
    "header_ink_proof",
    "reset_drawable_cjk_font_cache",
    "resolve_cjk_font",
    "supports_contract_text",
    "system_font_directories",
]
