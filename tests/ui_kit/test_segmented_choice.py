"""Contracts for binary choices that retain a hidden QComboBox state surface."""
from __future__ import annotations

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QComboBox, QFormLayout, QWidget

from mf4_analyzer.ui.inspector_sections._helpers import _configure_form, _fit_field
from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS
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
