---
id: pyqt-ui/2026-08-18-ultraview-preview-reading-gutter
status: active
owners: [codex]
keywords: [ultraview, preview, AlignTop, letterbox, pillarbox, 按原图比例, autofit, 4:3]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/layouts.py
  - mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - mf4_analyzer/ui/chart_stack/ultraview/compositor.py
  - mf4_analyzer/ui/chart_stack/ultraview/free_grid.py
  - tests/ui/test_ultraview_free_grid.py
checks:
  - rg -n "PREVIEW_READING_ASPECT|AlignHCenter \\| Qt.AlignTop|preview_reading_box" mf4_analyzer/ui/chart_stack/ultraview/layouts.py mf4_analyzer/ui/chart_stack/ultraview/widgets.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_free_grid.py::test_card_preview_pixmap_is_centered_not_stretched tests/ui/test_ultraview_free_grid.py::test_preview_reading_box_height_fills_a_wide_16x9_capture tests/ui/test_ultraview_free_grid.py::test_preview_reading_box_uses_the_capture_aspect_not_4x3 tests/ui/test_ultraview_free_grid.py::test_fit_rect_for_aspect_prefers_side_gutter_over_bottom_gap -q
---

# UltraView Card Preview Uses Capture Aspect

Trigger: Changing UltraView card preview scaling, `QLabel#ultraViewCardImage` alignment, `_fit_card_image`, export `_draw_preview`, or `preview_reading_box`.

Past failure: `AlignTop` contain filled width and dumped leftover under the chart. A later 4:3 reading frame letterboxed fullscreen 16:9 grabs, putting white bands on all four sides.

Rule: `preview_reading_box` KeepAspectRatio-contains the capture's real size in the full plot area (no forced 4:3). That height-fills when the slot is wider than the image. Center the pixmap. `fit_rect_for_aspect` still prefers leftover width (`FIT_LETTERBOX_COST`). Do not restore `AlignHCenter | AlignTop` or `PREVIEW_READING_ASPECT`.

Verification: `test_preview_reading_box_height_fills_a_wide_16x9_capture`, `test_preview_reading_box_uses_the_capture_aspect_not_4x3`, `test_card_preview_pixmap_is_centered_not_stretched`.
