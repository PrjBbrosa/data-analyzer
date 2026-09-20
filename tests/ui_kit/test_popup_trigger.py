"""Popup-trigger hover/down restore after QMenu / Qt.Popup dismissal."""
from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QApplication, QMenu, QPushButton, QToolButton, QWidget

from mf4_analyzer.ui_kit.popup_trigger import bind_popup_trigger, sync_popup_trigger


def _away_from(widget: QWidget) -> QPoint:
    return widget.mapToGlobal(QPoint(widget.width() + 80, widget.height() // 2))


def test_sync_clears_stale_hover_when_pointer_is_outside(qapp, qtbot):
    btn = QToolButton()
    qtbot.addWidget(btn)
    btn.resize(24, 24)
    btn.show()
    qtbot.waitExposed(btn)
    btn.setAttribute(Qt.WA_UnderMouse, True)
    btn.setDown(True)
    QCursor.setPos(_away_from(btn))
    qapp.processEvents()

    assert not btn.rect().contains(btn.mapFromGlobal(QCursor.pos()))
    sync_popup_trigger(btn)

    assert not btn.testAttribute(Qt.WA_UnderMouse)
    assert not btn.isDown()
    assert not btn.isChecked()


def test_sync_keeps_hover_when_pointer_stays_on_trigger(qapp, qtbot):
    btn = QToolButton()
    qtbot.addWidget(btn)
    btn.resize(24, 24)
    btn.show()
    qtbot.waitExposed(btn)
    btn.setAttribute(Qt.WA_UnderMouse, True)
    QCursor.setPos(btn.mapToGlobal(btn.rect().center()))
    qapp.processEvents()

    sync_popup_trigger(btn)

    assert btn.testAttribute(Qt.WA_UnderMouse)
    assert not btn.isChecked()


def test_sync_preserves_checked_active_and_focus(qapp, qtbot):
    btn = QToolButton()
    qtbot.addWidget(btn)
    btn.setCheckable(True)
    btn.setChecked(True)
    btn.setProperty("active", "true")
    btn.resize(24, 24)
    btn.show()
    qtbot.waitExposed(btn)
    btn.setFocus(Qt.OtherFocusReason)
    btn.setAttribute(Qt.WA_UnderMouse, True)
    QCursor.setPos(_away_from(btn))
    qapp.processEvents()

    sync_popup_trigger(btn)

    assert btn.isChecked()
    assert btn.property("active") == "true"
    assert btn.hasFocus()
    assert not btn.testAttribute(Qt.WA_UnderMouse)


def test_bind_is_idempotent_and_survives_destroyed_trigger(qapp, qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    btn = QPushButton("open", host)
    menu = QMenu(host)
    menu.addAction("item")
    bind_popup_trigger(menu, btn)
    bind_popup_trigger(menu, btn)
    syncs = [
        child for child in menu.children()
        if child.objectName() == "popupTriggerHoverSync"
    ]
    assert len(syncs) == 1

    btn.setAttribute(Qt.WA_UnderMouse, True)
    QCursor.setPos(_away_from(btn))
    btn.deleteLater()
    qapp.processEvents()
    menu.popup(QPoint(40, 40))
    qapp.processEvents()
    menu.close()
    qapp.processEvents()


def test_bind_skips_stale_hide_when_popup_reopens(qapp, qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(200, 80)
    host.show()
    btn = QToolButton(host)
    btn.resize(24, 24)
    btn.move(8, 8)
    btn.show()
    menu = QMenu(host)
    menu.addAction("item")
    bind_popup_trigger(menu, btn)

    btn.setAttribute(Qt.WA_UnderMouse, True)
    QCursor.setPos(_away_from(btn))
    qapp.processEvents()
    menu.popup(host.mapToGlobal(QPoint(8, 40)))
    qapp.processEvents()
    menu.hide()
    menu.popup(host.mapToGlobal(QPoint(8, 40)))
    qapp.processEvents()

    assert menu.isVisible()
    assert btn.testAttribute(Qt.WA_UnderMouse)

    menu.close()
    qapp.processEvents()
    QApplication.processEvents()
    assert not btn.testAttribute(Qt.WA_UnderMouse)
