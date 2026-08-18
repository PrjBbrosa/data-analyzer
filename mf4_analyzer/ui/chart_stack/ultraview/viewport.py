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
ZOOM_MAX = 3.0
ZOOM_DEFAULT = 1.0
ZOOM_BUTTON_STEP = 0.10
ZOOM_WHEEL_BASE = 1.1
# zoom_to_card / focus fills the raw viewport; keep a generous frame so a
# single card does not kiss the window edge. Board Fit uses
# ``FIT_CONTENT_MARGIN`` on the chrome-safe rect instead, so these two
# constants must stay distinct.
ZOOM_TO_RECT_MARGIN = 0.08
# Board Fit ("适应内容"): a hairline inset so cards fill the dotted
# canvas instead of floating in a 6%-per-side frame. Focus keeps
# ZOOM_TO_RECT_MARGIN.
FIT_CONTENT_MARGIN = 0.02
# Board Fit fills the stage-safe fill rect (rail-clear left, SAFE_MARGIN
# top and bottom); the ceiling is the same 300% cap as wheel / focus.
# Opening UltraView uses Fit, not a leftover camera.
BOARD_FIT_ZOOM_MAX = ZOOM_MAX
# Empty-board working frame: two standard 4×3 cards placed side by side.
STANDARD_CARD_SPAN = (4, 3)
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
_LOD_LEVELS = frozenset({LOD_FULL, LOD_NO_FOOTER, LOD_TITLE_ONLY})


@dataclass(frozen=True)
class LodVisibility:
    """Presentation flags for one LOD band. Cards must not invent a second table."""

    title: bool
    type_chip: bool
    trust: bool
    preview: bool
    footer: bool
    body_actions: bool


LOD_VISIBILITY = {
    LOD_FULL: LodVisibility(
        title=True,
        type_chip=True,
        trust=True,
        preview=True,
        footer=True,
        body_actions=True,
    ),
    LOD_NO_FOOTER: LodVisibility(
        title=True,
        type_chip=True,
        trust=True,
        preview=True,
        footer=False,
        body_actions=True,
    ),
    LOD_TITLE_ONLY: LodVisibility(
        title=True,
        type_chip=True,
        trust=True,
        preview=False,
        footer=False,
        body_actions=False,
    ),
}

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
    """Spike option B: scale every linear free-grid metric uniformly.

    The rounded integer fields stay, because chrome and card sizing read them.
    The result also carries ``scale`` / ``base`` so ``free_grid``'s grid ↔
    pixel mappings can work from the unrounded 1× geometry: rounding the pitch
    before multiplying by a cell index is what made zoom non-linear and the
    cursor anchor drift by tens of pixels once the elastic origin went signed.

    ``metrics`` must be 1×.  A already-scaled input is re-derived from its own
    base so scales never compound.
    """
    base = metrics.base if metrics.base is not None else metrics
    z = clamp_zoom(zoom)
    if abs(z - 1.0) < 1e-12:
        return base

    def _scale(value: int, *, min_value: int) -> int:
        return max(min_value, int(round(int(value) * z)))

    return GridMetrics(
        board_width=_scale(base.board_width, min_value=1),
        board_height=_scale(base.board_height, min_value=1),
        column_width=_scale(base.column_width, min_value=1),
        row_height=_scale(base.row_height, min_value=1),
        gutter=_scale(base.gutter, min_value=0),
        padding=_scale(base.padding, min_value=0),
        scale=z,
        base=base,
    )


def linear_zoom_anchor(canvas_point: ViewportPoint, zoom: float) -> ViewportPoint:
    """Canvas pixel → zoom-independent anchor, for a *linearly* scaled canvas.

    Template boards scale the whole canvas by one factor, so dividing by the
    zoom is an exact inverse.  The free-grid canvas is not linear in zoom: its
    pixel map rounds each metric before multiplying by a cell index (see
    ``scale_grid_metrics`` / ``free_grid.rect_to_pixels``), so it supplies its
    own anchor pair instead of reusing this one.
    """
    z = clamp_zoom(zoom)
    return (float(canvas_point[0]) / z, float(canvas_point[1]) / z)


def linear_zoom_point(anchor: ViewportPoint, zoom: float) -> ViewportPoint:
    """Inverse of :func:`linear_zoom_anchor` at ``zoom``."""
    z = clamp_zoom(zoom)
    return (float(anchor[0]) * z, float(anchor[1]) * z)


