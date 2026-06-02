# Subplot Vertical Spacing Design

Date: 2026-06-02
Branch: `plan/pyqtgraph-timedomain-migration`
Area: `mf4_analyzer/ui/pg_canvases.py` — `TimeDomainCanvasPG` subplot mode.
Supersedes the two-row special case in
`docs/lessons-learned/codex-pg-timedomain-frame-and-spacing.md`.

## Problem

Plotting **two** channels in subplot mode leaves a large blank band between
the top and bottom plots. Reported by the user; reproduced.

Root cause: `_unify_subplot_bottom_axis_heights` has two strategies keyed on
row count:

- **≥ 3 rows** — collapse the hidden upper rows' bottom-axis reserve to ~1 px,
  let only the final (visible) row reserve the X tick/label height. Tight, no
  gap.
- **exactly 2 rows** — the opposite: set *both* rows' bottom axes to the
  **max** measured height. The bottom row legitimately needs ~40 px for its
  ticks + "Time (s)" label; the top row's bottom axis is hidden
  (`showValues=False`, empty label) yet is forced to the same ~40 px. That
  reserved-but-empty 40 px **is** the blank band the user sees.

The 2-row branch was written to make the two ViewBoxes pixel-equal in height
(`test_two_subplots_have_equal_viewbox_heights`). It buys equal heights by
*adding* empty reserve to the top row — directly causing the gap.

## Why naive collapse alone is not enough

In a pyqtgraph `GraphicsLayout`, each `PlotItem` is one grid cell and reserves
its axis space *inside* that cell. Collapsing the hidden upper axes removes the
gap, but with the default (stretch 0) row distribution `QGraphicsGridLayout`
then hands the collapsed rows **extra cell height** — measured, a two-row plot
came out 318/236 px cells (top viewbox 316 vs bottom 196), so the bottom plot
looked cramped. Collapse fixes the gap but unbalances the heights.

The balance is recoverable *without* reading live geometry: give every row an
**equal constant preferred height plus equal stretch**. Equal preferred values
distribute proportionally, so the rows stay equal at any canvas size (verified
at 560 px and 800 px). Measured result: 2-row 274/237, 3-row 182/182/144, 5-row
107×4/70 — every viewbox equal except the last, which is shorter only by its
reserved X-axis band, and a ≤ 5 px inter-plot gap throughout.

## Decision

**Collapse hidden upper bottom-axes *and* balance the rows, uniformly for all
row counts (≥ 2).** Result: flush adjacency (no gap) with near-equal heights —
the stacked-shared-X idiom (matplotlib `sharex=True, hspace=0`); the bottom row
owns the time axis and is shorter only by that axis band.

Concretely: drop the 2-row special case and the fragile measure-the-max
round-trip. For **two or more** rows, collapse every hidden upper bottom-axis to
~1 px, auto-size the final row's, then set equal constant preferred height +
stretch on every grid row.

Rejected alternative: compensating row-stretch computed from the *live* axis
height (read `axis.height()` after `activate()`, add it to the bottom row's
stretch). That is the timing-sensitive round-trip the old 2-row branch used;
equal *constant* preferred heights achieve the same balance without ever reading
back geometry.

## Change

`_unify_subplot_bottom_axis_heights` becomes a single path:

1. Gather the per-row bottom `AxisItem`s (subplot mode only).
2. If fewer than two, return.
3. Set every axis except the last to `setHeight(1.0)`.
4. Set the last to `setHeight(None)` (auto — keeps ticks + label).
5. For every grid row, `setRowStretchFactor(row, 1)` and
   `setRowPreferredHeight(row, 100.0)` (constant; equal values balance the
   rows proportionally).
6. `layout.invalidate(); layout.activate()` once.

No max measurement, no row-count branch.

## Tests

- Replace `test_two_subplots_have_equal_viewbox_heights` with
  `test_two_subplots_do_not_reserve_hidden_top_axis_height`: in two-channel
  subplot mode the hidden top row's bottom axis is `≤ 4 px` while the bottom
  row's is `> 20 px` (the no-gap contract, mirroring the dense-row test).
- Keep `test_dense_subplots_do_not_reserve_hidden_xaxis_label_height` (5 rows)
  and `test_plot_items_draw_full_neutral_viewbox_frame` green — the unified
  path must not regress them.

## Acceptance Criteria

- Two-channel subplot mode shows the plots flush (no large mid-gap); the bottom
  plot carries the only X tick/label band.
- Three/four/five-channel subplot modes keep zero gap and now also balance row
  heights (every upper ViewBox equal; only the last is shorter).
- The bottom subplot is shorter than the rows above it only by ~its reserved
  X-axis band; this is intended.
- Balance holds across canvas resizes (constant equal preferred heights).
- The full neutral ViewBox frame still wraps every subplot.

## Lesson update

`codex-pg-timedomain-frame-and-spacing.md`: change the rule to "for two or more
rows, collapse hidden upper bottom-axis heights; only the final row reserves X
tick/label space" (drop the two-row equal-reserve carve-out), note the 2-row
mid-gap as the past failure, and fix its `tests:`/`checks:` commands to the
Windows venv entrypoint (`.\.venv\Scripts\python.exe`) per
`codex-hooks-use-windows-python-entrypoint.md`.
