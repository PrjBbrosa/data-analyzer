---
id: pyqt-ui/2026-08-16-ultraview-open-fits-content
status: active
owners: [codex]
keywords: [ultraview, zoom_fit, fit_on_open, open_ultraview, viewport restore, elastic halo]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - mf4_analyzer/ui/drawers/ultraview/sheet.py
  - mf4_analyzer/ui/main_window/window.py
  - tests/ui/test_ultraview_viewport.py
  - tests/ui/test_ultraview_mode_integration.py
  - tests/ui/test_ultraview_page.py
checks:
  - rg -n "fit_on_open|_apply_initial_viewport|initial_viewport" mf4_analyzer/ui/chart_stack/ultraview/page.py mf4_analyzer/ui/drawers/ultraview/sheet.py mf4_analyzer/ui/main_window/window.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py::test_fit_on_open_ignores_leftover_pan_and_zoom tests/ui/test_ultraview_viewport.py::test_switching_boards_fits_content_instead_of_restoring_zoom tests/ui/test_ultraview_page.py::test_new_board_first_show_fits_the_working_frame tests/ui/test_ultraview_mode_integration.py::test_reopening_ultraview_fits_instead_of_restoring_zoom tests/ui/test_ultraview_project_session.py::test_viewport_survives_save_and_reopen tests/ui/test_ultraview_project_session.py::test_switching_boards_persists_viewport_to_departing_board -q
---

# UltraView Open Parks On Fit, Not Leftover Viewport

Trigger: Changing UltraView window open/present, Board switch, `fit_on_open`, `_apply_initial_viewport`, `_restore_viewport_from_board`, or persisted `board.viewport` restore.

Past failure: Opening UltraView restored the last pan/zoom, or parked a new board on the 66% two-card working-frame centre. Switching boards restored that leftover camera, so only the first show fitted. On the signed elastic halo a stored centre is not the placed-card cluster.

Rule: Every UltraView window open (`open_ultraview`, sheet `present` / `showEvent`) and every Board switch (`set_board` / `_restore_viewport_from_board`) must call `page.fit_on_open()` → `zoom_fit`. Do not restore persisted pan/zoom as the show camera. Leave-board snapshots may still be written; they are not replayed on show.

Verification: `test_fit_on_open_ignores_leftover_pan_and_zoom`, `test_switching_boards_fits_content_instead_of_restoring_zoom`, `test_new_board_first_show_fits_the_working_frame`, `test_reopening_ultraview_fits_instead_of_restoring_zoom`, `test_viewport_survives_save_and_reopen`.
