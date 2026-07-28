---
id: batch-render-cjk-glyph-coverage
status: active
owners: [codex]
keywords: [batch, renderer, matplotlib, cjk, fonts, glyphs]
paths: [mf4_analyzer/batch_render.py]
checks: [PNG warning capture, SVG text parse, rendered screenshot]
tests: [tests/test_batch_renderer.py]
---

# Batch Render Proof Includes CJK Glyph Coverage

Trigger: Changing batch figure typography, titles, axis labels, legends, colorbars, SVG/PDF output, or cross-platform font fallback.

Past failure: English-only renderer tests were green while real batch exports emitted Matplotlib missing-glyph warnings for Chinese labels such as `单帧`; DejaVu Sans alone could not satisfy the product's Chinese UI/export contract.

Rule: Resolve a real installed CJK-capable font from an ordered macOS, Windows, and Linux fallback list, apply it consistently to every figure text surface within scoped Matplotlib state, and retain DejaVu only as the final Latin fallback. Tests must print Chinese PNG/SVG content and fail on missing-glyph warnings; if no CJK font exists, report an explicit skipped environment gate rather than fake success.

Verification: Run `tests/test_batch_renderer.py`, inspect the generated Chinese 1080p proof, parse SVG text to confirm Chinese remains selectable, and separately record real Windows/frozen font discovery as unverified until exercised there.
