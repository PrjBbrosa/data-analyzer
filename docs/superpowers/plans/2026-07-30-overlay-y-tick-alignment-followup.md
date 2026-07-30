# Overlay Y Ticks — Follow-up After `e448708`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Supersedes** `2026-07-30-overlay-y-wheel-label-and-repin-fixes.md`. Do NOT re-read
> that file for direction — it is the record of what `e448708` executed.

**Goal:** Ship the integer-label hotfix immediately, then deliver what the user actually
asked for — overlay Y tick *values* that are integer multiples of the division step. The
step-aware `per_div` formatter is **kept and corrected**, not retired: aligned values make
it unnecessary at normal magnitudes but it is the only thing that keeps high-offset and
tiny-step labels truthful and distinct.

**Tech Stack:** Python 3, PyQt5, pyqtgraph, NumPy, pytest, pytest-qt.

---

## 1. What `e448708` landed, verified by measurement

| Item | Before | After `e448708` | Verdict |
|---|---|---|---|
| Plot width, 4 channels, 2 notches (900 px) | 256.9 px | **568.9 px** | fixed |
| `_repin_overlay_channel_ticks()` after 1 notch | span `4.0 → 5.0` (+25 %) | **idempotent, +0.00 %** | fixed |
| `_reframe_companion_axes_after_visibility_change()` preserves wheel zoom | moved channels | unchanged | fixed + tested |
| Horizontal pixel-only wheel zooming Y | zoomed Y | `angle.y()` / `pixel.y()` only | fixed |
| `axis` parameter shadowed in the wheel loop | shadowed | renamed `target_axis` | fixed |
| `disable_interactive_quality()` with no re-arm | leaked on 2 paths | balanced | fixed |
| `PgLineCanvas` time preview: aux ViewBoxes desynced on Shift+wheel | desynced | all ViewBoxes zoom together, ticks re-pinned | fixed |
| Suite | — | 613 passed, 1 skipped | green |

Also correctly established, and it retires a finding from the previous plan:
`_handle_overlay_mouse_press()` returns `False` and no production path sets
`_overlay_dragging = True` (only the property setter at `overlay_axes.py:192`, used by
legacy tests). The drag-release snap phase inconsistency is therefore **not
user-reachable** and is out of scope.

## 2. What is still open — the original complaint

The reported defect was tick *values* like `0.0283967` instead of aligned ones.
`e448708` did not change the range phase; it shortened the labels instead. Current
behavior after one real off-center Shift-wheel notch:

```
ylim  = (-1.8793027844770882, 2.120697215522912)     <- still free phase
shown = ['-1.9','-1.5','-1.1','-0.7','-0.3','0.1','0.5','0.9','1.3','1.7','2.1']
```

The values under the grid lines are still unaligned; only their rendering is truncated.

## 3. New defects introduced by `e448708`

### P0 — `rstrip("0")` corrupts every integer tick label

`_fmt_tick` (`ui_kit/ticks_math.py:69-79`) ends with

```python
label = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
```

`decimals == 0` whenever `per_div >= 1`, and then the formatted string has no decimal
point, so `rstrip("0")` eats significant digits. Measured on a **real overlay canvas with
no wheel interaction at all** — plain `plot_channels` + `_repin_overlay_channel_ticks()`:

```
rpm 0..1000   (per_div 100)  true  0 100 200 300 400 500 600 700 800 900 1000
                             shown 0   1   2   3   4   5   6   7   8   9    1
temp 80..100  (per_div 2)    true  80 82 84 86 88 90 92 94 96 98 100
                             shown  8 82 84 86 88  9 92 94 96 98   1
```

Direct helper checks: `_fmt_tick(100, 100)` → `"1"`, `_fmt_tick(800, 80)` → `"8"`,
`_fmt_tick(101330, 2)` → `"10133"`, `_fmt_tick(2000, 500)` → `"2"`.

This hits every overlay and time-preview channel whose per-division is `>= 1` — RPM,
temperature, torque, kPa pressure, counters — on ordinary plotting. Worst measured label
error is **990–1070 % of a division**. The 613-test suite is green because every label
assertion uses `per_div < 1` (`-2.5..2.5` → `per_div 0.5`, and the high-offset case uses
`per_div 0.8`).

### P1 — one decimal too few

