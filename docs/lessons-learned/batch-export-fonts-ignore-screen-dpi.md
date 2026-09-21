---
id: batch-export-fonts-ignore-screen-dpi
status: active
owners: [codex]
keywords: [batch, export, dpi, qfont, font_scale, hidpi]
paths: [mf4_analyzer/batch_render_qt/_theme.py, mf4_analyzer/batch_render_qt/_builder.py]
checks: [export fonts at 96 CSS-DPI reference; PNG dpi metadata after paint]
tests: [tests/test_batch_render_qt.py::test_export_text_geometry_is_stable_across_logical_dpi]
---

# Batch Export Fonts Must Not Follow Screen DPI

Trigger: Changing Qt batch report titles, ticks, legends, stats cards, colorbars, or PNG export size.

Past failure: Windows logical DPI 192 made 12pt paint 41 px tall on a 640×360 export, overlapping ticks. A diagnostic child with `QT_FONT_DPI=96` looked fine while the real Batch path still followed the screen.

Rule: Keep `width_px`/`height_px` as output pixels and PNG `dpi` as metadata written after paint. Create Batch export fonts and QFontMetrics on a 96 CSS-DPI reference (point size compensated by `96/logicalDpi`, not `QFont.setPixelSize` if SSAA must scale strokes). Do not change `CHART_FONT_PT`, the GUI `QApplication` font, or the user's screen. `font_scale` still multiplies theme pt. Geometry across 96/144/192 must stay within 2 output pixels.

Verification: Fresh-process `test_export_text_geometry_is_stable_across_logical_dpi`; keep `test_subplot_export_draws_before_writing_dpi_metadata_and_contains_ticks`. A `QT_FONT_DPI=96` child is an experiment, not the product fix.
