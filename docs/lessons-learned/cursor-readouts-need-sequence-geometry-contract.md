---
id: cursor-readouts-need-sequence-geometry-contract
status: active
owners: [codex]
keywords: [cursor, geometry, sequence, pinned, tether, QTextDocument]
paths:
  - mf4_analyzer/ui/chart_stack/cursor_pill.py
  - mf4_analyzer/ui/chart_stack/pinning/presentation.py
checks: [git diff --check]
tests:
  - tests/ui/test_cursor_layout_stability.py
  - tests/ui/test_cursor_content_stability.py
  - tests/ui/test_cursor_placement_stability.py
---

# Cursor Readouts Need Sequence Geometry Contracts

Trigger: Changing cursor title wrapping, value-driven card size, visible-row fitting, pin placement, or tether publication.

Past failure: 774 existing cursor tests passed while alternating 31.5810s and 31.5925s repeatedly changed a P3 card from 123×114 to 123×131. Only table numbers had a retained width envelope; proportional title digits repacked on every sample. Short panes also changed visible-row counts. Cached pin occupancy kept the old size after growth, and intermediate resize/move events published unsettled tethers.

Rule: Test sequences as well as single frames. Stable structure retains bounded title/body/frame space across value updates; true mode/channel/field/font/host changes rebuild it, and clear releases it. Keep real values, branches and diagnostics fresh. Use actual painted contentsRect, including control margins, rather than the outer QLabel rectangle. Every cross-mode fixture must contain the intended real rows. Occupancy uses the current card size, and content-update transactions publish tethers after final placement.

Verification: Alternate the reported coordinates, signs/exponents, branch and diagnostic changes, and A=B. Assert card geometry, visible rows, painted glyph bounds, stale-text removal, structural reset, and final tether/obstacle rectangles. Run the focused tests above and inspect Cocoa production-widget plus actual ChartStack signal-chain images; identify Windows and original-project acceptance separately.