def scroll_for_anchor(
    canvas_point: ViewportPoint,
    anchor_vp: ViewportPoint,
    origin: ViewportPoint = (0.0, 0.0),
) -> ViewportPoint:
    """Scroll offset that puts ``canvas_point`` under ``anchor_vp``.

    ``origin`` is the board canvas origin inside the full-bleed scroll host
    (fit parking, plus any zoom pad).  Callers must apply the result *after*
    the zoomed canvas is laid out and must not re-center afterwards: a later
    fit-align pass would throw the anchor away.
    """
    return (
        float(canvas_point[0]) + float(origin[0]) - float(anchor_vp[0]),
        float(canvas_point[1]) + float(origin[1]) - float(anchor_vp[1]),
    )


def canvas_point_under(
    anchor_vp: ViewportPoint,
    scroll_offset: ViewportPoint,
    origin: ViewportPoint = (0.0, 0.0),
) -> ViewportPoint:
    """Canvas-local pixel currently sitting under ``anchor_vp``."""
    return (
        float(scroll_offset[0]) + float(anchor_vp[0]) - float(origin[0]),
        float(scroll_offset[1]) + float(anchor_vp[1]) - float(origin[1]),
    )


def zoom_at(
    zoom_before: float,
    zoom_after: float,
    anchor_vp: ViewportPoint,
    scroll_offset: ViewportPoint,
    origin: ViewportPoint = (0.0, 0.0),
) -> ViewportPoint:
    """Return the scroll offset that keeps the logical point under ``anchor_vp``.

    This is the *linear* closed form.  ``page._zoom_at`` no longer calls it:
    it asks the active canvas for ``zoom_anchor_at`` / ``point_for_zoom_anchor``
    so a canvas whose pixel map is not linear in zoom anchors on the metrics it
    actually laid out with.  Template canvases implement that pair with
    :func:`linear_zoom_anchor`, which keeps this the single source of the
    linear math.

    When ``zoom_after`` clamps to ``zoom_before``, this is an identity so a
    limit hit cannot introduce a scroll jump.
    """
    before = clamp_zoom(zoom_before)
    after = clamp_zoom(zoom_after)
    point = canvas_point_under(anchor_vp, scroll_offset, origin)
    return scroll_for_anchor(
        linear_zoom_point(linear_zoom_anchor(point, before), after),
        anchor_vp,
        origin,
    )


zoom_at_cursor = zoom_at


def fit_zoom(
    board_size: tuple[float, float], viewport_size: tuple[float, float]
) -> float:
    """Largest zoom that fits ``board_size`` in the viewport, up to 300%.

    Prefer ``board_fit_zoom`` for Board Fit (margin + same ceiling) and
    ``zoom_to_rect`` for focus. Window open / first show also use
    ``board_fit_zoom`` via ``zoom_fit``.
    """
    board_w = max(1.0, float(board_size[0]))
    board_h = max(1.0, float(board_size[1]))
    view_w = max(1.0, float(viewport_size[0]))
    view_h = max(1.0, float(viewport_size[1]))
    return clamp_zoom(min(view_w / board_w, view_h / board_h))


def two_card_working_frame(metrics: GridMetrics) -> tuple[float, float]:
    """Pixel size of two standard 4×3 cards at 1× plus padding and gutter.

    Empty Board Fit targets this frame, not the 1600×1020 logical canvas
    and not the elastic extent. Callers must pass unzoomed 1× metrics.
    """
    columns = int(STANDARD_CARD_SPAN[0]) * 2
    rows = int(STANDARD_CARD_SPAN[1])
    col_w = float(metrics.column_width)
    row_h = float(metrics.row_height)
    gutter = float(metrics.gutter)
    padding = float(metrics.padding)
    width = 2.0 * padding + columns * col_w + max(0, columns - 1) * gutter
    height = 2.0 * padding + rows * row_h + max(0, rows - 1) * gutter
    return (width, height)


