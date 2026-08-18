---
id: pyqt-ui/2026-08-16-ultraview-zoom-settle-and-fit-fill
status: active
owners: [codex]
keywords: [ultraview, zoom, flicker, extent, follow_view, board_fit_zoom, 适应, raise_window]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - mf4_analyzer/ui/chart_stack/ultraview/viewport.py
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - tests/ui/test_ultraview_viewport.py
  - tests/ui/test_ultraview_capture.py
checks:
  - rg -n "_broadcast_zoom|_zoom_transaction|follow_view|BOARD_FIT_ZOOM_MAX|raise_window" mf4_analyzer/ui/chart_stack/ultraview/page.py mf4_analyzer/ui/chart_stack/ultraview/viewport.py mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/main_window/ultraview_coordinator.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py::test_wheel_zoom_does_not_chase_viewport_while_scroll_is_in_flight tests/ui/test_ultraview_viewport.py::test_wheel_zoom_does_not_refresh_extent_until_idle tests/ui/test_ultraview_viewport.py::test_board_fit_zoom_fills_canvas_up_to_300_percent tests/ui/test_ultraview_viewport.py::test_zoom_fit_single_card_can_fill_up_to_300_percent tests/ui/test_ultraview_capture.py::test_user_sync_navigates_without_raising_the_analyzer -q
---

# UltraView Zoom Settles After Scroll; Fit Fills To 300%

Trigger: Changing UltraView board zoom, `zoom_fit` / 适应, elastic `workspace_extent`, `_broadcast_zoom`, or ToolRail 「一键更新源」 / `sync_preview` navigation.

Past failure: `_broadcast_zoom` refreshed the elastic extent (unioning the live viewport) before the caller applied `zoom_at` scroll, so the canvas origin moved under a stale scroll and every card trembled. Settling extent on every wheel tick (even after scroll, even with `follow_view=False`) still rebased the signed origin and kept the shake. Board Fit used a 6% chrome-safe inset that stopped above the navigation island, so a compact cluster sat at ~75% with large empty stage around it. Sync called `navigate_to_view` which `raise_()` / `activateWindow()` the Analyzer.

Rule: Interactive zoom must not refresh elastic extent at all. Apply zoom and scroll first; grow the halo on the idle smooth timer with ``preserve_visible=True``. Do not union `_visible_workspace_bounds()` or call `_sync_board_stack_geometry` while `_zoom_in_flight`. Board Fit (`board_fit_zoom`) fills `_content_fill_rect()` (rail-clear left, ``SAFE_MARGIN`` top and bottom) with a 2% hairline, up to `ZOOM_MAX` (300%). The fill origin must be that rect's top-left, not parking ``fit`` (which sits below the top islands). Opening the UltraView window always runs `fit_on_open` / `zoom_fit`; do not restore leftover pan/zoom as the open camera. Sync navigation uses `raise_window=False`; `open_source` still raises Analyzer. Raise the UltraView sheet only after the sync nav queue is empty.

Verification: `test_wheel_zoom_does_not_chase_viewport_while_scroll_is_in_flight`, `test_wheel_zoom_does_not_refresh_extent_until_idle`, `test_board_fit_zoom_fills_canvas_up_to_300_percent`, `test_zoom_fit_single_card_can_fill_up_to_300_percent`, `test_user_sync_navigates_without_raising_the_analyzer`.
