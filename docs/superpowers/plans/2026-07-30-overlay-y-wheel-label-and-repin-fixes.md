# Overlay Y Wheel — Label Legibility, Repin Idempotence, Cross-Canvas Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `d2c4bda`'s exact cursor anchoring and zero drift, but repair the two
regressions it introduced (unreadable graticule labels that eat the plot area, and a
non-idempotent `_repin_overlay_channel_ticks()`), then close the matching gaps in
`PgLineCanvas` and the wheel-delta bridge.

**Architecture:** The viewport range stays exactly as `d2c4bda` computes it — free
phase, anchored on the delivered cursor fraction. What changes is the *projection*:
tick labels get their precision from the division step instead of a fixed `%g`, and
`_repin_overlay_channel_ticks()` stops re-framing a range that already consists of `n`
equal nice divisions.

**Tech Stack:** Python 3, PyQt5, pyqtgraph, NumPy, pytest, pytest-qt.

## Background — measured evidence

Baseline `784392f` vs current `dec230e`, real `QWheelEvent` at cursor fraction 0.62,
overlay start range `(-2.5, 2.5)`, `n = 10`:

| | `784392f` | `dec230e` |
|---|---|---|
| labels after 1 notch | `-2, -1.6, -1.2, -0.8, …` | `-1.8793, -1.4793, -1.0793, -0.679303, …` |
| longest label, 4 channels | 4 chars | 9–10 chars |
| plot width after 1 notch (900px canvas) | 568.9 px | **308.9 px** |
| plot width after 2 notches | 568.9 px | **256.9 px** |
| `_repin_overlay_channel_ticks()` after 1 notch | idempotent | span `4.0 → 5.0` (**+25 %**), bottom shifts `-0.35` |

`axis.setWidth(None)` (`overlay_axes.py:663`) auto-sizes each Y gutter to its longest
label, so the label growth is what collapses the plot area.

Anchor/drift comparison over 630 parameterized round trips (`n = 3..20`, seven cursor
fractions, five starting steps):

| phase policy | round-trip failures | drift after balanced 200-notch walk | anchor shift per notch |
|---|---|---|---|
| `floor` (`607c630`) | 595 / 630 | 293 divisions | 1.0 division |
| free (`d2c4bda`) | **0 / 630** | **0 divisions** | **0 divisions** |
| `round` (rejected) | 315 / 630 | 19 divisions | 0.5 division |

Free phase is the only policy with zero drift, so the range math is kept. `round`
was evaluated as a "nice labels back" shortcut and **rejected** — it reintroduces drift.

## Global Constraints

- Do NOT change the Shift-wheel range construction in
  `OverlayAxisManager._handle_wheel_dispatch()`. `d2c4bda` is correct on R2/R3.
- Preserve Ctrl+wheel X zoom, plain-wheel Y pan, axis-gutter single-channel scope,
  the X-master `[0, 1]` lock, and the fixed `k/n` grid lines.
- Do not modify the retired selected-channel Y-drag / release-snap path. Its production
  press entry was removed on 2026-07-09; the remaining helpers are reachable only from
  legacy tests and need a separate cleanup decision.
- Ticks must stay a projection of the final viewport: first tick == `bottom`,
  last tick == `top`, `n + 1` ticks, equal steps.
- Use the repository virtual environment, `QT_QPA_PLATFORM=offscreen`, and a unique
  writable pytest `--basetemp`.
- Finish with `git diff --check`.

---

### Task 1: Step-Aware Graticule Tick Labels

**Files:**
- Modify: `mf4_analyzer/ui_kit/ticks_math.py` (`_fmt_tick`)
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py` (the three user-reachable
  `setTicks` consumers: repin, box zoom, and wheel; exclude the two retired snap
  helpers)
- Modify: `tests/ui/test_overlay_grid_ticks.py`

**Interfaces:**
- Produces: `_fmt_tick(value, per_div=None)` — when `per_div` is supplied, use the
  minimum decimal count that still separates adjacent ticks:
  `max(0, ceil(-log10(per_div)))`; strip trailing zeros, and render near-zero
  (`|value| < per_div * 1e-6`) rendered as `0`. Omitting `per_div` keeps today's
  behavior so the Cockpit sparkline caller
  (`acquisition_ui/widgets/live_cards.py:939`) is untouched.

- [x] Add a RED test asserting that after one real off-center Shift-wheel notch on a
      4-channel overlay, no Y tick label exceeds 6 characters and every label on an
      axis is unique. Confirm it fails on `dec230e` (currently 9–10 chars).
- [x] Add a RED test for the pre-existing high-offset defect: ticks
      `100000.74 + k*0.8` must produce five DISTINCT labels
      (today: `100001, 100002, 100002, 100003, 100004`).
- [x] Extend `_fmt_tick` with the optional `per_div` argument. Keep the existing
      `< 1e-9 → "0"` and sci-notation branches reachable when `per_div` is omitted.
- [x] Thread the active `per_div` through every user-reachable `overlay_axes.py`
      `setTicks` call. Leave the two retired snap helpers unchanged per Task 3.
- [x] Add a test asserting the Y gutter width and plot-area width after two notches
      stay within 10 % of the pre-zoom width (guards the plot-area collapse directly,
      not just the label text).
- [x] Keep the six-character cap scoped to the normal-scale real-wheel regression.
      Full absolute labels around `1e5` require eight characters to distinguish `0.8`
      differences; those labels must be distinct but are not subject to the cap.
      Compact high-offset notation is a separate UI design.
- [x] Keep `TestFmtTick`'s existing residue cases green.

### Task 2: Make `_repin_overlay_channel_ticks()` Idempotent

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py:770-795`
- Modify: `tests/ui/test_overlay_grid_ticks.py`

