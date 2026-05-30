# PyQtGraph Overlay Grid + Right-Axis Spacing Fix Plan

> Follow-up to `2026-05-29-pyqtgraph-overlay-toolbar-five-fixes.md`. Two overlay
> defects reported 2026-05-29 against `TimeDomainCanvasPG`. Pure UI/PyQt; TDD,
> one commit per fix. Preserve the W0 contract. Run tests with
> `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest <target> -q`.

**Files:** `mf4_analyzer/ui/pg_canvases.py`; tests
`tests/ui/test_pg_timedomain_canvas.py`.

---

## Issue 1 — Overlay grid lines are messed up (misaligned, multi-colored)

**Root cause (confirmed):** `_add_plot_item` calls
`pi.showGrid(x=True, y=True, alpha=0.28)` (`pg_canvases.py:534`) for the overlay
PlotItem. pyqtgraph's `showGrid(y=True)` enables the Y grid on BOTH the built-in
left and right axes; in overlay those are linked to different per-channel aux
ViewBoxes with different Y ranges, so each draws horizontal grid lines at its OWN
tick positions, in its OWN pen color (axis pen is set to the channel color in
`_apply_pg_axis_style`, `pg_canvases.py:734`). Result: ≥2 non-coincident,
differently-colored horizontal grid families → "messed up". single/subplot have
one Y range per plot so their grid is clean; overlay's N independent ranges break
the single-grid assumption.

**Measure:** In overlay mode show only the X grid (vertical lines, shared across
all channels via the single bottom axis) and DISABLE the Y grid (no single Y
range is canonical). Keep `showGrid(x=True, y=True)` for subplot/single.

### Task 1 (TDD)
- [ ] **Failing test.** Build overlay (≥3 channels), assert the Y grid is OFF on
  the overlay per-channel axes (e.g. each y `AxisItem.grid` is falsy, or the
  PlotItem's `ctrl.yGridCheck` is unchecked) while the X grid stays ON. Also
  assert subplot mode still has Y grid ON (guard against over-reach).
- [ ] **Run → FAIL.**
- [ ] **Implement.** Where overlay is built (`plot_channels` overlay branch,
  ~`pg_canvases.py:438-452`, or by adjusting `_add_plot_item`/post-build): set
  X-only grid for the overlay PlotItem — `pi.showGrid(x=True, y=False)` — or call
  `setGrid(False)` on every overlay y `AxisItem`. Leave subplot/single untouched.
  Keep it idempotent across rebuilds.
- [ ] **Run → PASS.**
- [ ] **Commit:** `fix(ui): overlay shows single X grid, no misaligned per-axis Y grid`

---

## Issue 2 — Right-side channel names crammed against the axes

**Root cause (confirmed; partly a regression from the bug-1 fix):**
1. ch3+ right axes are added column-adjacent via
   `primary_plot.layout.addItem(axis_item, 2, 2+index)` (`pg_canvases.py:573`)
   with NO inter-column spacing, so each rotated channel name butts against the
   neighboring axis's tick numbers.
2. `_configure_overlay_axis_geometry` pins each axis with
   `setWidth(self._overlay_axis_min_width=44)` (`pg_canvases.py:775-776`). The
   code comment claims pyqtgraph "auto-grows past this" — that is FALSE:
   `AxisItem.setWidth(w)` FIXES the width (it is a hard clamp, not a floor), so
   wide-number axes (e.g. `−2600`/`1400`) are jammed.
3. `setStyle(tickTextOffset=4)` (`pg_canvases.py:768`) only offsets tick text
   from tick marks, not the rotated label from the axis.
4. The bug-1 test only asserted `"\n" not in label` and `width>0` — it never
   verified the label visually clears the ticks, so the cramming passed CI.

**Measures (combine as needed):**
- Drop the hard `setWidth(44)` floor-that-is-actually-a-clamp. Either let the
  axis auto-size (`setWidth(None)`) and add real inter-axis spacing, or compute a
  width that fits `tick-text + rotated-name + gap` and pin THAT (analogue of
  subplot's coordinated `_unify_subplot_left_axis_widths`, `pg_canvases.py:2629`,
  adapted to the overlay right-axis stack).
- Add horizontal spacing between the stacked right axes (e.g.
  `primary_plot.layout.setHorizontalSpacing(n)` or per-column spacing) so names
  don't touch the neighbor's ticks.
- Optionally shorten the per-axis name further (more aggressive
  `_middle_ellipsis`) or move identities to a compact color-chip legend instead
  of N rotated full names (parity with matplotlib `_set_series_ylabel` horizontal
  chip, `canvases.py:251`) — decide based on how it looks live.

### Task 2 (TDD)
- [ ] **Runtime confirm.** Check whether `setWidth(44)` is the dominant cause
  (hard clamp) vs. missing inter-axis spacing; note the finding.
- [ ] **Failing test.** Build overlay (≥4 channels with wide numeric ranges and
  long names). Assert adjacent overlay y-`AxisItem` `sceneBoundingRect`s do NOT
  overlap (real clearance), and/or each axis width is ≥ its own tick-text width.
  This replaces the weak `\n`-only assertion.
- [ ] **Run → FAIL.**
- [ ] **Implement** per measures above (remove the bad pin; add spacing / proper
  width). Keep `enableAutoSIPrefix(False)` — that part of the bug-1 fix is fine.
- [ ] **Run → PASS.**
- [ ] **Commit:** `fix(ui): space overlay right axes so names clear the ticks`

---

## Task 3: Regression sweep + live GUI verify
- [ ] `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_chart_stack.py -q`
- [ ] `git diff --check`.
- [ ] LIVE GUI (REQUIRED — offscreen cannot prove the visual): overlay with 5+
  channels → grid is a single clean set; right-side names are readable and clear
  of the tick numbers and adjacent axes; subplot grid still has both X and Y.
- [ ] Report `ui_verified`, `tests_before/after`, `files_changed`, `symbols_touched`.
