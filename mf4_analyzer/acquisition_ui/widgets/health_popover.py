"""Floating detail popover for a health chip (Spec §B1).

A ``HealthChip`` is normally just an LED + value with a hover tooltip.
Clicking it pops up this frameless, non-modal ``HealthPopover`` showing a
few band-coloured rows sourced from the backing ``HealthSnapshot`` fields
(never free-form text).

Embedded-overlay rule (project gotcha + ``feedback-no-gray-bg-embedded-widgets``):
a custom ``QWidget`` used as a floating surface MUST paint its own rounded
background. ``WA_TranslucentBackground`` makes the frame's own QSS
background ineffective, so we self-draw the pill in :meth:`paintEvent`
(mirrors ``ui/chart_stack/cursor_pill.py`` — radius 9, near-white fill,
``#d8e0eb`` hairline). Row LEDs are inner ``QLabel`` children that carry
their own stylesheet colour and paint over the self-drawn background.
"""

from __future__ import annotations

from typing import Sequence

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Match cursor_pill.py so the two floating surfaces look identical.
_POPOVER_RADIUS = 9.0
_POPOVER_BG = QColor(255, 255, 255, 245)
_POPOVER_BORDER = QColor("#d8e0eb")

# Gap below the anchor chip and horizontal clamp margin inside the host.
_POPOVER_GAP = 6
_POPOVER_MARGIN = 6

# Deterministic layout floor (px) so the popover never collapses before the
# event loop polishes CJK labels: outer vertical margins + title band + per row.
_MARGIN_V = 21
_TITLE_H = 24
_ROW_H = 22

# Row LED colours per health level — kept local (not imported from
# health_strip) so this module has no back-dependency on the strip that
# constructs it.
_LEVEL_DOT = {
    "green": "#16a34a",
    "yellow": "#d97706",
    "red": "#dc2626",
    "off": "#94a3b8",
}


class HealthPopover(QFrame):
    """Self-painted rounded popover holding a title + level-coloured rows.

    Public API (also reused by the B2 preflight pill):

    - :meth:`set_title` — the anchor chip / pill name shown bold on top.
    - :meth:`set_rows` — ``[(key, value, level), ...]`` where ``level`` is
      one of ``"green" | "yellow" | "red" | "off"``.
    - :meth:`show_at` — position the popover just below an anchor widget,
      clamped inside the host window, then show + raise.
    - :meth:`dismiss` — hide the popover.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("healthPopover")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        # Non-modal, does not steal record shortcuts / keyboard focus.
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 11)
        outer.setSpacing(7)

        self._title = QLabel("", self)
        self._title.setObjectName("healthPopoverTitle")
        self._title.setTextInteractionFlags(Qt.NoTextInteraction)
        outer.addWidget(self._title)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(5)
        self._grid.setColumnStretch(1, 0)
        self._grid.setColumnStretch(2, 1)
        outer.addLayout(self._grid)

        self._row_count = 0
        self._anchor: QWidget | None = None
        self._refit_pending = False

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        self._title.setText(text or "")

    def title_text(self) -> str:
        return self._title.text()

    def set_rows(self, rows: Sequence[tuple[str, str, str]]) -> None:
        """Rebuild the detail rows. ``rows`` = ``[(key, value, level)]``."""
        self._clear_grid()
        for r, (key, value, level) in enumerate(rows):
            led = QLabel(self)
            led.setObjectName("healthPopoverLed")
            led.setFixedSize(8, 8)
            colour = _LEVEL_DOT.get(str(level), _LEVEL_DOT["off"])
            led.setStyleSheet(f"background-color: {colour}; border-radius: 4px;")
            key_label = QLabel(str(key), self)
            key_label.setObjectName("healthPopoverKey")
            value_label = QLabel(str(value), self)
            value_label.setObjectName("healthPopoverValue")
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(led, r, 0, Qt.AlignVCenter)
            self._grid.addWidget(key_label, r, 1, Qt.AlignVCenter)
            self._grid.addWidget(value_label, r, 2, Qt.AlignVCenter)
        self._row_count = len(rows)
        self._apply_min_size()
        self._resize_to_content()

    def _apply_min_size(self) -> None:
        """A deterministic floor so the popover never collapses/overlaps.

        Freshly-created CJK ``QLabel``s report a font-less (near-zero)
        ``sizeHint`` until the event loop polishes them, so a synchronous
        resize on a REUSED (already-visible) popover would squash all rows.
        Sizing from the row count keeps it readable immediately; the exact
        fit is applied on the next tick by :meth:`_refit`.
        """
        n = self._row_count
        min_w = 180
        min_h = _MARGIN_V + _TITLE_H + n * _ROW_H
        self.setMinimumSize(min_w, min_h)

    def _resize_to_content(self) -> None:
        """Force a layout pass then resize to ``max(sizeHint, minimum)``."""
        self._grid.invalidate()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.updateGeometry()
        hint = self.sizeHint()
        self.resize(
            max(hint.width(), self.minimumWidth()),
            max(hint.height(), self.minimumHeight()),
        )

    def row_count(self) -> int:
        return self._row_count

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._row_count = 0

    # ------------------------------------------------------------------
    # Placement / visibility
    # ------------------------------------------------------------------

    def show_at(self, anchor: QWidget) -> None:
        """Show the popover just below ``anchor``, clamped to the host."""
        self._anchor = anchor
        self._resize_to_content()
        self._reposition()
        self.show()
        self.raise_()
        self._schedule_refit()

    def _reposition(self) -> None:
        anchor = self._anchor
        host = self.parentWidget()
        if host is None or anchor is None:
            return
        anchor_bl_global = anchor.mapToGlobal(anchor.rect().bottomLeft())
        local = host.mapFromGlobal(anchor_bl_global)
        x = local.x()
        y = local.y() + _POPOVER_GAP
        max_x = max(_POPOVER_MARGIN, host.width() - self.width() - _POPOVER_MARGIN)
        x = max(_POPOVER_MARGIN, min(x, max_x))
        self.move(x, y)

    def _schedule_refit(self) -> None:
        """Apply the exact fit once the event loop has polished the labels."""
        if self._refit_pending:
            return
        self._refit_pending = True
        QTimer.singleShot(0, self._refit)

    def _refit(self) -> None:
        self._refit_pending = False
        if not self.isVisible():
            return
        self._resize_to_content()
        self._reposition()

    def dismiss(self) -> None:
        self.hide()

    # ------------------------------------------------------------------
    # Self-painted background (translucent-frame gotcha)
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setBrush(_POPOVER_BG)
            painter.setPen(QPen(_POPOVER_BORDER, 1.0))
            painter.drawRoundedRect(rect, _POPOVER_RADIUS, _POPOVER_RADIUS)
        finally:
            painter.end()
