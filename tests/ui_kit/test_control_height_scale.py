"""Rendered contracts for the three shared control-height tracks."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PyQt5.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QLineEdit, QPushButton, QSpinBox

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_HEIGHTS, set_control_role


_QSS_PATH = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui_kit" / "style.qss"


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


def _shown(widget):
    widget.show()
    QApplication.processEvents()
    return widget


def test_standard_form_controls_share_the_base_track(production_stylesheet):
    widgets = [QLineEdit(), QComboBox(), QSpinBox(), QDoubleSpinBox()]
    try:
        assert { _shown(widget).sizeHint().height() for widget in widgets } == {CONTROL_HEIGHTS["base"]}
    finally:
        for widget in widgets:
            widget.hide()
            widget.deleteLater()


@pytest.mark.parametrize(
    ("role", "size", "expected"),
    (("quiet", "base", "base"), ("primary", "cta", "cta")),
)
def test_explicit_button_height_track_renders_at_its_outer_height(
    production_stylesheet, role, size, expected,
):
    button = QPushButton("操作")
    try:
        set_control_role(button, role, size=size)
        _shown(button)
        assert button.sizeHint().height() == CONTROL_HEIGHTS[expected]
    finally:
        button.hide()
        button.deleteLater()


def test_search_role_has_base_height_without_a_text_control_maximum(production_stylesheet):
    field = QLineEdit()
    try:
        field.setProperty("role", "search")
        _shown(field)
        assert field.sizeHint().height() == CONTROL_HEIGHTS["base"]
    finally:
        field.hide()
        field.deleteLater()

    qss = _QSS_PATH.read_text(encoding="utf-8")
    for selector in (
        'QLineEdit[role="search"]',
        "QDialog#channelConfigManagerHtml QPushButton,",
    ):
        start = qss.index(selector)
        end = qss.index("\n}", start)
        assert "max-height" not in qss[start:end]
