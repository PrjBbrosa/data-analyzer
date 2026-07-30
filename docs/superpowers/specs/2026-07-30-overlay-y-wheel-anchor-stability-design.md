# Overlay Y Wheel Anchor Stability Design

**Date:** 2026-07-30

**Status:** Approved; revised by the tick-alignment follow-up

**Superseding follow-up:**
`docs/superpowers/plans/2026-07-30-overlay-y-tick-alignment-followup.md`
supersedes the original exact-anchor/free-phase decision in this document and the
projection-only strategy in
`docs/superpowers/plans/2026-07-30-overlay-y-wheel-label-and-repin-fixes.md`.

## 1. Context

Overlay `Shift+wheel` uses a discrete adjacent nice step for each notch and the
mouse's normalized Y position as the intended zoom anchor. The first implementation
floored the new lower bound. That made every phase error one-sided, so equal in/out
notches could translate a channel vertically even when its span returned.

A later free-phase implementation removed that drift and preserved the cursor value
exactly, but it exposed a different product defect: tick values such as `0.0283967`
were technically evenly spaced while no longer being readable nice-number values.
Trying to hide that phase in label formatting then caused significant-digit loss
(`100` displayed as `1`) and could widen every overlay gutter.

The final contract therefore treats span selection, range phase, label truthfulness,
and event routing as separate invariants. This is a range/tick projection issue, not a
duplicate wheel-event issue, and the nice-step ladder itself is not changed.

## 2. Decision

Keep cursor-targeted Y zoom and `_adjacent_nice_step()` for the per-division zoom
level. Quantize the resulting lower bound to the nearest multiple of that step:

```python
anchor = lo + frac * span
framed_span = n * next_per_div
raw_bottom = anchor - frac * framed_span
bottom = round(raw_bottom / next_per_div) * next_per_div
top = bottom + framed_span
ticks = [bottom + k * next_per_div for k in range(n + 1)]
```

Nearest rounding is deliberately used instead of `floor()`. It makes the phase error
unbiased and bounds movement of the data value under the cursor to half of the new
division. Exact cursor anchoring and globally aligned tick values cannot both hold for
an arbitrary cursor fraction; aligned, readable tick values are the product priority.

The formatter receives `per_div` and chooses the shortest truthful representation from
fixed and adaptive scientific candidates. It never changes the tick value or range.

## 3. Behavioral Contract

### R1. Gesture routing

- `Ctrl+wheel` changes X only.
- `Shift+wheel` changes Y only.
- Plain wheel pans Y by one displayed division.
- Zero delta is not consumed.
- In TimeDomain overlay mode, plot-area Shift zoom affects every channel; a channel
  gutter gesture retains its existing single-channel scope.
- In `PgLineCanvas` time preview, Shift zoom from the main plot, left axis, or any aux
  gutter updates every time-preview ViewBox using the same normalized cursor fraction.
  Each ViewBox still selects its own adjacent nice step, so span ratios may differ.
- The curveless TimeDomain X-master remains locked to its overlay Y range.

### R2. Cursor anchoring is bounded, not exact

For each affected channel:

```text
anchor_before = old_lo + frac * old_span
anchor_after  = new_lo + frac * new_span
abs(anchor_after - anchor_before) <= 0.5 * next_per_div + numeric_epsilon
```

The same delivered fraction is applied independently to channels with different units
and ranges. If event geometry is unavailable, `frac = 0.5` remains the fallback.

Tests must not assert exact per-notch anchoring. They must keep exact round-trip checks
from a globally aligned nice-step frame, where equal in/out transitions remain
reversible within floating-point tolerance.

### R3. Zoom is monotonic and reversible from aligned frames

- Positive Shift delta selects the immediately smaller nice step.
- Negative Shift delta selects the immediately larger nice step.
- Supported Y tick densities remain integers from 3 through 20.
- Every notch strictly changes the span in the requested direction.
- Four in and four out notches at a fixed position restore ranges that started on an
  aligned nice-step frame, for representative densities 3, 10, and 20.
- An arbitrary external range may normalize both step and phase on its first notch.
  Restoring that raw range would require hidden zoom-origin state and is out of scope.
- No one-sided drift may accumulate. Nearest rounding may cause bounded interleaved
  phase movement, but never the old `floor()` bias.

### R4. Tick values and labels are both part of the contract

- Every affected axis receives exactly `n + 1` major ticks.
- Tick 0 equals the final lower bound and tick `n` equals the upper bound.
- Adjacent tick values differ by `next_per_div` within numerical tolerance.
- Every tick value is an integer multiple of `next_per_div` within relative tolerance.
- `_nice_per_div`, `_adjacent_nice_step`, and `_NICE_STEP_MANTISSAS` remain unchanged.
- `_repin_overlay_channel_ticks()` is a no-op for an already aligned nice-step range;
  arbitrary external ranges and incompatible density changes may still use
  `_frame_to_nice()`.

