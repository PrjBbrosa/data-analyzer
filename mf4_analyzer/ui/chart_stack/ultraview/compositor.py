"""Off-screen UltraView board compositor.

Draws a fixed 1600×900 (1×) or 3200×1800 (2×) board from immutable Board
state plus PreviewStore records. Does not import MainWindow, grab widgets, or
call analysis compute.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen

from mf4_analyzer.ui.ultraview_state import (
    LAYOUT_MODE_FREE_GRID,
    SECTION_LABELS_ZH,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    UltraViewBoardState,
    UltraViewRef,
    layout_slots,
    slot_occupant,
)

from .layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    content_rect,
    slot_rects,
)
from .free_grid import grid_metrics, rect_to_pixels
from .preview_store import PreviewStore

TITLE_BAND = 36
BOARD_BG = QColor("#f5f7fb")
CARD_BG = QColor("#ffffff")
CARD_BORDER = QColor("#d7dee8")
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


def output_size(scale: int) -> tuple[int, int]:
    factor = 1 if int(scale) <= 1 else 2
    return BASE_BOARD_SIZE[0] * factor, BASE_BOARD_SIZE[1] * factor


def free_grid_output_size(board: UltraViewBoardState, scale: int) -> tuple[int, int]:
    """Return a bounded full logical free-grid export canvas (not viewport)."""
    metrics = grid_metrics(BASE_BOARD_SIZE, board.free_grid)
    factor = 1 if int(scale) <= 1 else 2
    return metrics.board_width * factor, (metrics.board_height + TITLE_BAND) * factor


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
) -> QImage:
    factor = 1 if int(scale) <= 1 else 2
    width, height = (
        free_grid_output_size(board, factor)
        if board.layout_mode == LAYOUT_MODE_FREE_GRID
        else output_size(factor)
    )
    image = QImage(width, height, QImage.Format_ARGB32)
    if image.isNull():
        raise ComposeError("allocation_failed", f"无法分配 {width}×{height} 合成图")
    image.setDevicePixelRatio(1.0)
    image.fill(BOARD_BG)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        _draw_board(painter, board, records, statuses, factor)
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


def _draw_board(painter, board, records, statuses, factor: int) -> None:
    title_h = TITLE_BAND * factor
    font = QFont()
    font.setPixelSize(max(12, 16 * factor))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(TITLE_COLOR)
    painter.drawText(
        QRect(BOARD_PADDING * factor, 0, painter.device().width() - 2 * BOARD_PADDING * factor, title_h),
        Qt.AlignVCenter | Qt.AlignLeft,
        str(board.name or ""),
    )
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        _draw_free_grid(painter, board, records, statuses, factor)
        return
    inner_w, inner_h = BASE_BOARD_SIZE[0], BASE_BOARD_SIZE[1] - TITLE_BAND
    content = content_rect((inner_w, inner_h), padding=BOARD_PADDING)
    cx, cy, cw, ch = content
    rects = slot_rects(board.layout_id, (cx, cy, cw, ch), board.primary_ratio)
    for slot_id in layout_slots(board.layout_id):
        x, y, w, h = rects[slot_id]
        slot = (
            x * factor,
            (y + TITLE_BAND) * factor,
            w * factor,
            h * factor,
        )
        ref = slot_occupant(board, slot_id)
        _draw_slot(painter, board, slot, ref, records, statuses, factor)


def _draw_free_grid(painter, board, records, statuses, factor: int) -> None:
    metrics = grid_metrics(BASE_BOARD_SIZE, board.free_grid)
    for placement in board.free_grid:
        x, y, width, height = rect_to_pixels(placement.rect, metrics)
        slot = (
            x * factor,
            (y + TITLE_BAND) * factor,
            width * factor,
            height * factor,
        )
        _draw_slot(painter, board, slot, placement.ref, records, statuses, factor)


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
    painter.fillRect(x + 1 * factor, y, w - 2 * factor, h, QColor("#eef2f7"))
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
