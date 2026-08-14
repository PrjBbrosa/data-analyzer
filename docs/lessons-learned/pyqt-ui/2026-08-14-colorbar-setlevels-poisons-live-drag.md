---
id: pyqt-ui/2026-08-14-colorbar-setlevels-poisons-live-drag
status: active
owners: [codex]
keywords: [pyqtgraph, ColorBarItem, setLevels, lo_prv, heatmap, apply_params, colorbar, drag, levels_changed]
paths: [mf4_analyzer/ui/pg_canvas/heatmap_canvas.py, mf4_analyzer/ui/inspector_sections/contextual_fft.py, mf4_analyzer/ui/inspector_sections/contextual_fft_time.py, mf4_analyzer/ui/inspector_sections/contextual_order.py, mf4_analyzer/ui/analysis_section_page.py, mf4_analyzer/ui/main_window/_analysis_mixin.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_colorbar_reset.py tests/ui/test_weighting_ui.py tests/ui/test_analysis_section_page.py tests/ui/test_inspector.py::test_analysis_contextuals_apply_params_is_silent tests/ui/test_no_lambda_signal_connections.py -q]
tests: [tests/ui/test_colorbar_reset.py, tests/ui/test_weighting_ui.py, tests/ui/test_analysis_section_page.py, tests/ui/test_inspector.py]
---

# ColorBarItem setLevels Poisons Live Drag

Trigger: Heatmap colorbar drag, `ColorBarItem.setLevels`, inspector `apply_params` of `z_floor`/`z_ceiling`, `levels_changed`, or locked-levels sibling mirror.

Past failure: Dragging 时频/阶次 colorbar compounded into the ±500 spin rails, collapsed to `500 → 500` (black plot, dead right-axis ticks). Double-click reset became a no-op because mid-drag `apply_params` emitted `display_params_changed`, replotted, and `setLevels` rewrote `lo_prv`/`hi_prv` while handles were still offset from the parked `(63, 191)` bar-space positions.

Rule: Never call `ColorBarItem.setLevels` while `region.moving` or a handle `InfiniteLine.moving`. Inspector restore of a live drag must wrap widget writes in `_applying_preset` (silent `apply_params`, like FRF). Persist the View ledger after `apply_params` returns. Do not replace `_rendered_levels` mid-drag. Double-click restore emits `colorbar_restored`, not `levels_changed`, and must not re-lock via combined auto of both matrices. Emit `levels_rebased` only after `_has_result` / `_matrix_disp` are set.

Verification: `test_plot_during_handle_drag_does_not_rewrite_lo_prv`, `test_*_colorbar_drag_does_not_emit_display_params`, `test_analysis_contextuals_apply_params_is_silent`, `test_locked_levels_skip_setlevels_on_moving_source`, `test_colorbar_restore_copies_window_to_locked_sibling`, `test_default_levels_lock_reapplies_after_heatmap_render`.
