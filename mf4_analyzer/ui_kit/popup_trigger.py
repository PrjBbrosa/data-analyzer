"""Restore a popup trigger's hover/pressed chrome after the popup hides.

Qt.Popup / QMenu grab the mouse and often skip Leave on the trigger. The
QSS ``:hover`` wash then sticks until the next real mouse move. Callers bind
a specific trigger to a specific popup; this helper never clears checked,
``active``, or focus, and it does not send synthetic clicks.
"""
from __future__ import annotations

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QTimer, Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QApplication, QWidget

_SYNC_CHILD_NAME = "popupTriggerHoverSync"


def pointer_is_over(widget: QWidget) -> bool:
    """Return whether the real pointer currently sits inside ``widget``."""
    if widget is None or sip.isdeleted(widget):
        return False
    return widget.rect().contains(widget.mapFromGlobal(QCursor.pos()))


def sync_popup_trigger(trigger: QWidget, *, popup: QWidget | None = None) -> None:
    """Align trigger hover/down with the live pointer after a popup dismisses.

    ``checked`` / dynamic ``active`` / focus are left untouched. ``down`` is
    cleared only when no mouse button is still held, so a new press is not
    interrupted. If ``popup`` is still visible (re-opened, nested), this is a
    no-op.
    """
    if trigger is None or sip.isdeleted(trigger):
        return
    if popup is not None and not sip.isdeleted(popup) and popup.isVisible():
        return

    changed = False
    if not pointer_is_over(trigger) and trigger.testAttribute(Qt.WA_UnderMouse):
        trigger.setAttribute(Qt.WA_UnderMouse, False)
        changed = True

    buttons = QApplication.mouseButtons()
    if trigger.isDown() and buttons == Qt.NoButton:
        trigger.setDown(False)
        changed = True

    if not changed:
        return
    style = trigger.style()
    if style is not None:
        style.unpolish(trigger)
        style.polish(trigger)
    trigger.update()


def bind_popup_trigger(popup: QWidget, trigger: QWidget) -> QWidget:
    """Bind ``popup`` hide/close to :func:`sync_popup_trigger` for ``trigger``.

    Idempotent for the same pair. Rebinding a reused popup to a new trigger
    replaces the previous sync object. The sync object is a child of
    ``popup``, so temporary menus do not accumulate callbacks.
    """
    if popup is None or trigger is None:
        return popup
    if sip.isdeleted(popup) or sip.isdeleted(trigger):
        return popup

    existing = _existing_sync(popup)
    if existing is not None:
        if existing.trigger() is trigger:
            return popup
        existing.setParent(None)
        existing.deleteLater()

    _PopupTriggerSync(popup, trigger)
    return popup


def _existing_sync(popup: QWidget) -> _PopupTriggerSync | None:
    for child in popup.findChildren(_PopupTriggerSync):
        if child.objectName() == _SYNC_CHILD_NAME:
            return child
    return None


class _PopupTriggerSync(QObject):
    """Queue one hover sync after the popup has actually finished hiding."""

    def __init__(self, popup: QWidget, trigger: QWidget):
        super().__init__(popup)
        self.setObjectName(_SYNC_CHILD_NAME)
        self._popup = popup
        self._trigger = trigger
        self._generation = 0
        self._queued_generation = 0
        self._flush = QTimer(self)
        self._flush.setSingleShot(True)
        self._flush.setInterval(0)
        self._flush.timeout.connect(self._apply)
        about_to_hide = getattr(popup, "aboutToHide", None)
        if about_to_hide is not None:
            about_to_hide.connect(self._queue)
        popup.installEventFilter(self)

    def trigger(self) -> QWidget:
        return self._trigger

    def eventFilter(self, obj, event):  # noqa: N802
        popup = self._popup
        if (
            obj is popup
            and event is not None
            and event.type() in (QEvent.Hide, QEvent.Close)
        ):
            self._queue()
        return False

    def _queue(self) -> None:
        if sip.isdeleted(self):
            return
        self._generation += 1
        self._queued_generation = self._generation
        self._flush.start()

    def _apply(self) -> None:
        if sip.isdeleted(self):
            return
        if self._queued_generation != self._generation:
            return
        popup = self._popup
        trigger = self._trigger
        if trigger is None or sip.isdeleted(trigger):
            return
        if popup is not None and not sip.isdeleted(popup) and popup.isVisible():
            return
        sync_popup_trigger(trigger, popup=popup)
