"""Numeric input widgets with compact display text.

This module also exposes :func:`no_buttons` — a tiny helper that strips
the up/down stepper from a ``Q(Double)SpinBox`` and tags the widget with
the ``compact`` dynamic property. The QSS in ``style.qss`` scopes the
spinbox stepper-suppression rules to ``[compact="true"]`` so widgets
that *want* native steppers (third-party dialogs, future reuse) are not
affected by the project's chrome reset. See lesson
``pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md`` for
why ``setProperty`` runs in ``__init__`` (before the first polish) — no
``unpolish/polish`` cycle is needed because the property is set before
the widget is shown.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QAbstractSpinBox, QDoubleSpinBox


def no_buttons(spin):
    """Strip the up/down stepper from a ``Q(Double)SpinBox``.

    Pairs Qt-side ``setButtonSymbols(NoButtons)`` (which removes the
    native widgets even on platforms whose style still paints them
    despite zero-width QSS) with the ``compact=True`` dynamic property
    that opts the widget into the project's QSS rules collapsing the
    spinbox subcontrols and tightening padding. Returns ``spin`` so
    callers can chain.
    """
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setProperty("compact", True)
    return spin


class CompactDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that preserves precision but trims trailing zeroes.

    Qt's stock QDoubleSpinBox uses ``decimals`` for both accepted precision
    and fixed-width display text. We keep the precision side intact while
    making the default visible text compact, with at least one decimal place
    so integer-valued floats read as floats (``1.0`` instead of ``1``).

    The constructor also opts the widget into the project's compact QSS
    by setting ``property('compact', True)``. Every spinbox in the
    Inspector / batch panels / dialogs / popovers funnels through this
    class, so the property propagates implicitly to their styling.
    """

    def __init__(self, parent=None, *, minimum_display_decimals: int = 1):
        super().__init__(parent)
        self._minimum_display_decimals = max(0, int(minimum_display_decimals))
        # Set BEFORE first show/polish so QSS picks it up cleanly without
        # an explicit unpolish/polish cycle (see lesson
        # 2026-04-27-qss-padding-overrides-setcontentsmargins.md).
        self.setProperty("compact", True)

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
