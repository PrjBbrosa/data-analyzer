# Pyqtgraph Wheel Routing And Interaction Budget Design

**Date:** 2026-07-29

**Status:** Approved for implementation planning

## 1. Context

The TimeDomain canvas now preserves a raw Qt wheel delta before pyqtgraph
converts the event into a scene-level wheel event. That repair is local to
`TimeDomainCanvasPG`; `PgLineCanvas` and `PgHeatmapCanvas` still host their
`_ModifierWheelViewBox` instances in a plain `GraphicsLayoutWidget`. On
precision-touchpad events that carry `pixelDelta()` but no `angleDelta()`, the
scene event therefore reaches the shared dispatch with a zero delta. Ctrl/Shift
zoom does not change either range, while conventional mouse-wheel events work.

Two adjacent TimeDomain performance contracts also need correction:

1. the 100 ms coarse-refresh scheduler calculates a remaining delay before it
   starts `QTimer`, but does not recheck the monotonic interval when the timer
   fires; Qt can wake early enough to exceed the declared 10 Hz hard ceiling;
2. the native-AA decision is coupled to the post-envelope displayed-point
   count. A wide, two-channel dense overlay can land just below the 7,000-point
   boundary after axis gutters reduce the plot width, allowing native AA even
   though the raw overlay is under the high-density performance policy.

## 2. Goals

1. Make modifier wheel zoom symmetric for positive and negative precision-
   touchpad deltas across TimeDomain, FFT, FFT time preview, FFT-vs-Time, Order,
   and the optional heatmap slice plot.
2. Preserve conventional angle-delta mouse-wheel behavior and unmodified
   pyqtgraph wheel behavior.
3. Enforce a real minimum interval of 100 ms between coarse TimeDomain data
   refreshes, including when Qt timers wake early.
4. Keep native AA disabled for a visible multi-channel high-density overlay
   using a policy signal that is independent of envelope output rounding and
   axis-gutter geometry.
5. Retain the accepted HDF interaction, dense-discrete raster, selection-delta,
   export, and visual-fidelity contracts.

## 3. Non-goals

- Do not redesign pyqtgraph's event system or replace `_ModifierWheelViewBox`.
- Do not change zoom factors, modifier meanings, cursor anchoring, or plain-
  wheel two-axis behavior.
- Do not modify the separate markup editor wheel handler in this change.
- Do not lower the global 7,000-point AA threshold as a numerical workaround.
- Do not increase envelope bucket counts merely to force the displayed metric
  above the AA boundary.
- Do not restructure the large TimeDomain canvas or merge all interaction
  policies into a new controller.

## 4. Design

### 4.1 Shared raw wheel-delta bridge

`_WheelDeltaGraphicsLayoutWidget` remains the single Qt viewport boundary that
reads a wheel event. It selects `angleDelta()` first and falls back to
`pixelDelta()` only when the angle delta is zero. The selected signed delta is
stored on the owner canvas only while `super().wheelEvent()` routes that same
event through the scene; a `finally` block clears it so one wheel event cannot
leak into the next.

`TimeDomainCanvasPG`, `PgLineCanvas`, and `PgHeatmapCanvas` must all construct
this widget with `owner_canvas=self`. Every `_ModifierWheelViewBox` continues to
read the legacy scene delta first and consults the owner-scoped raw value only
when the scene delta is zero. No canvas implements its own duplicate Qt wheel
parser.

The existing canvas handlers remain responsible for axis semantics:

- Ctrl + wheel changes X only;
- Shift + wheel changes Y only;
- positive delta zooms in and negative delta zooms out;
- a zero delta is not consumed;
- a wheel without Ctrl or Shift falls back to native pyqtgraph handling.

### 4.2 Timeout-time enforcement of the 10 Hz ceiling

Scheduling a `QTimer` is not evidence that the minimum interval has elapsed.
The coarse timeout path must read `monotonic()` immediately before refreshing.
If a previous coarse refresh exists and fewer than `_COARSE_REFRESH_MS` have
elapsed, it must restart the one-shot timer for the remaining interval and
return without calling `_refresh_visible_data()`.

The remaining delay must be rounded upward to whole milliseconds and clamped to
at least 1 ms. This avoids both an early callback and a zero-delay busy loop.
Only a callback that passes the elapsed-time guard may consume the pending
viewport, call the renderer, update `_last_coarse_refresh_at`, and schedule a
later coarse frame. The existing interaction generation, settle-timer race
avoidance, latest-target coalescing, and release-settle behavior stay intact.

The first coarse frame continues to wait the full 100 ms. A final settled frame
is not counted as a coarse frame.

### 4.3 Explicit high-density overlay AA pressure

Native-AA affordability must distinguish raw render pressure from the number of
points left after envelope generation. The quality layer will expose a separate
overlay-pressure decision based on visible raw channel data:

