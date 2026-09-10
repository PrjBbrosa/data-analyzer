"""Contracts for binary choices that retain a hidden QComboBox state surface."""
from __future__ import annotations

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QHoverEvent, QWheelEvent
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QComboBox, QFormLayout, QWidget

from mf4_analyzer.ui.inspector_sections._helpers import _configure_form, _fit_field
from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS
from mf4_analyzer.ui_kit.motion import (
    DURATION_MS,
    POLICY_LIGHT,
    POLICY_OFF,
    POLICY_REDUCED,
    selection_easing,
)
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
        assert choice.motion_policy() == POLICY_LIGHT
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
    assert choice.motion_policy() == POLICY_LIGHT
    assert top.combo_xaxis.isHidden()
    assert choice.height() == 32
    choice.buttons()[1].click()
    assert top.xaxis_mode() == "channel"


def _driver_is_active(choice: SegmentedChoice) -> bool:
    driver = choice._motion_driver
    return driver is not None and driver.is_active()


def test_frf_preset_apply_snaps_binary_choices_without_extra_signals(qtbot, qapp):
    from mf4_analyzer.ui.inspector_sections import FrfContextual

    panel = FrfContextual()
    qtbot.addWidget(panel)
    panel.resize(288, 900)
    panel.show()
    qapp.processEvents()

    names = (
        "choice_estimator",
        "choice_nfft_mode",
        "choice_magnitude_scale",
        "choice_frequency_scale",
        "choice_phase_mode",
    )
    choices = tuple(getattr(panel, name) for name in names)
    for choice in choices:
        assert choice.motion_policy() == POLICY_LIGHT
        assert not _driver_is_active(choice)

    baseline = panel.current_params()
    panel.apply_params(
        {
            "estimator": "h2",
            "nfft_mode": "manual",
            "magnitude_scale": "linear",
            "frequency_scale": "linear",
            "phase_mode": "wrapped",
        }
    )
    assert panel.current_params() != baseline
    for choice in choices:
        assert choice.currentIndex() == 1
        assert not _driver_is_active(choice)

    compute_spy = QSignalSpy(panel.compute_params_changed)
    display_spy = QSignalSpy(panel.display_params_changed)
    combo_spies = [
        QSignalSpy(choice.bound_combo().currentIndexChanged) for choice in choices
    ]
    choice_spies = [QSignalSpy(choice.currentIndexChanged) for choice in choices]

    panel.apply_builtin_preset("robust")

    assert panel.current_params() == baseline
    assert list(compute_spy) == [ [panel.compute_params()] ]
    assert list(display_spy) == [ [panel.display_params()] ]
    for combo_spy, choice_spy, choice in zip(combo_spies, choice_spies, choices):
        assert list(combo_spy) == [[0]]
        assert list(choice_spy) == [[0]]
        assert choice.currentIndex() == 0
        assert not _driver_is_active(choice)


