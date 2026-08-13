"""Per-amplitude-unit default display ranges used when toggling the
amplitude unit (dB ↔ Linear) on the Inspector / batch axis controls.

Switching the unit while the user has manually pinned a range carries the
previous unit's numbers into the new unit (e.g. -30..0 dB silently
becoming a Linear floor of -30, which renders mostly black). The
remediation per
``docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md`` §1.3
is to reset the range to a unit-appropriate default and re-enable auto
whenever the unit toggles.

Two axes need this, for the same reason:

* **Z** (color scale) — spectrogram / order-map ``combo_amp_unit``.
* **Y** (amplitude) — the 1-D FFT spectrum's ``combo_amp_y``. Same failure
  mode, different axis: a Linear window of 0..1 kept across a switch to dB
  clips the whole (negative) dB curve out of view, so the plot looks empty.

These constants live at the package leaf rather than per-section so the
``inspector_sections`` handlers (``OrderContextual``, ``FFTTimeContextual``,
``FFTContextual``) and the batch ``OutputPanel`` handler all consume the
same source of truth.
"""

# (floor, ceiling) per unit. dB defaults (-30..0) align with the legacy
# ``dynamic='30 dB'`` migration path; Linear (0..1) is a placeholder the
# user is expected to overwrite once they re-disable auto.
Z_RANGE_DEFAULTS: dict[str, tuple[float, float]] = {
    'dB': (-30.0, 0.0),
    'Linear': (0.0, 1.0),
}

# (min, max) per unit for a 1-D amplitude (Y) axis. Both entries are
# dimension-correct *placeholders*, not calibrated windows: the toggle also
# forces ``y_auto`` back on, so nothing is rendered from these numbers until
# the user deliberately re-disables auto. What they must guarantee is only
# that the spin boxes never show a value belonging to the previous unit.
# dB uses -80..0 (a peak-referenced spectrum sits at or below 0 dB, and 80 dB
# is the conventional single-screen dynamic range — wider than the Z default
# because a line plot shows one curve's whole span rather than a color ramp);
# Linear uses 0..1, mirroring ``Z_RANGE_DEFAULTS``.
Y_RANGE_DEFAULTS: dict[str, tuple[float, float]] = {
    'dB': (-80.0, 0.0),
    'Linear': (0.0, 1.0),
}


def z_range_for(unit_text: str) -> tuple[float, float]:
    """Return the default ``(floor, ceiling)`` Z range for ``unit_text``.

    Falls back to ``(0.0, 1.0)`` for unknown unit strings so the caller
    never raises on a future unit addition that lacks an entry here.
    """
    return Z_RANGE_DEFAULTS.get(unit_text, (0.0, 1.0))


def y_range_for(unit_text: str) -> tuple[float, float]:
    """Return the default ``(min, max)`` amplitude-Y range for ``unit_text``.

    Falls back to the Linear ``(0.0, 1.0)`` placeholder for unknown unit
    strings, matching :func:`z_range_for`.
    """
    return Y_RANGE_DEFAULTS.get(unit_text, (0.0, 1.0))
