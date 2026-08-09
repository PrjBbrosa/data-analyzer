"""Deterministic production-QSS render contracts for standard button roles."""
from __future__ import annotations

import os

import pytest
from PyQt5.QtCore import QEvent, QPoint, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPalette, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QToolButton, QWidget

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_ROLES, set_control_role


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


def _surface_pixel(widget: QWidget) -> QColor:
    image = widget.grab().toImage()
    return QColor(image.pixel(5, widget.height() // 2))


def _host_surface_pixel(host: QWidget, widget: QWidget) -> QColor:
    image = host.grab().toImage()
    return QColor(image.pixel(widget.x() + 5, widget.y() + widget.height() // 2))


def _luminance(color: QColor) -> float:
    return 0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()


def _button(role: str | None, *, tool: bool = False, parent=None) -> QWidget:
    button = QToolButton(parent) if tool else QPushButton(parent)
    button.setText("动作")
    button.setCheckable(True)
    if role is not None:
        set_control_role(button, role)
    button.resize(112, 36)
    button.show()
    QApplication.processEvents()
    return button


def test_standard_roles_keep_geometry_through_visual_states(production_stylesheet):
    for role in CONTROL_ROLES:
        for tool in (False, True):
            button = _button(role, tool=tool)
            try:
                baseline_hint = button.sizeHint()
                baseline_size = button.size()

                QApplication.sendEvent(button, QEvent(QEvent.Enter))
                QApplication.processEvents()
                QTest.mousePress(button, Qt.LeftButton, pos=QPoint(8, button.height() // 2))
                QApplication.processEvents()
                QTest.mouseRelease(button, Qt.LeftButton, pos=QPoint(8, button.height() // 2))
                button.setChecked(True)
                button.setEnabled(False)
                QApplication.processEvents()

                assert button.size() == baseline_size
                assert button.sizeHint() == baseline_hint
            finally:
                button.hide()
                button.deleteLater()


def test_role_surface_hierarchy_and_danger_states(production_stylesheet):
    host = QWidget()
    host.setAutoFillBackground(True)
    palette = host.palette()
    palette.setColor(QPalette.Window, QColor("#FFFFFF"))
    host.setPalette(palette)
    host.resize(640, 80)
    host.show()
    QApplication.processEvents()

    buttons = []
    try:
        for index, role in enumerate(("primary", "secondary", "quiet", "icon", "danger")):
            button = _button(role, parent=host)
            button.move(index * 120, 20)
            button.show()
            buttons.append(button)
        QApplication.processEvents()

        primary, secondary, quiet, icon, danger = buttons
        default = _button(None, parent=host)
        default.move(480, 20)
        default.show()
        QApplication.processEvents()

        assert _luminance(_host_surface_pixel(host, primary)) < _luminance(_host_surface_pixel(host, secondary))
        assert _luminance(_host_surface_pixel(host, secondary)) < _luminance(_host_surface_pixel(host, default))
        assert _luminance(_host_surface_pixel(host, default)) < _luminance(_host_surface_pixel(host, quiet))
        assert _luminance(_host_surface_pixel(host, default)) < _luminance(_host_surface_pixel(host, icon))

        qss = production_stylesheet.styleSheet()
        for state in (":hover", ":pressed"):
            selector = f'QPushButton[role="danger"]{state}'
            start = qss.index(selector)
            body = qss[start:qss.index("}", start)]
            assert "#FFF2F3" in body
            assert "#B42335" in body
    finally:
        for button in buttons:
            button.hide()
            button.deleteLater()
        if "default" in locals():
            default.hide()
            default.deleteLater()
        host.hide()
        host.deleteLater()


@pytest.mark.parametrize("edge", (24, 28))
def test_icon_role_does_not_inflate_fixed_compact_geometry(production_stylesheet, edge):
    button = QToolButton()
    try:
        set_control_role(button, "icon")
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor("#253247"))
        button.setIcon(QIcon(pixmap))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(edge, edge)
        button.show()
        QApplication.processEvents()
        assert button.size().width() == edge
        assert button.size().height() == edge
        assert button.minimumSize().width() <= edge
        assert button.minimumSize().height() <= edge
        assert button.sizeHint().width() <= edge
        assert button.sizeHint().height() <= edge
    finally:
        button.hide()
        button.deleteLater()