**Interfaces:**
- Consumes: `_nice_per_div(span / n)`.
- Produces: when `span / n` is already a nice step within `1e-9` relative tolerance,
  the handle keeps its exact `lo`/`hi` and only re-pins ticks; otherwise the existing
  `_frame_to_nice()` path runs unchanged.

- [x] Add a RED test: overlay, one Shift-wheel notch, then
      `_repin_overlay_channel_ticks()` — the range must be unchanged. Confirm it fails
      on `dec230e` with the measured `4.0 → 5.0` inflation.
- [x] Add a test that a genuinely arbitrary external range (`0.317, 8.42, n=8`) still
      re-frames to `(0.0, 9.6)` — the guard must not disable framing.
- [x] Add a test for the user-facing trigger: after a wheel zoom, calling
      `_reframe_companion_axes_after_visibility_change()` (the 显示原始 / 显示滤波后
      toggle path, `canvas.py:1203/1490/1545`) must not move channels whose visibility
      did not change.
- [x] Implement the nice-step guard in `_repin_overlay_channel_ticks()`.
- [x] Verify the tick-density path (`tick_density.py:56`) still re-frames when `n`
      changes such that `span / n` is no longer a nice step.

### Task 3: Keep The Retired Drag Path Out Of Scope

`_handle_overlay_mouse_press()` deliberately returns `False` and no production path
sets `_overlay_dragging = True`. The remaining snap helpers and tests are legacy code;
changing their phase policy in this wheel-label fix would add risk without changing a
user-reachable interaction.

- [x] Do not modify `_snap_overlay_channel_to_grid()`, `_animate_overlay_snap()`, or
      their legacy tests in this change.
- [x] Keep the existing snap tests green as regression coverage only.
- [x] If the dead path is to be removed or restored, write a separate design that first
      decides the intended user interaction.

### Task 4: Cross-Apply The R4 Invariant To `PgLineCanvas`

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py:609-649`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py:1174-1222`
- Modify: `tests/ui/test_pg_line_canvas.py`

**Interfaces:**
- Consumes: `_reframe_time_y_to_grid()` (`line_canvas.py:1174`), `_time_overlay_vbs`.
- Produces: a time-preview Shift-wheel that keeps every aux ViewBox and the pinned
  graticule in sync with the main ViewBox.

Measured on the analysis time preview today (2 sources, `n = 10`): one Shift-wheel
notch moves the main range `(-1.0, 1.0) → (-0.85, 0.85)` while the pinned ticks stay at
`-1.0 … 1.0`, so 2 of 11 ticks fall outside the view, the first/last ticks no longer
sit on the viewport edges, and the aux ViewBox is not zoomed at all — the overlaid
curves decouple. The time-domain overlay zooms every channel together; this canvas
does not.

- [x] Add a RED test asserting that after a Shift-wheel notch on `_plot_time`, every
      tick lies inside the view, `ticks[0] == bottom`, `ticks[-1] == top`, and the tick
      count still equals `_time_divisions + 1`.
- [x] Add a RED test asserting that the data value under the delivered cursor fraction
      stays under that same fraction for the main and every aux ViewBox. Each channel
      may choose its own adjacent nice step, so equal span ratios are not required.
- [x] Apply the same cursor-anchored, `n`-equal-division construction the overlay uses,
      to the main ViewBox and every aux ViewBox, then re-pin ticks from the final
      ranges.
- [x] Format the re-pinned time-preview ticks with their active `per_div`, so this
      cross-canvas fix does not recreate the long-label gutter regression.
- [x] Confirm the spectrum row (`_plot_amp`, no graticule) keeps its current free-range
      zoom.

