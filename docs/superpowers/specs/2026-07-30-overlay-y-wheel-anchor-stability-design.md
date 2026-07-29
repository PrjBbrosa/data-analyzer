# Overlay Y Wheel Anchor Stability Design

**Date:** 2026-07-30

**Status:** Approved by the user for implementation

## 1. Context

Overlay-mode `Shift+wheel` already routes to Y-only zoom and uses the mouse's
fractional viewport Y position as its intended anchor. Commit `607c630` fixed a
separate monotonicity defect by selecting the adjacent nice per-division step,
but its final range construction snaps the lower bound downward:

```python
new_lo = anchor - frac * framed_span
bottom = math.floor(new_lo / next_per_div) * next_per_div
```

That `floor()` changes the anchor after every notch. The error is one-sided,
so zooming in and back out near the top or bottom of the canvas accumulates a
vertical translation. The Y span can return to its original size while the
range itself has moved, which makes channels appear to pan during zoom and can
eventually move them outside the useful canvas region.

This is not a duplicate wheel-event problem: the handled scene event is
accepted. It is a viewport-range quantization problem inside
`OverlayAxisManager._handle_wheel_dispatch()`.

## 2. Decision

Keep cursor-anchored Y zoom. It is the established interaction in pyqtgraph and
in scientific/image viewers, and it lets the user target a feature without a
separate pan gesture.

Keep `_adjacent_nice_step()` as the discrete zoom-level selector so every
notch remains strictly monotonic and the shared overlay graticule keeps exactly
`n` equal divisions.

Remove phase snapping from the Shift-wheel viewport transform. The final range
is calculated directly from the old cursor anchor and the new span:

```python
anchor = lo + frac * span
framed_span = n * next_per_div
bottom = anchor - frac * framed_span
top = bottom + framed_span
ticks = [bottom + k * next_per_div for k in range(n + 1)]
```

The nice value controls the interval between ticks, not an absolute global
origin. Tick generation is a projection of the final viewport and must never
round, floor, ceil, or otherwise rewrite `bottom` or `top`.

## 3. Behavioral Contract

### R1. Gesture routing remains unchanged

- `Ctrl+wheel` changes X only.
- `Shift+wheel` changes Y only.
- Plain wheel pans Y by one displayed division.
- Zero delta is not consumed.
- The plot-area Shift gesture acts on every overlay channel.
- A Shift gesture over one Y-axis gutter (`axis == 1`) acts only on that
  gutter's channel.
- The curveless X-master remains locked to its overlay Y range.

### R2. Cursor anchoring is exact within floating-point tolerance

For each affected channel and every valid `frac` in `[0.0, 1.0]`:

```text
anchor_before = old_lo + frac * old_span
anchor_after  = new_lo + frac * new_span
anchor_after ~= anchor_before
```

The same normalized cursor fraction is applied independently to every overlay
channel, including channels with different units and Y ranges.

If scene geometry or the event position is unavailable, the existing fallback
`frac = 0.5` remains in force.

### R3. Zoom is monotonic and reversible

- Positive Shift-wheel delta selects the immediately smaller nice step.
- Negative Shift-wheel delta selects the immediately larger nice step.
- Supported Y tick densities remain integers from `3` through `20`.
- At a fixed cursor position, an equal number of zoom-in and zoom-out notches
  returns every affected channel to its original Y range within numerical
  tolerance.
- No one-sided drift may accumulate near the top, middle, or bottom of the
  plot.

### R4. Ticks do not own the viewport

- Every affected channel receives exactly `n + 1` major ticks.
- Tick 0 equals the final lower bound and tick `n` equals the final upper
  bound.
- Adjacent ticks differ by `next_per_div` within numerical tolerance.
- Shift-wheel code must not pass its range through `_frame_to_nice()` and must
  not apply `floor()`, `ceil()`, or `round()` to the range phase.
- `_repin_overlay_channel_ticks()`, tick-density changes, initial framing, box
  zoom, and drag-release snapping remain outside this change.

### R5. Event and rendering side effects remain unchanged

- A consumed Shift-wheel event is accepted once and must not fall through to
  native pyqtgraph pan/zoom.
