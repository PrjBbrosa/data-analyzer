"""Off-screen UltraView board compositor.

Template boards stay on the 1600×900 (1×) / 3200×1800 (2×) baseline.
Free-grid export uses the placed-content bounding box at the canonical
1600-wide cell pitch — the same crop on-screen fit-to-content uses — never
the empty 12-column floor, screen halo, or the live viewport zoom. Does not
import MainWindow, grab widgets, or call analysis compute.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
from typing import Mapping

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)

from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    LAYOUT_MODE_FREE_GRID,
    SECTION_LABELS_ZH,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    UltraViewBoardState,
    UltraViewRef,
    GridRect,
    layout_slots,
    slot_occupant,
)

from .author_render import draw_author_objects
from .elastic_workspace import author_content_bounds, content_bounds
from .feedback import format_export_too_large
from .free_grid import GridMetrics, export_grid_metrics, rect_to_pixels
from .layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    content_rect,
    logical_board_size,
    slot_rects,
)
from .preview_store import PreviewStore

TITLE_BAND = 36
MAX_EXPORT_EDGE = 8192
MAX_EXPORT_PIXELS = 16_000_000
BOARD_BG = QColor("#F7F8F7")
BOARD_BG_DEEP = QColor("#E9EFF1")
CARD_BG = QColor(255, 255, 254, 118)
CARD_BORDER = QColor(255, 255, 255, 166)
CARD_FOOTER_WASH = QColor(237, 242, 242, 126)
TITLE_COLOR = QColor("#1b2430")
MUTED_COLOR = QColor("#5b6775")
PLACEHOLDER_BG = QColor("#e8edf4")
STATUS_COLORS = {
    STATUS_STALE: QColor("#b45309"),
    STATUS_MISSING: QColor("#64748b"),
    STATUS_ORPHANED: QColor("#b42318"),
}
STATUS_TEXT = {
    STATUS_STALE: "源已变化",
    STATUS_MISSING: "尚无可用结果",
    STATUS_ORPHANED: "源已删除",
}


class ComposeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


def output_size(scale: int, layout_id: str | None = None) -> tuple[int, int]:
    """Return the canonical template export size.

    2/4/6 and hero templates keep the P0 1600×900 baseline.  9/12 templates
    use the same logical-board floor as the on-screen reading canvas so cards
    are not crushed below the readable content target.
    """
    factor = 1 if int(scale) <= 1 else 2
    width, height = BASE_BOARD_SIZE
    if layout_id:
        width, height = logical_board_size(layout_id, BASE_BOARD_SIZE)
    return width * factor, height * factor


def _extent_pixels(metrics: GridMetrics, n_cols: int, n_rows: int) -> tuple[int, int]:
    """Return 1× pixel size for a micro-grid extent at the export pitch."""
    columns = max(1, int(n_cols))
    rows = max(1, int(n_rows))
    _x, _y, width, height = rect_to_pixels(
        GridRect(0, 0, columns, rows), metrics
    )
    padding = metrics.exact_padding()
    return int(round(width + 2 * padding)), int(round(height + 2 * padding))


def _free_grid_export_layout(
    board: UltraViewBoardState,
) -> tuple[GridMetrics, tuple[int, int], int, int]:
    """Return 1× ``(metrics, origin_offset, width, height)`` without the title band.

    The canvas is the axis-aligned union of placed cards plus canonical
    padding, at the 1600-wide 12-column pitch. Empty columns/rows outside
    that union are not exported — matching on-screen fit-to-content. Gaps
    *between* cards stay. GridRect values are not rewritten; ``origin_offset``
    maps the leftmost/topmost occupied cell to padding. An empty board keeps
    a one-row 12-column placeholder.
    """
    placements = tuple(board.free_grid)
    metrics = export_grid_metrics(placements)
    author = author_content_bounds(board.author_objects)
    content = content_bounds(placements, author_objects=board.author_objects)
    if content.empty():
        col0, row0 = 0, 0
        column_end = GRID_COLUMNS
        row_end = 1
    else:
        col0 = content.column
        row0 = content.row
        column_end = max(content.column + 1, content.column_end)
        row_end = max(content.row + 1, content.row_end)
    width, height = _extent_pixels(
        metrics, column_end - col0, row_end - row0
    )
    if not author.empty():
        # Card rectangles intentionally omit their terminal inter-card gutter;
        # author geometry is continuous and may legitimately reach a cell edge.
        # Grow only when the author union needs that terminal pitch, preserving
        # the byte-for-byte card-only crop contract.
        padding = metrics.exact_padding()
        pitch_x, pitch_y = metrics.exact_pitch()
        author_right = padding + (author.column_end - col0) * pitch_x + padding
        author_bottom = padding + (author.row_end - row0) * pitch_y + padding
        width = max(width, int(math.ceil(author_right)))
        height = max(height, int(math.ceil(author_bottom)))
    return metrics, (col0, row0), width, height


def free_grid_output_size(
    board: UltraViewBoardState, scale: int, *, title: bool = True
) -> tuple[int, int]:
    """Return the free-grid export canvas: content bounding box, no halo."""
    _metrics, _origin, width, height = _free_grid_export_layout(board)
    factor = 1 if int(scale) <= 1 else 2
    extra = TITLE_BAND if title else 0
    return width * factor, (height + extra) * factor


def composed_slot_rects(
    board: UltraViewBoardState, *, scale: int = 1, title: bool = True
) -> dict[str, tuple[int, int, int, int]]:
    """Pixel rectangles in the composed image, including the optional title band."""
    factor = 1 if int(scale) <= 1 else 2
    title_h = TITLE_BAND if title else 0
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        metrics, origin, _width, _height = _free_grid_export_layout(board)
        return {
            f"grid:{item.ref.section}:{item.ref.view_id}": (
                x * factor,
                (y + title_h) * factor,
                width * factor,
                height * factor,
            )
            for item in board.free_grid
            for x, y, width, height in (
                rect_to_pixels(item.rect, metrics, origin_offset=origin),
            )
        }
    width, height = output_size(1, board.layout_id)
    inner_h = height - title_h if title else height
    content = content_rect((width, inner_h), padding=BOARD_PADDING)
    rects = slot_rects(board.layout_id, content, board.primary_ratio)
    return {
        slot_id: (
            x * factor,
            (y + title_h) * factor,
            w * factor,
            h * factor,
        )
        for slot_id, (x, y, w, h) in rects.items()
    }


def _guard_export_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ComposeError("allocation_failed", f"无法分配 {width}×{height} 合成图")
    if (
        width > MAX_EXPORT_EDGE
        or height > MAX_EXPORT_EDGE
        or width * height > MAX_EXPORT_PIXELS
    ):
        raise ComposeError(
            "export_too_large",
            format_export_too_large(width, height),
        )


def image_sha256(image: QImage) -> str:
    if image is None or image.isNull():
        raise ComposeError("empty_image", "image is null")
    converted = image.convertToFormat(QImage.Format_ARGB32)
    bits = converted.bits()
    try:
        bits.setsize(converted.byteCount())
        payload = bytes(bits)
    except (TypeError, ValueError, AttributeError):
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        blob = QByteArray()
        buffer = QBuffer(blob)
        buffer.open(QIODevice.WriteOnly)
        converted.save(buffer, "PNG")
        payload = bytes(blob)
    return hashlib.sha256(payload).hexdigest()


def compose_board(
    board: UltraViewBoardState,
    records: Mapping[UltraViewRef, object],
    statuses: Mapping[UltraViewRef, str],
    *,
    scale: int = 1,
    title: bool = True,
) -> QImage:
    factor = 1 if int(scale) <= 1 else 2
    width, height = (
        free_grid_output_size(board, factor, title=title)
        if board.layout_mode == LAYOUT_MODE_FREE_GRID
        else output_size(factor, board.layout_id)
    )
    _guard_export_size(width, height)
    image = QImage(width, height, QImage.Format_ARGB32)
    if image.isNull():
        raise ComposeError("allocation_failed", f"无法分配 {width}×{height} 合成图")
    image.setDevicePixelRatio(1.0)
    image.fill(BOARD_BG)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        _draw_export_canvas(painter, width, height)
        _draw_board(painter, board, records, statuses, factor, title=title)
    finally:
        painter.end()
    return image


def save_composed_png(image: QImage, path) -> None:
    target = Path(path)
    if image is None or image.isNull():
        raise ComposeError("empty_image", "合成图为空，未写入文件")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        if not image.save(str(tmp), "PNG"):
            raise ComposeError("save_failed", f"无法保存 PNG：{target}")
        if not tmp.exists() or tmp.stat().st_size <= 0:
            raise ComposeError("save_failed", f"PNG 写入为空：{target}")
        os.replace(tmp, target)
    except ComposeError:
        if tmp.exists():
            tmp.unlink()
        raise
    except OSError as exc:
        if tmp.exists():
            tmp.unlink()
        raise ComposeError("save_failed", str(exc)) from exc


def _draw_board(painter, board, records, statuses, factor: int, *, title: bool) -> None:
    if title:
        title_h = TITLE_BAND * factor
        font = QFont()
        font.setPixelSize(max(12, 16 * factor))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(TITLE_COLOR)
        painter.drawText(
            QRect(
                BOARD_PADDING * factor,
                0,
                painter.device().width() - 2 * BOARD_PADDING * factor,
                title_h,
            ),
            Qt.AlignVCenter | Qt.AlignLeft,
            str(board.name or ""),
        )
    rects = composed_slot_rects(board, scale=factor, title=title)
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        for item in board.free_grid:
            key = f"grid:{item.ref.section}:{item.ref.view_id}"
            _draw_slot(painter, board, rects[key], item.ref, records, statuses, factor)
        _draw_free_grid_author_objects(painter, board, factor, title=title)
        return
    for slot_id in layout_slots(board.layout_id):
        _draw_slot(
            painter,
            board,
            rects[slot_id],
            slot_occupant(board, slot_id),
            records,
            statuses,
            factor,
        )


def _draw_free_grid_author_objects(
    painter: QPainter,
    board: UltraViewBoardState,
    factor: int,
    *,
    title: bool,
) -> None:
    """Paint persisted author ink above cards in the shared export path.

    Template mode intentionally has no call site: authoring is a Free Grid
    capability and template boards retain their saved author payload without
    showing it.  The title band is a compositor-only offset, never part of a
    persisted Board coordinate.
    """
    if not board.author_objects:
        return
    metrics, origin, _width, _height = _free_grid_export_layout(board)
    painter.save()
    try:
        if title:
            painter.translate(0.0, float(TITLE_BAND * factor))
        draw_author_objects(
            painter,
            board.author_objects,
            metrics,
            origin_offset=origin,
            scale=float(factor),
        )
    finally:
        painter.restore()


def _draw_export_canvas(painter: QPainter, width: int, height: int) -> None:
    """Flatten the Titanium canvas for deterministic PNG output.

    The live card shell is translucent over :class:`CanvasHost`.  Export has
    no desktop backdrop, so it paints the same restrained paper, glow, dot and
    grid material first, then lets the card alpha blend into that fixed base.
    """
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, BOARD_BG)
    gradient.setColorAt(1.0, BOARD_BG_DEEP)
    painter.fillRect(0, 0, width, height, gradient)
    for center_x, center_y, radius, color in (
        (width * 0.16, height * 0.04, max(width, height) * 0.46, QColor(31, 104, 128, 31)),
        (width * 0.88, height * 0.09, max(width, height) * 0.42, QColor(238, 151, 58, 25)),
        (width * 0.64, height * 1.04, max(width, height) * 0.48, QColor(197, 76, 64, 16)),
    ):
        glow = QRadialGradient(center_x, center_y, radius)
        glow.setColorAt(0.0, color)
        edge = QColor(color)
        edge.setAlpha(0)
        glow.setColorAt(1.0, edge)
        painter.fillRect(0, 0, width, height, glow)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(44, 82, 93, 43))
    for y in range(10, height, 22):
        for x in range(10, width, 22):
            painter.drawRect(x, y, 1, 1)
    grid_pen = QPen(QColor(38, 74, 86, 26))
    grid_pen.setWidthF(1.0)
    painter.setPen(grid_pen)
    for x in range(0, width + 1, 110):
        painter.drawLine(x, 0, x, height)
    for y in range(0, height + 1, 110):
        painter.drawLine(0, y, width, y)


def _draw_slot(painter, board, slot, ref, records, statuses, factor: int) -> None:
    x, y, w, h = slot
    painter.setPen(QPen(CARD_BORDER, max(1, factor)))
    painter.setBrush(CARD_BG)
    painter.drawRoundedRect(x, y, w, h, 4 * factor, 4 * factor)
    if ref is None:
        painter.setPen(MUTED_COLOR)
        font = QFont()
        font.setPixelSize(max(10, 12 * factor))
        painter.setFont(font)
        painter.drawText(QRect(x, y, w, h), Qt.AlignCenter, "空槽")
        return
    record = records.get(ref)
    status = str(statuses.get(ref) or STATUS_MISSING)
    header_h = CARD_HEADER_HEIGHT * factor
    footer_h = CARD_FOOTER_HEIGHT * factor if board.show_sources else 0
    if board.show_titles:
        _draw_header(painter, ref, record, status, x, y, w, header_h, factor)
        painter.fillRect(x + 8 * factor, y + header_h - 3 * factor, 36 * factor, 2 * factor, TITLE_COLOR)
    else:
        _draw_status_only(painter, status, x, y, w, header_h, factor)
    image_y = y + header_h
    image_h = max(0, h - header_h - footer_h)
    _draw_preview(
        painter, record, status, x + 4 * factor, image_y, w - 8 * factor, image_h, factor,
    )
    if board.show_sources:
        _draw_footer(painter, ref, record, x, y + h - footer_h, w, footer_h, factor)


def _title_text(ref, record) -> str:
    title = getattr(record, "title", "") if record is not None else ""
    return str(title or ref.view_id)


def _draw_header(painter, ref, record, status, x, y, w, h, factor) -> None:
    font = QFont()
    font.setPixelSize(max(10, 12 * factor))
    painter.setFont(font)
    painter.setPen(TITLE_COLOR)
    painter.drawText(
        QRect(x + 8 * factor, y, w - 16 * factor, h),
        Qt.AlignVCenter | Qt.AlignLeft,
        _title_text(ref, record),
    )
    _draw_status_chip(painter, status, x, y, w, h, factor)


def _draw_status_only(painter, status, x, y, w, h, factor) -> None:
    _draw_status_chip(painter, status, x, y, w, h, factor)


def _draw_status_chip(painter, status, x, y, w, h, factor) -> None:
    color = STATUS_COLORS.get(status)
    if color is not None:
        painter.fillRect(
            x + w - 14 * factor,
            y + max(4, (h - 8 * factor) // 2),
            8 * factor,
            8 * factor,
            color,
        )
    label = STATUS_TEXT.get(status, "")
    if not label:
        return
    font = QFont()
    font.setPixelSize(max(9, 11 * factor))
    painter.setFont(font)
    painter.setPen(STATUS_COLORS.get(status, MUTED_COLOR))
    painter.drawText(
        QRect(x + 8 * factor, y, w - 16 * factor, h),
        Qt.AlignVCenter | Qt.AlignRight,
        label,
    )


def _draw_footer(painter, ref, record, x, y, w, h, factor) -> None:
    painter.fillRect(x + 1 * factor, y, w - 2 * factor, h, CARD_FOOTER_WASH)
    summary = getattr(record, "source_summary", "") if record is not None else ""
    section = SECTION_LABELS_ZH.get(ref.section, ref.section)
    text = str(summary or section)
    font = QFont()
    font.setPixelSize(max(9, 11 * factor))
    painter.setFont(font)
    painter.setPen(MUTED_COLOR)
    painter.drawText(
        QRect(x + 8 * factor, y, w - 16 * factor, h),
        Qt.AlignVCenter | Qt.AlignLeft,
        text,
    )


def _draw_preview(painter, record, status, x, y, w, h, factor) -> None:
    if w <= 0 or h <= 0:
        return
    image = getattr(record, "image", None) if record is not None else None
    usable = PreviewStore.image_valid(image) and status != STATUS_MISSING
    if not usable:
        painter.fillRect(x, y, w, h, PLACEHOLDER_BG)
        font = QFont()
        font.setPixelSize(max(10, 12 * factor))
        painter.setFont(font)
        painter.setPen(MUTED_COLOR)
        painter.drawText(
            QRect(x, y, w, h),
            Qt.AlignCenter,
            STATUS_TEXT.get(status, "尚无可用结果"),
        )
        return
    dw, dh = _contain_size(image.width(), image.height(), w, h)
    scaled = image.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ox = x + max(0, (w - scaled.width()) // 2)
    oy = y + max(0, (h - scaled.height()) // 2)
    painter.drawImage(ox, oy, scaled)


def _contain_size(raw_w: int, raw_h: int, box_w: int, box_h: int) -> tuple[int, int]:
    if raw_w <= 0 or raw_h <= 0 or box_w <= 0 or box_h <= 0:
        return 0, 0
    scale = min(box_w / float(raw_w), box_h / float(raw_h), 1.0)
    return max(1, int(raw_w * scale)), max(1, int(raw_h * scale))
