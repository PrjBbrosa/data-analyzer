# Decomposition — FFT-vs-Time / Order-vs-Time four-bug fix batch

**Date:** 2026-06-14
**Routing note:** This request did NOT match a squad trigger keyword
(`agent`/`squad`/`重构`/`refactor`/`多专家`). Main Claude routed it under the
**Missed-triggers** rule because it is a multi-file, multi-fix `.py` change to
the pyqtgraph UI canvases + inspector wiring. The verb 写好plan...执行 (write the
plan, execute it) is a substantive source-edit request — same class as the
`ui-redesign-verb-missed-squad-trigger` roster gap already on file, so no NEW
roster-gap lesson is warranted (the existing lesson already covers
keyword-bare UI bug-fix phrasing).

**User request (verbatim):** 你写好plan吧开始执行吧。

**Pre-diagnosed bugs (root causes confirmed by main Claude via source-read +
offscreen pyqtgraph repro — do NOT re-diagnose, the fix direction is already
chosen for each):**

- **FIX 1 — FFT time-window selection wrongly toggles the Time-Domain "使用选定
  时间范围" checkbox.** A single shared `QCheckBox chk_range`
  (`inspector_sections.py:1531`) is reparented across time/fft/fft_time/order
  modes (`inspector.py:157-178 _place_range_group_for_mode`). FFT preview drag
  → `line_canvas time_preview_range_changed` (`line_canvas.py:256`) →
  `main_window.py:1785 _on_fft_preview_range_changed` → `set_range_from_span()`
  → `inspector_sections.py:1739 self.chk_range.setChecked(True)`. Shared
  instance leaks the checked state into Time-Domain mode. Fix: FFT time-window
  selection must NOT force-toggle the shared time-domain checkbox (decouple
  per-mode checkbox state, OR stop `set_range_from_span` mutating `chk_range`
  when invoked from the FFT preview path). Files: `inspector_sections.py`,
  `inspector.py`, `main_window.py`.
- **FIX 2 — Empty/default heatmap axes span negative→positive** (offscreen
  X=[-0.5,0.5], Y=[-0.5,0.5]); time/frequency/order are never negative. Root:
  `PgHeatmapCanvas` never sets an empty-state range (constructor + `full_reset`),
  inheriting pyqtgraph's default [-0.5,0.5]. **USER DECISION: fixed non-negative
  default (e.g. X 0–30, Y 0–…). Keep simple, do NOT pull from loaded-channel
  extents.** File: `heatmap_canvas.py`.
- **FIX 3 — top/bottom heatmap gridlines don't align by time.** **USER
  DECISION: only fix the 'y' slice direction** (frequency/order → bottom X =
  time); the default 'x' direction stays untouched. Root: slice X axis is
  deliberately NOT XLinked to map X (`heatmap_canvas.py:613-619`); in 'y' mode
  `_apply_slice` calls `setData(xc, m[idx,:])` (`:1220`) WITHOUT a matching
  `setXRange(padding=0)`, while the map uses `setXRange(x0,x1,padding=0)`
  (`:866-872`). Fix: in 'y' slice mode make the slice X range match the map
  exactly (`setXRange(xc[0],xc[-1],padding=0)` after setData, OR XLink only
  while in 'y' mode and unlink in 'x' mode). File: `heatmap_canvas.py`.
