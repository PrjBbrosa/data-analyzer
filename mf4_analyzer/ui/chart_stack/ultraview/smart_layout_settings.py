"""QSettings-backed UltraView Smart Layout policy. No MainWindow state."""
from __future__ import annotations

from PyQt5.QtCore import QSettings

from mf4_analyzer.ultraview_core.smart_layout import (
    CANONICAL_VIEWPORT,
    Density,
    Mode,
    SmartLayoutPolicy,
)

DEFAULT_MODE: Mode = "balanced"
DEFAULT_DENSITY: Density = "auto"
DEFAULT_PRESERVE_LOCKED = True

KEY_MODE = "ultraview/smart_layout/mode"
KEY_DENSITY = "ultraview/smart_layout/density"
KEY_PRESERVE_LOCKED = "ultraview/smart_layout/preserve_locked"

MODES: tuple[Mode, ...] = ("balanced", "preserve_salience", "equal_grid")
DENSITIES: tuple[Density, ...] = ("auto", "comfortable", "compact")

MODE_LABELS: dict[Mode, str] = {
    "balanced": "均衡",
    "preserve_salience": "保留主次",
    "equal_grid": "等大网格",
}
DENSITY_LABELS: dict[Density, str] = {
    "auto": "自动疏密",
    "comfortable": "宽松",
    "compact": "紧凑",
}


def _store(settings: QSettings | None = None) -> QSettings:
    return settings if settings is not None else QSettings()


def _as_bool(raw: object, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return bool(raw)


def load_smart_layout_policy(
    *,
    target_viewport: tuple[int, int] = CANONICAL_VIEWPORT,
    settings: QSettings | None = None,
) -> SmartLayoutPolicy:
    store = _store(settings)
    mode = str(store.value(KEY_MODE, DEFAULT_MODE) or DEFAULT_MODE)
    if mode not in MODES:
        mode = DEFAULT_MODE
    density = str(store.value(KEY_DENSITY, DEFAULT_DENSITY) or DEFAULT_DENSITY)
    if density not in DENSITIES:
        density = DEFAULT_DENSITY
    preserve = _as_bool(
        store.value(KEY_PRESERVE_LOCKED, DEFAULT_PRESERVE_LOCKED),
        DEFAULT_PRESERVE_LOCKED,
    )
    return SmartLayoutPolicy(
        mode=mode,  # type: ignore[arg-type]
        density=density,  # type: ignore[arg-type]
        target_viewport=tuple(target_viewport),
        preserve_locked=preserve,
    )


def set_smart_layout_mode(mode: str, settings: QSettings | None = None) -> None:
    value: Mode = mode if mode in MODES else DEFAULT_MODE  # type: ignore[assignment]
    _store(settings).setValue(KEY_MODE, value)


def set_smart_layout_density(density: str, settings: QSettings | None = None) -> None:
    value: Density = density if density in DENSITIES else DEFAULT_DENSITY  # type: ignore[assignment]
    _store(settings).setValue(KEY_DENSITY, value)


def set_smart_layout_preserve_locked(
    preserve: bool, settings: QSettings | None = None
) -> None:
    _store(settings).setValue(KEY_PRESERVE_LOCKED, bool(preserve))
