"""Shared pure helpers for pyqtgraph time-domain canvas modules."""

from __future__ import annotations

import json

from mf4_analyzer.ui.canvases import _compact_axis_label


def _subplot_ylabel_text(name, unit):
    """Subplot left-axis label: compact channel name plus unit suffix."""
    compact = _compact_axis_label(name, unit, max_chars=20)
    return f"{compact}" + (f" ({unit})" if unit else "")


def _view_state_channel_key(data_id, name):
    stable_data_id = None if data_id is None else str(data_id)
    return json.dumps(
        [stable_data_id, str(name)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _hide_native_auto_button(plot) -> None:
    """Hide pyqtgraph's built-in lower-left auto-range button."""
    hide = getattr(plot, "hideButtons", None)
    if callable(hide):
        hide()