`decimals = max(0, ceil(-log10(step)))` does not guarantee the label separates adjacent
ticks. Swept over the full nice ladder (`1e-4 … 1e2`) and seven phase offsets:

| | duplicate-or-unequal-gap ladders | worst label error |
|---|---|---|
| current (`+0`) | 141 / 490 | 50 % of a division |
| with `+1` decimal | 48 / 490 | 5 % of a division |

Visible symptom: uniformly spaced grid lines showing unequal label gaps, e.g. `per_div`
0.25 → `-0.9, -0.7, -0.4, -0.2, 0.1` (gaps 0.2, 0.3, 0.2, 0.3).

### P1 — the `per_div` branch bypasses sci-notation

The new branch returns before the `abs(value) >= 1e6` / `< 1e-4` `%.2e` branch, so a
1e6-magnitude channel now renders 7-digit integers (`1000001, 1000081, …`) and the gutter
blowup returns for exactly those channels.

### P2 — `PgLineCanvas` gutter scroll and exception safety

The new branch (`line_canvas.py:630`) is gated on `view_box is self._plot_time.vb`, so a
Shift+wheel over an **aux** Y gutter still falls through to the generic single-ViewBox
`elif shift`, re-decoupling the curves. The branch also has no inner `try`/`except`: if
`setTicks` raises mid-loop, some ranges are already applied, the outer handler returns
`False`, and pyqtgraph's native zoom then runs on top — a double zoom.

## 4. Process root cause

The previous plan was rewritten **in place at the same filename** after the screenshot
arrived, changing the chosen policy from "free phase + step-aware labels" to "aligned
phase". The rewrite was never committed, so the executor read the committed superseded
copy and implemented the wrong strategy. Fix: a superseded plan is never edited in place
— write a new dated file and add a `Supersedes:` line, as this file does.

## 5. Chosen direction, verified

Align the phase. `bottom` becomes an exact multiple of `next_per_div`, so the graticule
carries round tick values and the label formatter no longer has to hide an arbitrary
offset. At the magnitudes the named regression fixtures cover, `_fmt_tick(value)` — the
original single-argument function — already produces short, truthful, uniformly spaced
labels.

The `per_div` parameter is **kept**, not deleted: at high offset and at tiny steps the
single-argument `%g` and `%.2e` branches both fail, collapsing multiple ticks onto one
string. Task 3 defines the flat contract — truthfulness and distinctness everywhere,
compactness only where a fixture asserts it.

Swept `n ∈ {3,6,10,20}` × 7 cursor fractions × 6 nice steps (incl. the screenshot's 0.008
and 0.006) × 4 grid offsets × 3 notches = **2016 ladders**:

- duplicate / unequal-gap / inexact labels: **0 / 2016**
- longest label across all cases: **6 chars**

On the screenshot's own ladder (`0.0283967`, step 0.008, `n = 6`):

```
notch 1  ylim=(0.036000, 0.072000)  ['0.036','0.042','0.048','0.054','0.06','0.066','0.072']
notch 2  ylim=(0.040000, 0.070000)  ['0.04','0.045','0.05','0.055','0.06','0.065','0.07']
notch 3  ylim=(0.044000, 0.068000)  ['0.044','0.048','0.052','0.056','0.06','0.064','0.068']
```

Cost, re-measured from grid-aligned seeds over 3150 cases (the earlier `round` rejection
used `lo = -0.5*n*p`, off-grid for odd `n`, so its first notch legitimately snapped and
every case was miscounted):

| policy | nested round trip (N in, N out) | interleaved balanced walk | anchor shift / notch | tick values |
|---|---|---|---|---|
| `floor` (`607c630`) | 3034 / 3150 fail | 237 divisions, one-sided | 1.0 division | aligned |
| free (current) | 0 / 3150 | 0 divisions | 0 | **unaligned** |
| `round` (**chosen**) | **0 / 3150**, error exactly 0.0 | 9 divisions, unbiased | 0.5 division | **aligned** |

`round` is exactly reversible for nested gestures — zoom in N notches, back out N notches,
bit-for-bit restore. With `r = p0/p1 > 1` the zoom-in phase error `|e| <= 0.5`; the return
trip divides it by `r` so `|e/r| < 0.5` and `round` recovers the original multiple; the
offset terms cancel because `c/r + c' = 0`. The residual 9-division wander appears only in
interleaved out-then-in sequences, where snapping onto a coarser grid discards
sub-division position that zooming back in cannot recover — inherent to any aligned
policy, and unlike `floor` it has no directional bias.

