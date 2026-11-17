"""Import progress dialog: content geometry and snapshot states.

The track assertion uses the QProgressBar widget rectangle. The busy
chunk painted by the style is not a width.
"""
from __future__ import annotations

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_HEIGHTS
from mf4_analyzer.ui_kit.dialog_geometry import SCREEN_MARGIN, as_rect
from mf4_analyzer.ui_kit.dialog_geometry import IntRect
from mf4_analyzer.ui_kit.import_progress_dialog import (
    ACTION_GAP,
    KIND_CANCELLED,
    KIND_CANCELLING,
    KIND_FAILED,
    KIND_HANDOFF,
    KIND_PARTIAL,
    KIND_READING,
    KIND_STAGE,
    KIND_SUCCESS,
    KIND_WAITING,
    KIND_WAITING_USER,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PREFERRED_WIDTH,
    ROW_GAP,
    SOFT_WIDTH_MAX,
    ImportProgressDialog,
    build_import_progress_snapshot,
)


_WORK = IntRect(0, 0, 1366, 768)
_NARROW = IntRect(0, 0, 360, 320)
_LONG_NAME = "方向盘扭矩_" + ("测量段" * 40) + ".mf4"
_LONG_PATH = "C:/eps/data/" + ("unbroken_directory_name_" * 12) + _LONG_NAME


def _load_sheet(qapp):
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    return previous


def _snapshot(**overrides):
    payload = dict(
        kind=KIND_WAITING,
        title="导入文件",
        file_name="torque.mf4",
        full_path="C:/eps/torque.mf4",
        index=1,
        total=2,
        phase="读取数据",
        elapsed_s=3,
        stage_fraction=None,
    )
    payload.update(overrides)
    return build_import_progress_snapshot(**payload)


def _show(qapp, qtbot, snapshot, *, available=_WORK, font_px=None):
    dialog = ImportProgressDialog(title=snapshot.title, available_rect=available)
    qtbot.addWidget(dialog)
    if font_px is not None:
        font = QFont(dialog.font())
        font.setPixelSize(font_px)
        for widget in (
            dialog, dialog.file_label, dialog.phase_label, dialog.cancel_button,
        ):
            widget.setFont(font)
    dialog.apply_snapshot(snapshot)
    dialog.show()
    qtbot.waitExposed(dialog)
    qapp.processEvents()
    dialog.relayout()
    qapp.processEvents()
    return dialog


def _edge(widget) -> int:
    geo = widget.geometry()
    return geo.x() + geo.width()


def _assert_track_aligns(dialog) -> None:
    bar = dialog.progress_bar
    button = dialog.cancel_button
    assert abs(_edge(bar) - _edge(button)) <= 1
    assert abs(bar.geometry().x() - MARGIN_LEFT) <= 1
    assert abs(_edge(bar) - (dialog.width() - MARGIN_RIGHT)) <= 1
    assert bar.width() > 80


def _content_formula(dialog) -> int:
    margins = dialog.layout().contentsMargins()
    assert margins.left() == MARGIN_LEFT
    assert margins.right() == MARGIN_RIGHT
    assert margins.top() == MARGIN_TOP
    assert margins.bottom() == MARGIN_BOTTOM
    return (
        margins.top()
        + dialog.file_label.height()
        + ROW_GAP
        + dialog.phase_label.height()
        + ROW_GAP
        + dialog.progress_bar.height()
        + ACTION_GAP
        + dialog.cancel_button.height()
        + margins.bottom()
    )


def test_waiting_is_file_index_not_a_percent():
    snapshot = _snapshot(kind=KIND_WAITING, index=1, total=4, stage_fraction=0.25)
    assert "当前第 1 个/共 4 个" in snapshot.headline
    assert snapshot.indeterminate is True
    assert snapshot.bar_total == 0
    assert "当前阶段" not in snapshot.headline
    assert "剩余" not in snapshot.headline
    assert snapshot.terminal is False


def test_reading_without_a_count_stays_busy_and_names_the_phase():
    snapshot = _snapshot(kind=KIND_READING, phase="读取表格", stage_fraction=-1)
    assert "读取表格" in snapshot.headline
    assert snapshot.indeterminate is True
    assert "当前阶段" not in snapshot.headline
    assert "%" not in snapshot.headline
    assert "剩余" not in snapshot.headline


def test_stage_fraction_is_labeled_as_the_current_stage():
    snapshot = _snapshot(kind=KIND_STAGE, stage_fraction=0.42, phase="读取通道")
    assert "当前阶段 42%" in snapshot.headline
    assert "读取通道" in snapshot.headline
    assert snapshot.indeterminate is False
    assert snapshot.bar_total == 1000
    assert snapshot.bar_current == 420
    assert "导入成功" not in snapshot.headline
    assert "整文件" not in snapshot.headline


