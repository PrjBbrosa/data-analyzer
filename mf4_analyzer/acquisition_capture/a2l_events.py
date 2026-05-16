"""DAQ event helpers for the Cockpit Left Pane.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Search And Filter Contract, ``build_event_intersection``.

This module is intentionally tiny — the heavy work of extracting
``IF_DATA XCP DAQ_EVENT`` blocks from an A2L belongs to a future Stage 3+
parser extension; today the helper consumes whatever
``MeasurementSummary.available_events`` is populated with by
``can_logger.p0.a2l_probe``.

Pure-data: no Qt, no IO.
"""

from __future__ import annotations

from collections.abc import Iterable

from can_logger.p0.a2l_probe import MeasurementSummary


def build_event_intersection(selected: Iterable[MeasurementSummary]) -> set[str]:
    """Return DAQ event names common to every selected measurement.

    Used by the batch-raster dropdown in the Cockpit Left Pane: when the
    user multi-selects measurements and reaches for "set raster", only
    events that all selected measurements support are valid choices.

    Empty selection or empty intersection ⇒ empty set. The UI MUST
    disable the dropdown with the tooltip ``"选中信号没有共同的 DAQ
    event"`` when this returns empty.

    A measurement that exposes no events (``available_events == ()``)
    collapses the intersection to empty — it cannot share any event.
    """
    selected_list = list(selected)
    if not selected_list:
        return set()
    intersection: set[str] | None = None
    for m in selected_list:
        events = set(m.available_events)
        if intersection is None:
            intersection = events
        else:
            intersection &= events
        if not intersection:
            return set()
    return intersection or set()
