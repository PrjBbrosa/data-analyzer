---
id: ultraview-idle-digest-keeps-armed-cursor
status: active
owners: [codex]
keywords: [ultraview, idle, capture, cursor, digest, pill, hide_transient]
paths:
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
  - mf4_analyzer/ui/chart_stack/stack.py
  - tests/ui/test_ultraview_capture.py
  - tests/ui/test_ultraview_mode_integration.py
checks:
  - rg -n "cursor_mode|cursor_geometry|_pill_fingerprint" mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
  - rg -n "_HOVER_CURSOR_LISTS|_host_is_dual_cursor" mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
  - rg -n "grab_presentation_pixmap|_IDLE_CAPTURE_MS" mf4_analyzer/ui/chart_stack/stack.py mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_capture.py::test_transient_overlays_hidden_but_markup_revision_is_captured tests/ui/test_ultraview_capture.py::test_idle_capture_coalesces_range_signals tests/ui/test_ultraview_capture.py::test_idle_cursor_info_does_not_project_each_signal tests/ui/test_ultraview_capture.py::test_digest_changed_requeues_and_publishes tests/ui/test_ultraview_capture.py::test_idle_pending_per_ref_not_starved_by_other_canvas tests/ui/test_ultraview_capture.py::test_presentation_digest_pixel_affecting_field_matrix tests/ui/test_ultraview_mode_integration.py::test_idle_pan_and_markup_recaptures_time_preview -q
---

# UltraView Idle Recapture Keeps Armed Cursor And Cursor Digest

Trigger: Changing UltraView capture, presentation digest, `hide_transient_overlays`, idle recapture, or copy-as-image pill compositing.

Past failure: Pan/zoom/cursor/markup left Board cards stale-looking-fresh. Digest ignored `cursor_mode`, so recapture skipped. `hide_transient_overlays` hid armed single-cursor lines (`_cursor_line_items` is hover when dual and the armed line when single). The readout pill lives on ChartStack, so canvas `grab_pixmap` never had the numbers.

Rule: Digest must include `cursor_mode`, armed **dual** cursor x, and dual
readout pill text fingerprint, or idle recapture will skip. Hide hover
follow lines in both single and dual (`_cursor_line_items` / `_cursor_lines`)
plus `rbScaleBox`; keep dual armed A/B lines and extreme markers. Single
mode has no armed cursor — hover x must not enter digest. Presentation-only
facts (cursor geometry, pill fingerprint) commit into the runtime ledger at
grab time and are reread when the canvas is unbound or hidden. Grab through
`grab_presentation_pixmap` (canvas + overlapping pill) at 1×. Coalesce
pan/cursor/markup onto one single-shot idle timer **per ref** (store last
signal time; do not restart the global timer so canvas A cannot starve B).
Do not `_push_preview` or `request_capture` on each `cursor_info`. Sheet
hidden → no extra idle grabs. `digest-changed` at grab time must requeue
with the live digest, capped at `_DIGEST_RETRY_LIMIT`. Cursor-move while
settling may keep the previous FRESH frame until the idle window elapses;
do not require a STALE flash before the recapture.

Verification: `test_transient_overlays_hidden_but_markup_revision_is_captured`, `test_idle_capture_coalesces_range_signals`, `test_presentation_digest_pixel_affecting_field_matrix`, `test_idle_pan_and_markup_recaptures_time_preview`.
