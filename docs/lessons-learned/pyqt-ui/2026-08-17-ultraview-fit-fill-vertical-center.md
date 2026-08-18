---
id: pyqt-ui/2026-08-17-ultraview-fit-fill-vertical-center
status: active
owners: [codex]
keywords: [ultraview, zoom_fit, 适应, _content_fill_rect, SAFE_MARGIN, fill origin]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - mf4_analyzer/ui/chart_stack/ultraview/viewport.py
  - tests/ui/test_ultraview_viewport.py
checks:
  - rg -n "_content_fill_rect|SAFE_MARGIN" mf4_analyzer/ui/chart_stack/ultraview/page.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py::test_zoom_fit_fill_rect_is_taller_than_parking_fit tests/ui/test_ultraview_viewport.py::test_zoom_fit_centers_content_in_the_safe_zone -q
---

# UltraView Fit Fill Is Vertically Stage-Centered

Trigger: Changing UltraView `_content_fill_rect`, `zoom_fit`, `_apply_zoom_and_center` origin, or `SAFE_MARGIN` vs parking `fit.y`.

Past failure: 适应 kept parking's 64px top inset and only `SAFE_MARGIN` at the bottom, so the fill centre sat 26px below the stage centre. Expanding the top by that 26px only moves the centre by 13px. Raising `fill.y` while still parking the stack at `_fit_origin()` leaves the visual centre low or lower.

Rule: `_content_fill_rect` top and bottom are both `SAFE_MARGIN` (rail-clear left stays `fit.x`). `zoom_fit` must place the stack at the fill origin, not parking `fit`. 1× parking still uses `fit`. Do not expand one edge by the centre-offset; match the opposite inset.

Verification: `test_zoom_fit_fill_rect_is_taller_than_parking_fit` (`fill.y == SAFE_MARGIN`, vertical centre on the stage) and `test_zoom_fit_centers_content_in_the_safe_zone`.
