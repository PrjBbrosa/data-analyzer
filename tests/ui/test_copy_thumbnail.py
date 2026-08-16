from PyQt5.QtCore import QPoint, Qt, QEvent
from PyQt5.QtGui import QColor, QEnterEvent, QPixmap
from PyQt5.QtWidgets import QToolButton, QWidget

from mf4_analyzer.ui.markup import CopyThumbnail


def _pixmap(width=640, height=360):
    pix = QPixmap(width, height)
    pix.fill(QColor("#1769e0"))
    return pix


def test_present_shows_bottom_right_scaled_preview(qtbot):
    parent = QWidget()
    parent.resize(900, 600)
    qtbot.addWidget(parent)
    parent.show()

    thumb = CopyThumbnail(parent)
    qtbot.addWidget(thumb)
    pix = _pixmap()

    thumb.present(pix)

    assert thumb.isVisible()
    assert thumb._original_pixmap.cacheKey() == pix.cacheKey()
    assert thumb.geometry().right() <= parent.rect().right()
    assert thumb.geometry().bottom() <= parent.rect().bottom()
    assert thumb.geometry().left() >= parent.width() - thumb.width() - 24
    assert thumb.geometry().top() >= parent.height() - thumb.height() - 24
    assert thumb._hide_timer.isActive()


def test_body_click_emits_original_full_resolution_pixmap(qtbot):
    thumb = CopyThumbnail()
    qtbot.addWidget(thumb)
    pix = _pixmap(1024, 512)
    thumb.present(pix)

    with qtbot.waitSignal(thumb.clicked, timeout=200) as blocker:
        qtbot.mouseClick(thumb, Qt.LeftButton, pos=thumb.rect().center())

    emitted = blocker.args[0]
    assert emitted.size() == pix.size()
    assert emitted.cacheKey() == pix.cacheKey()


def test_close_button_and_dismiss_hide_thumbnail(qtbot):
    thumb = CopyThumbnail()
    qtbot.addWidget(thumb)
    thumb.present(_pixmap())

    close = thumb.findChild(QToolButton, "copyThumbnailClose")
    assert close is not None
    assert close.text() == ""
    assert not close.icon().isNull()
    assert (close.width(), close.height()) == (28, 28)
    qtbot.mouseClick(close, Qt.LeftButton)
    assert not thumb.isVisible()

    thumb.present(_pixmap())
    assert thumb.isVisible()
    thumb.dismiss()
    assert not thumb.isVisible()
    assert not thumb._hide_timer.isActive()


def test_close_button_does_not_open_the_editor(qtbot):
    thumb = CopyThumbnail()
    qtbot.addWidget(thumb)
    thumb.present(_pixmap())

    with qtbot.assertNotEmitted(thumb.clicked):
        qtbot.mouseClick(thumb._close, Qt.LeftButton)
    assert not thumb.isVisible()


def test_enter_pauses_and_leave_resumes_auto_dismiss_timer(qtbot):
    thumb = CopyThumbnail()
    qtbot.addWidget(thumb)
    thumb.present(_pixmap())
    assert thumb._hide_timer.isActive()

    enter = QEnterEvent(QPoint(2, 2), QPoint(2, 2), QPoint(2, 2))
    thumb.event(enter)
    assert not thumb._hide_timer.isActive()

    thumb.event(QEvent(QEvent.Leave))
    assert thumb._hide_timer.isActive()
