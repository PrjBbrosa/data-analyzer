---
id: view-restore-range-and-ticks-need-full-transaction
status: active
owners: [codex]
keywords: [wwt, native-ticks, overlay, view-restore, tick-density, axisitem]
paths:
  - mf4_analyzer/ui/pg_canvas/tick_density.py
  - mf4_analyzer/ui/pg_canvas/overlay_axes.py
  - mf4_analyzer/ui/pg_canvas/native_axes.py
  - mf4_analyzer/ui/main_window/_view_mixin.py
  - mf4_analyzer/ui/view_bridge.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_native_render.py tests/ui/test_view_bridge.py::test_passive_capture_preserves_native_ticks -q
---

# View Restore Range And Ticks Need The Full Transaction

Trigger: Changing TimeDomain View restore, overlay `set_tick_density()`, WWT `native_ticks`, or `_repin_overlay_channel_ticks()`.

Past failure: Shared-axis tests asserted `restore_visible_ylims()` then stopped. Production still ran default density 15, which nice-reframed speed `0..460` to `0..600`, then native helper wrote labels from spec `lo/hi` only. Local tests stayed green while the right axis showed a 23% unlabeled band.

Rule: After a stable frame, ViewState/effective range, `PgAxisHandle.get_*lim()`, and `AxisItem.range` must match; native explicit ticks must be the native cadence over that same range. Assert this after the full restore sequence (`plot` → restore X/Y → density → native project → settle/resize), not after a single helper. Passive capture must keep `native_ticks`; only an explicit density user action may drop it.

Verification: Run `tests/ui/test_wwt_native_render.py` and `tests/ui/test_view_bridge.py::test_passive_capture_preserves_native_ticks` with offscreen Qt, plus `git diff --check`.
