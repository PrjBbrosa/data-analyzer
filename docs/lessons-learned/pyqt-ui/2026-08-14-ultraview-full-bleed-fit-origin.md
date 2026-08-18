---
id: pyqt-ui/2026-08-14-ultraview-full-bleed-fit-origin
status: active
owners: [codex]
keywords: [ultraview, floating chrome, fit, origin, full-bleed, BoardScrollArea, immersive]
paths: [mf4_analyzer/ui/chart_stack/ultraview/floating_layout.py, mf4_analyzer/ui/chart_stack/ultraview/page.py, mf4_analyzer/ui/chart_stack/ultraview/viewport.py, tests/ui/test_ultraview_floating_layout.py, tests/ui/test_ultraview_viewport.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_floating_layout.py tests/ui/test_ultraview_viewport.py -q]
tests: [tests/ui/test_ultraview_floating_layout.py, tests/ui/test_ultraview_viewport.py]
---

# UltraView Full-Bleed Canvas Parks Fit At Origin

Trigger: Changing UltraView `FloatingLayout.board`, BoardScrollArea geometry, `zoom_fit`, or zoom-at-cursor scroll math.

Past failure: The scroll host was inset to the right of the rail and below the top islands, so zoom could not travel under the floating chrome. Making the host full-bleed without a parking origin would put 1× cards under the toolbar.

Rule: `board` is the full-bleed scroll host. `fit` is the chrome-safe 1× parking rect. Place the 1× stack at `fit` origin inside the host and keep 1× at scroll 0. 适应 uses `_content_fill_rect()` (same left as `fit`, `SAFE_MARGIN` top and bottom) and must park the stack at that fill origin — not at `fit`, or the cluster sits low. Zoom-at-cursor and persisted center must subtract/add the live stack origin. Do not relayout cards to the full window size.

Verification: `test_standard_stage_keeps_canvas_target_and_separates_chrome` (`board` is the stage, `fit` stays inset) and `test_canvas_is_full_bleed_and_fit_parks_cards_in_the_safe_zone`.