For a positive finite `per_div`, label formatting has a flat contract:

1. `float(label)` differs from the tick by at most 1% of a division plus numerical
   epsilon.
2. Labels on one axis are distinct.
3. Parsed adjacent-label gaps differ from `per_div` by at most 2% of a division.
4. A six-character cap applies only to the named ordinary fixtures: the four-channel
   `±2.5` overlay and the `0..1000` / `80..100` engineering overlay.

Label length is otherwise unbounded until axis-offset notation exists. A value/step
interval cannot carry a truthful global character cap: `12345.1` at step `0.1` needs
seven characters and `99999.0001` at step `1e-4` needs ten.

Fixed notation uses one guard decimal beyond the step-derived minimum. Scientific
precision derives from the value-to-step resolution:

```python
sig = max(2, ceil(log10(abs(value)) - log10(0.01 * per_div)) + 1)
```

Fixed and adaptive-scientific candidates that violate the 1% bound are discarded; the
shortest remaining candidate wins, with fixed notation winning ties. Invalid/non-finite
inputs, zero, near-zero residues, and the single-argument formatter retain their prior
handling.

### R5. Events are consumed even after a per-axis refresh failure

- A handled modifier-wheel event is accepted once and never falls through to native
  pyqtgraph zoom.
- `PgLineCanvas` isolates each time-preview axis update with its own exception boundary.
  One failure does not abort later axes, and the handler still returns `True`.
- This is not atomic. Earlier ranges, and the failing axis's range if its label refresh
  fails afterward, may already have changed. Snapshot-and-restore is a separate design.
- Existing visible-range, redraw, idle-quality, and layout notification routing remains.

## 4. Scope

Production:

- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`: aligned Shift-wheel phase.
- `mf4_analyzer/ui_kit/ticks_math.py`: truthful shortest-candidate labels.
- `mf4_analyzer/ui/pg_canvas/line_canvas.py`: aligned time-preview phase, aux-gutter
  dispatch, and per-axis failure isolation.

Tests:

- `tests/ui/test_overlay_grid_ticks.py`
- `tests/ui/test_pg_line_canvas.py`

The shared `_frame_to_nice()` implementation is explicitly outside this follow-up.

## 5. Non-goals

- No change to modifier meanings, delta polarity, raw pixel-wheel routing, or the
  nice-step ladder/selectors.
- No stored per-channel zoom origin to combine exact anchors with aligned ticks.
- No axis-offset notation for arbitrary high-offset channels.
- No all-or-nothing rollback in the `PgLineCanvas` multi-axis loop.
- No drive-by `_frame_to_nice()` floor-tolerance change.
- No retired overlay drag/snap restoration and no heatmap Y-zoom change.

## 6. Test Strategy

- RED evidence includes the off-grid `0.0283967` phase, significant-zero labels, fixed
  scientific collisions, aux-gutter delivery, and an axis refresh exception.
- Cursor fractions: 0.15, 0.50, and 0.85; densities: 3, 10, and 20 for round trips and
  every integer 3 through 20 for strict monotonicity.
- The label sweep covers the full nice ladder `1e-4..1e2`, seven phase offsets, ordinary,
  engineering, `1e5`, and `1e6` magnitudes. It asserts value error, uniqueness, and
  parsed gaps rather than length alone.
- Real viewport events verify accepted delivery and prevent native fallback.
- Repin idempotence, plot/gutter width, X lock, and existing pan/zoom routes remain in
  regression coverage.

## 7. Acceptance Criteria

1. Significant integer zeros survive (`100`, `800`, `2000`, `101330`).
2. Every Shift-wheel Y tick is aligned to its division step.
3. Per-notch cursor movement is no greater than half of the new division.
4. Nice-frame 4-in/4-out ranges restore and spans remain strictly monotonic.
5. Universal labels satisfy 1% truthfulness, uniqueness, and 2% parsed-gap bounds.
6. Only the named ordinary fixtures carry the six-character cap.
7. Main/left/aux time-preview wheel routes synchronize all ViewBoxes.
8. A per-axis exception is consumed without native zoom and later axes still update.
9. Nice-step selectors are byte-identical and `_frame_to_nice()` is unchanged.
10. Focused UI modules pass and `git diff --check` is clean.

## 8. Regression Risks And Guards

- **Anchor regression:** bounded at several fractions and verified through a real event.
- **Step/phase regression:** integer-multiple tick assertions and exact aligned-frame
  round trips.
- **Truth hidden by compact labels:** universal parsed-value and parsed-gap assertions.
- **Gutter route bypass:** a real aux-axis viewport event must enter the shared handler.
- **Double zoom after partial failure:** expected receiving range is asserted exactly
  after a synthetic `setTicks()` exception.
- **Shared-helper scope creep:** byte comparison/inspection of nice-step selectors and an
  explicit no-change check for `_frame_to_nice()`.
