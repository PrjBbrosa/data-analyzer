---
id: pyqt-ui/2026-08-17-ultraview-fit-fill-vertical-center
status: active
owners: [codex]
keywords: [ultraview, zoom_fit, 适应, _content_fill_rect, SAFE_MARGIN, fill origin, session camera]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - mf4_analyzer/ui/chart_stack/ultraview/viewport.py
  - tests/ui/test_ultraview_viewport.py
  - tests/ui/test_ultraview_project_session.py
checks:
  - rg -n "_content_fill_rect|SAFE_MARGIN" mf4_analyzer/ui/chart_stack/ultraview/page.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py::test_zoom_fit_fill_rect_is_taller_than_parking_fit tests/ui/test_ultraview_viewport.py::test_zoom_fit_centers_content_in_the_safe_zone tests/ui/test_ultraview_viewport.py::test_session_camera_restore_replays_stack_origin_not_fit_origin tests/ui/test_ultraview_project_session.py::test_switching_boards_restores_session_camera -q
---

# UltraView Fit Fill Is Vertically Stage-Centered

Trigger: Changing UltraView `_content_fill_rect`, `zoom_fit`, `_apply_zoom_and_center` origin, `SAFE_MARGIN` vs parking `fit.y`, or `_restore_viewport_from_board`.

Past failure: 适应 kept parking's 64px top inset and only `SAFE_MARGIN` at the bottom, so the fill centre sat 26px below the stage centre. Expanding the top by that 26px only moves the centre by 13px. Raising `fill.y` while still parking the stack at `_fit_origin()` leaves the visual centre low or lower. Session-camera restore later reused that same `_fit_origin()` snap: after Select+Sticky made `layout.fit.y` 64 while live zoom stayed on fill `y=12`, switching boards restored zoom+center but moved the stack 52px and failed `test_switching_boards_restores_session_camera`.

Rule: `_content_fill_rect` top and bottom are both `SAFE_MARGIN` (rail-clear left stays `fit.x`). `zoom_fit` must place the stack at the fill origin, not parking `fit`. 1× parking still uses `fit`. `_apply_zoom_and_center` without an explicit origin keeps `_board_content_origin()`. Session restore must replay the parked stack origin from `_session_camera`; do not snap restore onto `layout.fit`.

Verification: `test_zoom_fit_fill_rect_is_taller_than_parking_fit` (`fill.y == SAFE_MARGIN`, vertical centre on the stage), `test_zoom_fit_centers_content_in_the_safe_zone`, `test_session_camera_restore_replays_stack_origin_not_fit_origin`, and `test_switching_boards_restores_session_camera`.
