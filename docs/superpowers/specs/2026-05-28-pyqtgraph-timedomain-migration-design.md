# TimeDomainCanvas pyqtgraph Migration Design Spec

**Date:** 2026-05-28
**Branch:** `plan/pyqtgraph-timedomain-migration`
**Status:** revised after evidence review; implementation requires the companion plan
**Companion plan:** `docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md`
**Related review:** `docs/analyzer/reviews/2026-05-28-plot-perf-vs-asammdf.md`
**Chosen tier:** B: replace only TimeDomainCanvas rendering internals; keep FFT / Heatmap / Spectrogram / Order on matplotlib

---

## 0. Review Corrections Applied

This revision fixes the first draft before implementation. The prior draft was not safe to execute as written.

| Finding | Evidence | Correction |
| --- | --- | --- |
| The old goal said "`pyqtgraph + self-maintained paintEvent / pixmap cache`", but the phases mostly described plain `PlotDataItem.setData`. | The local asammdf comparison shows the fast path depends on `trim_c`, pixel-space scaling, cached paths, and cached pixmaps, not just using pyqtgraph widgets (`.venv/.../asammdf/gui/widgets/plot.py:1063-1193`, `:5434-5683`). | The implementation target is now explicit: a TimeDomain-only pyqtgraph canvas with a custom curve layer / cached pixmap path. Plain `PlotDataItem` is allowed only in the Phase 0 smoke spike, not as the production performance path. |
| The old scope excluded performance baseline and performance regression tests, which conflicts with the user's goal. | User goal for this round: performance optimization, current logic unchanged, UI unchanged. Existing code has only behavior tests for envelope and xlim refresh; no pyqtgraph migration baseline exists. | Baseline measurement and a slow opt-in performance check are now mandatory Phase 0 and final acceptance gates. |
| The old spec allowed 5-10% visual drift for inside labels. | Current implementation decides inside labels from rendered bbox overlap (`mf4_analyzer/ui/canvases.py:938-989`). User explicitly says UI must not adjust. | No visual or workflow drift is accepted as a planned outcome. If exact bbox parity is not feasible, implementation must keep the old matplotlib canvas until a measured equivalent is proven. |
| The old spec implied SpanSelector UX changes. | Current app intentionally does not enable drag-to-select in `plot_time` (`mf4_analyzer/ui/main_window.py:993-996`). | `enable_span_selector(cb)` remains a compatibility method only. No new button, gesture, or automatic span mode is introduced. |
| The old spec referenced `docs/superpowers/reports/2026-05-28-timedomain-surface-survey.md`, but that file is absent in the current branch. | Local check returned missing file. | This spec now embeds the required surface inventory and the companion plan adds a test-first contract freeze. |
| The adjacent `2026-05-28-review-followup-fixes.md` is historical bugfix scope, not part of the performance migration. | Current code already contains the B1-B7 fixes, including xlim tangent guard at `mf4_analyzer/ui/main_window.py:433` and dropped-frame rearm fields at `mf4_analyzer/acquisition_ui/main_window.py:214-218`. | That file is marked completed/out-of-scope; this migration must not reopen B1-B7. |

---

## 1. Goal

Make the time-domain plot feel smooth with multiple channels by replacing the TimeDomainCanvas rendering hot path, while preserving the current functional logic and the current UI.

Target scenario:

- 5 visible channels
- 100k samples per channel
- pan/zoom interaction on the time-domain chart
- no user-visible workflow changes

Performance target:

- P50 pan refresh <= 8 ms with the `asammdf.blocks.cutils.positions` path
- P95 pan refresh <= 15 ms with the `asammdf.blocks.cutils.positions` path
- If the C path is unavailable or rejected, numpy fallback must still show a measured improvement over the current matplotlib path and must be reported as fallback-grade, not as asammdf-equivalent.

---

## 2. Non-Goals