### Task 5: Wheel-Delta Bridge Hardening

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/viewbox.py:20-37`
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py:1395-1425`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Consumes: `QWheelEvent.angleDelta()`, `QWheelEvent.pixelDelta()`.
- Produces: a vertical-only delta and a balanced quality lifecycle.

- [x] Add a RED test: an event with `angleDelta(0, 0)` and `pixelDelta(12, 0)` — a pure
      horizontal trackpad swipe — must NOT change any Y range. Today it zooms Y
      (measured dispatch delta `+12`), because `_WheelDeltaGraphicsLayoutWidget`
      evaluates `angle.x() or angle.y()`, preferring the horizontal component. Before
      `26e001e` these events were a no-op.
- [x] Read only the vertical components: use `angleDelta().y()` first and, when it is
      zero, fall back to `pixelDelta().y()`. Never dispatch an X component as Y zoom.
- [x] Fix the quality-lifecycle leak: `overlay_axes.py:1310` calls
      `disable_interactive_quality()` unconditionally, but the non-overlay
      `return False` paths at `:1397` and `:1419` never call
      `schedule_idle_quality()`, leaving antialiasing off with no re-arm.
- [x] Rename the loop-local `axis` at `overlay_axes.py:1375` (it shadows the `axis`
      parameter that carries pyqtgraph's gutter flag; harmless today only because the
      parameter is read once before the loop).
- [x] Do not add a zoom floor in this change; it is unrelated to the reproduced input
      routing bug and needs its own numeric-range policy.

### Task 6: Documentation And Lessons

**Files:**
- Modify: `docs/lessons-learned/codex-overlay-wheel-anchor-invariants.md`
- Modify: `docs/superpowers/specs/2026-07-30-overlay-y-wheel-anchor-stability-design.md`
- Modify: `docs/lessons-learned/INDEX.md`
- Create: `docs/lessons-learned/codex-overlay-free-phase-consumer-audit.md`
- Create: `docs/lessons-learned/codex-nice-step-tolerance-checks-neighbors.md`

- [x] Amend R4 in the design doc: free-phase bounds are correct, but tick *formatting*
      and *repin* are part of the same invariant. A span-and-anchor test suite that
      never inspects label text or gutter width passes while the plot area halves.
- [x] Add the lesson: when a viewport transform stops producing grid-aligned bounds,
      audit every consumer of those bounds — label formatter, auto-width, re-pin, and
      user-reachable snap/reframe paths — not just the transform. Promote the lesson
      through the repository candidate workflow so the index and validation state stay
      consistent.
- [x] Note in the anchor-invariants lesson that `round`-quantized phase was measured and
      rejected (315/630 round-trip failures, 19-division drift).
- [x] Record the review-discovered boundary rule: a ceiling-oriented nice-step helper
      must also compare its lower adjacent candidate before applying relative tolerance.

---

## Acceptance Criteria

1. Every existing test in `tests/ui/test_overlay_grid_ticks.py` (103 cases) stays green,
   including the exact-anchor and exact-round-trip tests from `d2c4bda`.
2. After two real Shift-wheel notches on a 4-channel overlay, the plot-area width is
   within 10 % of its pre-zoom value (today: −56 %).
3. In the normal-scale real-wheel regression no Y tick label exceeds 6 characters.
   In the separate `1e5` high-offset fixture, labels on one axis are pairwise distinct;
   full absolute high-offset labels are not subject to the six-character cap.
4. `_repin_overlay_channel_ticks()` is a no-op on any range that is already `n` equal
   nice divisions.
5. `PgLineCanvas` time-preview Shift-wheel keeps ticks inside the view, on the viewport
   edges, and every aux ViewBox in sync.
6. A pixel-only horizontal wheel event changes no Y range.
7. `tests/ui/test_overlay_grid_ticks.py`, `tests/ui/test_pg_timedomain_canvas.py`,
   `tests/ui/test_pg_line_canvas.py`, `tests/ui/test_pg_heatmap_canvas.py`, and
   `tests/ui/test_overlay_shared_axis.py` pass.
   Note: `test_x_tick_target_count_backs_off_before_label_overlap` already fails on
   `03539b0` (pre-dates all of these commits) — a font-environment failure under
   offscreen Qt, out of scope here.
8. `git diff --check` reports no whitespace errors.

## Out Of Scope

- Changing the Shift-wheel range construction or the anchoring policy.
- Replacing `_adjacent_nice_step` or redesigning `_frame_to_nice`.
- Compact axis offset notation at large absolute offsets (for example a `+1.0e5`
  header plus short residual labels). This change preserves distinct full labels up to
  `1e5`; offset notation remains its own UI change.
- Heatmap canvas Y zoom (uses pyqtgraph auto ticks; no pinned graticule to desync).
- The interaction-budget commits `642a530` / `b8727fb` / `c1b6885` / `502e000`.
