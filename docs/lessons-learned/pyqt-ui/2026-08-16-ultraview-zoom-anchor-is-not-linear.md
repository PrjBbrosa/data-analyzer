---
id: pyqt-ui/2026-08-16-ultraview-zoom-anchor-is-not-linear
status: active
owners: [claude]
keywords: [ultraview, zoom, anchor, jitter, rect_to_pixels, scale_grid_metrics, exact_pitch, elastic, workspace_extent, quantization]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/free_grid.py
  - mf4_analyzer/ui/chart_stack/ultraview/viewport.py
  - mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - tests/ui/test_ultraview_viewport.py
checks:
  - rg -n "exact_pitch|exact_padding|exact_cell|zoom_anchor_at|point_for_zoom_anchor" mf4_analyzer/ui/chart_stack/ultraview/free_grid.py mf4_analyzer/ui/chart_stack/ultraview/widgets.py mf4_analyzer/ui/chart_stack/ultraview/page.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py::test_wheel_zoom_anchor_holds_after_the_elastic_origin_expands tests/ui/test_ultraview_viewport.py::test_zoomed_pixel_map_error_does_not_grow_with_the_cell_index tests/ui/test_ultraview_viewport.py::test_ctrl_wheel_keeps_the_logical_point_under_the_cursor tests/ui/test_ultraview_viewport.py::test_extent_rebase_keeps_the_view_still "tests/ui/test_ultraview_viewport.py::test_zoom_at_keeps_board_point_under_cursor_in_every_corner" -q
---

# UltraView Zoom Anchors On Canvas Metrics, Not `logical * zoom`

Trigger: Changing UltraView zoom anchoring, the free-grid grid↔pixel map
(`rect_to_pixels` / `pixel_to_origin` / `pixels_to_grid_delta`),
`scale_grid_metrics`, or anything that moves the signed elastic origin.

Past failure: `scale_grid_metrics` rounds each metric, and `rect_to_pixels`
then multiplied that **rounded** pitch by the cell index. The rounding error
is therefore proportional to the index. While the free grid was a fixed
12-column frame the index was 0..11 and the error stayed under 1 px, so
nobody noticed. The elastic canvas made the origin signed and only-growing
(`expand_extent` is a high-water mark, floor `SAFETY_COLUMN_MIN = -48`), which
pushed the effective index past 40 and blew the error up to **43 px** in the
pure map and **76 px worst / 26 px mean** of real cursor-anchor drift per
wheel notch, sign flipping notch to notch — the user-visible "缩放时画面来回
抖". It got worse the longer a session ran, because the origin only ever
expanded.

Two things hid it. First, `page._zoom_at` predicted the post-zoom position
as `logical * zoom`, which is the *linear* model — true for template boards,
false for the free grid's rounded stair. Second, every anchor guardrail was
written in that same linear model (`_logical_under_cursor` = `scroll / zoom`),
so it confirmed the wrong number against the wrong number and stayed green
while cards visibly jumped. Refresh-timing fixes (`_zoom_transaction`,
`follow_view`, deferring the settle — see
[UltraView Zoom Settles After Scroll](2026-08-16-ultraview-zoom-settle-and-fit-fill.md))
removed one extra rebase per tick but could not touch this, because the defect
is in the *value* of the origin, not in *when* it is refreshed.

Rule:
- Every grid↔pixel mapping goes through `GridMetrics.exact_padding()` /
  `exact_pitch()` / `exact_cell()` — the unrounded 1× geometry times `scale` —
  and rounds only the final edges. Never multiply a rounded pitch by a cell
  index. 1× metrics leave `scale=1.0, base=None`, where every mapping reduces
  to the original integer arithmetic, so the export/compositor path is
  unchanged (batch⇄GUI parity still holds).
- Interactive zoom must not extrapolate. `page._zoom_at` asks the active
  canvas for `zoom_anchor_at()` / `point_for_zoom_anchor()` and re-projects
  through the metrics that were actually laid out. `FreeGridBoard` anchors in
  absolute signed workspace cells so the anchor survives an extent rebase
  between the two calls; `BoardGrid` uses `linear_zoom_anchor` /
  `linear_zoom_point`, which keeps `viewport.zoom_at` the single source of the
  linear math.
- The same rule covers the *scroll compensation* when an extent rebase moves
  the widget-local plane (`_refresh_workspace_extent`). Round the two origins
  and subtract; never `rounded pitch * cell delta`. That third site was missed
  on the first pass and left the view sliding up to 3 px on every halo growth.
- An anchor guardrail must measure **real widget geometry** (where the card
  actually sits in the scroll viewport), not `scroll / zoom`. Multi-notch, both
  directions, and with the elastic origin already expanded — a single notch at
  the default origin lands inside the old error and proves nothing. Drive the
  extent through the real wheel+settle path: parking `_workspace_extent`
  directly leaves the scroll bars clamped against the old maximum and the test
  measures its own setup instead of the defect.

Verification: `test_wheel_zoom_anchor_holds_after_the_elastic_origin_expands`,
`test_zoomed_pixel_map_error_does_not_grow_with_the_cell_index`,
`test_ctrl_wheel_keeps_the_logical_point_under_the_cursor`,
`test_zoom_at_keeps_board_point_under_cursor_in_every_corner`,
`test_extent_rebase_keeps_the_view_still`. All 13 anchor cases fail without the
map fix; the rebase case shifts 4 px without the compensation fix. Real-window
(`QT_QPA_PLATFORM=cocoa`) drift over a 24-notch in/out sweep: **76.4 px worst /
26.1 px mean → 1.6 px / 0.6 px**.
