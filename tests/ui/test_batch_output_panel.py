"""Tests for ``mf4_analyzer.ui.drawers.batch.output_panel.OutputPanel``.

W2 of the 2026-05-01 codex-review-fixes plan adds a unit-toggle reset
contract to ``combo_amp_unit`` mirroring the W1 inspector behaviour: the
old unit's numeric Z range must NOT bleed into the new unit. See spec
§1.2 / §1.4 / §1.5.
"""
from __future__ import annotations

import pytest


def _make_panel(qtbot):
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel
    panel = OutputPanel()
    qtbot.addWidget(panel)
    return panel


def test_batch_output_panel_unit_toggle_resets_z_range_db_to_linear(qtbot):
    """dB → Linear: floor/ceiling reset to (0, 1), z_auto re-enabled,
    spinboxes disabled, ``changed`` emitted exactly once.

    Pins all five §1.2 invariants plus the W2 emit-once mitigation
    (§5 风险 OutputPanel emits).
    """
    panel = _make_panel(qtbot)
    # Default unit is dB; lock a manual dB range first.
    assert panel.combo_amp_unit.currentText() == "dB"
    panel.chk_z_auto.setChecked(False)
    panel.spin_z_floor.setValue(-30.0)
    panel.spin_z_ceiling.setValue(0.0)

    # Counter from now (drop pre-toggle emits).
    emits = []
    panel.changed.connect(lambda: emits.append(1))

    panel.combo_amp_unit.setCurrentText("Linear")

    # §1.2 invariants
    assert panel.chk_z_auto.isChecked() is True
    assert panel.spin_z_floor.value() == 0.0
    assert panel.spin_z_ceiling.value() == 1.0
    assert panel.spin_z_floor.isEnabled() is False
    assert panel.spin_z_ceiling.isEnabled() is False

    # §5 risk mitigation: emit-once (not 3+ from chk + spin + spin + combo).
    assert len(emits) == 1, (
        f"changed should emit once on unit toggle, got {len(emits)}"
    )


def test_batch_output_panel_unit_toggle_resets_z_range_linear_to_db(qtbot):
    """Reverse direction: Linear → dB resets floor/ceiling to (-30, 0)."""
    panel = _make_panel(qtbot)
    # Switch to Linear first (without asserting reset behaviour here —
    # that is covered by the dB→Linear test). Block the combo signal so
    # this setup does NOT pre-trigger the W2 reset handler.
    panel.combo_amp_unit.blockSignals(True)
    panel.combo_amp_unit.setCurrentText("Linear")
    panel.combo_amp_unit.blockSignals(False)
    panel.chk_z_auto.setChecked(False)
    panel.spin_z_floor.setValue(0.2)
    panel.spin_z_ceiling.setValue(0.9)

    emits = []
    panel.changed.connect(lambda: emits.append(1))

    panel.combo_amp_unit.setCurrentText("dB")

    assert panel.chk_z_auto.isChecked() is True
    assert panel.spin_z_floor.value() == -30.0
    assert panel.spin_z_ceiling.value() == 0.0
    assert panel.spin_z_floor.isEnabled() is False
    assert panel.spin_z_ceiling.isEnabled() is False
    assert len(emits) == 1


def test_batch_output_panel_apply_axis_params_does_not_trigger_reset(qtbot):
    """Preset load via ``apply_axis_params`` MUST NOT trigger the
    unit-toggle reset handler — otherwise the user's persisted
    ``z_floor`` / ``z_ceiling`` get wiped to the defaults the moment a
    preset comes back from disk.

    This is the strong RED case for §1.5 边界: the handler is wired
    on user-driven ``currentTextChanged``, but ``setCurrentIndex`` from
    a programmatic preset loader must round-trip the user's numbers
    intact AND must NOT fire the W2 reset handler (otherwise the
    handler emits ``changed`` and dirties the batch preset for an
    operation the user did not initiate).

    Strong-RED proof: removing the ``blockSignals(True/False)`` wrap
    around ``combo_amp_unit.setCurrentIndex`` in ``apply_axis_params``
    causes ``_on_amp_unit_changed`` to fire on the cross-unit preset
    apply, which both (a) emits a spurious ``changed`` and (b) the
    handler runs ``self.changed.emit()`` — bringing the assertion
    ``len(emits) == 0`` below to FAIL. Verified locally during W2
    development.
    """
    panel = _make_panel(qtbot)
    # First preset: stays on dB but pins a non-default range.
    params = {
        "x_auto": False, "x_min": 1.0, "x_max": 2.0,
        "y_auto": False, "y_min": 3.0, "y_max": 4.0,
        "z_auto": False, "z_floor": -50.0, "z_ceiling": -10.0,
        "amplitude_mode": "amplitude_db",
    }
    panel.apply_axis_params(params)

    assert panel.chk_z_auto.isChecked() is False
    assert panel.spin_z_floor.value() == -50.0
    assert panel.spin_z_ceiling.value() == -10.0
    assert panel.combo_amp_unit.currentText() == "dB"

    # Second preset: Linear unit + custom ranges. This is the cross-unit
    # apply that WOULD trip ``_on_amp_unit_changed`` if combo's
    # ``setCurrentIndex`` were not wrapped in ``blockSignals``.
    params2 = {
        "z_auto": False, "z_floor": 0.05, "z_ceiling": 0.75,
        "amplitude_mode": "amplitude",
    }

    # Counter: the W2 reset handler MUST NOT run during a programmatic
    # preset load. We replace ``_on_amp_unit_changed`` with a counter so
    # we can detect whether ``combo_amp_unit.setCurrentIndex`` slipped
    # past ``blockSignals`` (which would re-trigger the dB↔Linear reset
    # and clobber the preset's z_floor/z_ceiling).
    handler_calls = []
    real_handler = panel._on_amp_unit_changed

    def _spy(text):
        handler_calls.append(text)
        return real_handler(text)
    panel._on_amp_unit_changed = _spy
    # Re-wire so the spy actually receives the signal — the original
    # connection captured the bound method by reference.
    try:
        panel.combo_amp_unit.currentTextChanged.disconnect(real_handler)
    except TypeError:
        pass
    panel.combo_amp_unit.currentTextChanged.connect(_spy)

    panel.apply_axis_params(params2)

    assert panel.combo_amp_unit.currentText() == "Linear"
    assert panel.chk_z_auto.isChecked() is False
    assert panel.spin_z_floor.value() == pytest.approx(0.05)
    assert panel.spin_z_ceiling.value() == pytest.approx(0.75)
    # Strong-RED pin: handler must not run on programmatic combo set.
    # Verified: removing blockSignals around setCurrentIndex causes
    # this to be ['Linear'] (1 call) and the per-W2 reset clobbers
    # spin_z_floor/ceiling to (-30, 0) instead of (0.05, 0.75).
    assert handler_calls == [], (
        "_on_amp_unit_changed must not fire on programmatic preset "
        f"apply; got calls={handler_calls!r} — combo_amp_unit."
        "setCurrentIndex likely missing blockSignals wrap."
    )