def test_broker_completion_is_handoff_not_import_success():
    snapshot = _snapshot(kind=KIND_HANDOFF, phase="读取完成", stage_fraction=1.0)
    assert snapshot.kind == KIND_HANDOFF
    assert snapshot.indeterminate is True
    assert snapshot.bar_total == 0
    assert "读取完成" in snapshot.headline
    assert "导入成功" not in snapshot.headline
    assert "100%" not in snapshot.headline
    assert snapshot.terminal is False


def test_success_is_the_only_full_bar():
    snapshot = _snapshot(kind=KIND_SUCCESS, loaded=2, failed=0)
    assert snapshot.terminal is True
    assert snapshot.indeterminate is False
    assert snapshot.bar_current == snapshot.bar_total == 1000
    assert "已导入 2 个文件" in snapshot.headline
    assert "100%" in snapshot.headline


def test_partial_and_failed_do_not_claim_success():
    partial = _snapshot(kind=KIND_PARTIAL, loaded=1, failed=2)
    failed = _snapshot(kind=KIND_FAILED, loaded=0, failed=1)
    for snapshot in (partial, failed):
        assert snapshot.terminal is True
        assert snapshot.indeterminate is False
        assert snapshot.bar_current != snapshot.bar_total
        assert snapshot.bar_total > 0
        assert "导入成功" not in snapshot.headline
        assert "100%" not in snapshot.headline
    assert "已加载 1 个" in partial.headline
    assert "失败 2 个" in partial.headline
    assert "失败 1 个" in failed.headline


def test_cancelling_and_cancelled_and_user_wait_are_distinct():
    cancelling = _snapshot(kind=KIND_CANCELLING)
    cancelled = _snapshot(kind=KIND_CANCELLED, loaded=1)
    waiting = _snapshot(kind=KIND_WAITING_USER, message="等待确认是否延长并重试")
    assert cancelling.headline == "正在取消…"
    assert cancelling.cancel_enabled is False
    assert cancelling.action_label == "正在取消…"
    assert "已取消" in cancelled.headline
    assert "1" in cancelled.headline
    assert cancelled.indeterminate is False
    assert cancelled.bar_current != cancelled.bar_total
    assert "等待确认是否延长并重试" in waiting.headline
    assert waiting.indeterminate is False
    assert "剩余" not in waiting.headline


