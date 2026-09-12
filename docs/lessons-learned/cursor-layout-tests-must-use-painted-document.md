---
id: cursor-layout-tests-must-use-painted-document
status: active
owners: [codex]
keywords: [cursor, QTextDocument, QLabel, clipping, Custom-X, prototype]
paths: [mf4_analyzer/ui/chart_stack/cursor_pill.py, mf4_analyzer/ui/chart_stack/cursor_display.py]
checks: [git diff --check]
tests: [tests/ui/test_cursor_table_geometry.py, tests/ui/test_cursor_table_modes.py, tests/ui/test_cursor_single_pipeline.py]
---

# Cursor geometry acceptance must inspect the painted document

Trigger: Cursor rich-text layout, prototype-to-Qt implementation, or reports that aligned values are clipped.

Past failure: A separately constructed wrapping QTextDocument passed width assertions while the actual nowrap QLabel required 373px inside 264px; the final delta column was outside the visible label. Always-grouped layout also contradicted the approved horizontal prototype, while a Time-X-only rendering gate left Custom-X branches outside the table.

Rule: Measure and paint the same document configuration with production QSS. Check every visible glyph against the widget content rectangle, not only equal column positions or the imposed textWidth. Cover Time/Custom-X, single/dual, full/mini, diagnostic-first and zero-visible-channel cases. Do not change the spec to justify a prototype mismatch. Preserve the single projection apply boundary and legacy +/- sizing when introducing a shared widget.

Verification: Run the focused geometry/mode/single-pipeline tests and applicable chart-stack toggle/capture regressions. Inspect real ChartStack renderings with screenshot-length names, short names, units, and direction/diagnostic fixtures. Record offscreen, native Cocoa, foreground original project, and Windows separately.
