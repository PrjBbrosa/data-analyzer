"""Rebuild-time popover: frameless QDialog with focus-out auto-close."""
from PyQt5.QtCore import Qt, QEvent, QPoint
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QApplication, QDialog, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout,
)

from ..widgets.compact_spinbox import CompactDoubleSpinBox

# Geometry-clipping constants for ``show_at``: keep popover this many pixels
# inside the available screen rect, and leave this much vertical gap when
# flipping above the anchor because below would overflow.
MARGIN = 8
GAP = 4


class RebuildTimePopover(QDialog):
    def __init__(self, parent, target_filename, current_fs):
        super().__init__(parent)
        self.setObjectName("PopoverSurface")
        # §8.1: frameless QDialog with manual focus-out close. NOT Qt.Popup
        # because Qt.Popup + child QSpinBox can close when the spin buttons
        # take focus; the dialog must stay open while user edits Fs.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setModal(False)
        # §8.2 (2026-04-26): Guard against the accept/WindowDeactivate
        # race. ``QDialog.done(r)`` is NOT idempotent: it sets the
        # result code, then calls ``hide()``. On macOS Cocoa, ``hide()``
        # synchronously dispatches ``QEvent.WindowDeactivate`` to the
        # dialog while ``isVisible()`` is still ``True``. Without this
        # flag, ``event()`` would interpret that deactivate as a
        # focus-out auto-close, call ``reject()``, and the second
        # ``done(Rejected)`` would overwrite the user's
        # ``done(Accepted)`` — turning every "click 确定" into an
        # effective cancel. ``_is_closing`` short-circuits the auto-
        # reject branch once an explicit ``accept`` or ``reject`` is
        # already in flight, while still letting genuine focus-out
        # deactivates (no explicit close pending) reject as before.
        self._is_closing = False
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(QLabel("重建时间轴"))
        root.addWidget(QLabel(f"目标：[{target_filename}]"))
        h = QHBoxLayout()
        h.addWidget(QLabel("Fs:"))
        self.spin_fs = CompactDoubleSpinBox()
        self.spin_fs.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(current_fs)
        self.spin_fs.setSuffix(" Hz")
        h.addWidget(self.spin_fs)
        root.addLayout(h)
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setProperty("role", "tool")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setProperty("role", "primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)

    def new_fs(self):
        return self.spin_fs.value()

    def _available_geometry_for(self, anchor_widget):
        """Pick the screen the anchor is sitting on; fallback to primary."""
        try:
            anchor_center_global = anchor_widget.mapToGlobal(
                anchor_widget.rect().center()
            )
            screen = QGuiApplication.screenAt(anchor_center_global)
        except Exception:
            screen = None
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            # Extreme fallback: invent a generous rect so we never crash.
            from PyQt5.QtCore import QRect
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    def show_at(self, anchor_widget):
        # Force layout/sizeHint resolution before reading frameGeometry.
        self.adjustSize()
        size = self.sizeHint()
        w = max(size.width(), self.width())
        h = max(size.height(), self.height())

        anchor_top_global = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft())
        anchor_bot_global = anchor_widget.mapToGlobal(
            anchor_widget.rect().bottomLeft()
        )
        avail = self._available_geometry_for(anchor_widget)

        # Default: anchor.bottomLeft.
        x = anchor_bot_global.x()
        y = anchor_bot_global.y()

        # Horizontal clipping: keep within [avail.left+M, avail.right-M].
        # Qt's ``right()`` is inclusive (left + width - 1), so the constraint
        # is ``x + w - 1 <= right_limit``.
        right_limit = avail.right() - MARGIN
        left_limit = avail.left() + MARGIN
        if x + w - 1 > right_limit:
            x = right_limit - w + 1
        if x < left_limit:
            x = left_limit

        # Vertical clipping: if placing below overflows, flip above the
        # anchor; if above also overflows, clamp to top margin. Use
        # exclusive max-y bounds (right/bottom in Qt are inclusive, so
        # the constraint is ``y + h - 1 <= bottom_limit``).
        bottom_limit = avail.bottom() - MARGIN
        top_limit = avail.top() + MARGIN
        if y + h - 1 > bottom_limit:
            flipped_y = anchor_top_global.y() - h - GAP
            if flipped_y >= top_limit and flipped_y + h - 1 <= bottom_limit:
                y = flipped_y
            else:
                # Anchor is in a corner where neither below nor above fits
                # cleanly; clamp so the bottom edge sits at bottom_limit.
                y = bottom_limit - h + 1
        if y < top_limit:
            y = top_limit

        self.move(QPoint(x, y))
        self.show()
        self.spin_fs.setFocus()
        self.activateWindow()

    def accept(self):
        # Mark the dialog as closing BEFORE QDialog.accept() runs done()
        # — the synchronous ``hide()`` inside ``done()`` may dispatch a
        # ``WindowDeactivate`` while ``isVisible()`` is still ``True``,
        # and ``event()`` must see ``_is_closing == True`` so it does
        # NOT auto-reject and overwrite the result.
        self._is_closing = True
        super().accept()

    def reject(self):
        # Mirror ``accept`` so an explicit reject also short-circuits
        # the auto-reject branch in ``event``. Without this, a fast
        # double-deactivate could enter ``event`` twice and call
        # ``reject`` recursively while the first reject is still on
        # the stack — ``_is_closing`` keeps the contract simple.
        self._is_closing = True
        super().reject()

    def event(self, ev):
        # Only auto-reject on focus-out when no explicit close is in
        # flight. ``_is_closing`` is set by ``accept``/``reject`` above
        # so the WindowDeactivate that ``hide()`` synthesizes during
        # ``done()`` does NOT trigger a second ``done(Rejected)``.
        if (
            ev.type() == QEvent.WindowDeactivate
            and self.isVisible()
            and not self._is_closing
        ):
            self.reject()
        return super().event(ev)
