---
id: cursor-close-chrome-needs-sibling-polish
status: active
owners: [codex]
keywords: [cursor, Cocoa, QPushButton, polish, geometry]
paths: [mf4_analyzer/ui/chart_stack/cursor_pill.py]
checks: [git diff --check]
tests: [tests/ui/test_cursor_table_geometry.py, tests/ui/test_cursor_pill_formatting.py]
---

# Cursor Close Chrome Needs Sibling Polish

Trigger: Changing cursor title actions, their role transitions, or button styling.

Past failure: The close button had the historical rounded-square QSS but still painted as a circular button on Cocoa. Only the adjacent P button was explicitly polished. Text-only style inspection missed the actual appearance and the effective size change after polishing.

Rule: Align action centers, not top edges, and reserve control width only on the header block. Do not widen the entire panel by adding the control width to every time fragment. Resolve all affected title-action styles before measuring and packing. Check the rendered close-button pixels, not just its stylesheet. Keep title fragment width independent of the numeric table width so removing whitespace cannot replace valid time values with an out-of-space message.

Verification: Run test_pinned_close_uses_rounded_square_fill and test_compact_pinned_dual_keeps_time_fragments in tests/ui/test_cursor_table_geometry.py, test_pinned_header_centers_actions_and_releases_body_width, plus role-change geometry in tests/ui/test_cursor_pill_formatting.py. Inspect a Cocoa render with production QSS; offscreen evidence is separate.
