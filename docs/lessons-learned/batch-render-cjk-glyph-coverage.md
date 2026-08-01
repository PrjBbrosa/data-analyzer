---
id: batch-render-cjk-glyph-coverage
status: active
owners: [codex]
keywords: [batch, renderer, qt, pyqtgraph, cjk, fonts, glyphs, ink]
paths: [mf4_analyzer/batch_render_qt/_fonts.py, mf4_analyzer/batch_render_qt/_builder.py]
checks: [Qt glyph coverage, rendered header ink delta, PNG inspection]
tests: [tests/test_batch_render_qt.py]
---

# Qt Batch Render Proof Includes CJK Glyph And Ink Coverage

Trigger: Changing Qt batch titles, axis labels, legends, colorbars, PNG output,
or cross-platform chart-font fallback.

Past failure: English-only exports passed while Chinese text was missing. Under
Qt, checking only the selected family name is still a false green because font
fallback can resolve to tofu or blank glyphs without a Matplotlib-style warning.

Rule: Resolve the first installed family in the shared macOS/Windows/Linux Qt
fallback order, then require both per-character coverage via
`QRawFont.supportsCharacter` (or `QFontMetrics.inFontUcs4`) and a rendered-ink
delta against an empty control image. Apply that font to every report text
surface. If no font covers the full contract string, report an explicit skipped
environment gate rather than accepting a family-name-only result.

Verification: Run
`tests/test_batch_render_qt.py::test_cjk_font_support_and_header_ink_proof`,
require supported characters and an ink count above the blank control, inspect a
real Chinese PNG, and keep Windows frozen font discovery unverified until it is
exercised on that artifact.