- Do not change the TimeChartCard UI: no new buttons, labels, shortcuts, hint text, control placement, or interaction model.
- Do not migrate FFTCanvas, HeatmapCanvas, SpectrogramCanvas, or PlotCanvas (order).
- Do not switch from PyQt5 to PySide6.
- Do not enable pyqtgraph OpenGL by default.
- Do not vendor or copy asammdf source code. Calling an installed dependency is allowed only after the Phase 0 dependency/license gate.
- Do not change data semantics: statistics, cursor values, range filtering, custom X axis, overlay selection, xlim preservation, color updates, and screenshot-copy behavior must match the current app.
- Do not use the completed B1-B7 review-followup spec as implementation scope for this migration.

---

## 3. Current Evidence Surface

### 3.1 Current TimeDomainCanvas contract

Current `TimeDomainCanvas` is a matplotlib `FigureCanvas` with the four signals that downstream code consumes (`mf4_analyzer/ui/canvases.py:497-502`):

- `cursor_info: pyqtSignal(str)`
- `dual_cursor_info: pyqtSignal(str)`
- `span_selected: pyqtSignal(float, float)`
- `overlay_channel_selected: pyqtSignal(object)`

Current public or externally relied-on methods/attributes:

- `plot_channels`, `clear`, `full_reset`, `set_cursor_visible`, `set_dual_cursor_mode`, `set_tick_density`, `enable_span_selector`, `get_statistics`, `invalidate_envelope_cache`, `invalidate_monotonicity_cache`
- `axes_list`, `channel_data`, `_channel_lines`, `_primary_xaxis_ax`, `_flush_pending_refresh`, `_ax`, `_bx`, `_placing`, `_refresh`

The direct private-field dependency is real. `MainWindow._reset_cursors` mutates `_ax`, `_bx`, `_placing`, and `_refresh` directly (`mf4_analyzer/ui/main_window.py:680-685`). The migration must first introduce and use `reset_cursor_state()` before the production switch.

### 3.2 Current TimeChartCard UI contract

`ChartStack` constructs `TimeDomainCanvas` and wraps it in `TimeChartCard` (`mf4_analyzer/ui/chart_stack.py:728-733`). The base `_ChartCard` creates a matplotlib `NavigationToolbar2QT` and then adds the current options/copy buttons and hint UI (`mf4_analyzer/ui/chart_stack.py:260-384`).

The Time-domain controls are the current UI and must remain unchanged:

- plot mode buttons: `分屏`, `叠加` (`mf4_analyzer/ui/chart_stack.py:554-564`)
- cursor buttons: `游标关`, `单游标`, `双游标` (`mf4_analyzer/ui/chart_stack.py:570-580`)
- shortcuts: Ctrl+1 through Ctrl+5 (`mf4_analyzer/ui/chart_stack.py:165-173`, `:603-618`)
- copy-image compositing with the floating cursor pill (`mf4_analyzer/ui/chart_stack.py:827-850`)

### 3.3 Current data and interaction logic

`MainWindow` currently expects the time canvas to preserve:

- cursor visibility and dual cursor mode (`mf4_analyzer/ui/main_window.py:347-349`)
- xlim capture/restore across subplot/overlay rebuilds (`mf4_analyzer/ui/main_window.py:382-448`)
- custom X axis and range-filter cache invalidation (`mf4_analyzer/ui/main_window.py:664-670`, `:942-956`)
- statistics computed from raw post-filter samples, not envelope output (`mf4_analyzer/ui/main_window.py:982-986`)
- time plot inputs shaped as `(name, True, x_axis, sig, color, unit, fid)` (`mf4_analyzer/ui/main_window.py:984-990`)
- retired always-on SpanSelector behavior (`mf4_analyzer/ui/main_window.py:993-996`)

### 3.4 Current ChartOptionsDialog coupling

`ChartOptionsDialog` directly calls matplotlib axis and artist methods:

- `ax.get_xlim`, `get_ylim`, `get_xlabel`, `get_xscale`, `get_lines` (`mf4_analyzer/ui/dialogs.py:536-568`, `:666-674`)
- `ax.set_title`, `set_xlim`, `set_ylim`, `autoscale`, `grid`, `legend` (`mf4_analyzer/ui/dialogs.py:595-664`)
- line/color synchronization by walking `ax.figure.canvas`, `axes_list`, and `_channel_lines` (`mf4_analyzer/ui/dialogs.py:750-793`)

