"""Qt-free Card Fit DTO, scorer, and local hug solver (Spec F2/F3).

Card Fit reshapes the current card so its shell matches the preview aspect,
keeping the already-displayed scale. It never scans the full min/max board,
never calls the displacement planner, and never moves neighbours.

Scoring uses KeepAspectRatio contain with virtual upscale for aspect error
only. The on-screen renderer still uses :func:`preview_reading_box` (contain
plus no-upscale); that gutter is not a reason to collapse a large card.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from mf4_analyzer.ui.ultraview_state import (
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    GridRect,
)

from mf4_analyzer.ultraview_core.grid_geometry import (
    GridMetrics,
    HugChrome,
    hug_plot_targets as _hug_plot_targets,
    hug_span_centers as _hug_span_centers,
    plot_size_for_rect,
    preferred_hug_axis as _preferred_hug_axis,
    preferred_hug_span as _preferred_hug_span,
    rects_overlap,
    snap_plot_to_span as _snap_plot_to_span,
)

from .layouts import (
    CARD_FIT_CHROME_HEIGHT,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    CARD_IMAGE_PADDING,
)

REASON_NO_PREVIEW = "no_preview"
REASON_NO_IMPROVEMENT = "no_improvement"
REASON_NO_SPACE = "no_space"

# Chrome-quantization neighborhood around each hug snap. Not a board search.
CARD_FIT_SNAP_WINDOW = 2

CardFitReason = str | None
CardFitKey = tuple[int, int, float, int, int, float, int, int]


@dataclass(frozen=True)
class CardFitFacts:
    """Live chrome + placement facts consumed by the Card Fit solver."""

    image_logical_size: tuple[int, int] | None
    current_rect: GridRect
    metrics: GridMetrics
    header_height: int
    footer_height: int
    image_margin_x: int
    image_margin_y: int
    occupied: tuple[GridRect, ...] = ()
    min_column_span: int = GRID_MIN_COLUMN_SPAN
    max_column_span: int = GRID_MAX_COLUMN_SPAN
    min_row_span: int = GRID_MIN_ROW_SPAN
    max_row_span: int = GRID_MAX_ROW_SPAN
    safety_column_min: int = SAFETY_COLUMN_MIN
    safety_column_max: int = SAFETY_COLUMN_MAX
    safety_row_min: int = SAFETY_ROW_MIN
    safety_row_max: int = SAFETY_ROW_MAX
    orphan_height: int = 0


@dataclass(frozen=True)
class CardFitScore:
    """Lexicographic F3 hug score. Lower is better; first term must be 0."""

    crop_or_stretch_violation: int
    unused_area_ratio: float
    grows: int
    longest_unused_axis_ratio: float
    bottom_unused_ratio: float
    area_delta: int
    span_delta: int
    row_span: int
    column_span: int

    def key(self) -> CardFitKey:
        return (
            int(self.crop_or_stretch_violation),
            int(self.grows),
            float(self.unused_area_ratio),
            int(self.area_delta),
            int(self.span_delta),
            float(self.bottom_unused_ratio),
            int(self.row_span),
            int(self.column_span),
        )


@dataclass(frozen=True)
class CardFitResult:
    candidate: GridRect
    score: CardFitScore | None
    improved: bool
    reason: CardFitReason


def default_card_fit_chrome(*, footer_visible: bool = True) -> tuple[int, int, int, int]:
    """Fallback header/footer/image margins when no live card is present."""
    footer = CARD_FOOTER_HEIGHT if footer_visible else 0
    return (
        CARD_HEADER_HEIGHT,
        footer,
        CARD_IMAGE_PADDING,
        CARD_IMAGE_PADDING,
    )


def unconstrained_card_fit_facts(
    origin: GridRect,
    image_size: tuple[int, int] | None,
    metrics: GridMetrics,
    *,
    chrome_height: int | None = None,
    occupied: Sequence[GridRect] = (),
) -> CardFitFacts:
    """Build facts for the unconstrained (or caller-supplied occupied) case.

    ``chrome_height=None`` uses the live-constant split (header, footer, 2×
    image padding on both axes) so the plot area matches the renderer.
    ``chrome_height=0`` is a chrome-free search. Any other explicit value is
    treated as plot-height chrome only, matching the historical wrapper.
    """
    if chrome_height is None or chrome_height == CARD_FIT_CHROME_HEIGHT:
        header, footer, margin_x, margin_y = default_card_fit_chrome()
    elif int(chrome_height) <= 0:
        header = footer = margin_x = margin_y = 0
    else:
        header = 0
        footer = int(chrome_height)
        margin_x = 0
        margin_y = 0
    return CardFitFacts(
        image_logical_size=image_size,
        current_rect=origin,
        metrics=metrics,
        header_height=header,
        footer_height=footer,
        image_margin_x=margin_x,
        image_margin_y=margin_y,
        occupied=tuple(occupied),
    )


def fit_rect_for_aspect(
    origin: GridRect,
    image_size: tuple[int, int],
    metrics: GridMetrics,
    *,
    chrome_height: int = CARD_FIT_CHROME_HEIGHT,
) -> GridRect:
    """Unconstrained Card Fit at the pinned origin.

    Occupied neighbours are not considered here; the Card Fit command builds
    full :class:`CardFitFacts`.
    """
    image_w = max(1, int(image_size[0]))
    image_h = max(1, int(image_size[1]))
    result = solve_card_fit(
        unconstrained_card_fit_facts(
            origin,
            (image_w, image_h),
            metrics,
            chrome_height=chrome_height,
        )
    )
    return result.candidate


def _hug_chrome(facts: CardFitFacts) -> HugChrome:
    return HugChrome(
        header_height=int(facts.header_height),
        footer_height=int(facts.footer_height),
        image_margin_x=int(facts.image_margin_x),
        image_margin_y=int(facts.image_margin_y),
        orphan_height=int(facts.orphan_height),
        min_column_span=int(facts.min_column_span),
        max_column_span=int(facts.max_column_span),
        min_row_span=int(facts.min_row_span),
        max_row_span=int(facts.max_row_span),
    )


def card_fit_plot_size(
    rect: GridRect, facts: CardFitFacts
) -> tuple[int, int] | None:
    """Plot-area pixels for ``rect``: outer cell box minus live chrome/margins."""
    return plot_size_for_rect(rect, facts.metrics, _hug_chrome(facts))


def aspect_contain_box(
    avail_width: int,
    avail_height: int,
    image_size: tuple[int, int],
) -> tuple[int, int] | None:
    """KeepAspectRatio contain box, allowing virtual upscale.

    Used only to measure aspect leftover. The live preview still refuses to
    enlarge the capture past its logical pixels.
    """
    width = max(1, int(avail_width))
    height = max(1, int(avail_height))
    image_w = max(1, int(image_size[0]))
    image_h = max(1, int(image_size[1]))
    scale = min(width / float(image_w), height / float(image_h))
    if scale <= 0.0:
        return None
    reading_w = max(1, int(round(image_w * scale)))
    reading_h = max(1, int(round(image_h * scale)))
    if reading_w > width or reading_h > height:
        return None
    return reading_w, reading_h


def _image_size(facts: CardFitFacts) -> tuple[int, int] | None:
    size = facts.image_logical_size
    if size is None:
        return None
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        return None
    return width, height


def _candidate_in_bounds(rect: GridRect, facts: CardFitFacts) -> bool:
    if rect.column_span < int(facts.min_column_span):
        return False
    if rect.column_span > int(facts.max_column_span):
        return False
    if rect.row_span < int(facts.min_row_span):
        return False
    if rect.row_span > int(facts.max_row_span):
        return False
    if rect.column < int(facts.safety_column_min):
        return False
    if rect.row < int(facts.safety_row_min):
        return False
    if rect.column + rect.column_span > int(facts.safety_column_max):
        return False
    if rect.row + rect.row_span > int(facts.safety_row_max):
        return False
    return True


def _overlaps_occupied(rect: GridRect, facts: CardFitFacts) -> bool:
    return any(rects_overlap(rect, occupied) for occupied in facts.occupied)


def snap_plot_to_span(
    plot_size: tuple[int, int], facts: CardFitFacts
) -> tuple[int, int]:
    """Nearest legal ``(column_span, row_span)`` for a desired plot box."""
    return _snap_plot_to_span(plot_size, facts.metrics, _hug_chrome(facts))


def hug_plot_targets(facts: CardFitFacts) -> tuple[tuple[int, int], ...]:
    """Keep-width and keep-height plot boxes around the current reading scale."""
    image = _image_size(facts)
    plot = card_fit_plot_size(facts.current_rect, facts)
    if image is None or plot is None:
        return ()
    aspect = image[0] / float(image[1])
    if aspect <= 0.0:
        return ()
    return _hug_plot_targets(plot, aspect)


def hug_span_centers(facts: CardFitFacts) -> tuple[tuple[int, int], ...]:
    """Snap the keep-width and keep-height plot targets."""
    image = _image_size(facts)
    plot = card_fit_plot_size(facts.current_rect, facts)
    if image is None or plot is None:
        return ()
    aspect = image[0] / float(image[1])
    if aspect <= 0.0:
        return ()
    return _hug_span_centers(plot, aspect, facts.metrics, _hug_chrome(facts))


def preferred_hug_span(facts: CardFitFacts) -> tuple[int, int] | None:
    """Pick the hug snap that stays closest to the current area, without growing."""
    image = _image_size(facts)
    plot = card_fit_plot_size(facts.current_rect, facts)
    if image is None or plot is None:
        return None
    aspect = image[0] / float(image[1])
    if aspect <= 0.0:
        return None
    return _preferred_hug_span(
        facts.current_rect, plot, aspect, facts.metrics, _hug_chrome(facts)
    )


def preferred_hug_axis(facts: CardFitFacts) -> str | None:
    """``'width'`` keeps columns; ``'height'`` keeps rows."""
    image = _image_size(facts)
    plot = card_fit_plot_size(facts.current_rect, facts)
    if image is None or plot is None:
        return None
    aspect = image[0] / float(image[1])
    if aspect <= 0.0:
        return None
    return _preferred_hug_axis(
        facts.current_rect, plot, aspect, facts.metrics, _hug_chrome(facts)
    )


def iter_card_fit_search_rects(facts: CardFitFacts) -> tuple[GridRect, ...]:
    """Origin-pinned window around the preferred hug snap, plus current."""
    origin = facts.current_rect
    column = int(origin.column)
    row = int(origin.row)
    found: list[GridRect] = []
    seen: set[tuple[int, int]] = set()

    def _add(column_span: int, row_span: int) -> None:
        key = (int(column_span), int(row_span))
        if key in seen:
            return
        seen.add(key)
        found.append(GridRect(column, row, key[0], key[1]))

    current_cols = max(int(origin.column_span), int(facts.min_column_span))
    current_rows = max(int(origin.row_span), int(facts.min_row_span))
    _add(int(origin.column_span), int(origin.row_span))
    axis = preferred_hug_axis(facts)
    preferred = preferred_hug_span(facts)
    if axis is None or preferred is None:
        return tuple(found)
    window = max(0, int(CARD_FIT_SNAP_WINDOW))
    if axis == "height":
        target_cols = int(preferred[0])
        for column_span in range(target_cols - window, target_cols + window + 1):
            _add(column_span, current_rows)
    else:
        target_rows = int(preferred[1])
        for row_span in range(target_rows - window, target_rows + window + 1):
            _add(current_cols, row_span)
    return tuple(found)


def card_fit_score(
    rect: GridRect, facts: CardFitFacts
) -> CardFitScore | None:
    """Return the F3 hug score, or ``None`` when the candidate is illegal."""
    image = _image_size(facts)
    if image is None:
        return None
    if rect.column != facts.current_rect.column or rect.row != facts.current_rect.row:
        return None
    if not _candidate_in_bounds(rect, facts):
        return None
    if _overlaps_occupied(rect, facts):
        return None
    plot = card_fit_plot_size(rect, facts)
    if plot is None:
        return None
    plot_w, plot_h = plot
    reading = aspect_contain_box(plot_w, plot_h, image)
    if reading is None:
        return None
    reading_w, reading_h = reading
    plot_area = float(plot_w * plot_h)
    reading_area = float(reading_w * reading_h)
    unused_area = max(0.0, plot_area - reading_area)
    unused_w = max(0.0, float(plot_w - reading_w))
    unused_h = max(0.0, float(plot_h - reading_h))
    current = facts.current_rect
    current_area = int(current.column_span) * int(current.row_span)
    area = int(rect.column_span) * int(rect.row_span)
    return CardFitScore(
        crop_or_stretch_violation=0,
        unused_area_ratio=unused_area / plot_area,
        grows=1 if area > current_area else 0,
        longest_unused_axis_ratio=max(
            unused_w / float(plot_w), unused_h / float(plot_h)
        ),
        bottom_unused_ratio=unused_h / float(plot_h),
        area_delta=abs(area - current_area),
        span_delta=abs(int(rect.column_span) - int(current.column_span))
        + abs(int(rect.row_span) - int(current.row_span)),
        row_span=int(rect.row_span),
        column_span=int(rect.column_span),
    )


def iter_legal_card_fit_rects(facts: CardFitFacts) -> tuple[GridRect, ...]:
    """Legal origin-pinned hug-window candidates. Does not call ``plan_layout``."""
    if _image_size(facts) is None:
        return ()
    found: list[GridRect] = []
    for candidate in iter_card_fit_search_rects(facts):
        if card_fit_score(candidate, facts) is None:
            continue
        found.append(candidate)
    return tuple(found)


def solve_card_fit(facts: CardFitFacts) -> CardFitResult:
    """Pick the F3-minimum hug-window candidate at the pinned origin."""
    current = facts.current_rect
    image = _image_size(facts)
    if image is None:
        return CardFitResult(
            candidate=current,
            score=None,
            improved=False,
            reason=REASON_NO_PREVIEW,
        )
    legal = iter_legal_card_fit_rects(facts)
    if not legal:
        return CardFitResult(
            candidate=current,
            score=card_fit_score(current, _facts_without_occupied(facts)),
            improved=False,
            reason=REASON_NO_SPACE,
        )
    ranked = sorted(
        ((card_fit_score(rect, facts), rect) for rect in legal),
        key=lambda item: item[0].key(),
    )
    best_score, best_rect = ranked[0]
    if best_rect == current:
        unconstrained = _facts_without_occupied(facts)
        unconstrained_legal = iter_legal_card_fit_rects(unconstrained)
        unconstrained_best = None
        if unconstrained_legal:
            unconstrained_best = min(
                unconstrained_legal,
                key=lambda rect: card_fit_score(rect, unconstrained).key(),
            )
        if unconstrained_best is not None and unconstrained_best != current:
            return CardFitResult(
                candidate=current,
                score=best_score,
                improved=False,
                reason=REASON_NO_SPACE,
            )
        return CardFitResult(
            candidate=current,
            score=best_score,
            improved=False,
            reason=REASON_NO_IMPROVEMENT,
        )
    return CardFitResult(
        candidate=best_rect,
        score=best_score,
        improved=True,
        reason=None,
    )


def _facts_without_occupied(facts: CardFitFacts) -> CardFitFacts:
    if not facts.occupied:
        return facts
    return replace(facts, occupied=())
