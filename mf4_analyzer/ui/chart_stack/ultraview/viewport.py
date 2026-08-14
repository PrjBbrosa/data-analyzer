"""Qt-free UltraView board viewport math (zoom, pan, LOD, persistence).

Screen zoom must not change export compositor metrics. ``grid_metrics`` keeps
a fixed ``GRID_ROW_HEIGHT``, so passing a zoomed viewport alone would widen
columns without raising rows. The free-grid screen path therefore scales the
computed ``GridMetrics`` after measuring the unzoomed viewport (spike option B).
Template boards still use option A: ``logical_board_size`` / ``slot_rects`` see
a zoomed viewport or content rect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping
import math

from .free_grid import GridMetrics

ZOOM_MIN = 0.25
ZOOM_MAX = 2.0
ZOOM_DEFAULT = 1.0
ZOOM_BUTTON_STEP = 0.10
ZOOM_WHEEL_BASE = 1.1
SMOOTH_DELAY_MS = 300
QUALITY_FAST = "fast"
QUALITY_SMOOTH = "smooth"

LOD_FULL = "full"
LOD_NO_FOOTER = "no_footer"
LOD_TITLE_ONLY = "title_only"
LOD_FOOTER_HIDE = 0.60
LOD_TITLE_ONLY_ZOOM = 0.40
LOD_HYSTERESIS = 0.04
FOCUS_PREVIEW_RATIO = 0.75

ViewportPoint = tuple[float, float]


def clamp_zoom(zoom: float) -> float:
    try:
        value = float(zoom)
    except (TypeError, ValueError):
        return ZOOM_DEFAULT
    if value != value:  # NaN
        return ZOOM_DEFAULT
    return min(ZOOM_MAX, max(ZOOM_MIN, value))


def zoom_percent(zoom: float) -> int:
    return int(round(clamp_zoom(zoom) * 100.0))


def zoomed_viewport_size(
    viewport_size: tuple[int, int], zoom: float
) -> tuple[int, int]:
    """Spike option A: scale the viewport passed into template geometry."""
    z = clamp_zoom(zoom)
    width, height = int(viewport_size[0]), int(viewport_size[1])
    return (
        max(1, int(round(width * z))),
        max(1, int(round(height * z))),
    )


def scale_grid_metrics(metrics: GridMetrics, zoom: float) -> GridMetrics:
    """Spike option B: scale every linear free-grid metric uniformly."""
    z = clamp_zoom(zoom)
    if abs(z - 1.0) < 1e-12:
        return metrics

    def _scale(value: int, *, min_value: int) -> int:
        return max(min_value, int(round(int(value) * z)))

    return GridMetrics(
        board_width=_scale(metrics.board_width, min_value=1),
        board_height=_scale(metrics.board_height, min_value=1),
        column_width=_scale(metrics.column_width, min_value=1),
        row_height=_scale(metrics.row_height, min_value=1),
        gutter=_scale(metrics.gutter, min_value=0),
        padding=_scale(metrics.padding, min_value=0),
    )


def zoom_at_cursor(
    zoom_before: float,
    zoom_after: float,
    cursor_in_viewport: ViewportPoint,
    scroll_offset: ViewportPoint,
    origin: ViewportPoint = (0.0, 0.0),
) -> ViewportPoint:
    """Return the scroll offset that keeps the logical point under the cursor.

    ``origin`` is the chrome-safe parking offset of the board inside the
    full-bleed scroll host.  Fit keeps scroll at 0 so content sits at
    ``origin``; zoom then lets that content travel under the floating chrome.
    """
    before = clamp_zoom(zoom_before)
    after = clamp_zoom(zoom_after)
    cursor_x, cursor_y = float(cursor_in_viewport[0]), float(cursor_in_viewport[1])
    scroll_x, scroll_y = float(scroll_offset[0]), float(scroll_offset[1])
    origin_x, origin_y = float(origin[0]), float(origin[1])
    logical_x = (scroll_x + cursor_x - origin_x) / before
    logical_y = (scroll_y + cursor_y - origin_y) / before
    return (
        logical_x * after + origin_x - cursor_x,
        logical_y * after + origin_y - cursor_y,
    )


def fit_zoom(
    board_size: tuple[float, float], viewport_size: tuple[float, float]
) -> float:
    """Largest zoom that fits the 1x board in the visible viewport."""
    board_w = max(1.0, float(board_size[0]))
    board_h = max(1.0, float(board_size[1]))
    view_w = max(1.0, float(viewport_size[0]))
    view_h = max(1.0, float(viewport_size[1]))
    return clamp_zoom(min(view_w / board_w, view_h / board_h))


def zoom_to_rect(
    rect: tuple[float, float, float, float],
    viewport_size: tuple[float, float],
    *,
    margin: float = 0.08,
) -> tuple[float, ViewportPoint]:
    """Return ``(zoom, center)`` so ``rect`` fills the viewport with a margin."""
    _x, _y, width, height = (float(part) for part in rect)
    view_w = max(1.0, float(viewport_size[0]))
    view_h = max(1.0, float(viewport_size[1]))
    usable_w = max(1.0, view_w * (1.0 - 2.0 * margin))
    usable_h = max(1.0, view_h * (1.0 - 2.0 * margin))
    zoom = clamp_zoom(min(usable_w / max(1.0, width), usable_h / max(1.0, height)))
    return zoom, rect_center(rect)


def rect_center(rect: tuple[float, float, float, float]) -> ViewportPoint:
    x, y, width, height = (float(part) for part in rect)
    return (x + width / 2.0, y + height / 2.0)


def center_from_scroll(
    scroll_offset: ViewportPoint,
    viewport_size: tuple[float, float],
    zoom: float,
) -> ViewportPoint:
    z = clamp_zoom(zoom)
    return (
        (float(scroll_offset[0]) + float(viewport_size[0]) / 2.0) / z,
        (float(scroll_offset[1]) + float(viewport_size[1]) / 2.0) / z,
    )


def scroll_for_center(
    center: ViewportPoint,
    viewport_size: tuple[float, float],
    zoom: float,
) -> ViewportPoint:
    z = clamp_zoom(zoom)
    return (
        float(center[0]) * z - float(viewport_size[0]) / 2.0,
        float(center[1]) * z - float(viewport_size[1]) / 2.0,
    )


def wheel_event_delta_y(angle_delta_y: float, pixel_delta_y: float = 0.0) -> float:
    """Return a 120-unit-notch-equivalent wheel delta for zoom.

    Cocoa trackpad events often arrive with ``angleDelta == 0`` and a
    nonzero ``pixelDelta``. Treat the pixel value on the same 120-unit
    scale so pinch-as-wheel still zooms.
    """
    angle = float(angle_delta_y)
    if angle:
        return angle
    return float(pixel_delta_y)


def wheel_zoom_factor(angle_delta_y: float, pixel_delta_y: float = 0.0) -> float:
    steps = wheel_event_delta_y(angle_delta_y, pixel_delta_y) / 120.0
    if steps == 0.0:
        return 1.0
    return ZOOM_WHEEL_BASE ** steps


def lod_level(zoom: float, previous: str | None = None) -> str:
    """Fixed chrome bands with hysteresis so the threshold does not chatter."""
    z = clamp_zoom(zoom)
    current = previous if previous in {LOD_FULL, LOD_NO_FOOTER, LOD_TITLE_ONLY} else None
    hide_footer = LOD_FOOTER_HIDE
    title_only = LOD_TITLE_ONLY_ZOOM
    if current == LOD_NO_FOOTER:
        hide_footer += LOD_HYSTERESIS
    elif current == LOD_TITLE_ONLY:
        hide_footer += LOD_HYSTERESIS
        title_only += LOD_HYSTERESIS
    elif current == LOD_FULL:
        hide_footer -= LOD_HYSTERESIS
        title_only -= LOD_HYSTERESIS
    if z < title_only:
        return LOD_TITLE_ONLY
    if z < hide_footer:
        return LOD_NO_FOOTER
    return LOD_FULL


def needs_focus_recapture(
    display_size: tuple[int, int], preview_size: tuple[int, int]
) -> bool:
    display_w, display_h = max(1, int(display_size[0])), max(1, int(display_size[1]))
    preview_w, preview_h = max(0, int(preview_size[0])), max(0, int(preview_size[1]))
    if preview_w <= 0 or preview_h <= 0:
        return True
    return (
        display_w > preview_w * FOCUS_PREVIEW_RATIO
        or display_h > preview_h * FOCUS_PREVIEW_RATIO
    )


def focus_grab_scale(
    native_size: tuple[float, float],
    target_size: tuple[float, float],
    *,
    max_edge: float,
) -> float:
    """Scale so the published preview satisfies ``needs_focus_recapture``.

    ``needs_focus_recapture`` is true while display > preview * 0.75, so the
    grab must produce at least ``display / 0.75`` pixels. Capping at
    ``max_edge`` is the reachable ceiling; callers must treat a capped
    preview as satisfied.
    """
    native_w = max(1.0, float(native_size[0]))
    native_h = max(1.0, float(native_size[1]))
    target_w = max(1.0, float(target_size[0]))
    target_h = max(1.0, float(target_size[1]))
    ratio = FOCUS_PREVIEW_RATIO if FOCUS_PREVIEW_RATIO > 0 else 0.75
    needed_w = math.ceil(target_w / ratio - 1e-9)
    needed_h = math.ceil(target_h / ratio - 1e-9)
    scale = max(needed_w / native_w, needed_h / native_h, 1.0)
    produced = max(native_w, native_h) * scale
    limit = max(1.0, float(max_edge))
    if produced > limit:
        scale *= limit / produced
    return max(1.0, float(scale))


def normalize_viewport_payload(
    raw: Any,
) -> tuple[dict[str, float], list[str]]:
    """Legalize a persisted viewport. Missing payload is a silent default."""
    warnings: list[str] = []
    if raw is None:
        return default_viewport_payload(), warnings
    if not isinstance(raw, Mapping):
        warnings.append("illegal_viewport")
        return default_viewport_payload(), warnings
    zoom = ZOOM_DEFAULT
    if "zoom" in raw:
        parsed = _try_float(raw.get("zoom"))
        if parsed is None:
            warnings.append(f"viewport_zoom_clamped: {raw.get('zoom')!r}")
        else:
            zoom = clamp_zoom(parsed)
            if zoom != parsed:
                warnings.append(f"viewport_zoom_clamped: {parsed}")
    center_x = _finite_or_warn(raw, "center_x", 0.0, warnings)
    center_y = _finite_or_warn(raw, "center_y", 0.0, warnings)
    return (
        {"zoom": float(zoom), "center_x": float(center_x), "center_y": float(center_y)},
        warnings,
    )


def default_viewport_payload() -> dict[str, float]:
    return {"zoom": ZOOM_DEFAULT, "center_x": 0.0, "center_y": 0.0}


def viewport_to_payload(state: "BoardViewport") -> dict[str, float]:
    return {
        "zoom": float(state.zoom()),
        "center_x": float(state.center()[0]),
        "center_y": float(state.center()[1]),
    }


def _try_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _finite_number(value: Any, fallback: float) -> float:
    parsed = _try_float(value)
    return fallback if parsed is None else parsed


def _finite_or_warn(
    raw: Mapping[str, Any], key: str, fallback: float, warnings: list[str]
) -> float:
    if key not in raw:
        return fallback
    parsed = _try_float(raw.get(key))
    if parsed is None:
        warnings.append(f"viewport_{key}_clamped: {raw.get(key)!r}")
        return fallback
    return parsed


@dataclass
class PanSession:
    last: ViewportPoint
    button: int = 0


@dataclass
class BoardViewport:
    """Owned zoom/pan/quality session. Widgets must not keep a parallel copy."""

    _owned_names: ClassVar[tuple[str, ...]] = (
        "_zoom",
        "_center",
        "_quality",
        "_space_down",
        "_pan",
        "_lod",
    )
    _zoom: float = field(default=ZOOM_DEFAULT, init=False)
    _center: ViewportPoint = field(default=(0.0, 0.0), init=False)
    _quality: str = field(default=QUALITY_SMOOTH, init=False)
    _space_down: bool = field(default=False, init=False)
    _pan: PanSession | None = field(default=None, init=False)
    _lod: str = field(default=LOD_FULL, init=False)

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> float:
        self._zoom = clamp_zoom(zoom)
        self._lod = lod_level(self._zoom, self._lod)
        return self._zoom

    def center(self) -> ViewportPoint:
        return self._center

    def set_center(self, center: ViewportPoint) -> None:
        self._center = (float(center[0]), float(center[1]))

    def quality(self) -> str:
        return self._quality

    def set_quality(self, quality: str) -> None:
        self._quality = QUALITY_FAST if quality == QUALITY_FAST else QUALITY_SMOOTH

    def lod(self) -> str:
        return self._lod

    def space_down(self) -> bool:
        return self._space_down

    def set_space_down(self, down: bool) -> None:
        self._space_down = bool(down)
        if not self._space_down and self._pan is not None:
            self._pan = None

    def is_panning(self) -> bool:
        return self._pan is not None

    def begin_pan(self, global_pos: ViewportPoint, button: int = 0) -> None:
        self._pan = PanSession(
            (float(global_pos[0]), float(global_pos[1])), int(button)
        )
        self._quality = QUALITY_FAST

    def update_pan(self, global_pos: ViewportPoint) -> ViewportPoint:
        if self._pan is None:
            return (0.0, 0.0)
        last_x, last_y = self._pan.last
        dx = last_x - float(global_pos[0])
        dy = last_y - float(global_pos[1])
        self._pan.last = (float(global_pos[0]), float(global_pos[1]))
        return (dx, dy)

    def end_pan(self, button: int | None = None) -> bool:
        if self._pan is None:
            return False
        if (
            button is not None
            and self._pan.button != 0
            and int(button) != self._pan.button
        ):
            return False
        self._pan = None
        return True

    def restore_payload(self, payload: Mapping[str, Any] | None) -> list[str]:
        legal, warnings = normalize_viewport_payload(payload)
        self._zoom = legal["zoom"]
        self._center = (legal["center_x"], legal["center_y"])
        self._lod = lod_level(self._zoom, None)
        return warnings
