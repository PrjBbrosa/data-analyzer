"""Numeric input widgets with compact display text."""
from __future__ import annotations

from PyQt5.QtWidgets import QDoubleSpinBox


class CompactDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that preserves precision but trims trailing zeroes.

    Qt's stock QDoubleSpinBox uses ``decimals`` for both accepted precision
    and fixed-width display text. We keep the precision side intact while
    making the default visible text compact, with at least one decimal place
    so integer-valued floats read as floats (``1.0`` instead of ``1``).
    """

    def __init__(self, parent=None, *, minimum_display_decimals: int = 1):
        super().__init__(parent)
        self._minimum_display_decimals = max(0, int(minimum_display_decimals))

    def textFromValue(self, value):  # noqa: N802 (Qt API)
        decimals = max(int(self.decimals()), self._minimum_display_decimals)
        text = f"{float(value):.{decimals}f}"
        if "." not in text:
            return text
        head, tail = text.split(".", 1)
        tail = tail.rstrip("0")
        if len(tail) < self._minimum_display_decimals:
            tail = tail + ("0" * (self._minimum_display_decimals - len(tail)))
        return f"{head}.{tail}" if tail else head