def test_fft_amp_y_restore_snaps_and_click_does_not_animate_weighting(qtbot, qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    panel = FFTContextual()
    qtbot.addWidget(panel)
    panel.resize(288, 900)
    panel.show()
    qapp.processEvents()

    amp = panel.choice_amp_y
    weighting = panel.choice_weighting
    assert amp.motion_policy() == POLICY_LIGHT
    assert weighting.motion_policy() == POLICY_LIGHT
    assert amp.currentIndex() == 0
    assert weighting.currentIndex() == 0

    y_before = (
        panel.chk_y_auto.isChecked(),
        panel.spin_y_min.value(),
        panel.spin_y_max.value(),
    )
    compute_spy = QSignalSpy(panel.compute_params_changed)
    display_spy = QSignalSpy(panel.display_params_changed)
    amp_combo_spy = QSignalSpy(amp.bound_combo().currentIndexChanged)
    amp_choice_spy = QSignalSpy(amp.currentIndexChanged)
    weight_combo_spy = QSignalSpy(weighting.bound_combo().currentIndexChanged)
    weight_choice_spy = QSignalSpy(weighting.currentIndexChanged)

    panel.apply_params({"amp_y": "dB", "y_auto": False, "y_min": 1.0, "y_max": 2.0})

    assert amp.currentIndex() == 1
    assert panel.combo_amp_y.currentText() == "dB"
    assert panel.chk_y_auto.isChecked() is False
    assert panel.spin_y_min.value() == pytest.approx(1.0)
    assert panel.spin_y_max.value() == pytest.approx(2.0)
    assert list(amp_combo_spy) == []
    assert list(amp_choice_spy) == []
    assert list(weight_combo_spy) == []
    assert list(weight_choice_spy) == []
    assert list(compute_spy) == []
    assert list(display_spy) == []
    assert not _driver_is_active(amp)
    assert not _driver_is_active(weighting)
    assert y_before != (
        False,
        1.0,
        2.0,
    )

    QTest.mouseClick(amp.buttons()[0], Qt.LeftButton)

    assert amp.currentIndex() == 0
    assert panel.combo_amp_y.currentText() == "Linear"
    assert list(amp_combo_spy) == [[0]]
    assert list(amp_choice_spy) == [[0]]
    assert list(weight_combo_spy) == []
    assert list(weight_choice_spy) == []
    assert list(compute_spy) == []
    display_after_click = list(display_spy)
    assert _driver_is_active(amp)
    assert not _driver_is_active(weighting)
    amp._motion_driver.clock().setCurrentTime(300)
    assert list(amp_combo_spy) == [[0]]
    assert list(amp_choice_spy) == [[0]]
    assert list(weight_combo_spy) == []
    assert list(weight_choice_spy) == []
    assert list(compute_spy) == []
    assert list(display_spy) == display_after_click
    assert not _driver_is_active(amp)
    assert not _driver_is_active(weighting)


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


def _token_name(name: str) -> str:
    return QColor(CONTROL_COLORS[name]).name()


def _show_bound_choice_in_parent(qtbot, qapp, *, width=260) -> tuple[QWidget, SegmentedChoice]:
    parent = QWidget()
    choice = SegmentedChoice(parent)
    choice.bind(_binary_combo())
    choice.setGeometry(0, 0, width, 32)
    parent.resize(width, 32)
    qtbot.addWidget(parent)
    parent.show()
    qapp.processEvents()
    return parent, choice


def _set_effective_enabled(choice: SegmentedChoice, parent, enabled: bool, via: str) -> None:
    if via == "ancestor":
        parent.setEnabled(enabled)
        return
    choice.setEnabled(enabled)


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


def _force_hover_and_focus(widget, qapp) -> None:
    pos = QPoint(max(widget.width() // 2, 1), 4)
    widget.setAttribute(Qt.WA_UnderMouse, True)
    QTest.mouseMove(widget, pos)
    qapp.sendEvent(widget, QEvent(QEvent.Enter))
    qapp.sendEvent(widget, QHoverEvent(QEvent.HoverEnter, pos, QPoint(-1, -1)))
    qapp.sendEvent(widget, QEvent(QEvent.FocusIn))
    widget.setFocus()
    qapp.processEvents()


def test_motion_policy_defaults_off_and_click_does_not_start_a_clock(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    assert choice.motion_policy() == POLICY_OFF
    assert choice._motion_driver is None
    assert choice._selection_pill is None
    assert "_motion_driver" not in choice.__dict__

    QTest.mouseClick(choice.buttons()[1], Qt.LeftButton)
    qapp.processEvents()

    assert choice.currentIndex() == 1
    assert choice.buttons()[1].isChecked()
    assert choice._motion_driver is None
    assert choice._selection_pill is None
    assert "_motion_driver" not in choice.__dict__
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
    assert "_motion_driver" not in choice.__dict__

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    QTest.mouseClick(second, Qt.LeftButton)

    assert choice.bound_combo().currentIndex() == 1
    assert choice.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == [[1]]
    assert list(choice_spy) == [[1]]
    assert driver.is_active()
    assert driver.clock().duration() == DURATION_MS["selection_control"] == 300
    used = driver.clock().easingCurve()
    assert used.valueForProgress(0.25) == pytest.approx(0.735, abs=0.005)
    assert used.valueForProgress(0.50) == pytest.approx(0.937, abs=0.005)
    assert used.valueForProgress(0.25) == pytest.approx(
        selection_easing().valueForProgress(0.25), abs=0.001
    )

    clock = driver.clock()
    clock.setCurrentTime(0)
    assert QRect(driver.current()) == first.geometry()
    assert pill.geometry() == first.geometry()

    clock.setCurrentTime(75)
    mid_25 = QRect(driver.current())
    assert first.x() < mid_25.x() < second.x()
    assert pill.geometry() == mid_25
    assert mid_25 != first.geometry()
    assert mid_25 != second.geometry()

    clock.setCurrentTime(150)
    mid_50 = QRect(driver.current())
    assert mid_50.x() > mid_25.x()
    assert pill.geometry() == mid_50
    assert first.x() < mid_50.x() < second.x()

    clock.setCurrentTime(300)
    assert QRect(driver.current()) == second.geometry()
    assert pill.geometry() == second.geometry()
    assert not driver.is_active()
    assert list(combo_spy) == [[1]]
    assert list(choice_spy) == [[1]]
    assert choice.height() == 32


def test_motion_interrupt_continues_from_displayed_rect(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    QTest.mouseClick(second, Qt.LeftButton)
    driver.clock().setCurrentTime(75)
    mid = QRect(driver.current())
    assert mid not in (first.geometry(), second.geometry())

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    QTest.mouseClick(first, Qt.LeftButton)

    assert choice.currentIndex() == 0
    assert first.isChecked()
    assert list(combo_spy) == [[0]]
    assert driver.is_active()
    assert QRect(driver.clock().startValue()) == mid
    assert QRect(driver.target()) == first.geometry()
    assert QRect(driver.current()) == mid
    assert choice._selection_pill.geometry() == mid


def test_program_set_current_index_snaps_while_visible_light(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    pill = choice._selection_pill
    assert driver is not None and pill is not None
    assert not driver.is_active()

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    choice.setCurrentIndex(1)

    assert choice.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == [[1]]
    assert list(choice_spy) == [[1]]
    assert not driver.is_active()
    assert pill.geometry() == second.geometry()

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    choice.bound_combo().setCurrentIndex(0)

    assert choice.currentIndex() == 0
    assert first.isChecked() and not second.isChecked()
    assert list(combo_spy) == [[0]]
    assert list(choice_spy) == [[0]]
    assert not driver.is_active()
    assert pill.geometry() == first.geometry()


def test_preset_blocked_combo_sync_does_not_animate(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    combo = choice.bound_combo()
    combo_spy = QSignalSpy(combo.currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    combo.blockSignals(True)
    try:
        combo.setCurrentIndex(1)
    finally:
        combo.blockSignals(False)
    choice.sync_from_bound_combo()

    assert combo.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == []
    assert list(choice_spy) == []
    assert not driver.is_active()
    assert choice._selection_pill.geometry() == second.geometry()


def test_linked_instance_snaps_while_direct_click_animates(qtbot, qapp):
    choice_a = _show_bound_choice(qtbot, qapp)
    choice_b = _show_bound_choice(qtbot, qapp)
    choice_a.set_motion_policy(POLICY_LIGHT)
    choice_b.set_motion_policy(POLICY_LIGHT)
    driver_a = choice_a._motion_driver
    driver_b = choice_b._motion_driver
    assert driver_a is not None and driver_b is not None
    assert not driver_a.is_active()
    assert not driver_b.is_active()

    choice_a.currentIndexChanged.connect(choice_b.setCurrentIndex)
    spy_a = QSignalSpy(choice_a.currentIndexChanged)
    spy_b = QSignalSpy(choice_b.currentIndexChanged)
    QTest.mouseClick(choice_a.buttons()[1], Qt.LeftButton)

    assert choice_a.currentIndex() == 1
    assert choice_b.currentIndex() == 1
    assert list(spy_a) == [[1]]
    assert list(spy_b) == [[1]]
    assert driver_a.is_active()
    assert driver_a.clock().duration() == 300
    assert not driver_b.is_active()
    assert choice_b._selection_pill.geometry() == choice_b.buttons()[1].geometry()

    driver_a.clock().setCurrentTime(300)
    assert not driver_a.is_active()
    assert not driver_b.is_active()
    assert list(spy_a) == [[1]]
    assert list(spy_b) == [[1]]


def test_business_correction_snaps_to_corrected_index(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver

    def _correct(_index: int) -> None:
        if choice.bound_combo().currentIndex() == 1:
            choice.bound_combo().setCurrentIndex(0)

    choice.currentIndexChanged.connect(_correct)
    QTest.mouseClick(second, Qt.LeftButton)

    assert choice.currentIndex() == 0
    assert first.isChecked() and not second.isChecked()
    assert not driver.is_active()
    assert choice._selection_pill.geometry() == first.geometry()


def test_sync_from_blocked_combo_snaps_to_end_state(qtbot, qapp):
    choice = _show_bound_choice(qtbot, qapp)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    QTest.mouseClick(second, Qt.LeftButton)
    driver.clock().setCurrentTime(75)
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
    QTest.mouseClick(second, Qt.LeftButton)
    driver.clock().setCurrentTime(75)
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

    QTest.mouseClick(second, Qt.LeftButton)
    driver.clock().setCurrentTime(75)
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
    plates = [
        child
        for child in choice.findChildren(QWidget)
        if child.objectName() == "selectionIndicatorPlate"
    ]
    assert len(plates) == 1
    assert plates[0] is choice._selection_pill

    QTest.mouseClick(second, Qt.LeftButton)
    driver.clock().setCurrentTime(0)
    choice.repaint()

    assert second.isChecked() and not first.isChecked()
    assert choice._selection_pill.geometry() == first.geometry()
    assert _background_at(choice, first) == QColor(
        CONTROL_COLORS["CONTROL_SURFACE_TOP"]
    ).name()
    assert _background_at(choice, second) == QColor(CONTROL_COLORS["CONTROL_TRACK"]).name()
    plates = [
        child
        for child in choice.findChildren(QWidget)
        if child.objectName() == "selectionIndicatorPlate"
    ]
    assert len(plates) == 1

    driver.clock().setCurrentTime(300)
    choice.repaint()
    assert choice._selection_pill.geometry() == second.geometry()
    assert _background_at(choice, first) == QColor(CONTROL_COLORS["CONTROL_TRACK"]).name()
    assert _background_at(choice, second) == QColor(
        CONTROL_COLORS["CONTROL_SURFACE_TOP"]
    ).name()
    assert not driver.is_active()


def test_motion_deferred_delete_owns_pill_driver_and_hidden_combo(qapp):
    host = QWidget()
    combo = _binary_combo()
    choice = SegmentedChoice(host)
    choice.bind(combo)
    host.resize(260, 32)
    host.show()
    qapp.processEvents()
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


@pytest.mark.parametrize("via", ("self", "ancestor"))
def test_disable_preserves_selection_and_does_not_emit_index_signals(
    qtbot, production_stylesheet, via,
):
    if via == "ancestor":
        parent, choice = _show_bound_choice_in_parent(qtbot, production_stylesheet)
    else:
        parent, choice = None, _show_bound_choice(qtbot, production_stylesheet)
    choice.setCurrentIndex(1)
    production_stylesheet.processEvents()
    first, second = choice.buttons()
    assert second.isChecked() and not first.isChecked()

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    _set_effective_enabled(choice, parent, False, via)
    production_stylesheet.processEvents()

    assert choice.currentIndex() == 1
    assert choice.bound_combo().currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == []
    assert list(choice_spy) == []
    assert not choice.isEnabled()

    _set_effective_enabled(choice, parent, True, via)
    production_stylesheet.processEvents()

    assert choice.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == []
    assert list(choice_spy) == []
    assert choice.isEnabled()


@pytest.mark.parametrize("via", ("self", "ancestor"))
def test_disabled_mouse_keyboard_and_wheel_do_not_change_index(
    qtbot, production_stylesheet, via,
):
    if via == "ancestor":
        parent, choice = _show_bound_choice_in_parent(qtbot, production_stylesheet)
    else:
        parent, choice = None, _show_bound_choice(qtbot, production_stylesheet)
    choice.setCurrentIndex(1)
    production_stylesheet.processEvents()
    first, second = choice.buttons()
    _set_effective_enabled(choice, parent, False, via)
    production_stylesheet.processEvents()

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    QTest.mouseClick(first, Qt.LeftButton)
    QTest.keyClick(first, Qt.Key_Space)
    QTest.keyClick(first, Qt.Key_Return)
    QTest.keyClick(choice, Qt.Key_Left)
    _send_wheel(choice, production_stylesheet)
    _send_wheel(first, production_stylesheet)
    _send_wheel(choice.bound_combo(), production_stylesheet)
    production_stylesheet.processEvents()

    assert choice.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == []
    assert list(choice_spy) == []


@pytest.mark.parametrize("via", ("self", "ancestor"))
def test_disabled_hover_and_focus_do_not_restore_white_selected_fill(
    qtbot, production_stylesheet, via,
):
    if via == "ancestor":
        parent, choice = _show_bound_choice_in_parent(qtbot, production_stylesheet)
    else:
        parent, choice = None, _show_bound_choice(qtbot, production_stylesheet)
    choice.setCurrentIndex(1)
    production_stylesheet.processEvents()
    first, second = choice.buttons()
    _set_effective_enabled(choice, parent, False, via)
    production_stylesheet.processEvents()
    _force_hover_and_focus(second, production_stylesheet)
    choice.repaint()

    assert _background_at(choice, second) == _token_name("CONTROL_DISABLED_BG")
    assert _background_at(choice, first) == _token_name("CONTROL_TRACK")
    assert _background_at(choice, second) != _token_name("CONTROL_SURFACE_TOP")


@pytest.mark.parametrize("via", ("self", "ancestor"))
def test_reenable_restores_white_selected_pill_and_original_index(
    qtbot, production_stylesheet, via,
):
    if via == "ancestor":
        parent, choice = _show_bound_choice_in_parent(qtbot, production_stylesheet)
    else:
        parent, choice = None, _show_bound_choice(qtbot, production_stylesheet)
    choice.setCurrentIndex(1)
    production_stylesheet.processEvents()
    first, second = choice.buttons()
    _set_effective_enabled(choice, parent, False, via)
    production_stylesheet.processEvents()
    assert _background_at(choice, second) == _token_name("CONTROL_DISABLED_BG")

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    _set_effective_enabled(choice, parent, True, via)
    production_stylesheet.processEvents()
    choice.repaint()

    assert choice.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == []
    assert list(choice_spy) == []
    assert _background_at(choice, second) == _token_name("CONTROL_SURFACE_TOP")
    assert _background_at(choice, first) == _token_name("CONTROL_TRACK")


@pytest.mark.parametrize("policy", (None, POLICY_OFF))
def test_disabled_checked_qss_uses_disabled_tokens_when_motion_off(
    qtbot, production_stylesheet, policy,
):
    choice = _show_bound_choice(qtbot, production_stylesheet)
    if policy is not None:
        choice.set_motion_policy(policy)
    choice.setCurrentIndex(1)
    production_stylesheet.processEvents()
    first, second = choice.buttons()
    assert _background_at(choice, second) == _token_name("CONTROL_SURFACE_TOP")

    choice.setEnabled(False)
    production_stylesheet.processEvents()
    choice.repaint()

    assert choice.motion_policy() == POLICY_OFF
    assert choice._selection_pill is None or choice._selection_pill.isHidden()
    assert _background_at(choice, second) == _token_name("CONTROL_DISABLED_BG")
    assert _background_at(choice, first) == _token_name("CONTROL_TRACK")
    assert _background_at(choice, second) != _token_name("CONTROL_SURFACE_TOP")


def test_motion_light_disable_mid_animation_snaps_and_paints_disabled(
    qtbot, production_stylesheet,
):
    choice = _show_bound_choice(qtbot, production_stylesheet)
    choice.set_motion_policy(POLICY_LIGHT)
    first, second = choice.buttons()
    driver = choice._motion_driver
    pill = choice._selection_pill
    production_stylesheet.processEvents()
    assert pill is not None and driver is not None

    QTest.mouseClick(second, Qt.LeftButton)
    driver.clock().setCurrentTime(75)
    mid = QRect(driver.current())
    assert driver.is_active()
    assert mid not in (first.geometry(), second.geometry())
    assert pill.geometry() == mid

    combo_spy = QSignalSpy(choice.bound_combo().currentIndexChanged)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    choice.setEnabled(False)
    production_stylesheet.processEvents()
    choice.repaint()

    assert choice.currentIndex() == 1
    assert second.isChecked() and not first.isChecked()
    assert list(combo_spy) == []
    assert list(choice_spy) == []
    assert not driver.is_active()
    assert pill.geometry() == second.geometry()
    assert _background_at(choice, second) == _token_name("CONTROL_DISABLED_BG")
    assert _background_at(choice, first) == _token_name("CONTROL_TRACK")
    assert _background_at(choice, second) != _token_name("CONTROL_SURFACE_TOP")

    choice.setEnabled(True)
    production_stylesheet.processEvents()
    choice.repaint()

    assert choice.currentIndex() == 1
    assert choice.motion_policy() == POLICY_LIGHT
    assert not driver.is_active()
    assert pill.geometry() == second.geometry()
    assert _background_at(choice, second) == _token_name("CONTROL_SURFACE_TOP")
    assert _background_at(choice, first) == _token_name("CONTROL_TRACK")