- **FIX 4 — extra/duplicate gridlines while zooming heatmaps.** Root:
  `showGrid(x=True,y=True)` enables grid on ALL FOUR axes; heatmap does NOT
  disable top/right grid (`line_canvas.py:145-146` DOES). top/right are plain
  `AxisItem` that re-draw the boundary lines the `_BoundaryGridAxisItem`
  left/bottom suppress; sub-pixel offset during zoom = visible doubled lines
  (offscreen: right axis 6 horizontal lines vs left's 4). Fix: mirror
  line_canvas — after `showGrid`, call `getAxis('top').setGrid(False)` and
  `getAxis('right').setGrid(False)` on BOTH the main plot AND the slice plot.
  File: `heatmap_canvas.py`.

**Branch state:** `heatmap_canvas.py` and `line_canvas.py` already have
uncommitted `_BoundaryGridAxisItem` changes on this branch; tests
`tests/ui/test_pg_heatmap_canvas.py` and `tests/ui/test_pg_line_canvas.py` show
modified. Specialists must run/extend the relevant test module.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S1: FIX 1 — decouple the shared `chk_range` checkbox so FFT time-window preview drags do NOT force-toggle the Time-Domain "使用选定时间范围" checkbox. Touches `inspector_sections.py` + `inspector.py` + `main_window.py` (the wiring path), NO numeric/algorithm change. | pyqt-ui-engineer | [] | Pure signal/slot + widget-state wiring across inspector and main_window. No FFT/Welch/numeric computation, so signal-processing-expert is not needed. Disjoint fileset from S2 (`heatmap_canvas.py`) → runs in parallel safely. |
| S2: FIX 2 + FIX 3 + FIX 4 BUNDLED — all three edits to `heatmap_canvas.py`: (2) fixed non-negative empty-state X/Y range in `PgHeatmapCanvas.__init__` and `full_reset`; (3) in 'y' slice mode match slice X range to the map exactly; (4) `getAxis('top'/'right').setGrid(False)` on BOTH main and slice plots after `showGrid`. | pyqt-ui-engineer | [] | All three are pyqtgraph canvas-surface (range/axis/grid) concerns → pyqt-ui-engineer. **MUST be one subtask, not three:** FIX 2/3/4 all mutate the SAME file `heatmap_canvas.py`. Splitting same-file edits across separate dispatches triggers `parallel-same-file-drawer-task-collision` (git-index commit race) and false cross-specialist rework detection; bundle them so one specialist owns the file end-to-end. |

**Why two subtasks, parallel-safe:** S1 (`inspector_sections.py`/`inspector.py`/
`main_window.py`) and S2 (`heatmap_canvas.py`) have DISJOINT filesets, both go to
the same expert (pyqt-ui-engineer). Per the parallel-mutators lessons, disjoint
same-expert tasks still contend on the shared git index/HEAD if dispatched
simultaneously — main Claude should **serialize the two dispatches** (S1 then S2,
either order) rather than send them in one parallel block, OR commit between
them. They have no logical dependency, so order is free.

## Lessons consulted (read in step 4)

- `docs/lessons-learned/pyqt-ui/2026-06-14-boundary-grid-suppression-and-stacked-left-axis-unify.md`
  — the `_BoundaryGridAxisItem` `generateDrawSpecs` boundary-line suppression
  already on this branch; FIX 4's top/right `setGrid(False)` is the OTHER half
  of the same double-line problem (top/right plain AxisItems re-draw the
  suppressed boundary). Directly relevant to S2/FIX 4. Also documents the
  offscreen-test trap: monkeypatch `generateDrawSpecs`, do NOT drive the real
  method with `QPainter(QPicture())` (access-violates).
- `docs/lessons-learned/pyqt-ui/2026-05-29-pyqtgraph-axisitem-setwidth-clamp-and-builtin-right-column-spacing.md`
  — `showGrid(y=...)` toggles the Y grid on BOTH built-in left+right axes; the
  canonical fix is x-only grid OR explicit per-axis `setGrid(False)`. Confirms
  FIX 4's root cause and the line_canvas pattern S2 must mirror.
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`
  — same `chk_range` / `PersistentTop` inspector family as FIX 1; warns that
  checkbox-state and conditional-row sync must seed at `__init__` end and that
  shared/reparented widgets carry their own state flags. Relevant to S1's
  per-mode-state decoupling and to not breaking the conditional range-row sync.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
  and `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
  — basis for bundling FIX 2/3/4 into ONE subtask (same file) and serializing
  S1/S2 dispatch.

## Routing notes

- No `superpowers:brainstorming`: request is unambiguous — each fix has a
  user-chosen direction already.
- No `superpowers:writing-plans`: 2 specialist dispatches, below the >3
  threshold.
- No `[routing][roster-gap]` lesson: keyword-bare UI bug-fix phrasing is already
  covered by `2026-05-30-ui-redesign-verb-missed-squad-trigger.md`; the missed
  trigger is expected, not a new gap.

## Re-dispatch addendum (written by main Claude after execution)

A THIRD subtask (S3) was dispatched mid-run as a flagged-handling re-dispatch,
NOT in the original plan:

- **S3: FIX 4 completion — shared context-menu grid toggle** → `pyqt-ui-engineer`,
  file `context_menu.py` (+ `tests/ui/test_pg_timedomain_canvas.py`). S2 flagged
  that `_build_grid_submenu._apply_grid` calls `plot_item.showGrid(x, y)`, whose
  pyqtgraph `updateGrid` re-lights top/right grid on ALL FOUR axes — silently
  UNDOING the S2/FIX 4 constructor `setGrid(False)` the moment a user toggles the
  grid from the right-click menu (the double-gridline returns). Shared by BOTH
  line and heatmap canvases.

**Decomposition lesson:** FIX 4 (disable top/right grid in the canvas
constructor) is INCOMPLETE on its own — any code path that re-invokes
`showGrid(x, y)` (here the shared `context_menu.py` grid toggle) re-lights the
suppressed axes. When a fix's invariant is "top/right never carry grid," scope
must include EVERY `showGrid` caller, not just the constructor. The orchestrator
plan scoped FIX 4 to `heatmap_canvas.py` only; the shared context-menu
`showGrid` caller should have been bundled into FIX 4 from the start. Future
"axis/grid policy" fixes: grep for ALL `showGrid(` call sites and treat them as
one fileset. (The technical trap itself is already captured in
`pyqt-ui/2026-06-14-boundary-grid-suppression-and-stacked-left-axis-unify.md`,
so no new pyqt-ui lesson was written — this addendum records only the
decomposition-scope miss.)

**Rework check:** S1 (`inspector_sections.py`, `inspector.py`), S2
(`heatmap_canvas.py`), S3 (`context_menu.py`) have DISJOINT non-test filesets →
no cross-specialist rework. All three ran as `pyqt-ui-engineer`, serialized.

## Post-review correction addendum (C1)

Any decomposition wording that implies the short-signal FFT paths are
"三路径一致" / identical is too broad. Their behavior is intentionally
different:

- Welch / 线性平均 clamps the segment length to the real signal length
  (`effective_nfft = n`) and returns the true `fs/n` resolution; this path now
  emits a `UserWarning` when it clamps a requested `nfft`.
- Single-frame FFT and peak-hold fallback still zero-pad the short signal to
  the requested `nfft`.

So for `n < nfft`, returned lengths and frequency spans are allowed to differ;
the invariant is that each path is explicit and numerically defined, not that
all three produce identical output.