def test_track_matches_cancel_button_under_production_qss(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = _show(qapp, qtbot, _snapshot())
        _assert_track_aligns(dialog)
        assert dialog.width() == PREFERRED_WIDTH
        assert dialog.height() < 200
        surplus = dialog.height() - _content_formula(dialog)
        assert 0 <= surplus <= 8
        assert dialog.cancel_button.height() == CONTROL_HEIGHTS["base"]
        assert dialog.cancel_button.minimumWidth() >= 74
        flags = int(dialog.windowFlags())
        assert flags & int(Qt.WindowContextHelpButtonHint) == 0
        assert dialog.file_label.textFormat() == Qt.PlainText
        assert dialog.phase_label.textFormat() == Qt.PlainText
        assert dialog.progress_bar.minimum() == dialog.progress_bar.maximum() == 0
    finally:
        qapp.setStyleSheet(previous)


@pytest.mark.parametrize("font_px", [12, 16, 24])
def test_track_stays_aligned_when_the_font_changes(qapp, qtbot, font_px):
    previous = _load_sheet(qapp)
    try:
        dialog = _show(qapp, qtbot, _snapshot(kind=KIND_STAGE, stage_fraction=1), font_px=font_px)
        _assert_track_aligns(dialog)
        assert dialog.width() <= SOFT_WIDTH_MAX
        assert dialog.cancel_button.height() >= CONTROL_HEIGHTS["base"]
    finally:
        qapp.setStyleSheet(previous)


def test_busy_track_and_full_track_share_the_widget_width(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = _show(qapp, qtbot, _snapshot(kind=KIND_READING, phase="读取表格"))
        busy_width = dialog.progress_bar.width()
        assert dialog.progress_bar.minimum() == dialog.progress_bar.maximum()
        dialog.apply_snapshot(_snapshot(kind=KIND_SUCCESS, loaded=1))
        qapp.processEvents()
        full = dialog.progress_bar
        assert full.maximum() > full.minimum()
        assert full.value() == full.maximum()
        assert full.width() == busy_width
        _assert_track_aligns(dialog)
    finally:
        qapp.setStyleSheet(previous)


def test_long_path_stays_inside_the_work_area_and_keeps_the_full_path(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        snapshot = _snapshot(
            file_name=_LONG_NAME,
            full_path=_LONG_PATH,
            phase="读取通道 <raw> & 方向盘扭矩",
        )
        dialog = _show(qapp, qtbot, snapshot, available=_NARROW)
        assert dialog.width() < PREFERRED_WIDTH
        assert dialog.width() <= SOFT_WIDTH_MAX
        frame = as_rect(dialog.frameGeometry())
        safe = _NARROW.adjusted(
            SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN,
        )
        assert safe.contains_rect(frame)
        assert dialog.file_label.width() <= dialog.width() - MARGIN_LEFT - MARGIN_RIGHT + 1
        assert dialog.file_label.toolTip() == _LONG_PATH
        assert dialog.file_label.full_text() == _LONG_PATH
        assert dialog.file_label.text() != _LONG_PATH
        assert "…" in dialog.file_label.text() or dialog.file_label.text() != _LONG_NAME
        assert "<raw>" in dialog.phase_label.text()
        dialog.file_label.setFocus()
        QTest.keyClick(dialog.file_label, Qt.Key_C, Qt.ControlModifier)
        assert QApplication.clipboard().text() == _LONG_PATH
        _assert_track_aligns(dialog)
    finally:
        qapp.setStyleSheet(previous)


def test_long_cancel_label_grows_and_stays_within_the_soft_cap(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = _show(
            qapp,
            qtbot,
            _snapshot(action_label="取消导入并保留已经打开的来源"),
        )
        assert dialog.cancel_button.minimumWidth() > 74
        assert dialog.width() <= SOFT_WIDTH_MAX
        _assert_track_aligns(dialog)
    finally:
        qapp.setStyleSheet(previous)


def test_title_close_and_escape_request_cancel_once_and_stay_open(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = _show(qapp, qtbot, _snapshot())
        cancels = []

        def record_cancel():
            cancels.append(True)

        dialog.cancel_requested.connect(record_cancel)
        dialog.close()
        qapp.processEvents()
        assert dialog.isVisible()
        assert len(cancels) == 1
        QTest.keyClick(dialog, Qt.Key_Escape)
        qapp.processEvents()
        assert dialog.isVisible()
        assert len(cancels) == 1
        dialog.dismiss()
        qapp.processEvents()
        assert not dialog.isVisible()
        assert len(cancels) == 1
    finally:
        qapp.setStyleSheet(previous)


def _track_colors(bar):
    image = bar.grab().toImage()
    colors = set()
    accent = 0
    width = image.width()
    height = image.height()
    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            if color.alpha() < 16:
                continue
            red, green, blue = color.red(), color.green(), color.blue()
            colors.add((red, green, blue))
            if blue > red + 40 and blue > 140 and blue > green:
                accent += 1
    return colors, accent, width * height


def test_busy_track_and_full_track_paint_different_colors(qapp, qtbot):
    """Production QSS must show a groove and a chunk. Both were white on Cocoa."""
    previous = _load_sheet(qapp)
    try:
        busy = _show(qapp, qtbot, _snapshot())
        full = _show(
            qapp, qtbot, _snapshot(kind=KIND_SUCCESS, loaded=1, failed=0),
        )
        qapp.processEvents()
        busy_colors, busy_accent, busy_area = _track_colors(busy.progress_bar)
        full_colors, full_accent, full_area = _track_colors(full.progress_bar)
        assert busy_colors != {(255, 255, 255)}
        assert full_colors != {(255, 255, 255)}
        assert full_accent > busy_accent
        assert full_accent > full_area // 4
        assert busy_accent < busy_area // 2
    finally:
        qapp.setStyleSheet(previous)


def test_cancel_button_and_repeat_are_distinct_from_programmatic_close(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = _show(qapp, qtbot, _snapshot())
        cancels = []

        def record_cancel():
            cancels.append(True)

        dialog.cancel_requested.connect(record_cancel)
        qtbot.mouseClick(dialog.cancel_button, Qt.LeftButton)
        assert len(cancels) == 1
        dialog.apply_snapshot(_snapshot(kind=KIND_CANCELLING))
        qtbot.mouseClick(dialog.cancel_button, Qt.LeftButton)
        QTest.keyClick(dialog, Qt.Key_Escape)
        assert len(cancels) == 1
        assert not dialog.cancel_button.isEnabled()
        assert dialog.isVisible()
        dialog.dismiss()
        assert len(cancels) == 1
    finally:
        qapp.setStyleSheet(previous)