Therefore the migration needs an adapter boundary. Updating dialog internals is allowed only to preserve the same UI and behavior; the dialog layout/content must not change.

### 3.5 asammdf performance evidence

Local dependency evidence:

- `.venv` has `asammdf 8.8.7`
- `.venv` has `asammdf.blocks.cutils.positions` importable
- `.venv` currently does not have `pyqtgraph` importable directly; it must be added explicitly to `requirements.txt`
- `asammdf/blocks/cutils.pyi` does not list `positions`, so the wrapper cannot rely on typing stubs alone

Local source evidence:

- asammdf `PlotSignal.trim_c` uses `positions(...)`, preallocated buffers, and trim-info caching (`.venv/lib/python3.12/site-packages/asammdf/gui/widgets/plot.py:1063-1193`)
- asammdf `paintEvent` draws into a cached pixmap, disables antialiasing, paints cached axis pictures, and then blits the curve pixmap (`.venv/lib/python3.12/site-packages/asammdf/gui/widgets/plot.py:5434-5683`)

The migration must copy the strategy, not the source.

---

## 4. Design Invariants

### 4.1 UI invariants

- The first screen and toolbar layout remain visually the same.
- The existing `TimeChartCard` controls keep the same labels, shortcuts, enabled states, and signal names.
- The bottom hint bar text remains unchanged.
- The copy-image action still captures the visible canvas plus cursor pill exactly as today.
- No new user-facing dev flag, settings toggle, or migration switch is exposed.

### 4.2 Functional invariants

- `plot_channels` accepts the existing row shape, including optional `data_id`.
- `channel_data` remains `{display_name: (t, sig, color, unit)}` and remains raw/full-resolution after range filtering, never envelope output.
- `get_statistics(time_range)` reads `channel_data` and produces the same keys and values as current code.
- Single cursor and dual cursor emit the same HTML structure as the current `_update_single` and `_format_dual_html` path.
- Overlay selection/deselection and per-series Y drag preserve the current semantics.
- Scroll behavior preserves current semantics: Ctrl+wheel zooms X, Shift+wheel zooms Y, plain wheel pans Y.
- Custom X axis invalidation and non-monotonic fallback remain valid.
- `enable_span_selector(cb)` remains callable but is not automatically enabled in `plot_time`.

### 4.3 Performance invariants

- The hot path cannot call matplotlib `draw_idle()`, `tight_layout()`, or `Line2D.set_data`.
- Pan/zoom refresh must not rebuild the whole chart structure.
- Envelope output may be cached, but statistics and cursor interpolation must use raw `channel_data`.
- The C-extension path must have a tested numpy fallback and a loggable reason when fallback is used.

---

## 5. Architecture

### 5.1 Files

New files:

- `mf4_analyzer/ui/pg_canvases.py`: pyqtgraph-backed `TimeDomainCanvasPG`, custom curve layer, toolbar adapter, and small matplotlib-like facades needed by existing code.
- `mf4_analyzer/ui/_axis_handle.py`: `AxisHandle`, `MplAxisHandle`, `PgAxisHandle`, `LineHandle`, and optional mappable no-op handles.
- `mf4_analyzer/signal/_envelope_cutils.py`: wrapper around `asammdf.blocks.cutils.positions` with numpy fallback.
- `tests/ui/test_timedomain_canvas_contract.py`: freezes the current TimeDomainCanvas public/surface contract before migration.
- `tests/ui/test_pg_timedomain_canvas.py`: pyqtgraph canvas behavior parity tests.
- `tests/ui/test_axis_handle.py`: adapter tests for matplotlib and pyqtgraph handles.
- `tests/perf/test_timedomain_pan_perf.py`: opt-in slow performance check.

Modified files:

- `requirements.txt`: add `pyqtgraph>=0.13.3`.
- `mf4_analyzer/ui/canvases.py`: keep existing matplotlib TimeDomainCanvas during migration; add only compatibility helpers if needed.
- `mf4_analyzer/ui/chart_stack.py`: instantiate the new time canvas only after parity tests pass; keep UI labels/controls unchanged.
- `mf4_analyzer/ui/dialogs.py`: accept an `AxisHandle` or adapt `Axes` through `MplAxisHandle`; dialog UI unchanged.
- `mf4_analyzer/ui/_axis_interaction.py`: route hit testing and chart-options opening through the adapter.
- `mf4_analyzer/ui/main_window.py`: replace direct cursor-private mutation with `canvas_time.reset_cursor_state()`; keep public behavior unchanged.

### 5.2 Rendering model

Production performance path:

1. Keep full-resolution arrays in `channel_data`.
2. On x-range change, compute visible min/max envelope through `positions_envelope(...)`.
3. Convert visible envelope points to pixel-space coordinates once per range.
4. Build/cache a `QPainterPath` per channel and range key.
5. Draw the curve layer into a `QPixmap` with antialiasing off.
6. During paint, blit cached axis/grid/pixmap layers and draw cursor/selection overlays.

Plain `pg.PlotDataItem.setData(...)` is not the final architecture because it does not satisfy the same cached-pixmap strategy identified in asammdf. It is allowed only for Phase 0 import/smoke validation.

### 5.3 Axis/dialog adapter

`AxisHandle` is the only contract that `ChartOptionsDialog` should know about after migration:

```python
class AxisHandle(Protocol):
    def get_xlim(self) -> tuple[float, float]: ...
    def set_xlim(self, lo: float, hi: float) -> None: ...
    def get_ylim(self) -> tuple[float, float]: ...
    def set_ylim(self, lo: float, hi: float) -> None: ...
    def autoscale(self, axis: str = "both") -> None: ...
    def set_xscale(self, scale: str) -> None: ...
    def set_yscale(self, scale: str) -> None: ...
    def get_xlabel(self) -> str: ...
    def set_xlabel(self, label: str) -> None: ...
    def get_ylabel(self) -> str: ...
    def set_ylabel(self, label: str) -> None: ...
    def get_title(self) -> str: ...
    def set_title(self, title: str) -> None: ...
    def grid(self, enabled: bool) -> None: ...
    def get_lines(self) -> list["LineHandle"]: ...
    def get_mappables(self) -> list[object]: ...
    def request_redraw(self) -> None: ...
```

For non-time canvases, `MplAxisHandle` delegates to matplotlib. For the new time canvas, `PgAxisHandle` delegates to pyqtgraph view boxes and axis items. Mappables may be empty for TimeDomain; that must only disable the existing color-map group, not change the dialog UI.

### 5.4 Toolbar adapter

The time card cannot use `NavigationToolbar2QT` once the canvas is not a matplotlib `FigureCanvas`. The replacement toolbar must preserve the existing action keys and semantics:

- action keys: `home`, `back`, `forward`, `pan`, `zoom`, `save`
- methods/properties used by existing code: `pan()`, `zoom()`, `mode`, `actions()`, `widgetForAction(...)`, `insertWidget(...)`, `addWidget(...)`, `setIconSize(...)`
- existing `apply_chinese_toolbar_labels`, `_find_action`, `_install_nav_shortcuts`, and `_apply_mdi_icons` must keep working or must be replaced with behavior-equivalent code without UI changes.

### 5.5 Compatibility facades

To reduce blast radius, the new canvas should expose compatibility objects for code that currently expects matplotlib-like surfaces:

- `axes_list`: list of lightweight axis facades.
- `_channel_lines`: `{name: (axis_facade, line_facade)}` for tests and color sync while the codebase is migrated.
- `_primary_xaxis_ax`: axis facade with `get_xlim`, `set_xlim`, and callback registry.
- `draw_idle()`: schedules or no-ops redraw without forcing a full rebuild.
- `_flush_pending_refresh()`: drains pending x-range refresh for xlim-preservation paths.
- `reset_cursor_state()`: replaces direct `_ax/_bx/_placing/_refresh` mutation in `MainWindow`.

These are compatibility seams, not new product APIs. Remove private reliance only after the pyqtgraph path is stable.

---

## 6. Execution Phases

### Phase 0: Evidence gate and dependency proof

Purpose: prove the environment and baseline before product code changes.

Required work:

- Add pyqtgraph to requirements and verify it imports with PyQt5.
- Verify `asammdf.blocks.cutils.positions` is importable on the active environment.
- Record the current matplotlib pan baseline for 5 channels x 100k samples.
- Record the current behavior-test baseline.
- Confirm dependency/license route:
  - If calling installed asammdf `positions` is approved, continue with C path.
  - If not approved or unavailable, lock to numpy fallback and lower the performance claim.

No production canvas switch is allowed in this phase.

### Phase 1: Contract freeze

Purpose: prevent accidental behavior and UI drift.

Required tests:

- Time canvas has the current four signals.
- Time canvas supports the current public methods.
- `plot_channels` keeps `channel_data` raw and keeps `data_id` metadata separate.
- `get_statistics` is unchanged before/after viewport refresh.
- xlim preservation still skips tangent-only overlap.
- always-on SpanSelector remains disabled from `plot_time`.
- TimeChartCard button labels and shortcuts are unchanged.

### Phase 2: Adapter boundaries

Purpose: decouple dialog and axis interaction without switching the renderer.

Required work:

- Add `AxisHandle`, `MplAxisHandle`, `PgAxisHandle`.
- Convert `ChartOptionsDialog` internals to the handle while preserving its UI.
- Convert `_axis_interaction.py` to construct handles.
- Add `reset_cursor_state()` to the current canvas and update `MainWindow._reset_cursors`.

Acceptance:

- Existing matplotlib canvases still pass their chart-options and axis-hit tests.
- No time-domain renderer switch yet.

### Phase 3: Envelope C path with fallback

Purpose: isolate downsampling performance before the canvas switch.

Required work:

- Add `positions_envelope(...)`.
- Match `build_envelope(...)` output semantics for empty input, reversed xlim, non-monotonic input, NaNs, small spans, and dtype changes.
- Fall back to `build_envelope(...)` when:
  - C function is unavailable
  - input is not monotonic
  - arrays are too small to benefit
  - dtype/contiguity requires a safe copy

Acceptance:

- Functional parity tests pass.
- Micro-benchmark reports current `build_envelope` vs `positions_envelope`.

### Phase 4: pyqtgraph canvas behind tests

Purpose: build the new canvas without exposing it to users.

Required work:

- Implement `TimeDomainCanvasPG` in `pg_canvases.py`.
- Implement single-channel path, axis facade, cursor signals, and raw `channel_data`.
- Implement custom curve-layer drawing path; do not rely on production `PlotDataItem.setData`.
- Implement screenshot grabbing compatible with current `ChartStack._copy_card_image`.

Acceptance:

- New pyqtgraph tests pass offscreen.
- Current matplotlib TimeDomainCanvas remains the production canvas.

### Phase 5: subplot, overlay, and interaction parity

Purpose: reach feature parity with current time-domain behavior.

Required work:

- Implement subplot mode.
- Implement overlay mode with per-channel Y axis and selection.
- Implement blank-click deselect, selected-channel Y drag, scroll behavior, hover cursor affordance, single cursor, dual cursor, and span compatibility method.
- Implement inside labels with behavior-equivalent placement. No planned 5-10% drift.
- Implement xlim-preservation and `_flush_pending_refresh` equivalent.

Acceptance:

- New parity tests cover current visible behaviors.
- Manual smoke confirms no UI control or workflow change.

### Phase 6: production switch

Purpose: make TimeDomainCanvas use the new renderer by default.

Required work:

- Switch `ChartStack` time canvas construction to the pyqtgraph canvas.
- Keep TimeChartCard UI unchanged.
- Keep the old matplotlib `TimeDomainCanvas` in the tree for one release/PR cycle.
- Run focused UI tests, full tests, slow performance check, and manual smoke.

Acceptance:

- Full tests pass.
- Performance target is met or the fallback-grade result is explicitly reported.
- No UI deltas are introduced.

### Phase 7: cleanup after stability

Purpose: remove old implementation only after production soak.

Required work:

- Delete old matplotlib TimeDomainCanvas only after the user approves cleanup.
- Keep `build_envelope` if non-time code still imports it.
- Write a retrospective report with actual baseline, final numbers, remaining risks, and verification commands.

