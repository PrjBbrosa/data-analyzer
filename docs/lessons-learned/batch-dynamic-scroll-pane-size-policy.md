---
id: batch-dynamic-scroll-pane-size-policy
status: active
owners: [codex]
keywords: [BatchSheet, QScrollArea, widgetResizable, QSizePolicy, dynamic form, button text, clipping]
paths: [mf4_analyzer/ui/drawers/batch/sheet.py, mf4_analyzer/ui/drawers/batch]
checks: [offscreen geometry, Cocoa geometry, pane scroll reachability, text bounds]
tests: [tests/ui/test_batch_smoke.py, tests/ui/test_batch_method_buttons.py]
---

# Batch Dynamic Panes Need Scroll And Text Geometry Proof

Trigger: Changing BatchSheet columns, dynamic method fields, compact button rows, or any `QScrollArea(widgetResizable=True)` pane whose content grows, shrinks, or contains unequal labels.

Past failure: A Preferred-size panel was compressed to its `minimumSizeHint()` so lower controls disappeared instead of scrolling. After vertical reachability was fixed, equal-width compact buttons still clipped the longer `FFT vs Time` label at the supported 288 px pane width even though structural tests passed.

Rule: Give scroll content `QSizePolicy.Minimum` vertically so `sizeHint()` remains the scrollable extent. Keep the footer outside scroll areas. For compact horizontal rows, allocate stretch or minimum width from rendered label demand instead of assuming equal cells; do not infer Cocoa reachability or text fit from offscreen structure alone.

Verification: Run BatchSheet geometry tests at 1080x760 and 288-320 px pane widths, assert each method button's text fits its content rect, inspect an offscreen screenshot with the longest form, and perform a Cocoa exercise that reads the full `FFT vs Time` label and scrolls every pane to its last control while the footer remains visible.
