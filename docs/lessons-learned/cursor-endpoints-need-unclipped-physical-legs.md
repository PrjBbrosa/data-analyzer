---
id: cursor-endpoints-need-unclipped-physical-legs
status: active
owners: [codex]
keywords: [cursor, custom-x, interpolation, clipping, delta]
paths: [mf4_analyzer/ui/pg_canvas/cursor.py]
checks: [git diff --check]
tests: [tests/ui/test_custom_x_cursor_contract.py]
---

# Cursor Endpoints Need Unclipped Physical Legs

Trigger: Changing Custom-X dual-cursor statistics or endpoint differences.

Past failure: Sampling A/B from range-clipped paths removed interpolation
neighbors. Off-grid endpoints displayed no delta despite valid physical legs;
full-path unit tests alone missed the UI integration defect.

Rule: Clip samples for Min/Max/Avg. Sample endpoints on the corresponding
original physical leg, matched by acquisition indices rather than direction
alone. Preserve ambiguity and out-of-path rejection; never join cycles or gaps.

Verification: The canvas-level regression must cover off-grid endpoints,
reversed A/B, out-of-path endpoints, and unchanged in-range extrema.
