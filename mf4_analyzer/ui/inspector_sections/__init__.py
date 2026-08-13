"""Package re-exports for mf4_analyzer.ui.inspector_sections.

This module replaces the former monolithic inspector_sections.py. Every
public name that the app and test suite imports from this path continues to
work via explicit re-exports below.

Monkeypatch anchor
------------------
``from PyQt5.QtWidgets import QMenu`` is re-exported here so that the
test-suite's ``monkeypatch.setattr("mf4_analyzer.ui.inspector_sections.QMenu",
...)`` resolves as a module-level attribute (required by pytest monkeypatch
when the target is not defined in a function scope).
"""

# --- monkeypatch anchor (MUST stay at module level) ---
from PyQt5.QtWidgets import QMenu  # noqa: F401

# --- helpers, constants, axis builders ---
from ._helpers import (  # noqa: F401
    _PRESET_ORG,
    _PRESET_APP,
    BUILTIN_PRESET_KEYS,
    BUILTIN_PRESET_DISPLAY,
    BUILTIN_PRESET_BLURB,
    _PRESET_KEY_TO_SLOT,
    _TORQUE_UNITS,
    _VIBRATION_UNITS,
    _SHORT_FIELD_MAX_WIDTH,
    _LONG_FIELD_MAX_WIDTH,
    _AXIS_LABEL_W,
    _AXIS_CHK_W,
    _AXIS_ROW_GAP,
    _AXIS_ARROW_W,
    _AXIS_MANUAL_GAP,
    _preset_settings,
    _normalize_unit,
    _dynamic_to_floor,
    recommend_preset_for_unit,
    _no_buttons,
    _make_group_header,
    _make_params_card,
    _settings_bool,
    _preset_value_text,
    _configure_form,
    _fit_field,
    _pair_field,
    _enforce_label_widths,
    _set_form_row_visible,
    _AxisRangeHost,
    _build_axis_row,
    _build_axis_header,
    _make_axis_settings_group,
)

# --- collapsible section ---
from .collapsible import _CollapsibleParamSection  # noqa: F401

# --- preset widgets ---
from .presets import _PresetHoverCard, PresetBar  # noqa: F401

# --- main contextual widgets ---
from .persistent_top import PersistentTop  # noqa: F401
from .contextual_time import TimeContextual  # noqa: F401
from .contextual_fft import FFTContextual  # noqa: F401
from .contextual_order import OrderContextual  # noqa: F401
from .contextual_fft_time import FFTTimeContextual  # noqa: F401
from .contextual_frf import FrfContextual  # noqa: F401
from .contextual_ultraview import UltraViewContextual  # noqa: F401