---

## 7. Test Strategy

Focused commands:

```bash
.venv/bin/python -m pytest tests/ui/test_timedomain_canvas_contract.py -q
.venv/bin/python -m pytest tests/ui/test_axis_handle.py tests/ui/test_axis_interaction.py -q
.venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
.venv/bin/python -m pytest tests/ui/test_xlim_refresh.py tests/ui/test_canvases.py -q
```

Full regression:

```bash
.venv/bin/python -m pytest tests/ -x --no-cov -q
```

Opt-in performance check:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q -m slow
```

Manual smoke:

1. Load one file and plot one time-domain channel.
2. Plot five time-domain channels in subplot mode.
3. Plot five time-domain channels in overlay mode.
4. Switch subplot <-> overlay and confirm x window preservation.
5. Use Ctrl+wheel, Shift+wheel, plain wheel.
6. Select and deselect overlay channel; drag selected Y axis.
7. Use single cursor and dual cursor; confirm pill values.
8. Open ChartOptionsDialog and edit limits/color.
9. Copy image and confirm cursor pill is included.

---

## 8. Acceptance Criteria

- [ ] No UI control, text, shortcut, workflow, or layout change is introduced.
- [ ] Current time-domain functional logic is preserved by contract tests.
- [ ] `ChartOptionsDialog` works for matplotlib canvases and pyqtgraph time canvas.
- [ ] `pytest tests/ -x --no-cov -q` passes.
- [ ] Current matplotlib baseline and new pyqtgraph result are recorded in a report.
- [ ] 5 channel x 100k pan P50 <= 8 ms and P95 <= 15 ms on the C path.
- [ ] If C path is unavailable, fallback performance is reported honestly and not called asammdf-equivalent.
- [ ] Packaging/import smoke covers pyqtgraph.
- [ ] Old matplotlib TimeDomainCanvas remains available until the user approves cleanup.

---

## 9. Risk Register

| ID | Risk | Impact | Mitigation |
| --- | --- | --- | --- |
| R1 | `cutils.positions` is importable but not typed in `cutils.pyi` | Wrapper may drift across asammdf versions | Treat it as optional; keep a tested numpy fallback and record the actual version. |
| R2 | LGPL/legal approval is outside Codex's authority | Cannot claim approved distribution route | Phase 0 records the dependency route; fallback to numpy if approval is not given. |
| R3 | A plain pyqtgraph PlotDataItem implementation may not hit the target | False performance confidence | Production path must use custom curve/pixmap cache or must fail the Phase 4/5 performance gate. |
| R4 | Dialog adapter breaks FFT/Heatmap/Spectrogram/Order | Cross-canvas regression | Introduce `MplAxisHandle` first and run existing axis/dialog tests before pyqtgraph switch. |
| R5 | Private field compatibility hides old coupling | Later cleanup risk | Add `reset_cursor_state()` and compatibility tests; cleanup only after stable switch. |
| R6 | Overlay behavior is the largest interaction surface | Functional regression | Freeze current overlay tests before migration, then run parity tests against both canvases where practical. |
| R7 | pyqtgraph import selects the wrong Qt binding | Startup crash | Set Qt binding before importing pyqtgraph and smoke-test import under PyQt5. |
| R8 | Performance benchmark becomes flaky in CI/headless | Unreliable gate | Keep perf test opt-in/slow; require local measured report for final sign-off. |

---

## 10. Decision Log

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-05-28 | Keep scope to TimeDomainCanvas only | The performance complaint is interactive time-domain pan/zoom; other canvases are not the same hot path. |
| 2026-05-28 | Require baseline and final performance evidence | The goal is measured performance improvement, not a library swap. |
| 2026-05-28 | Keep UI unchanged as a hard invariant | User explicitly requested no UI adjustment. |
| 2026-05-28 | Use installed asammdf `positions` only behind an optional wrapper | It is locally importable but not typed in stubs and needs dependency/license gating. |
| 2026-05-28 | Keep old TimeDomainCanvas through production switch | Enables rollback while the new renderer soaks. |