## Global Constraints

- Do NOT modify `_nice_per_div()`, `_adjacent_nice_step()`, or `_NICE_STEP_MANTISSAS`.
- Preserve Ctrl+wheel X zoom, plain-wheel Y pan, axis-gutter single-channel scope, the
  X-master `[0, 1]` lock, and the fixed `k/n` grid lines.
- Do not touch the retired drag / snap helpers (`_snap_overlay_channel_to_grid`,
  `_animate_overlay_snap`) — dead path, per §1.
- Keep every regression `e448708` added green; only the label-cap assertions may be
  re-scoped, and only as Task 3 directs.
- Repository virtual environment, `QT_QPA_PLATFORM=offscreen`, unique writable
  `--basetemp`. Finish with `git diff --check`.

---

### Task 1: P0 Hotfix — Stop Stripping Significant Digits

Ship as its own commit before anything else. Independent of the phase decision, because
the `per_div` path is live in repin, box zoom, the wheel, and `line_canvas` right now.

**Files:**
- Modify: `mf4_analyzer/ui_kit/ticks_math.py:69-79`
- Modify: `tests/ui/test_overlay_grid_ticks.py`

- [x] Add a RED test: `_fmt_tick(100, 100) == "100"`, `_fmt_tick(800, 80) == "800"`,
      `_fmt_tick(2000, 500) == "2000"`, `_fmt_tick(101330, 2) == "101330"`.
- [x] Add a RED canvas test: overlay a 0..1000 channel and an 80..100 channel, explicitly
      set those exact Y ranges with `n = 10` (steps 100 and 2), and use no wheel input —
      every label must equal its true tick value. Do not rely on auto-range padding here;
      that can select step 2.5 and would mix Task 3 precision into this P0-only test.
- [x] Guard the strip: only `rstrip("0")` when `"." in text`.
- [x] Confirm both tests fail before the fix and pass after.

