"""Pure UltraView board geometry.

The same ``slot_rects`` function drives the on-screen board grid and the
Task 7 off-screen compositor. Card chrome heights are layout constants, not
scaled with board size (P0 has no board zoom).
"""
from __future__ import annotations

from mf4_analyzer.ui.ultraview_state import (
    EQUAL_LAYOUTS,
    HERO_LAYOUTS,
    LAYOUT_SLOTS,
    clamp_ratio,
)

BASE_BOARD_SIZE = (1600, 900)
BOARD_PADDING = 16
SLOT_GUTTER = 12  # UltraView-owned; do not reuse analysis split 4*scale / 8px.

# P1 reading-mode floor for the large equal-grid templates.  These are logical
# pixels, deliberately independent of the export compositor's output scale.
# A 9/12-card Board becomes scrollable instead of squeezing card chrome below
# this usable plot area.
MIN_CARD_CONTENT_SIZE = (300, 180)

# Fixed chrome. Never derived from board width/height or a zoom factor.
CARD_HEADER_HEIGHT = 34
CARD_FOOTER_HEIGHT = 24
MIN_CARD_CHROME_HEIGHT = CARD_HEADER_HEIGHT + CARD_FOOTER_HEIGHT

Rect = tuple[int, int, int, int]


def template_grid_shape(layout_id: str) -> tuple[int, int] | None:
    """Return ``(rows, columns)`` for an equal-grid template.

    Hero and split templates are intentionally absent: their existing
    fill-the-viewport geometry remains the reading contract for P1.
    """
    return {
        "grid_2x2": (2, 2),
        "grid_3x2": (2, 3),
        "grid_3x3": (3, 3),
        "grid_4x3": (3, 4),
    }.get(layout_id)


def logical_board_size(
    layout_id: str,
    viewport_size: tuple[int, int],
    *,
    min_card_content_size: tuple[int, int] = MIN_CARD_CONTENT_SIZE,
) -> tuple[int, int]:
    """Return the P1 reading canvas size for ``layout_id``.

    Only the new 9/12-card templates claim a minimum logical canvas.  Older
    templates continue to fill the available viewport, preserving their P0
    presentation.  The returned dimensions include Board padding and gutters,
    so callers can use them as a widget minimum size without a second layout
    calculation.
    """
    if layout_id not in LAYOUT_SLOTS:
        raise ValueError(f"unknown layout_id: {layout_id!r}")
    viewport_w = max(1, int(viewport_size[0]))
    viewport_h = max(1, int(viewport_size[1]))
    shape = template_grid_shape(layout_id)
    if shape is None or layout_id not in {"grid_3x3", "grid_4x3"}:
        return viewport_w, viewport_h
    rows, columns = shape
    card_w = max(1, int(min_card_content_size[0]))
    card_h = max(1, int(min_card_content_size[1]))
    floor_w = 2 * BOARD_PADDING + columns * card_w + (columns - 1) * SLOT_GUTTER
    floor_h = 2 * BOARD_PADDING + rows * card_h + (rows - 1) * SLOT_GUTTER
    return max(viewport_w, floor_w), max(viewport_h, floor_h)


def content_rect(
    board_size: tuple[int, int] = BASE_BOARD_SIZE,
    padding: int = BOARD_PADDING,
) -> Rect:
    """Inner rect of a board after uniform padding."""
    width, height = int(board_size[0]), int(board_size[1])
    pad = max(0, int(padding))
    return (pad, pad, max(0, width - 2 * pad), max(0, height - 2 * pad))


def slot_rects(
    layout_id: str,
    content: tuple[int, int, int, int],
    primary_ratio: float,
) -> dict[str, Rect]:
    """Return unique, non-overlapping slot rects inside ``content``.

    ``content`` is ``(x, y, w, h)``. ``primary_ratio`` is clamped and only
    affects ``hero_left_4`` / ``hero_top_4``; equal templates ignore it.
    """
    if layout_id not in LAYOUT_SLOTS:
        raise ValueError(f"unknown layout_id: {layout_id!r}")
    x, y, width, height = (int(content[0]), int(content[1]), int(content[2]), int(content[3]))
    gutter = SLOT_GUTTER
    ratio = clamp_ratio(primary_ratio)
    if layout_id == "split_horizontal":
        rects = _split_axis((x, y, width, height), axis="x", names=("left", "right"), gutter=gutter)
    elif layout_id == "split_vertical":
        rects = _split_axis((x, y, width, height), axis="y", names=("top", "bottom"), gutter=gutter)
    elif layout_id == "grid_2x2":
        rects = _grid((x, y, width, height), rows=2, cols=2, names=("tl", "tr", "bl", "br"), gutter=gutter)
    elif layout_id == "grid_3x2":
        rects = _grid(
            (x, y, width, height),
            rows=2,
            cols=3,
            names=("r0c0", "r0c1", "r0c2", "r1c0", "r1c1", "r1c2"),
            gutter=gutter,
        )
    elif layout_id == "grid_3x3":
        rects = _grid(
            (x, y, width, height),
            rows=3,
            cols=3,
            names=LAYOUT_SLOTS[layout_id],
            gutter=gutter,
        )
    elif layout_id == "grid_4x3":
        rects = _grid(
            (x, y, width, height),
            rows=3,
            cols=4,
            names=LAYOUT_SLOTS[layout_id],
            gutter=gutter,
        )
    elif layout_id == "hero_left_4":
        rects = _hero_left((x, y, width, height), ratio, gutter)
    else:
        rects = _hero_top((x, y, width, height), ratio, gutter)
    expected = LAYOUT_SLOTS[layout_id]
    if tuple(rects) != expected:
        # Keep slot id order stable even if a helper used a dict literal.
        rects = {slot: rects[slot] for slot in expected}
    if layout_id in EQUAL_LAYOUTS:
        _ = ratio  # retained by BoardState; geometry ignores it
    elif layout_id not in HERO_LAYOUTS:
        raise ValueError(f"unhandled layout_id: {layout_id!r}")
    return rects


