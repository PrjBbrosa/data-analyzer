"""Inspector time-range SegmentedChoice contract (plan T0 / T1).

Visible chrome is ``全时段 | 指定范围``. ``chk_range`` and ``btn_range_max``
stay as hidden compatibility widgets. These tests pin the new control
surface; they must not be relaxed back to the old checkbox + 「全部」 row.
"""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication, QCheckBox

from mf4_analyzer.ui.inspector import Inspector, _INSPECTOR_CONTENT_MAX_WIDTH
from mf4_analyzer.ui.inspector_sections.persistent_top import (
    PersistentTop,
    RangeEditQuery,
)
from mf4_analyzer.ui_kit.widgets.segmented_choice import SegmentedChoice


RANGE_FULL_LABEL = "全时段"
RANGE_SPAN_LABEL = "指定范围"
RANGE_MODES = ("time", "fft", "fft_time", "order", "frf")
_NARROW_INSPECTOR_WIDTH = _INSPECTOR_CONTENT_MAX_WIDTH + 16  # 288


def time_range_choice(top) -> SegmentedChoice:
    """Return the visible 全时段 | 指定范围 control."""
    choice = getattr(top, "choice_range", None)
    assert isinstance(choice, SegmentedChoice), (
        "PersistentTop.choice_range must be the visible "
        f"{RANGE_FULL_LABEL} | {RANGE_SPAN_LABEL} SegmentedChoice"
    )
    labels = [button.text() for button in choice.buttons()]
    assert labels == [RANGE_FULL_LABEL, RANGE_SPAN_LABEL], (
        f"choice_range labels must be {RANGE_FULL_LABEL} | {RANGE_SPAN_LABEL}, "
        f"got {labels}"
    )
    return choice


def select_time_range_mode(top, enabled: bool) -> None:
    """Click the visible segment. ``enabled=True`` selects 指定范围."""
    choice = time_range_choice(top)
    choice.buttons()[1 if enabled else 0].click()