### Task 2: Align The Shift-Wheel Phase

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py:1390-1394`
- Modify: `tests/ui/test_overlay_grid_ticks.py`

**Interfaces:**
- Consumes: `_adjacent_nice_step(current_per_div, direction)` — unchanged.
- Produces: `bottom = round((anchor - frac * framed_span) / next_per_div) * next_per_div`;
  `top = bottom + n * next_per_div`; `n + 1` ticks from those bounds.

- [x] Add a RED test reproducing the screenshot: `n = 6`, off-grid autoscaled start, one
      Shift-wheel notch — every tick value must be an integer multiple of the division
      step within `1e-9` relative tolerance.
- [x] Apply the round-quantized `bottom`.
- [x] Re-scope `_assert_cursor_anchor_preserved` from exact to "within half a division",
      and state the tolerance in its docstring.
- [x] Keep the nested round-trip test exact — 4 in + 4 out from a nice-step frame must
      restore the original ranges to `pytest.approx`. This still holds under `round`.
- [x] Keep the `n = 3..20` strict span monotonicity tests green.
- [x] Keep `e448708`'s repin-idempotence and visibility-repin tests green — an aligned
      bottom satisfies the nice-step guard by construction.

### Task 3: Fix The `per_div` Formatter's Precision — Keep It, Flatten The Contract

**Revised.** The earlier version of this task said to delete the `per_div` path and
restore `%.2e` as the only policy. That contradicts acceptance criteria 4, 5, and 9:
around `1e6` with `per_div = 80`, `%.2e` renders **every** tick as `1.00e+06` — 8
characters (over the 6-char cap) and neither truthful nor distinct. Measured:

```
_fmt_tick(1000000.74 + k*80)  ->  ['1.00e+06','1.00e+06','1.00e+06','1.00e+06','1.00e+06']
```

So the `per_div` path stays. What changes is its precision rule and its ordering.

**Revised again.** The tier table this task previously carried was itself unsatisfiable in
two places, both confirmed by measurement:

- `abs(value) < 1e5` does not bound the label to 6 characters. With the `+1` decimal rule:
  `12345.1` at step `0.1` → `"12345.1"` (7), `54321.25` at step `0.25` → `"54321.25"` (8),
  `99999.0001` at step `1e-4` → `"99999.0001"` (10).
- A fixed `%.2e` for `per_div < 1e-4` does not reach 1 % of a division:
  `1.23456e-5` at step `1e-6` → `1.23e-05`, **4.56 %**; at step `1e-7`, **45.6 %**;
  `9.87654e-6` at step `1e-7` → **3.46 %**. And at high offset it collides outright —
  `1e5 + k*1e-4` renders all six ticks as `1.00e+05`.

**Label contract — flat, not tiered:**

1. **Truthfulness** — `float(label)` is within 1 % of a division of the true tick value.
   Hard requirement at **every** magnitude and step. No exemptions.
2. **Distinctness** — no two ticks on one axis render identically. Hard requirement at
   every magnitude and step.
3. **Compactness (≤ 6 chars)** — a requirement of the **named normal-magnitude regression
   fixtures only**: the `±2.5` four-channel overlay (`per_div` 0.5) and the `0..1000` /
   `80..100` engineering fixtures. It is deliberately NOT expressed as a value/step
   interval, because no such interval bounds label length while (1) and (2) hold.

Length outside those fixtures is **unbounded by design**. With the shortest-truthful
selection rule below, `1e6 + 0.74 + k*80` uses 7-character fixed labels, while
`1e5 + k*1e-4` uses 6 characters at `k = 0` and 11 characters for non-zero `k`.
The adaptive scientific candidates are longer (13 and 17–18 characters respectively)
and therefore are not selected in those examples. Axis offset notation (a `+1.0e5`
header plus small residuals) is the only general way to impose a global compactness cap.
If a character cap is ever wanted outside the named fixtures, offset notation must be
brought INTO scope as its own task — never met by rounding labels until ticks collide.

**Adaptive scientific precision.** Preserve the current invalid-input, non-finite, and
near-zero handling before this branch. In particular, `value == 0` must return `"0"`
without evaluating `log10(0)`, and a missing/non-positive/non-finite `per_div` must keep
the existing single-argument fallback. For a finite non-zero value and positive step,
replace fixed `%.2e` with a mantissa width derived from how many digits it takes to
resolve one division. Use a difference of logarithms so the intermediate ratio cannot
overflow or underflow:

```python
sig = max(2, ceil(log10(abs(value)) - log10(0.01 * per_div)) + 1)
label = "%.*e" % (sig - 1, value)
```

Measured against the failing cases above — all within 1 % of a division, all distinct:

| value | per_div | fixed `%.2e` | adaptive | error |
|---|---|---|---|---|
| `1.23456e-5` | `1e-6` | 4.56 % | `1.2346e-05` | 0.04 % |
| `1.23456e-5` | `1e-7` | 45.6 % | `1.23456e-05` | 0.00 % |
| `9.87654e-6` | `1e-7` | 3.46 % | `9.8765e-06` | 0.04 % |
| `1e6 + 0.74` | `80` | collides | `1.0000007e+06` | 0.05 % |
| `1e5 + k*1e-4` | `1e-4` | all identical | sci candidate 17–18 chars; selected fixed 6/11 | 0.00 % |

**Files:**
- Modify: `mf4_analyzer/ui_kit/ticks_math.py` (`_fmt_tick`)
- Modify: `tests/ui/test_overlay_grid_ticks.py`, `tests/ui/test_pg_line_canvas.py`

- [x] Apply the `+1` decimal correction to the fixed-notation branch:
      `decimals = max(0, ceil(-log10(per_div)) + 1)`. Measured over the full nice ladder ×
      7 phase offsets: unequal-gap-or-duplicate ladders drop from **141 / 490 to 48 / 490**,
      worst label error from **50 % to 5 %** of a division. Measured under the current free
      phase; after Task 2 the aligned phase removes the residual 48 as well.
- [x] Replace the fixed `%.2e` with the adaptive `sig` rule above, and apply it wherever
      scientific notation is chosen — including the `abs(value) >= 1e6` branch, which today
      collides at `per_div = 80`.
- [x] Generate fixed and adaptive-scientific candidates, discard any candidate whose
      parsed value exceeds the 1 %-of-division error bound, then choose the shortest
      remaining candidate (fixed wins ties). The truthfulness bound itself guarantees
      adjacent ticks cannot collide. Do not use a hard magnitude threshold: a `>= 1e6`
      value with a large `per_div` must stay in fixed notation when that is shorter.
- [x] Add a truthfulness + distinctness sweep over the full nice ladder (`1e-4 … 1e2`) ×
      channel magnitudes (`±2.5`, `0..1000`, `1e5 + k*1e-4`, `1e6 + k*80`) × 7 phase
      offsets. Assert (1) and (2) on every case, and assert NO character cap there.
- [x] Add the ≤ 6 char assertion only to the named normal-magnitude fixtures, and comment
      in the test why it is fixture-scoped rather than interval-scoped.
- [x] Record in the design doc that compactness is fixture-scoped, that truthfulness and
      distinctness are universal, and that label length is unbounded until offset notation
      lands.

### Task 4: `PgLineCanvas` Gutter Scroll And Event Consumption

**Revised.** The earlier wording claimed `try`/`except` + `continue` prevents a partial
range application. It does not — a raise partway through the ViewBox loop leaves earlier
ViewBoxes already moved. What it does prevent is the event falling through to pyqtgraph's
native zoom on top of a partly applied change. The goal is therefore stated as event
consumption, not atomicity.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py:630-667`
- Modify: `tests/ui/test_pg_line_canvas.py`

