"""Per-amplitude-unit default Z-axis range used when toggling
``combo_amp_unit`` (dB ↔ Linear) on the spectrogram / order-map Inspector
controls.

Switching the unit while the user has manually pinned a Z range carries
the previous unit's numbers into the new unit (e.g. -30..0 dB silently
becoming a Linear floor of -30, which renders mostly black). The
remediation per
``docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md`` §1.3
is to reset the Z range to a unit-appropriate default and re-enable
auto-Z whenever the unit toggles.

These constants live at the package leaf rather than per-section so the
two ``inspector_sections`` handlers (``OrderContextual``,
``FFTTimeContextual``) and the batch ``OutputPanel`` handler all consume
the same source of truth.
"""

# (floor, ceiling) per unit. dB defaults (-30..0) align with the legacy
# ``dynamic='30 dB'`` migration path; Linear (0..1) is a placeholder the
# user is expected to overwrite once they re-disable auto.
Z_RANGE_DEFAULTS: dict[str, tuple[float, float]] = {
    'dB': (-30.0, 0.0),
    'Linear': (0.0, 1.0),
}


def z_range_for(unit_text: str) -> tuple[float, float]:
    """Return the default ``(floor, ceiling)`` Z range for ``unit_text``.

    Falls back to ``(0.0, 1.0)`` for unknown unit strings so the caller
    never raises on a future unit addition that lacks an entry here.
    """
    return Z_RANGE_DEFAULTS.get(unit_text, (0.0, 1.0))
