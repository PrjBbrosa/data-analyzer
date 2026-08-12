"""Seven-family contracts for the shared selected-segment visual signature."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QPushButton, QWidget

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS


_QSS_PATH = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui_kit" / "style.qss"

_FAMILIES = (
    ("choice", 'QFrame#segmentedChoice QPushButton[role="choice"]', "segmentedChoice", "role", "choice"),
    ("frf", 'QFrame#frfSegmentChoice QPushButton[role="frf-segment"]', "frfSegmentChoice", "role", "frf-segment"),
    ("chart", 'QWidget#chartToolbar QPushButton[role="chart-choice"]', "chartToolbar", "role", "chart-choice"),
    ("tick", 'QFrame#TickDensitySurface QPushButton[role="tick-density-preset"]', "TickDensitySurface", "role", "tick-density-preset"),
    ("slice", 'QWidget#sliceDirToggle QPushButton[role="slice-seg"]', "sliceDirToggle", "role", "slice-seg"),
    ("cockpit", 'QWidget#cockpitModeSegment QPushButton[cockpitMode]', "cockpitModeSegment", "cockpitMode", "time"),
    ("batch", 'QWidget#BatchMethodGroup QPushButton[batchMethod]', "BatchMethodGroup", "batchMethod", "fft"),
)


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def production_stylesheet(qapp):
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        yield qapp
    finally:
        qapp.setStyleSheet(previous)


def _selector_body(qss: str, selector: str) -> str:
    try:
        start = qss.index(selector)
        end = qss.index("\n}", start)
    except ValueError as exc:
        raise AssertionError(selector) from exc
    return qss[start:end]


def _family_widget(family):
    _name, _selector, root_name, property_name, property_value = family
    root = QFrame() if root_name in {"segmentedChoice", "frfSegmentChoice", "TickDensitySurface"} else QWidget()
    root.setObjectName(root_name)
    layout_parent = root
    if root_name == "TickDensitySurface":
        host = QFrame(root)
        host.setObjectName("tickDensityPresetHost")
        layout = QHBoxLayout(host)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(host)
        layout_parent = host
    else:
        layout = QHBoxLayout(root)
    layout.setContentsMargins(2, 2, 2, 2)
    layout.setSpacing(0)
    button = QPushButton("段", layout_parent)
    button.setCheckable(True)
    button.setProperty(property_name, property_value)
    layout.addWidget(button)
    root.resize(120, 48)
    root.show()
    QApplication.processEvents()
    return root, button


def _checked_pill_row_colors(button: QPushButton) -> set[str]:
    image = button.grab().toImage()
    y = button.height() // 2
    return {
        QColor(image.pixel(x, y)).name().upper()
        for x in range(button.width())
    }


def test_all_family_qss_selectors_share_the_same_normal_and_checked_tokens():
    qss = _QSS_PATH.read_text(encoding="utf-8")
    for _name, selector, _root, _property, _value in _FAMILIES:
        normal = _selector_body(qss, selector)
        hover = _selector_body(qss, selector + ":hover")
        checked = _selector_body(qss, selector + ":checked")

        assert "transparent" in normal
        assert "{{CONTROL_TEXT_MUTED}}" in normal
        assert "{{CONTROL_TEXT}}" in hover
        assert "{{CONTROL_TRACK}}" not in hover
        for token in (
            "{{CONTROL_SURFACE_TOP}}",
            "{{CONTROL_SELECT_LINE}}",
            "{{CONTROL_TEXT_ON_SELECT}}",
        ):
            assert token in checked, (selector, token)


def test_all_selection_families_keep_size_hint_when_checked(production_stylesheet):
    widgets = []
    try:
        for family in _FAMILIES:
            root, button = _family_widget(family)
            widgets.append(root)
            normal_hint = button.sizeHint()
            button.setChecked(True)
            QApplication.processEvents()
            assert button.sizeHint() == normal_hint, family[0]
    finally:
        for root in widgets:
            root.hide()
            root.deleteLater()


def test_all_selection_families_render_the_same_checked_pill_pixels(production_stylesheet):
    widgets = []
    try:
        for family in _FAMILIES:
            root, button = _family_widget(family)
            widgets.append(root)
            button.setChecked(True)
            QApplication.processEvents()
            row_colors = _checked_pill_row_colors(button)
            # chart-choice and cockpitMode reserve an exterior QSS margin,
            # so x=0 belongs to the margin rather than the painted border.
            # Search the rendered center row for the two actual pill inks
            # instead of treating that unpainted margin as a third signature.
            assert CONTROL_COLORS["CONTROL_SURFACE_TOP"] in row_colors, family[0]
            assert CONTROL_COLORS["CONTROL_SELECT_LINE"] in row_colors, family[0]
    finally:
        for root in widgets:
            root.hide()
            root.deleteLater()


def test_batch_grouping_card_keeps_a_one_pixel_border_when_checked():
    """Checked state must keep the base 1px frame (color only — no border: shorthand)."""
    qss = _QSS_PATH.read_text(encoding="utf-8")
    checked = _selector_body(qss, "QPushButton#BatchGroupingCard:checked")
    assert "border: 2px" not in checked
    assert "border-color: {{CONTROL_SELECT_LINE}}" in checked
    # border: shorthand in a state rule would zero the 9px radius (E2).
    assert "border: 1px" not in checked