def board_fit_zoom(
    content_size: tuple[float, float],
    viewport_size: tuple[float, float],
    *,
    margin: float = FIT_CONTENT_MARGIN,
) -> float:
    """Board Fit zoom for a placed-card union or empty working frame.

    Fills the chrome-clear viewport with ``margin`` inset on each side.
    Amplifies a small card union up to ``ZOOM_MAX`` (300%). Window open
    uses this path.
    """
    content_w = max(1.0, float(content_size[0]))
    content_h = max(1.0, float(content_size[1]))
    view_w = max(1.0, float(viewport_size[0]))
    view_h = max(1.0, float(viewport_size[1]))
    inset = max(0.0, min(0.45, float(margin)))
    usable_w = max(1.0, view_w * (1.0 - 2.0 * inset))
    usable_h = max(1.0, view_h * (1.0 - 2.0 * inset))
    computed = min(usable_w / content_w, usable_h / content_h)
    return clamp_zoom(computed)


def zoom_to_rect(
    rect: tuple[float, float, float, float],
    viewport_size: tuple[float, float],
    *,
    margin: float = ZOOM_TO_RECT_MARGIN,
) -> tuple[float, ViewportPoint]:
    """Return ``(zoom, center)`` so ``rect`` fills the viewport with a margin.

    Focus / ``zoom_to_card`` may reach ``ZOOM_MAX`` (300%). Board Fit uses
    ``board_fit_zoom`` with the same ceiling so content fills the canvas.
    """
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
    """Scroll offset that places ``center`` in the middle of the viewport.

    100% (``zoom == 1.0``) must keep the current viewport center; page.py
    applies this after ``zoom_reset`` once the zoomed canvas is laid out.
    Do not re-park at the fit origin afterwards — that would throw the
    center away. Viewport changes must not mark Board content mutation.
    """
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
    """Fixed chrome bands with hysteresis so the threshold does not chatter.

    Hysteresis only widens the boundary that is **adjacent** to the current
    band, i.e. the one the zoom would have to cross to leave it.  Moving the
    far boundary too shifts a band the state is not even touching and lets a
    single jump land two bands away from both the static band and the sticky
    one (review 2026-08-15 P1-3: ``lod_level(0.37, FULL)`` used to return
    ``no_footer``, skipping ``title_only`` entirely, and ``_lod`` is sticky so
    the card stayed there until the next zoom change).
    """
    z = clamp_zoom(zoom)
    current = previous if previous in _LOD_LEVELS else None
    hide_footer = LOD_FOOTER_HIDE
    title_only = LOD_TITLE_ONLY_ZOOM
    if current == LOD_NO_FOOTER:
        hide_footer += LOD_HYSTERESIS
    elif current == LOD_TITLE_ONLY:
        title_only += LOD_HYSTERESIS
    elif current == LOD_FULL:
        hide_footer -= LOD_HYSTERESIS
    if z < title_only:
        return LOD_TITLE_ONLY
    if z < hide_footer:
        return LOD_NO_FOOTER
    return LOD_FULL


def lod_visibility(level: str) -> LodVisibility:
    """Return the canonical visibility row for ``level``.

    Page passes the LOD token; Card renders this table. Tests must call this
    helper instead of hard-coding a second 60/40 threshold set.
    """
    key = level if level in LOD_VISIBILITY else LOD_FULL
    return LOD_VISIBILITY[key]


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
    """Persist-legalization fallback. Open / first show use ``zoom_fit``."""
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
    origin: ViewportPoint = (0.0, 0.0)
    committed: bool = True


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

    def pan_button(self) -> int:
        return 0 if self._pan is None else int(self._pan.button)

    def pan_committed(self) -> bool:
        return bool(self._pan is not None and self._pan.committed)

    def begin_pan(
        self, global_pos: ViewportPoint, button: int = 0, *, deferred: bool = False
    ) -> None:
        pos = (float(global_pos[0]), float(global_pos[1]))
        self._pan = PanSession(
            last=pos,
            button=int(button),
            origin=pos,
            committed=not deferred,
        )
        if not deferred:
            self._quality = QUALITY_FAST

    def update_pan(
        self, global_pos: ViewportPoint, threshold: float = 0.0
    ) -> ViewportPoint:
        if self._pan is None:
            return (0.0, 0.0)
        x = float(global_pos[0])
        y = float(global_pos[1])
        if not self._pan.committed:
            origin_x, origin_y = self._pan.origin
            if abs(x - origin_x) + abs(y - origin_y) < float(threshold):
                self._pan.last = (x, y)
                return (0.0, 0.0)
            self._pan.committed = True
        last_x, last_y = self._pan.last
        dx = last_x - x
        dy = last_y - y
        self._pan.last = (x, y)
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
