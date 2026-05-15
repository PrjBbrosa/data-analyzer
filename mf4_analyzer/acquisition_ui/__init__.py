"""Acquisition Cockpit Qt UI package.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
Plan: ``docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md``

The Cockpit is a separate same-process partner window to the Analyzer.
This package depends on ``mf4_analyzer.acquisition_capture`` for the
capture core (health, ring buffer, backends, thresholds) and on
``mf4_analyzer.ui_kit`` for shared UI primitives (stylesheet, fonts,
icons). It MUST NOT import Analyzer internals — Stage 5 adds the single
public handoff method on the Analyzer ``MainWindow``.

Public surface (Stage 4):

- :class:`CockpitMainWindow` — the partner ``QMainWindow``.
- :class:`CockpitState` — the four-state enum + transitions in
  :mod:`mf4_analyzer.acquisition_ui.state`.

All numeric thresholds come from
``mf4_analyzer.acquisition_capture.thresholds``. UI never inlines a
threshold literal.
"""

from __future__ import annotations

from mf4_analyzer.acquisition_ui.state import (
    CockpitState,
    CockpitStateMachine,
    HealthyPredicateResult,
)

__all__ = [
    "CockpitState",
    "CockpitStateMachine",
    "HealthyPredicateResult",
]