def _even_sizes(length: int, count: int, gutter: int) -> list[int]:
    if count <= 0:
        return []
    if count == 1:
        return [max(0, length)]
    usable = length - gutter * (count - 1)
    if usable < 0:
        usable = 0
    base, remainder = divmod(usable, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _pack(origin: int, sizes: list[int], gutter: int) -> list[tuple[int, int]]:
    pos = origin
    packed: list[tuple[int, int]] = []
    for index, size in enumerate(sizes):
        packed.append((pos, size))
        pos += size
        if index < len(sizes) - 1:
            pos += gutter
    return packed


def _split_axis(
    content: Rect,
    *,
    axis: str,
    names: tuple[str, ...],
    gutter: int,
) -> dict[str, Rect]:
    x, y, width, height = content
    if axis == "x":
        sizes = _even_sizes(width, len(names), gutter)
        spans = _pack(x, sizes, gutter)
        return {
            name: (start, y, size, height) for name, (start, size) in zip(names, spans)
        }
    sizes = _even_sizes(height, len(names), gutter)
    spans = _pack(y, sizes, gutter)
    return {
        name: (x, start, width, size) for name, (start, size) in zip(names, spans)
    }


def _grid(
    content: Rect,
    *,
    rows: int,
    cols: int,
    names: tuple[str, ...],
    gutter: int,
) -> dict[str, Rect]:
    x, y, width, height = content
    col_sizes = _even_sizes(width, cols, gutter)
    row_sizes = _even_sizes(height, rows, gutter)
    xs = _pack(x, col_sizes, gutter)
    ys = _pack(y, row_sizes, gutter)
    rects: dict[str, Rect] = {}
    for index, name in enumerate(names):
        row, col = divmod(index, cols)
        sx, sw = xs[col]
        sy, sh = ys[row]
        rects[name] = (sx, sy, sw, sh)
    return rects


def _hero_primary_size(usable: int, ratio: float) -> tuple[int, int]:
    if usable <= 0:
        return 0, 0
    if usable == 1:
        return 1, 0
    primary = int(round(usable * ratio))
    primary = min(max(primary, 1), usable - 1)
    return primary, usable - primary


def _hero_left(content: Rect, ratio: float, gutter: int) -> dict[str, Rect]:
    x, y, width, height = content
    primary_w, aux_w = _hero_primary_size(width - gutter, ratio)
    aux_heights = _even_sizes(height, 3, gutter)
    aux_y = _pack(y, aux_heights, gutter)
    aux_x = x + primary_w + gutter
    return {
        "primary": (x, y, primary_w, height),
        "aux_0": (aux_x, aux_y[0][0], aux_w, aux_y[0][1]),
        "aux_1": (aux_x, aux_y[1][0], aux_w, aux_y[1][1]),
        "aux_2": (aux_x, aux_y[2][0], aux_w, aux_y[2][1]),
    }


def _hero_top(content: Rect, ratio: float, gutter: int) -> dict[str, Rect]:
    x, y, width, height = content
    primary_h, aux_h = _hero_primary_size(height - gutter, ratio)
    aux_widths = _even_sizes(width, 3, gutter)
    aux_x = _pack(x, aux_widths, gutter)
    aux_y = y + primary_h + gutter
    return {
        "primary": (x, y, width, primary_h),
        "aux_0": (aux_x[0][0], aux_y, aux_x[0][1], aux_h),
        "aux_1": (aux_x[1][0], aux_y, aux_x[1][1], aux_h),
        "aux_2": (aux_x[2][0], aux_y, aux_x[2][1], aux_h),
    }