def _send_wheel(widget, qapp) -> None:
    pos = QPoint(max(widget.width() // 2, 1), max(widget.height() // 2, 1))
    event = QWheelEvent(
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        QPoint(0, 120),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )
    qapp.sendEvent(widget, event)


def _assert_mode_matches_owner(top, *, enabled: bool) -> None:
    choice = time_range_choice(top)
    assert top.range_enabled() is enabled
    assert top.chk_range.isChecked() is enabled
    assert choice.currentIndex() == (1 if enabled else 0)
    assert choice.buttons()[1 if enabled else 0].isChecked()
    assert top.spin_start.isReadOnly() is (not enabled)
    assert top.spin_end.isReadOnly() is (not enabled)
    assert top.spin_start.isEnabled()
    assert top.spin_end.isEnabled()
    assert not top.spin_start.isHidden()
    assert not top.spin_end.isHidden()


def test_time_range_visible_control_is_segmented_choice_not_checkbox(qapp):
    top = PersistentTop()
    choice = time_range_choice(top)

    assert not choice.isHidden()
    assert isinstance(top.chk_range, QCheckBox)
    assert top.chk_range.isHidden()
    assert top.btn_range_max.isHidden()
    combo = choice.bound_combo()
    assert combo.isHidden()
    assert combo.count() == 2

    _assert_mode_matches_owner(top, enabled=False)


def test_time_range_segment_toggles_readonly_without_hiding_pair_row(qapp):
    top = PersistentTop()
    top.show()
    try:
        qapp.processEvents()
        _assert_mode_matches_owner(top, enabled=False)

        select_time_range_mode(top, True)
        _assert_mode_matches_owner(top, enabled=True)

        select_time_range_mode(top, False)
        _assert_mode_matches_owner(top, enabled=False)
    finally:
        top.hide()


def test_reselecting_current_time_range_segment_does_not_emit_user_signals(qapp):
    top = PersistentTop()
    choice = time_range_choice(top)
    combo = choice.bound_combo()

    edited = QSignalSpy(top.range_edited)
    invalid = QSignalSpy(top.range_edit_invalid)
    max_requested = QSignalSpy(top.max_range_requested)
    toggled = QSignalSpy(top.chk_range.toggled)
    combo_spy = QSignalSpy(combo.currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)

    select_time_range_mode(top, False)
    assert list(edited) == []
    assert list(invalid) == []
    assert list(max_requested) == []
    assert list(toggled) == []
    assert list(combo_spy) == []
    assert list(choice_spy) == []

    select_time_range_mode(top, True)
    assert top.range_enabled() is True
    assert list(edited) == []
    assert list(max_requested) == []
    assert list(toggled) == [[True]]
    assert list(combo_spy) == [[1]]
    assert list(choice_spy) == [[1]]

    toggled_after = QSignalSpy(top.chk_range.toggled)
    combo_after = QSignalSpy(combo.currentIndexChanged)
    choice_after = QSignalSpy(choice.currentIndexChanged)
    edited_after = QSignalSpy(top.range_edited)
    select_time_range_mode(top, True)
    assert list(toggled_after) == []
    assert list(combo_after) == []
    assert list(choice_after) == []
    assert list(edited_after) == []
    _assert_mode_matches_owner(top, enabled=True)


def test_full_mode_set_range_values_updates_without_range_edited(qapp, qtbot):
    top = PersistentTop()
    qtbot.addWidget(top)
    _assert_mode_matches_owner(top, enabled=False)

    edited = []
    top.range_edited.connect(lambda lo, hi: edited.append((lo, hi)))
    top.set_range_values(12.0, 18.0)

    assert top.range_values() == pytest.approx((12.0, 18.0))
    assert edited == []
    assert top.query_range_edit().status == RangeEditQuery.UNCHANGED
    _assert_mode_matches_owner(top, enabled=False)

    select_time_range_mode(top, True)
    edited.clear()
    top.set_range_values(1.5, 9.5)
    assert top.range_values() == pytest.approx((1.5, 9.5))
    assert edited == []
    assert top.query_range_edit().status == RangeEditQuery.UNCHANGED
    _assert_mode_matches_owner(top, enabled=True)


def test_set_range_from_span_silently_selects_specified_range(qapp, qtbot):
    top = PersistentTop()
    qtbot.addWidget(top)
    edited = QSignalSpy(top.range_edited)
    toggled = QSignalSpy(top.chk_range.toggled)

    top.set_range_from_span(2.0, 4.0)

    assert top.range_values() == pytest.approx((2.0, 4.0))
    assert list(edited) == []
    assert list(toggled) == []
    _assert_mode_matches_owner(top, enabled=True)


def test_full_mode_blocks_key_paste_step_and_wheel_but_allows_copy(qapp, qtbot):
    top = PersistentTop()
    qtbot.addWidget(top)
    top.resize(288, 240)
    top.show()
    qtbot.waitExposed(top)
    qapp.processEvents()

    top.set_range_values(12.0, 18.0)
    _assert_mode_matches_owner(top, enabled=False)
    original = top.range_values()
    start_text = top.spin_start.lineEdit().text()

    start = top.spin_start
    edit = start.lineEdit()
    start.setFocus()
    qapp.processEvents()

    QTest.keyClick(start, Qt.Key_Down)
    QTest.keyClick(start, Qt.Key_Up)
    QTest.keyClicks(edit, "9")
    QApplication.clipboard().setText("88.875")
    QTest.keyClick(edit, Qt.Key_V, Qt.ControlModifier)
    QTest.keyClick(edit, Qt.Key_V, Qt.MetaModifier)
    _send_wheel(start, qapp)
    _send_wheel(edit, qapp)

    assert top.range_values() == pytest.approx(original)
    assert start.isReadOnly()
    assert edit.isReadOnly()
    assert "88.875" not in edit.text()
    assert edit.text() == start_text

    edit.selectAll()
    selected = edit.selectedText()
    assert selected
    QApplication.clipboard().clear()
    edit.copy()
    copied = QApplication.clipboard().text()
    assert copied
    assert start_text.startswith(copied) or copied in start_text

    select_time_range_mode(top, True)
    qapp.processEvents()
    start.setFocus()
    before = start.value()
    QTest.keyClick(start, Qt.Key_Down)
    qapp.processEvents()
    assert start.value() != pytest.approx(before)
    assert not start.isReadOnly()


def test_hidden_max_range_button_still_emits_compat_signal(qapp):
    top = PersistentTop()
    assert top.btn_range_max.isHidden()
    fired = QSignalSpy(top.max_range_requested)
    top.btn_range_max.click()
    assert list(fired) == [[]]


@pytest.mark.parametrize("mode", RANGE_MODES)
def test_shared_range_segment_stays_single_row_at_narrow_inspector(
    qapp, qtbot, mode,
):
    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        from mf4_analyzer.ui_kit import load_stylesheet
        load_stylesheet(qapp)

        inspector = Inspector()
        qtbot.addWidget(inspector)
        inspector.resize(_NARROW_INSPECTOR_WIDTH, 900)
        inspector.set_mode(mode)
        inspector.show()
        qtbot.waitExposed(inspector)
        qapp.processEvents()

        top = inspector.top
        choice = time_range_choice(top)
        group = top._range_group
        first, second = choice.buttons()

        assert abs(first.width() - second.width()) <= 1
        assert first.y() == second.y()
        assert top.spin_start.width() == top.spin_end.width()
        assert top.spin_start.mapTo(group, QPoint(0, 0)).y() == (
            top.spin_end.mapTo(group, QPoint(0, 0)).y()
        )
        choice_left = choice.mapTo(group, QPoint(0, 0)).x()
        start_left = top.spin_start.mapTo(group, QPoint(0, 0)).x()
        assert abs(choice_left - start_left) <= 1

        for button in (first, second):
            text_w = button.fontMetrics().horizontalAdvance(button.text())
            assert text_w <= button.contentsRect().width(), (
                f"{button.text()!r} clipped in {mode} at "
                f"{_NARROW_INSPECTOR_WIDTH}px "
                f"(text={text_w}px, inner={button.contentsRect().width()}px)"
            )

        choice_right = choice.mapTo(
            inspector, choice.rect().topRight(),
        ).x()
        pair_right = top._range_row_host.mapTo(
            inspector, top._range_row_host.rect().topRight(),
        ).x()
        assert choice_right <= inspector.width()
        assert pair_right <= inspector.width()
        assert not top.spin_start.isHidden()
        assert not top.spin_end.isHidden()
    finally:
        qapp.setStyleSheet(old_sheet)


def test_five_section_remount_keeps_segment_readonly_and_silent_checkout(
    qapp, qtbot,
):
    inspector = Inspector()
    qtbot.addWidget(inspector)
    inspector.resize(_NARROW_INSPECTOR_WIDTH, 900)
    inspector.show()
    qtbot.waitExposed(inspector)
    top = inspector.top

    edited = []
    top.range_edited.connect(lambda lo, hi: edited.append((lo, hi)))
    toggled = []
    top.chk_range.toggled.connect(toggled.append)

    inspector.set_mode("time")
    qapp.processEvents()
    top.set_range_values(12.0, 18.0)
    select_time_range_mode(top, True)
    assert toggled == [True]
    edited.clear()
    toggled.clear()
    _assert_mode_matches_owner(top, enabled=True)
    assert top.range_values() == pytest.approx((12.0, 18.0))

    inspector.set_mode("fft")
    qapp.processEvents()
    assert edited == []
    assert toggled == []
    _assert_mode_matches_owner(top, enabled=False)

    top.set_range_from_span(3.0, 4.0)
    assert edited == []
    assert toggled == []
    _assert_mode_matches_owner(top, enabled=True)
    assert top.range_values() == pytest.approx((3.0, 4.0))

    inspector.set_mode("time")
    qapp.processEvents()
    assert edited == []
    assert toggled == []
    _assert_mode_matches_owner(top, enabled=True)
    assert top.range_values() == pytest.approx((3.0, 4.0))

    inspector.set_mode("fft")
    qapp.processEvents()
    _assert_mode_matches_owner(top, enabled=True)

    for mode in RANGE_MODES:
        inspector.set_mode(mode)
        qapp.processEvents()
        assert time_range_choice(top) is top.choice_range
        assert top.range_group().isVisible()
        assert not top.spin_start.isHidden()
        assert not top.spin_end.isHidden()
        _assert_mode_matches_owner(top, enabled=top.range_enabled())
        assert edited == []
        assert toggled == []
        top.set_range_values(5.0, 6.0)
        assert edited == []
        assert top.query_range_edit().status == RangeEditQuery.UNCHANGED
