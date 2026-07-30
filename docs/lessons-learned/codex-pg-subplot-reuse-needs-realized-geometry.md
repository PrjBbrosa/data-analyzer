---
id: codex-pg-subplot-reuse-needs-realized-geometry
status: active
owners: [codex]
keywords: [pyqtgraph, subplot, view-switch, selection-delta, object-reuse, sceneBoundingRect, layout, ViewState, cursor]
paths: [mf4_analyzer/ui/pg_canvas/canvas.py, mf4_analyzer/ui/pg_canvas/cursor.py, mf4_analyzer/ui/main_window/window.py, mf4_analyzer/ui/view_bridge.py, tests/ui/test_pg_timedomain_canvas.py, tests/ui/test_view_switch_integration.py, tests/ui/test_main_window_smoke.py]
checks: [rg -n "subplot-empty-selection-reset|subplot-realized-geometry-invalid|sceneBoundingRect|_cursor_item_owners" mf4_analyzer/ui tests/ui]
tests: [tests/ui/test_pg_timedomain_canvas.py, tests/ui/test_view_switch_integration.py, tests/ui/test_main_window_smoke.py, tests/ui/test_timedomain_hotpath_perf.py]
---

# Codex PG Subplot Reuse Needs Realized Geometry

Trigger: Changing or reviewing time-domain subplot selection-delta reuse,
especially hide-all/restore, empty View switches, or retained PlotItem rows.

Past failure: Tests proved object identity, visibility, and a positive
`maximumHeight()`, yet a shown canvas still restored every ViewBox at only
`8.5 x 0.5` pixels after all rows had first been constrained to zero. The
outer GraphicsLayout had collapsed and no resize occurred to realize it again.
The same owner round trip also overwrote the saved X range with the cleared
canvas fallback `(0, 1)`. A later cursor fix exposed a related identity trap:
matching cursor-item counts did not prove that the items belonged to the
current ViewBoxes, and removing through `parentItem()` left scene ghosts.

Rule: Do not treat widget constraints or PlotItem visibility as proof that a
reused subplot layout recovered. Exercise the zero-active-row transition on a
shown canvas, process Qt layout events, and verify realized scene geometry; a
structural fallback is safer whenever measured geometry contradicts the
recovery contract. Keep "measured and collapsed" separate from "not measurable
at all": a hidden canvas or zero-size viewport must skip the check, because
failing closed there routes to a rebuild that is equally unrealized and
permanently downgrades the warm path.

At a canonical-empty boundary, capture semantic ranges before the owner
replot and never record fallback ranges from a canvas with no live primary X
owner. For non-empty warm deltas, reconcile cursor graphics by exact ordered
ViewBox identity—not count—and remove stale items through their recorded
ViewBox owner.

Verification: Reproduce populated subplot -> zero active rows -> restore rows
through both `try_apply_selection_delta()` and a MainWindow View switch. Assert
each active `view_box.sceneBoundingRect()` has meaningful width and height
relative to the canvas before accepting the change; also verify a one-pixel
window resize is not required to recover the plot. Assert X/Y/cursor state
after the owner rebuild, and cover an equal-count `[a, b] -> [b, c]` delta so
old cursor items are detached from both their ViewBox and scene.