- `visible_range_changed`, redraw scheduling, idle-quality scheduling, and
  dense-raster resuppression/rebuild retain their current routing.
- No channel data, visibility, selection, X envelope, or render-profile state
  is mutated by the range calculation.

## 4. Scope

### Production file

- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
  - Change only the Shift-wheel range construction in
    `OverlayAxisManager._handle_wheel_dispatch()`.

### Test file

- `tests/ui/test_overlay_grid_ticks.py`
  - Add direct dispatch invariants for cursor anchoring and round trips.
  - Add one real `QWheelEvent` round-trip regression away from plot center.
  - Retain the current monotonicity, axis-gutter, X-lock, and plain-pan tests.

## 5. Non-goals

- Do not change modifier meanings, delta polarity, zoom factor policy, or raw
  pixel-wheel routing.
- Do not switch to center-fixed zoom.
- Do not replace adjacent nice steps with continuous `0.85` scaling.
- Do not redesign `_frame_to_nice()` or shared `ui_kit` tick helpers.
- Do not change initial autoscale, box zoom, drag-release snapping, tick-density
  controls, subplot behavior, or non-TimeDomain canvases.
- Do not add a user preference for zoom anchoring.
- Do not refactor `OverlayAxisManager` beyond the lines needed for this fix.

## 6. Test Strategy

### 6.1 RED evidence

Before production edits, tests must demonstrate both current failures:

1. With the cursor near the top or bottom, one Shift-wheel step changes the
   data value held under the cursor.
2. With a fixed off-center cursor, repeated zoom-in notches followed by the
   same number of zoom-out notches leave the Y span restored but the Y range
   translated.

The failure must be behavioral (`get_ylim()`/anchor mismatch), not a source-text
assertion.

### 6.2 Focused coverage

- Cursor fractions: `0.15`, `0.50`, `0.85`.
- Tick densities: representative sparse/default/dense values `3`, `10`, `20`.
- Two overlay channels with deliberately different initial Y ranges.
- At least four zoom-in steps followed by four zoom-out steps.
- One real viewport `QWheelEvent` at an off-center vertical position.
- X-master range unchanged throughout.
- Existing `n=3..20` strict monotonic tests remain green.

### 6.3 Regression coverage

Run the complete overlay grid/tick test file, the TimeDomain real viewport
wheel tests, and the complete TimeDomain canvas test module. Finish with
`git diff --check`.

## 7. Acceptance Criteria

1. The new anchor test fails against `784392f`/`607c630` for the expected
   `floor()`-induced mismatch and passes after the implementation change.
2. At fractions `0.15`, `0.50`, and `0.85`, every affected channel preserves
   the cursor data anchor for every tested notch.
3. Four zoom-in notches followed by four zoom-out notches restore the original
   ranges for tick densities `3`, `10`, and `20`.
4. A real off-center `QWheelEvent` round trip restores the original ranges and
   leaves X unchanged.
5. Existing strict monotonicity tests for all densities `3..20` pass.
6. Existing plain-wheel pan, Ctrl-wheel X zoom, plot-area all-channel scope,
   and axis-gutter single-channel scope pass unchanged.
7. `tests/ui/test_overlay_grid_ticks.py` and
   `tests/ui/test_pg_timedomain_canvas.py` pass in the repository virtual
   environment with `QT_QPA_PLATFORM=offscreen` and a unique writable
   `--basetemp`.
8. `git diff --check` reports no whitespace errors.

## 8. Regression Risks And Guards

- **Monotonicity regression:** guarded by the existing exhaustive `3..20`
  tests; `_adjacent_nice_step()` is not changed.
- **Loss of cursor targeting:** guarded at three vertical fractions and with a
  real Qt event.
- **Tick/grid desynchronization:** guarded by first/last tick and equal-step
  assertions against the final range.
- **Cross-axis mutation:** guarded by unchanged X and axis-gutter scope tests.
- **Event double handling:** guarded by real viewport delivery and the existing
  accepted-event route.
- **Scope creep in fragile plot code:** production ownership is restricted to
  one method in one file; no shared tick helper is modified.

