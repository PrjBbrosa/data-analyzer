---
id: pyqt-ui/2026-08-20-ultraview-card-fit-hugs-current-scale
status: active
owners: [codex]
keywords: [ultraview, autofit, 按原图比例, card-fit, unused-area, hug]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/card_fit.py
  - mf4_analyzer/ui/chart_stack/ultraview/free_grid.py
  - docs/analyzer/specs/2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md
checks:
  - rg -n "unused_area_ratio|CARD_FIT_SNAP_WINDOW|hug_plot_targets" mf4_analyzer/ui/chart_stack/ultraview/card_fit.py
tests:
  - tests/ui/test_ultraview_card_fit.py::test_card_fit_does_not_jump_to_global_min_waste_size
  - tests/ui/test_ultraview_card_fit.py::test_card_fit_keeps_scale_for_the_same_image_at_different_origins
  - tests/ui/test_ultraview_card_fit.py::test_card_fit_does_not_collapse_a_large_card_around_a_small_preview
---

# UltraView Card Fit Hugs Current Scale

Trigger: Changing UltraView Card Fit / 「按原图比例」, `solve_card_fit`, `fit_rect_for_aspect`, first-insert auto-aspect, or spec F3.

Past failure: F3 used unused-area ratio over every min/max span as the primary key. The same 16:9 capture jumped to 13×11 from any origin; 1550×800 jumped to 20×15; a small capture collapsed to 4×4 because no-upscale gutter grew with card size.

Rule: Card Fit is a local reshape around the current reading scale. Prefer the hug axis that does not grow, then search only that free axis (±2) plus the current span. Score "does not grow" before aspect leftover, and measure leftover with virtual upscale. Do not treat renderer no-upscale gutter as a reason to collapse a large card, and do not scan the full board for the single lowest unused ratio.

Verification: `tests/ui/test_ultraview_card_fit.py` hug-scale tests plus `test_ultraview_free_grid.py::test_fit_rect_for_aspect_stays_near_the_current_scale`.