- [x] Add a RED test: Shift+wheel with `view_box` set to an aux time-preview ViewBox must
      zoom every ViewBox around the same delivered cursor fraction, not just that one.
      Each axis still chooses its own adjacent nice step, so their span ratios may differ.
- [x] Widen the branch condition to any time-preview ViewBox (main or aux), deriving the
      cursor fraction from the ViewBox that received the event.
- [x] Apply the same aligned phase as Task 2 so the time-preview graticule matches the
      time-domain overlay.
- [x] Wrap the per-ViewBox body in its own `try`/`except` + `continue` so one failing axis
      cannot abort the remaining ViewBoxes.
- [x] Add a test asserting that when one axis raises, the handler still returns `True`,
      the event is accepted, and no native pyqtgraph zoom is applied on top. Assert
      exactly that — do NOT assert that no range was partially applied.
- [x] If all-or-nothing application is wanted, it needs a separate design: snapshot every
      target range first, apply, and restore the snapshot on any failure. Out of scope
      here; note it in the design doc as a known limitation.

### Task 5: REMOVED — `_frame_to_nice` Float Tolerance

**Cut from this plan. Do not touch the shared `_frame_to_nice()` here.**

The RED case previously written into this task was wrong, and it is worth recording why so
the separate investigation does not restart from the same bad premise.

- The asserted reproducer `_frame_to_nice(-2.28, -2.28 + 6*0.006, 6)` returns
  `-2.2800000000000002`. That is a **0.000000-division** drop — a last-bit float
  representation difference, not a lost division. The assertion `bottom == -2.28` would
  have failed on exact equality only, which is not the defect.
- The **281 / 8010** figure came from an isolated `math.floor((m*p)/p) != m` probe. That
  number is the hazard rate of the bare expression, not of `_frame_to_nice()`, and quoting
  it as the latter was a misattribution.
- The `while` guard already carries a tolerance
  (`top < hi - max(abs(per_div)*1e-9, 1e-12)`); only the `floor` does not.

The hazard is nevertheless real when driven through `_frame_to_nice()`, just rarer and
with a different signature. Swept `n ∈ {3,6,8,10,12,20}` × the full nice ladder
(`1e-4 … 1e2`) × grid-aligned `lo`, 24360 cases:

- **114 / 24360** (0.47 %) drop more than half a division; worst is exactly
  **1.000000 division**.
- Reproducer: `_frame_to_nice(-95 * 0.012, -95 * 0.012 + 8 * 0.012, 8)` →
  `bottom = -1.155`, `per_div = 0.015`. The ULP residue makes `floor` land one division
  low, `top < hi` then fires the guard loop, and the span inflates `0.096 → 0.12`
  (**+25 %**) on top of the shift.
- Adding `+1e-9` to the `floor` changes **354 / 24360** results, e.g.
  `lo = 0.0059, per_div = 1e-4, n = 3`: `0.00588 → 0.0059`. So the tolerance is not a
  no-op — which is exactly why it needs its own investigation rather than a drive-by edit.

Reasons to separate it: it is pre-existing and unrelated to every commit under review; the
helper is shared with `acquisition_ui/widgets/live_cards.py:293`; and after Task 2 the
overlay wheel path no longer reaches `_frame_to_nice()` at all, because `e448708`'s
nice-step guard short-circuits aligned ranges. The remaining callers are build, autoscale,
box zoom, and density change on arbitrary ranges.

