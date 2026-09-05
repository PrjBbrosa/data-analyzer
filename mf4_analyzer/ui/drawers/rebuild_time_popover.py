"""Rebuild-time popover: frameless QDialog with focus-out auto-close."""
from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtGui import QTextOption
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout,
)

from mf4_analyzer.ui_kit.dialog_geometry import (
    FrameInsets,
    IntRect,
    Size,
    apply_plan,
    client_budget,
    constrain_client_size,
    frame_insets_of,
    plan_geometry,
    resolve_available_rect,
)

from ..widgets.compact_spinbox import CompactDoubleSpinBox

# Geometry-clipping constants for ``show_at``: keep popover this many pixels
# inside the available screen rect, and leave this much vertical gap when
# flipping above the anchor because below would overflow.
MARGIN = 8
GAP = 4
_SURFACE_H_MARGINS = 24
_PREFERRED_WRAP_WIDTH = 360


class _SelectableWrapLabel(QTextEdit):
    """Filename line that wraps anywhere and stays fully selectable."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("PopoverTargetName")
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.document().setDocumentMargin(0)
        self.setViewportMargins(0, 0, 0, 0)
        self.viewport().setAutoFillBackground(False)
        self.setAutoFillBackground(False)
        self.setStyleSheet(
            "QTextEdit#PopoverTargetName {"
            " background: transparent; color: #334155;"
            " border: none; padding: 0;"
            "}"
        )
        self.setPlainText(text)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        width = max(1, int(width))
        self.document().setTextWidth(width)
        return max(
            self.fontMetrics().lineSpacing(),
            int(self.document().size().height()) + 2,
        )

    def sizeHint(self):
        cap = self.maximumWidth()
        ideal = max(1, int(self.document().idealWidth()) + 2)
        width = ideal if cap >= 16777215 else min(ideal, cap)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.averageCharWidth() * 8, fm.lineSpacing())


class RebuildTimePopover(QDialog):
    def __init__(self, parent, target_filename, current_fs):
        super().__init__(parent)
        self.setObjectName("PopoverShell")
        # §8.1: frameless QDialog with manual focus-out close. NOT Qt.Popup
        # because Qt.Popup + child QSpinBox can close when the spin buttons
        # take focus; the dialog must stay open while user edits Fs.
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        # Rounded corners with no leftover square frame: the dialog *window*
        # is translucent (so the area outside the 12px radius is transparent,
        # not an opaque box / native rectangular shadow), and an inner QFrame
        # (#PopoverSurface) paints the rounded white surface. A top-level
        # QDialog does NOT reliably paint its own stylesheet background once
        # translucent, so the fill must live on a child QFrame — parity with
        # inspector_sections._PresetHoverCard and SignalPickerPopup.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
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
        # Transparent shell holds a single rounded surface frame. Zero margins
        # so frameGeometry()/sizeHint() (used by show_at clamping) stay tied
        # to the content size, not an inflated shadow gutter.
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        self._surface = QFrame(self)
        self._surface.setObjectName("PopoverSurface")
        self._surface.setAttribute(Qt.WA_StyledBackground, True)
        shell.addWidget(self._surface)
        root = QVBoxLayout(self._surface)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(QLabel("重建时间轴"))
        self._target = _SelectableWrapLabel(
            f"目标：[{target_filename}]", self._surface,
        )
        root.addWidget(self._target)
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
        self.btn_cancel.setProperty("role", "quiet")
        self.btn_cancel.setProperty("controlSize", "base")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setProperty("role", "primary")
        self.btn_ok.setProperty("controlSize", "base")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)

    def new_fs(self):
        return self.spin_fs.value()

    def _prepare_content_width(self, budget_width):
        inner = max(1, min(_PREFERRED_WRAP_WIDTH, int(budget_width) - _SURFACE_H_MARGINS))
        self._target.setMaximumWidth(inner)
        self.setMaximumWidth(max(1, int(budget_width)))

    def show_at(self, anchor_widget):
        try:
            center = anchor_widget.mapToGlobal(anchor_widget.rect().center())
            top_left = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft())
            anchor_h = max(1, anchor_widget.height())
        except RuntimeError:
            return
        available = resolve_available_rect(
            anchor_global=center, widget=self, parent=anchor_widget,
        )
        insets = frame_insets_of(self)
        budget = client_budget(available, insets, MARGIN)
        self._prepare_content_width(budget.width)
        if self.layout() is not None:
            self.layout().activate()
        self.adjustSize()
        hint = self.sizeHint().expandedTo(self.minimumSizeHint())
        preferred = Size(
            min(max(hint.width(), self.width()), max(1, budget.width)),
            max(hint.height(), self.height()),
        )
        fitted, _compact, needs_scroll = constrain_client_size(
            preferred, budget, content_minimum=preferred,
        )
        if needs_scroll:
            self._target.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Synthetic same-width anchor keeps the historical left/bottom-left
        # default. ``fit_popover`` right-aligns, which would fail the
        # below-widget contract in ``tests/ui/test_drawers.py``.
        anchor = IntRect(
            top_left.x(), top_left.y(),
            max(1, fitted.width + insets.horizontal), anchor_h,
        )
        plan = plan_geometry(
            available,
            fitted,
            frame=insets,
            margin=MARGIN,
            content_minimum=preferred,
            anchor=anchor,
            position="below",
            gap=0,
        )
        apply_plan(self, plan)
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
