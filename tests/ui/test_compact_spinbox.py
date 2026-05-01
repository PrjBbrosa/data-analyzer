"""W5 — `[compact="true"]` dynamic-property convergence (P8-O1).

The QSS in ``style.qss`` will be tightened so spinbox-stepper QSS rules
only match widgets that opt-in via ``setProperty('compact', True)``.
Two production constructors must set this property:

1. ``CompactDoubleSpinBox.__init__`` — every consumer in the project
   (Inspector, dialogs, batch panels, popovers) constructs one of these.
2. The shared ``no_buttons`` helper used by inspector_sections + batch
   ``method_buttons`` for plain ``QSpinBox`` widgets.

A plain ``QSpinBox()`` constructed without going through the helper
must **not** carry the property — that is the regression guard which
keeps the QSS scope narrow.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QAbstractSpinBox, QSpinBox

from mf4_analyzer.ui.widgets.compact_spinbox import (
    CompactDoubleSpinBox,
    no_buttons,
)


def test_compact_double_spinbox_sets_compact_property(qapp):
    spin = CompactDoubleSpinBox()
    assert spin.property("compact") is True


def test_no_buttons_helper_sets_compact_property(qapp):
    spin = no_buttons(QSpinBox())
    assert spin.property("compact") is True
    assert spin.buttonSymbols() == QAbstractSpinBox.NoButtons


def test_plain_qspinbox_has_no_compact_property(qapp):
    """Regression guard: bare QSpinBox must not pick up the property."""
    spin = QSpinBox()
    # Qt returns an invalid QVariant (None / not-True) for absent props.
    assert spin.property("compact") is not True


def test_method_button_spinboxes_have_compact_property(qapp, qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    # Cover all five spinboxes constructed inside DynamicParamForm.
    for attr in (
        "_w_nfft",
        "_w_max_order",
        "_w_order_res",
        "_w_time_res",
        "_w_overlap",
    ):
        spin = getattr(form, attr)
        assert spin.property("compact") is True, (
            f"{attr} missing compact property"
        )
        assert spin.buttonSymbols() == QAbstractSpinBox.NoButtons


def test_inspector_no_buttons_helper_sets_compact_property(qapp):
    """Inspector's ``_no_buttons`` must continue to tag spinboxes too.

    After the helper hoist, ``inspector_sections._no_buttons`` is a thin
    re-export of ``widgets.compact_spinbox.no_buttons``. This guards
    against a future regression that removes one of the two paths.
    """
    from mf4_analyzer.ui.inspector_sections import _no_buttons as _ns_no_buttons

    spin = _ns_no_buttons(QSpinBox())
    assert spin.property("compact") is True
    assert spin.buttonSymbols() == QAbstractSpinBox.NoButtons