- [x] Do not modify `mf4_analyzer/ui_kit/ticks_math.py:_frame_to_nice` in this plan.
Future follow-up only (not an executable checkbox in this plan): file a separate
investigation carrying the corrected reproducer and the 114 / 24360 and 354 / 24360
figures above.

### Task 6: Close The Coverage Gap That Let The P0 Ship

**Files:**
- Modify: `tests/ui/test_overlay_grid_ticks.py`, `tests/ui/test_pg_line_canvas.py`

- [x] Parameterize every tick-label assertion over per-division magnitudes spanning
      `per_div < 1`, `per_div == 1`, and `per_div > 1` — the P0 lives entirely in the
      `per_div >= 1` band that no existing test touches.
- [x] Add a channel-magnitude axis to the label fixtures: small (`±2.5`), engineering
      (`0..1000`), and high-offset (`1e6 + 800`).
- [x] Assert label *truthfulness* — `float(label)` must equal the tick value to within a
      stated fraction of a division — not only length and uniqueness. Length and
      uniqueness both passed while `100` rendered as `1`.

### Task 7: Documentation And Lessons

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-overlay-y-wheel-anchor-stability-design.md`
- Modify: `docs/lessons-learned/codex-overlay-wheel-anchor-invariants.md`
- Modify: `docs/lessons-learned/codex-overlay-free-phase-consumer-audit.md`
- Modify: `docs/lessons-learned/INDEX.md`

- [x] Rewrite R2: the cursor anchor holds to within half a division, not exactly. Exact
      anchoring and aligned tick values are mutually exclusive; aligned values win because
      the graticule is the product's read-out surface.
- [x] Rewrite R4: the contract covers tick *values*, not just count and placement.
- [x] New lesson: a label formatter that rounds for compactness must assert
      truthfulness. `rstrip("0")` on a zero-decimal format is digit loss, not cosmetics;
      length and uniqueness tests both stayed green while `100` displayed as `1`.
- [x] New lesson: never edit a superseded plan in place. Write a new dated file with a
      `Supersedes:` line — `e448708` executed a stale committed copy of a plan whose
      strategy had already been replaced in the working tree.
- [x] Record the corrected phase-policy table so the off-grid-seed measurement error is
      not repeated.
- [x] Record Task 3's flat label contract as the standing rule: truthfulness and
      distinctness are universal, compactness is asserted only by named fixtures. Two
      earlier drafts of this plan were self-contradictory — one demanded both `%.2e` at
      `1e6` and a 6-character truthful label; the next bound the cap to
      `abs(value) < 1e5`, which `12345.1` (7 chars) and `99999.0001` (10 chars) already
      violate. A character cap expressed as a value/step interval is unsatisfiable.
- [x] Record that a fixed scientific precision cannot be truthful: `%.2e` is off by 45.6 %
      of a division at `1.23456e-5 / 1e-7` and collides outright at `1e5 + k*1e-4`.
      Precision must derive from `value / per_div`.
- [x] New lesson: a hazard rate measured on an extracted expression is not the hazard rate
      of its caller. The `math.floor` probe reported 281 / 8010 in isolation; driven
      through `_frame_to_nice()` the reachable rate is 114 / 24360 with a different
      signature (guard-loop span inflation, not a bare shift). Quote the number for the
      path you actually intend to change.

---

## Acceptance Criteria

1. `_fmt_tick` never drops a significant digit: `100 → "100"`, `800 → "800"`,
   `101330 → "101330"`, `2000 → "2000"`.
2. A plain overlay of a `0..1000` channel and an `80..100` channel labels every tick with
   its true value, with no wheel input.
3. Every overlay Y tick value is an integer multiple of its division step, for all
   `n = 3..20` and every cursor fraction — the `0.0283967` class of value cannot occur.
4. **Universal, no magnitude exemptions.** Across the full swept ladder (`per_div`
   `1e-4 … 1e2` × magnitudes `±2.5`, `0..1000`, `1e5 + k*1e-4`, `1e6 + k*80` × 7 phase
   offsets): `float(label)` is within 1 % of a division of its tick value, no two ticks on
   one axis render identically, and parsed-label gaps equal `per_div` within a 2 %-of-
   division absolute tolerance (the sum of two 1 % endpoint error bounds). Scientific
   notation must use the adaptive `sig` rule — a fixed `%.2e` fails this at
   `1.23456e-5 / 1e-7` (45.6 %) and collides at `1e5 + k*1e-4`.
5. **Fixture-scoped, not interval-scoped.** No Y tick label exceeds 6 characters in the
   named normal-magnitude fixtures (the `±2.5` four-channel overlay, and the `0..1000` /
   `80..100` engineering fixtures), and plot-area width after two notches stays within
   10 % of pre-zoom (currently satisfied, must not regress). There is deliberately no
   value/step interval carrying this cap: with criteria 4 held, `12345.1` at step `0.1`
   needs 7 characters and `99999.0001` at step `1e-4` needs 10, so any interval-based cap
   is unsatisfiable. Label length outside the named fixtures is unbounded until offset
   notation lands.
6. Four zoom-in notches then four zoom-out restore every channel's range to
   `pytest.approx`, for `n = 3, 10, 20` at fractions `0.15`, `0.50`, `0.85`.
7. Strict span monotonicity holds for every `n = 3..20` in both directions.
8. `_repin_overlay_channel_ticks()` is a no-op on a wheel-zoomed range.
9. A `1e6`-magnitude channel renders **distinct, truthful** tick labels — the current
   `%.2e` collapse to five identical `1.00e+06` strings must not occur, and neither must
   the `1e5 + k*1e-4` collapse to six identical `1.00e+05` strings. Its gutter is allowed
   to be wider than a normal-magnitude channel's. Under the shortest-valid rule,
   `1e6 + 0.74 + k*80` selects 7-character fixed labels; `1e5 + k*1e-4` selects a
   6-character label at `k = 0` and 11-character fixed labels otherwise. Compactness at
   arbitrary high offsets requires offset notation, which is a Non-goal here.
10. `PgLineCanvas` time-preview Shift+wheel zooms every ViewBox together whether the event
    lands on the plot area, the left axis, or an aux gutter. When one axis raises, the
    handler still returns `True` and no native pyqtgraph zoom is applied on top; partial
    range application is an accepted, documented limitation.
11. `_nice_per_div`, `_adjacent_nice_step`, and `_NICE_STEP_MANTISSAS` are byte-identical.
12. `tests/ui/test_overlay_grid_ticks.py`, `test_pg_timedomain_canvas.py`,
    `test_pg_line_canvas.py`, `test_pg_heatmap_canvas.py`, and
    `test_overlay_shared_axis.py` pass except for the documented
    `test_x_tick_target_count_backs_off_before_label_overlap` baseline failure. It also
    fails on `03539b0`, which pre-dates every commit involved — a font-environment
    failure under offscreen Qt, out of scope.
13. `git diff --check` reports no whitespace errors.

## Non-goals

- Any change to the nice-step ladder or its selectors.
- Zero-drift-plus-aligned-ticks via a stored per-channel zoom origin. It is the only way
  to get both, but it adds state to invalidate on repin, autoscale, box zoom, pan, and
  density change. Revisit only if the unbiased interleaved wander is observed in use.
- Axis offset notation (a `+1.0e6` header plus small residuals) for high-offset channels.
  Wanted, but its own design. **Conditionally in scope:** if a character cap is ever
  required outside the named normal-magnitude fixtures, offset notation must be brought in
  as its own task — the cap must never be met by rounding labels until ticks collide.
  Measured shortest-valid output: 7 chars at `1e6 / step 80`, and 6/11 chars at
  `1e5 / step 1e-4`; the corresponding scientific candidates are 13 and 17–18 chars.
- All-or-nothing range application in the `PgLineCanvas` wheel loop. Needs a
  snapshot-and-restore design; partial application on a mid-loop raise is an accepted,
  documented limitation here (Task 4).
- `_frame_to_nice()`'s tolerance-free `math.floor` (former Task 5). Real but separable —
  114 / 24360 aligned cases drop > 0.5 division, reproducer and figures recorded in the
  Task 5 section for a standalone investigation.
- The retired overlay drag / snap helpers.
- Heatmap canvas Y zoom (pyqtgraph auto ticks, no pinned graticule).
- The interaction-budget commits `642a530` / `b8727fb` / `c1b6885` / `502e000`.