- the canvas is in overlay mode;
- at least two native curve items are visible;
- at least two corresponding raw channels have a decimation ratio of at least
  `8.0`, calculated as visible raw sample count divided by current plot pixel
  width.

The `8.0` threshold is the existing dense-stack decimation policy already used
by the renderer; it must be shared from one named constant rather than copied as
a new magic number. Identity lookup must use the existing composite channel key
so same-name channels from different sources remain distinct. Hidden or dormant
selection-delta rows must not contribute.

When overlay pressure is active, idle native AA and forced export native AA are
unaffordable regardless of the post-envelope point count. The reader-facing
quality status must report a distinct block reason such as
`overlay-density-pressure`; it must continue reporting the actual displayed
point metric rather than inflating it. Dense-discrete hard gates and ready
raster coverage retain their existing precedence.

Low-density overlays, single visible curves, subplot mode, and ordinary curves
below the shared decimation threshold continue through the existing AA
hysteresis. Envelope bucket sizing is unchanged.

## 5. Failure Handling And State Safety

- If a Qt wheel event cannot provide either delta form, preserve the current
  zero-delta/native fallback behavior.
- Owner-scoped raw wheel state must be cleared even if scene routing raises.
- A stale-generation coarse timer must remain unable to mutate new plot items.
- If raw channel identity or length cannot be resolved for the overlay-pressure
  check, treat that channel as not proven dense; do not fail closed for all
  curves.
- Quality-status calculation must not mutate curve data, visibility, render
  profiles, or view ranges.

## 6. Test Strategy

### 6.1 Wheel routing

Use real `QWheelEvent` delivery to each canvas viewport. Cover pixel-only
positive and negative deltas for both Ctrl and Shift on:

- `PgLineCanvas` amplitude plot and time preview;
- `PgHeatmapCanvas` main plot and optional slice plot;
- the existing TimeDomain overlay path.

Assert that only the intended range changes and that its span decreases for a
positive delta and increases for a negative delta. Retain angle-only viewport
tests to prove conventional mouse-wheel compatibility. Include a sequential
event test proving raw delta state is cleared between events.

### 6.2 Coarse scheduler

Add deterministic tests around an early timeout: patch the canvas module's
monotonic clock, invoke the timeout path before 100 ms, and assert zero renderer
refreshes plus a positive reschedule. Advance to the boundary and assert exactly
one refresh. Keep an integration test that records real coarse refresh
timestamps during a moving drag and asserts every adjacent interval is at least
100 ms subject only to a documented 2 ms clock/timer observation tolerance.

Run the existing buffer, settled refresh, generation replacement, resize, and
selection-delta tests unchanged.

### 6.3 AA policy

Test at least these states:

- two visible 500,000-sample overlay curves at the existing 1920x600 fixture:
  native AA remains off and status reports overlay density pressure even when
  the displayed metric is below 7,000;
- one of those curves hidden: the pressure block clears;
- two low-density overlay curves: existing AA hysteresis remains eligible;
- the same dense curves in subplot mode: the new overlay-specific gate does not
  engage;
- same-name dense channels from different sources are counted independently by
  composite identity;
- export affordability follows the same pressure decision without changing
  envelope data.

## 7. Acceptance Criteria

1. All pixel-only Ctrl/Shift viewport tests pass in both directions across the
   specified canvases and subplots.
2. Existing angle-delta wheel tests pass without changed zoom semantics.
3. Repeated coarse-refresh integration runs do not exceed 10 Hz, and the
   deterministic early-timeout test proves that no early `setData()` occurs.
4. The dense two-channel overlay cannot re-enable native AA solely because axis
   gutters reduce the displayed metric below 7,000.
5. Low-density and single-curve AA behavior remains eligible under the existing
   hysteresis policy.
6. `tests/ui/test_pg_line_canvas.py`, `tests/ui/test_pg_heatmap_canvas.py`, the
   relevant TimeDomain scheduler/quality tests, and
   `tests/ui/test_timedomain_hotpath_perf.py` pass in the repository virtual
   environment with isolated Qt settings and writable temporary directories.
7. `git diff --check` reports no whitespace errors.

## 8. Agent Execution Boundaries

Implementation will use three fresh agent tasks with TDD and review gates:

1. wheel routing owns `viewbox.py`, `line_canvas.py`, `heatmap_canvas.py`, and
   their focused wheel tests;
2. coarse scheduling owns the scheduler section of `canvas.py` and focused
   TimeDomain scheduler tests;
3. AA pressure owns `renderer.py`, `quality.py`, and focused quality tests.

Tasks that touch the shared TimeDomain test file execute sequentially. The root
agent reviews each diff before the next overlapping task, then runs the combined
regression and lessons completion gate. Agents must preserve unrelated dirty
worktree changes and must not commit or revert files outside their assigned
scope.
