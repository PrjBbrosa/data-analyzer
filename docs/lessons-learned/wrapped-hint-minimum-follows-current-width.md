---
id: wrapped-hint-minimum-follows-current-width
status: active
owners: [codex]
keywords: [word-wrap, QLabel, QFormLayout, minimum-height, resize]
paths: [mf4_analyzer/ui/widgets/wrapped_hint.py, mf4_analyzer/ui/inspector_sections/persistent_top.py]
checks: [git diff --check]
tests: [tests/ui/test_inspector.py::test_xaxis_hint_resists_vertical_compression_and_remeasures]
---

# Wrapped Hint Minimum Follows Current Width

Trigger: A wrapped hint inside a nested form is intermittently compressed.

Past failure: Normal settled constructions looked correct, but a deterministic
short height allocation clipped the text. Word-wrap size hints alone did not
protect the row from vertical pressure.

Rule: Propagate the layout's current height-for-width as an explicit minimum.
Refresh on resize, layout, font and style changes; allow the minimum to shrink
when width grows or text shortens. Do not hard-code a two-line pixel height.

Verification: Exercise vertical pressure, narrow/wide widths, longer/shorter
text, and larger fonts, then inspect Cocoa with the production stylesheet.
Keep the unknown original trigger separate from this defensive regression.
