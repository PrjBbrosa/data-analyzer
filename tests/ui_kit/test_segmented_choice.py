"""Contracts for binary choices that retain a hidden QComboBox state surface."""
from __future__ import annotations

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QRect, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QComboBox, QFormLayout, QWidget

from mf4_analyzer.ui.inspector_sections._helpers import _configure_form, _fit_field
from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, POLICY_REDUCED
from mf4_analyzer.ui_kit.widgets.segmented_choice import SegmentedChoice


def _binary_combo(parent=None) -> QComboBox:
    combo = QComboBox(parent)
    combo.addItem("自动", "auto")
    combo.addItem("手动", "manual")
    combo.setItemData(0, "自动模式的完整说明", Qt.ToolTipRole)
    combo.setItemData(1, "手动模式的完整说明", Qt.ToolTipRole)
    return combo


@pytest.fixture
def production_stylesheet(qapp):
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        yield qapp
    finally:
        qapp.setStyleSheet(previous)


def test_segmented_choice_binds_hidden_combo_bidirectionally_without_signal_loop(qtbot):
    combo = _binary_combo()
    choice = SegmentedChoice()
    qtbot.addWidget(choice)
    choice.bind(combo)

    assert choice.objectName() == "segmentedChoice"
    assert combo.isHidden()
    assert choice.height() == 32
    assert [button.property("role") for button in choice.buttons()] == ["choice", "choice"]
    assert [button.toolTip() for button in choice.buttons()] == [
        "自动模式的完整说明", "手动模式的完整说明",
    ]
    assert choice.currentIndex() == combo.currentIndex() == 0

    combo_spy = QSignalSpy(combo.currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    QTest.mouseClick(choice.buttons()[1], Qt.LeftButton)

    assert combo.currentIndex() == 1
    assert choice.currentIndex() == 1
    assert list(combo_spy) == [[1]]
    assert list(choice_spy) == [[1]]

    combo_spy = QSignalSpy(combo.currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    combo.setCurrentIndex(0)

    assert choice.currentIndex() == 0
    assert choice.buttons()[0].isChecked()
    assert list(combo_spy) == [[0]]
    assert list(choice_spy) == [[0]]


@pytest.mark.parametrize("item_count", [1, 3])
def test_segmented_choice_rejects_non_binary_combo(qtbot, item_count):
    combo = QComboBox()
    for index in range(item_count):
        combo.addItem(str(index), index)
    choice = SegmentedChoice()
    qtbot.addWidget(choice)

    with pytest.raises(ValueError, match="exactly two"):
        choice.bind(combo)


def test_segmented_choice_fills_the_32px_inspector_field_slot(qtbot, qapp):
    panel = QWidget()
    qtbot.addWidget(panel)
    form = QFormLayout(panel)
    _configure_form(form)
    reference = _binary_combo(panel)
    choice = SegmentedChoice(panel)
    choice.bind(_binary_combo())
    form.addRow("下拉:", _fit_field(reference, max_width=260))
    form.addRow("分段:", _fit_field(choice, max_width=260))
    panel.resize(288, 120)
    panel.show()
    qapp.processEvents()

    reference_left = reference.mapTo(panel, reference.rect().topLeft()).x()
    reference_right = reference.mapTo(panel, reference.rect().topRight()).x()
    choice_left = choice.mapTo(panel, choice.rect().topLeft()).x()
    choice_right = choice.mapTo(panel, choice.rect().topRight()).x()

    assert choice.height() == 32
    assert (choice_left, choice_right) == (reference_left, reference_right)


def test_segmented_choice_production_qss_renders_a_stable_track_and_selected_pill(
    qtbot, production_stylesheet,
):
    choice = SegmentedChoice()
    choice.bind(_binary_combo())
    choice.resize(260, 32)
    qtbot.addWidget(choice)
    choice.show()
    production_stylesheet.processEvents()

    first, second = choice.buttons()
    first_geometry = first.geometry()
    second_geometry = second.geometry()

    def background_at(button):
        image = choice.grab().toImage()
        point_x = button.x() + button.width() // 2
        return QColor(image.pixel(point_x, button.y() + 2)).name()

    assert choice.size().width() == 260
    assert choice.size().height() == 32
    assert first.height() == second.height() == 26
    assert background_at(first) == QColor(CONTROL_COLORS["CONTROL_SURFACE_TOP"]).name()
    assert background_at(second) == QColor(CONTROL_COLORS["CONTROL_TRACK"]).name()

    QTest.mouseClick(second, Qt.LeftButton)
    production_stylesheet.processEvents()

    assert choice.size().width() == 260
    assert choice.size().height() == 32
    assert first.geometry() == first_geometry
    assert second.geometry() == second_geometry
    assert background_at(first) == QColor(CONTROL_COLORS["CONTROL_TRACK"]).name()
    assert background_at(second) == QColor(CONTROL_COLORS["CONTROL_SURFACE_TOP"]).name()


def test_segmented_choice_deferred_delete_owns_buttons_group_and_reparented_combo(qapp):
    host = QWidget()
    combo = _binary_combo()
    choice = SegmentedChoice(host)
    choice.bind(combo)
    group = choice._group
    buttons = choice.buttons()

    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()

    assert sip.isdeleted(choice)
    assert sip.isdeleted(combo)
    assert sip.isdeleted(group)
    assert all(sip.isdeleted(button) for button in buttons)


@pytest.mark.parametrize(
    "factory, choice_names",
    [
        ("FFTContextual", ("choice_amp_y", "choice_weighting")),
        ("FFTTimeContextual", ("choice_weighting", "choice_amp_unit")),
        ("OrderContextual", ("choice_rpm_mode", "choice_weighting", "choice_amp_unit")),
        (
            "FrfContextual",
            (
                "choice_estimator",
                "choice_nfft_mode",
                "choice_magnitude_scale",
                "choice_frequency_scale",
                "choice_phase_mode",
            ),
        ),
    ],
)
def test_contextual_binary_choices_keep_hidden_combo_state_and_32px_height(
    qtbot, qapp, factory, choice_names
):
    from mf4_analyzer.ui import inspector_sections

    panel = getattr(inspector_sections, factory)()
    qtbot.addWidget(panel)
    panel.resize(288, 900)
    panel.show()
    qapp.processEvents()

    for name in choice_names:
        choice = getattr(panel, name)
        assert isinstance(choice, SegmentedChoice)
        assert choice.height() == 32
        assert choice.bound_combo().isHidden()
        assert choice.currentIndex() == choice.bound_combo().currentIndex()


def test_persistent_top_xaxis_source_is_a_full_width_segmented_choice(qtbot, qapp):
    from mf4_analyzer.ui.inspector_sections.persistent_top import PersistentTop

    top = PersistentTop()
    qtbot.addWidget(top)
    top.resize(288, 500)
    top.show()
    qapp.processEvents()

    choice = top.choice_xaxis
    assert isinstance(choice, SegmentedChoice)
    assert top.combo_xaxis.isHidden()
    assert choice.height() == 32
    choice.buttons()[1].click()
    assert top.xaxis_mode() == "channel"


def _show_bound_choice(qtbot, qapp, *, width=260) -> SegmentedChoice:
    choice = SegmentedChoice()
    choice.bind(_binary_combo())
    choice.resize(width, 32)
    qtbot.addWidget(choice)
    choice.show()
    qapp.processEvents()
    return choice


def _background_at(choice: SegmentedChoice, button) -> str:
    image = choice.grab().toImage()
    point_x = button.x() + button.width() // 2
    point_y = button.y() + button.height() // 2
    return QColor(image.pixel(point_x, point_y)).name()


def test_motion_policy_defaults_off_and_click_does_not_start_a_clock(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    assert choice.motion_policy() == POLICY_OFF
    assert choice._motion_driver is None
    assert choice._selection_pill is None

    QTest.mouseClick(choice.buttons()[1], Qt.LeftButton)
    qapp.processEvents()

    assert choice.currentIndex() == 1
    assert choice.buttons()[1].isChecked()
    assert choice._motion_driver is None
    assert choice._selection_pill is None
    assert choice.height() == 32


def test_motion_pill_tracks_0_25_50_100_percent_frames(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    pill = choice._selection_pill
    driver = choice._motion_driver
    assert pill is not None and driver is not None
    assert pill.geometry() == first.geometry()
    assert not driver.is_active()

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    choice.setCurrentIndex(1)

    assert choice.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == [[1]]
    assert list(choice_spy) == [[1]]
    assert driver.is_active()
    assert driver.clock().duration() == 160

    clock = driver.clock()
    clock.setCurrentTime(0)
    assert QRect(driver.current()) == first.geometry()
    assert pill.geometry() == first.geometry()

    clock.setCurrentTime(40)
    mid_25 = QRect(driver.current())
    assert first.x() < mid_25.x() < second.x()
    assert pill.geometry() == mid_25
    assert mid_25 != first.geometry()
    assert mid_25 != second.geometry()

    clock.setCurrentTime(80)
    mid_50 = QRect(driver.current())
    assert mid_50.x() > mid_25.x()
    assert pill.geometry() == mid_50
    assert first.x() < mid_50.x() < second.x()

    clock.setCurrentTime(160)
    assert QRect(driver.current()) == second.geometry()
    assert pill.geometry() == second.geometry()
    assert not driver.is_active()
    assert choice.height() == 32


def test_motion_interrupt_continues_from_displayed_rect(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    choice.setCurrentIndex(1)
    driver.clock().setCurrentTime(40)
    mid = QRect(driver.current())
    assert mid not in (first.geometry(), second.geometry())

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice.setCurrentIndex(0)

    assert choice.currentIndex() == 0
    assert first.isChecked()
    assert list(combo_spy) == [[0]]
    assert driver.is_active()
    assert QRect(driver.clock().startValue()) == mid
    assert QRect(driver.target()) == first.geometry()
    assert QRect(driver.current()) == mid
    assert choice._selection_pill.geometry() == mid


def test_sync_from_blocked_combo_snaps_to_end_state(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    choice.setCurrentIndex(1)
    driver.clock().setCurrentTime(40)
    assert driver.is_active()

    combo = choice.bound_combo()
    combo_spy = QSignalSpy(combo.currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    combo.blockSignals(True)
    try:
        combo.setCurrentIndex(0)
    finally:
        combo.blockSignals(False)
    choice.sync_from_bound_combo()

    assert combo.currentIndex() == 0
    assert first.isChecked() and not second.isChecked()
    assert list(combo_spy) == []
    assert list(choice_spy) == []
    assert not driver.is_active()
    assert choice._selection_pill.geometry() == first.geometry()


def test_resize_snaps_to_measured_button_rect_without_chasing(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp, width=260)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    choice.setCurrentIndex(1)
    driver.clock().setCurrentTime(40)
    assert driver.is_active()
    assert first.width() == second.width()

    choice._layout.setStretch(0, 1)
    choice._layout.setStretch(1, 3)
    choice.resize(400, 32)
    qapp.processEvents()

    assert first.width() != second.width()
    assert not driver.is_active()
    assert choice._selection_pill.geometry() == second.geometry()
    half = QRect(choice.width() // 2, second.y(), choice.width() // 2, second.height())
    assert choice._selection_pill.geometry() != half
    assert choice.height() == 32


def test_refresh_and_hide_restore_snap_without_replaying(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    combo = choice.bound_combo()
    first, second = choice.buttons()
    driver = choice._motion_driver

    choice.setCurrentIndex(1)
    driver.clock().setCurrentTime(40)
    combo.setItemText(0, "Auto")
    combo.setItemText(1, "Fixed")
    choice.refresh_from_bound_combo()

    assert [button.text() for button in choice.buttons()] == ["Auto", "Fixed"]
    assert not driver.is_active()
    assert choice._selection_pill.geometry() == second.geometry()

    choice.hide()
    combo.blockSignals(True)
    try:
        combo.setCurrentIndex(0)
    finally:
        combo.blockSignals(False)
    choice.sync_from_bound_combo()
    choice.show()
    qapp.processEvents()

    assert first.isChecked()
    assert not driver.is_active()
    assert choice._selection_pill.geometry() == first.geometry()


def test_reduced_motion_matches_off_endpoints_without_a_running_clock(
    qtbot, qapp, production_stylesheet,
):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_REDUCED)
    first, second = choice.buttons()
    QTest.mouseClick(second, Qt.LeftButton)
    production_stylesheet.processEvents()

    assert choice.motion_policy() == POLICY_REDUCED
    assert choice.currentIndex() == 1
    assert choice._motion_driver is None or not choice._motion_driver.is_active()
    assert choice._selection_pill is None or choice._selection_pill.isHidden()
    assert choice.height() == 32
    assert _background_at(choice, first) == QColor(CONTROL_COLORS["CONTROL_TRACK"]).name()
    assert _background_at(choice, second) == QColor(
        CONTROL_COLORS["CONTROL_SURFACE_TOP"]
    ).name()


def test_light_motion_has_one_plate_and_checked_text_updates_immediately(
    qtbot, qapp, production_stylesheet,
):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    production_stylesheet.processEvents()

    choice.setCurrentIndex(1)
    driver.clock().setCurrentTime(0)
    choice.repaint()

    assert second.isChecked() and not first.isChecked()
    assert choice._selection_pill.geometry() == first.geometry()
    assert _background_at(choice, first) == QColor(
        CONTROL_COLORS["CONTROL_SURFACE_TOP"]
    ).name()
    assert _background_at(choice, second) == QColor(CONTROL_COLORS["CONTROL_TRACK"]).name()

    driver.clock().setCurrentTime(160)
    choice.repaint()
    assert choice._selection_pill.geometry() == second.geometry()
    assert _background_at(choice, first) == QColor(CONTROL_COLORS["CONTROL_TRACK"]).name()
    assert _background_at(choice, second) == QColor(
        CONTROL_COLORS["CONTROL_SURFACE_TOP"]
    ).name()


def test_motion_deferred_delete_owns_pill_driver_and_hidden_combo(qapp):
    host = QWidget()
    combo = _binary_combo()
    choice = SegmentedChoice(host)
    choice.bind(combo)
    choice.set_motion_policy(POLICY_LIGHT)
    group = choice._group
    buttons = choice.buttons()
    pill = choice._selection_pill
    driver = choice._motion_driver
    assert pill is not None and driver is not None
    assert combo.parent() is choice

    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()

    assert sip.isdeleted(choice)
    assert sip.isdeleted(combo)
    assert sip.isdeleted(group)
    assert sip.isdeleted(pill)
    assert sip.isdeleted(driver)
    assert all(sip.isdeleted(button) for button in buttons)
