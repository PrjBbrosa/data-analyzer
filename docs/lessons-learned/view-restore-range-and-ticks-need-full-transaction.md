---
id: view-restore-range-and-ticks-need-full-transaction
status: active
owners: [codex]
keywords: [wwt, initial-ranges, overlay, view-restore, tick-density, axisitem]
paths:
  - mf4_analyzer/ui/pg_canvas/tick_density.py
  - mf4_analyzer/ui/pg_canvas/overlay_axes.py
  - mf4_analyzer/ui/main_window/_view_mixin.py
  - mf4_analyzer/ui/view_bridge.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_initial_view_contract.py tests/ui/test_view_bridge.py::test_passive_capture_discards_retired_native_ticks -q
---

# View Restore Range And Ticks Need The Full Transaction

Trigger: Changing TimeDomain View restore, committed initial ranges, overlay
`set_tick_density()`, or `_repin_overlay_channel_ticks()`.

Past failure: Shared-axis tests asserted `restore_visible_ylims()` then stopped. Production still ran default density 15, which nice-reframed speed `0..460` to `0..600`, then native helper wrote labels from spec `lo/hi` only. Local tests stayed green while the right axis showed a 23% unlabeled band.

The partial-native case was a useful counterexample: a canvas-level source-specific
policy skipped normal tick projection for axes absent from its policy. That second
Canvas owner is retired by the [minimal initial-view contract plan](../analyzer/plans/2026-09-01-wwt-minimal-initial-view-contract-simplification-plan.md).

Rule: After a stable frame, ViewState/effective range, `PgAxisHandle.get_*lim()`,
and `AxisItem.range` must match; ordinary/adaptive ticks and grid must cover that
same final range. Import facts may supply a one-time committed or fallback initial
range, but must not become an active Canvas display policy. Assert after the full
normal restore transaction (`plot` → restore X/Y → density without re-framing a
committed range → settle/resize), not after one helper. Canvas must not own a WWT
native policy. Passive capture normalizes ordinary axis options and discards retired
`native_ticks` rather than preserving or conditionally exiting a second policy.

Verification: Run `tests/ui/test_wwt_initial_view_contract.py` and
`tests/ui/test_view_bridge.py::test_passive_capture_discards_retired_native_ticks`
with offscreen Qt, plus `git diff --check`.
