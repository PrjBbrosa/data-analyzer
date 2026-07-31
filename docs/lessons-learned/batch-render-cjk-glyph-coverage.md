---
id: batch-render-cjk-glyph-coverage
status: active
owners: [codex]
keywords: [batch, renderer, matplotlib, cjk, fonts, glyphs]
paths: [mf4_analyzer/batch_render.py]
checks: [PNG warning capture, SVG text parse, Poppler PDF text/raster check, rendered screenshot]
tests: [tests/test_batch_renderer.py, tests/test_frozen_batch_render_smoke.py]
---

# Batch Render Proof Includes CJK Glyph Coverage

Trigger: Changing batch figure typography, titles, axis labels, legends, colorbars, SVG/PDF output, or cross-platform font fallback.

Past failure: English-only renderer tests were green while real batch exports emitted Matplotlib missing-glyph warnings for Chinese labels such as `单帧`; DejaVu Sans alone could not satisfy the product's Chinese UI/export contract. A later PDF looked correct but Matplotlib's Type 3 embedding had no Unicode map, so Poppler extracted gibberish instead of selectable CJK text.

Rule: Resolve a real installed CJK-capable font from an ordered macOS, Windows, and Linux fallback list, apply it consistently to every figure text surface within scoped Matplotlib state, and retain DejaVu only as the final Latin fallback. Tests must print Chinese PNG/SVG content and fail on missing-glyph warnings; PDF export must use scoped TrueType embedding (`pdf.fonttype=42`) and prove the CJK title is both Poppler-extractable and visually present after rasterization. If no CJK font exists, report an explicit skipped environment gate rather than fake success.

Verification: Run `tests/test_batch_renderer.py` and `tests/test_frozen_batch_render_smoke.py`, inspect the generated Chinese proof, parse SVG text, extract PDF text with Poppler, and inspect Poppler-rendered PDF PNGs. Separately record real Windows/frozen font discovery as unverified until exercised there.
