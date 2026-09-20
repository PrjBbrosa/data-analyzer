---
id: empty-pin-replacement-must-clear-overlay
status: active
owners: [codex]
keywords: [pinned-cursor, empty, overlay, view-switch, orphan-label]
paths: [mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py, mf4_analyzer/ui/chart_stack/pinning/presentation.py]
checks: [git diff --check]
tests:
  - tests/ui/test_pinned_cursor_lifecycle.py::test_empty_collection_replacement_clears_all_projections
  - tests/ui/test_pinned_cursor_lifecycle.py::test_pending_nonempty_then_empty_does_not_resurrect_old_pins
---

# Empty Pin Replacement Must Clear Every Projection

Trigger: Replacing a Pin collection, restoring a View/pane, or checking Pin cleanup.

Past failure: `set_collection(empty_collection())` removed pills/labels but retained overlay records and lines. A subsequent reflow recreated P1/P2 from stale overlay layout; clicks found no model intent and did nothing. Existing lifecycle tests asserted empty records and pills only and passed. Reproduced with real ChartStack on offscreen and Cocoa on 2026-09-20, HEAD 24b45a94. Empty replacement now publishes `overlay.clear()` in the same transaction and `project_axis_labels` rejects orphan layout IDs.

Rule: Empty is an authoritative replacement. The controller must synchronize model, overlay records/items/tethers, presenter labels/pills, and queued work in the same replacement transaction. Clearing QWidget maps alone is not cleanup. Do not hide orphan clicks by minting new records.

Verification: `tests/ui/test_pinned_cursor_lifecycle.py::test_empty_collection_replacement_clears_all_projections` and `test_pending_nonempty_then_empty_does_not_resurrect_old_pins` seed two pins, replace with `empty_collection()`, drain queued work, reflow/pan/resize, and assert zero model records, overlay records/lines/tethers, pills, and axis labels. Cover Time/FFT; View restore, FRF, and Windows remain separate gates.
