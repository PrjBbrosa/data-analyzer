# Spec Review Rev 2 — 2026-04-26-ui-polish-and-order-rpm-removal-design.md

Line references use:

- `rev2`: `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md`
- `rev1`: `docs/superpowers/reports/2026-04-26-ui-polish-and-order-rpm-removal-spec-review.md`
- `canvas-perf`: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md`
- `batch-preset`: `docs/superpowers/specs/2026-04-26-order-batch-preset-design.md`

## Rev 1 critical issues — disposition

### C1 — S5 hover conflict with default Pan: fixed

Rev 1 finding: hover short-circuited on `toolbar.mode != ''`, which breaks default Pan.

Rev 2 evidence:

- `rev2:269` explicitly says default toolbar mode is `'pan'` and that `"toolbar.mode != ''"` would make hover never trigger.
- `rev2:274-276` short-circuits only through `_is_actively_dragging()`.
- `rev2:289-293` defines active dragging as a mouse-button-down flag: `"True iff a mouse button is currently held down on this canvas"` and `_mouse_button_pressed` is set on press/release.
- Targeted grep for `toolbar.mode` in rev 2 found only the explanatory rejection at `rev2:269`; it is not used as the sole implementation guard.
- `rev2:300` says Pan/Zoom active but mouse not pressed keeps hover active.
- `rev2:423` adds S5-T7: `Pan 模式空闲（默认状态）下 hover 仍生效`.

Disposition: fixed.

### C2 — S4 deletion coverage incomplete: fixed

Each requested symbol is now explicitly listed in S4 deletion scope and covered by the unified grep acceptance test.

| Symbol | Deletion-scope evidence | Unified grep evidence | Disposition |
|---|---|---|---|
| `compute_order_spectrum` | `rev2:169` says "`compute_order_spectrum` legacy facade ... 删"; `rev2:19` also supersedes it. | `rev2:207` includes `compute_order_spectrum\b`. | fixed |
| `OrderAnalysisParams.rpm_res` | `rev2:166` says "`OrderAnalysisParams.rpm_res` 字段 ... 删"; `rev2:21` also supersedes it. | `rev2:207` includes `rpm_res`, which covers the field. | fixed |
| `spin_rpm_res` | `rev2:144` deletes inspector `spin_rpm_res`; `rev2:161` deletes batch-sheet `spin_rpm_res`; `rev2:194` deletes test references. | `rev2:207` includes `rpm_res`, which matches `spin_rpm_res`. | fixed |
| `转速-阶次` | `rev2:141` deletes the `QPushButton("转速-阶次")`; `rev2:158` deletes `"当前转速-阶次"`; `rev2:134` scopes the whole feature. | `rev2:207` includes `转速-阶次`. | fixed |
| `_compute_order_rpm_dataframe` | `rev2:178` deletes the classmethod; `rev2:23` supersedes it. | `rev2:207` includes `_compute_order_rpm_dataframe`. | fixed |

Disposition: fixed.

### C3 — Squad wave overlap: fixed

Rev 2 reorganizes by file ownership instead of feature label:

- Ownership table: signal files and non-UI tests go to `signal-processing-expert` at `rev2:506-509`; UI files and UI tests go to `pyqt-ui-engineer` at `rev2:510-514`.
- Wave 1 has two specialists:
  - W1-A owns `signal/order.py`, `signal/__init__.py`, `batch.py`, `tests/test_order_analysis.py`, and `tests/test_batch_runner.py` at `rev2:517-523`.
  - W1-B owns `inspector_sections.py`, `inspector.py`, `main_window.py`, `drawers/batch_sheet.py`, `tests/ui/test_order_worker.py`, and `tests/ui/test_inspector.py` at `rev2:524-530`.
  - Intra-wave overlap check: no shared files between W1-A and W1-B.
- Wave 2 is single-specialist `pyqt-ui-engineer` only at `rev2:534-541`; no intra-wave specialist pair exists.
- Wave 3 is single-specialist `pyqt-ui-engineer` only at `rev2:545-548`; no intra-wave specialist pair exists.
- Cross-wave reuse of `main_window.py` is explicitly sequenced and called out as not an intra-wave conflict at `rev2:539`.

Disposition: fixed.

## Rev 1 should-fix issues — disposition

### SF-1 — Canonical S4 grep: fixed

Rev 1 should-fix statement: "replace both grep commands with one canonical post-delete check that includes `order_rpm`, `rpm_order`, `OrderRpmResult`, `btn_or\b`, `order_rpm_requested`, `do_order_rpm`, `_render_order_rpm`, `compute_rpm_order_result`, `_compute_order_rpm_dataframe`, `compute_order_spectrum`, `rpm_res`, and the Chinese string `转速-阶次` unless any retained item is explicitly justified" (`rev1:18-19`).

Rev 2 says:

- `rev2:204-209` defines one unified grep.
- The grep at `rev2:207` includes all requested terms: `rpm_order`, `order_rpm`, `OrderRpmResult`, `compute_rpm_order_result`, `compute_order_spectrum\b`, `_render_order_rpm`, `do_order_rpm`, `order_rpm_requested`, `btn_or\b`, `_compute_order_rpm_dataframe`, `rpm_res`, and `转速-阶次`.

Disposition: fixed.

### SF-2 — Axis helper purity and side effects: fixed

Rev 1 should-fix statement: "specify `_find_axis_for_dblclick(fig, x_px, y_px, margin=45)` as pure, and specify `_edit_axis_dialog(parent_widget, ax, axis) -> bool` as a side-effecting UI helper; each canvas should call `draw_idle()` only when the helper returns `True`" (`rev1:21-23`).

Rev 2 says:

- `rev2:221-251` creates `_axis_interaction.py` with `find_axis_for_dblclick(fig, x_px, y_px, margin)` and `edit_axis_dialog(parent_widget, ax, axis)`.
- `rev2:230-238` labels hit detection as pure.
- `rev2:241-249` labels `edit_axis_dialog` as side-effecting and states the caller owns `draw_idle()`.
- `rev2:253-259` shows each canvas calling `self.draw_idle()` only after `edit_axis_dialog(...)` returns true.

Disposition: fixed.

### SF-3 — Toolbar i18n ordering / stable action keys: fixed

Rev 1 should-fix statement: "remove Back/Forward and wire Save/Pan/Zoom before clearing text, or preserve the original normalized action name in `act.data()` and make `_find_action`, pan/zoom hookup, and i18n all use that stable key" (`rev1:25-27`).

Rev 2 says:

- `rev2:329-352` defines `apply_chinese_toolbar_labels`.
- `rev2:343-346` preserves the English key with `act.setData(key)`.
- `rev2:347-350` explicitly avoids `act.setText("")`.
- `rev2:354-359` gives the required ordering: `_strip_subplots_action(toolbar)` -> `_find_action(toolbar, 'save')` -> `apply_chinese_toolbar_labels(toolbar)` -> later `_find_action` calls use `act.data()`.
- `rev2:364-369` updates `_find_action` to match `act.data()` first.
- `rev2:375-379` updates Pan/Zoom hookup to use `act.data()` when present.

Disposition: fixed.

### SF-4 — Hover priority table across existing modes: fixed

Rev 1 should-fix statement: "document the priority table for hover/double-click across Pan/Zoom, active rubber-band, TimeDomain cursor placement, TimeDomain SpanSelector, PlotCanvas remarks, and Spectrogram time selection; add tests for axis hover while axis lock is selected, while cursor mode is on, and while a Spectrogram slice axis is under the pointer" (`rev1:29-31`).

Rev 2 says:

- `rev2:295-307` provides the revised priority table covering mouse-drag, Pan/Zoom idle, TimeDomain cursor modes, SpanSelector, PlotCanvas remarks, Spectrogram time-slice click mode, and outside-window cases.
- `rev2:419` adds S5-T3 for Spectrogram slice-axis double-click.
- `rev2:423-425` adds tests for default Pan hover, axis-lock hover, and TimeDomain dual-cursor hover readout.

Disposition: fixed.

### SF-5 — Enumerate S1 layout calls and PlotCanvas decision: fixed

Rev 1 should-fix statement: "list every layout call to change, including `main_window.py:1257` and `main_window.py:1584`, and explicitly decide whether `PlotCanvas` should stay `20x12` or move to `10x6`" (`rev1:33-35`).

Rev 2 says:

- `rev2:51-60` lists Spectrogram, TimeDomain, PlotCanvas, FFT, and order-track layout calls, including `main_window.py:1257` and `main_window.py:1584`.
- `rev2:61` explicitly keeps `PlotCanvas` figsize unchanged at `(20, 12)`.

Disposition: fixed.

### SF-6 — Spectrogram colorbar order and bbox tests: fixed

Rev 1 should-fix statement: "specify whether `subplots_adjust` runs before or after `fig.colorbar`, and add an assertion on the colorbar axes bounding box as well as `fig.subplotpars`; for `tight_layout(pad=0.4)`, verify actual label/text bounding boxes..." (`rev1:37-39`).

Rev 2 says:

- `rev2:54` requires `subplots_adjust(**SPECTROGRAM_SUBPLOT_ADJUST)` after `fig.colorbar(...)`.
- `rev2:70-74` repeats the after-colorbar rationale in the constant comment.
- `rev2:89-92` adds S1-T1 through S1-T4 covering subplotpars, colorbar bbox non-overlap, and ylabel-vs-ytick bbox non-overlap.

Disposition: fixed.

### SF-7 — Acceptance test coverage: fixed

Rev 1 should-fix statement: "add explicit test names for S1 subplotpars plus colorbar bbox, S2 `update_stats({})` on return to time mode, S3 reset-to-default display names, S4 no `rpm_res`/`order_rpm` leftovers if deleted, S5 Back/Forward removal, Chinese segmented buttons, default-pan hover behavior, axis-lock hover, and Spectrogram main/slice double-click" (`rev1:41-43`).

Rev 2 says:

- S1 test coverage is listed at `rev2:85-93`.
- S2 includes `update_stats({})` returning to time mode at `rev2:109`.
- S3 includes reset-to-default display names at `rev2:131`.
- S4 includes unified `rpm_res` / `order_rpm` grep at `rev2:207` and S4-T1 at `rev2:213`.
- S5 includes Spectrogram slice-axis double-click, default Pan hover, axis-lock hover, Back/Forward removal, and Chinese segmented buttons at `rev2:419`, `rev2:423-429`.

Disposition: fixed. Note: several tests are named by acceptance ID plus file rather than final pytest function name, but every rev 1 missing behavior now has an explicit test slot.

### SF-8 — Supersedes prior spec: partial

Rev 1 should-fix statement: "add a short 'Supersedes prior spec' paragraph naming the exact prior clauses now void: `compute_rpm_order_result`, `_render_order_rpm`, `OrderRpmResult`, `do_order_rpm`, RPM-bin tests, and `compute_order_spectrum` if it is removed" (`rev1:45-47`).

Rev 2 says:

- `rev2:14-25` adds `## 0. Supersedes prior spec`.
- `rev2:18-23` names `compute_rpm_order_result`, `compute_order_spectrum`, `OrderRpmResult`, `OrderAnalysisParams.rpm_res`, `do_order_rpm`, `_render_order_rpm`, `_compute_order_rpm_dataframe`, and `order_rpm`.
- `rev2:25` voids counts, argmin vectorization, and `_render_order_rpm` imshow-direction clauses.

Remaining issue:

- `rev2:19` and `rev2:169` cite a prior `§A4`; `rg -n "A4|§A4"` in `canvas-perf` found no such section. The actual public API guarantee is `canvas-perf:446-448` under `### 6.1 OrderAnalyzer 公共方法保持不变`.
- `rev2:25` cites `§6.2 / §A4` for counts, argmin, and `_render_order_rpm`; `canvas-perf:450-477` shows §6.2 is `PlotCanvas.plot_or_update_heatmap`, not those RPM-order clauses.

Disposition: partial.

## Rev 1 nice-to-have — disposition

### NTH-1 — Named constants: partial

Rev 1 nice-to-have statement: "define named module constants such as `CHART_TIGHT_LAYOUT_KW`, `SPECTROGRAM_SUBPLOT_ADJUST`, `SPECTROGRAM_COLORBAR_PAD`, and `AXIS_HIT_MARGIN_PX`, then test those behaviorally" (`rev1:51-53`).

Rev 2 says:

- `rev2:63-79` defines `CHART_TIGHT_LAYOUT_KW`, `SPECTROGRAM_SUBPLOT_ADJUST`, and `AXIS_HIT_MARGIN_PX`.
- `rev2:89-92` behaviorally tests the layout effects.
- `SPECTROGRAM_COLORBAR_PAD` was not found after grep for `SPECTROGRAM_COLORBAR_PAD`. Rev 2 leaves colorbar pad unchanged at `rev2:53`, so this is not a functional blocker.

Disposition: partial.

### NTH-2 — Do not mention blank-area double-click in Home tooltip: fixed

Rev 1 nice-to-have statement: "keep Home tooltip to `重置视图` for this iteration, and add the blank-area hint only in the future task that implements it" (`rev1:55-57`).

Rev 2 says:

- `_ACTION_TOOLTIPS['home']` is `('重置视图', True)` at `rev2:318-320`.
- Blank-area double-click reset is excluded and the tooltip no longer mentions it at `rev2:435`.

Disposition: fixed.

### NTH-3 — New helper and test files are explicit: fixed

Rev 1 nice-to-have statement: "the plan should create the modules before wiring imports and should either create the named test files or state which existing test files will be extended" (`rev1:59-61`).

Rev 2 says:

- `rev2:221` creates `_axis_interaction.py`.
- `rev2:312` creates `_toolbar_i18n.py`.
- `rev2:445-451` lists new modules and new test files.
- `rev2:429-431` states existing `tests/ui/test_chart_stack.py` will be extended for segmented buttons, toolbar height, and `_TOOL_HINTS`.

Disposition: fixed.

### NTH-4 — Toolbar QSS selector robustness: fixed

Rev 1 nice-to-have statement: "verify the selector actually matches `NavigationToolbar2QT`; using both `QToolBar#chartToolbar` and `QWidget#chartToolbar` would be safer across Qt style resolution" (`rev1:63-65`).

Rev 2 says:

- `rev2:405-410` includes `QToolBar#chartToolbar`, `QWidget#chartToolbar`, and `NavigationToolbar2QT#chartToolbar`.

Disposition: fixed.

## §0 Supersedes section — verification

- Present: rev 2 has `## 0. Supersedes prior spec` at `rev2:14`.
- It names the two related prior specs at `rev2:16`.
- It correctly names the main voided symbols and behavior from `canvas-perf`: `compute_rpm_order_result`, `compute_order_spectrum`, `OrderRpmResult`, `do_order_rpm`, `_render_order_rpm`, counts, argmin vectorization, and imshow orientation at `rev2:18-25`.
- Those clauses are present in `canvas-perf`, but not under the section names rev 2 cites:
  - `compute_rpm_order_result`, counts, and argmin appear in `canvas-perf:32-34`.
  - `do_order_rpm` appears in `canvas-perf:42`.
  - `compute_order_spectrum` public API guarantee appears in `canvas-perf:446-448` under §6.1.
  - `_render_order_rpm` appears in the worker result path at `canvas-perf:226-235` and in the orientation-risk row at `canvas-perf:549`.
  - No `§A4` or `A4` heading was found after grep in `canvas-perf`.
  - `canvas-perf:450-477` shows §6.2 is `PlotCanvas.plot_or_update_heatmap`, not the RPM counts/argmin clauses.
- It partially names voided items from `batch-preset`:
  - `batch-preset:17-33` lists `OrderRpmResult` and `compute_order_spectrum`.
  - `batch-preset:44-49` lists supported methods including `order_rpm`.
  - Rev 2 supersedes `BatchRunner._compute_order_rpm_dataframe` and `SUPPORTED_METHODS` at `rev2:23`, but those exact clause names are not present in `batch-preset`; only the supported-methods section is present.

Result: partial. The section exists and resolves the substantive conflict, but it should replace nonexistent `§A4` / misleading `§6.2` references with the actual prior sections: `canvas-perf` §2.1 included bullets, §4.3 worker flow, §6.1 public API, §7 acceptance #13, and `batch-preset` `### Order Analysis` / `### Batch Presets`.

## Module-level constants — verification

| Constant | Rev 2 values | Reasonableness | Usage references |
|---|---|---|---|
| `CHART_TIGHT_LAYOUT_KW` | `dict(pad=0.4, h_pad=0.6, w_pad=0.4)` at `rev2:68` | Valid `Figure.tight_layout` kwargs. Values are tight but plausible for compact Chinese UI; bbox tests are required by `rev2:83` and `rev2:92`. | Used for TimeDomain, PlotCanvas, FFT, and order-track tight layout replacements at `rev2:55-60`. |
| `SPECTROGRAM_SUBPLOT_ADJUST` | `dict(left=0.07, right=0.93, top=0.97, bottom=0.09)` at `rev2:72-74` | Valid `subplots_adjust` kwargs. `right=0.93` is reasonable because Spectrogram has a right-side colorbar; this correction is explained at `rev2:81`. | Used after `fig.colorbar(...)` at `rev2:54`; tested by S1-T1/S1-T3 at `rev2:89-91`. |
| `AXIS_HIT_MARGIN_PX` | `45` at `rev2:78` | Reasonable pixel gutter for axis tick-label hit detection; it matches the existing PlotCanvas margin called out in rev 1. | Used in dblclick helper call at `rev2:256` and hover helper call at `rev2:276`. |

Result: verified. The required constants are present, valid for their target APIs, and referenced where used.

## Acceptance test coverage — S1 through S5

### S1

| Acceptance criterion | Test plan | Covered? |
|---|---|---|
| S1-T1: Spectrogram `fig.subplotpars.right == 0.93 ± 0.005` (`rev2:89`) | `tests/ui/test_canvas_compactness.py::test_spectrogram_subplotpars` (`rev2:89`) | covered |
| S1-T2: TimeDomain / FFT / order_track `left ≤ 0.10` and `top ≥ 0.93` (`rev2:90`) | Same file, four tests (`rev2:90`) | covered |
| S1-T3: colorbar bbox does not overlap spectrogram axes (`rev2:91`) | Same file (`rev2:91`) | covered |
| S1-T4: ylabel bbox does not overlap yticks bbox (`rev2:92`) | Same file (`rev2:92`) | covered |
| S1-T5: four-mode screenshots archived (`rev2:93`) | Manual screenshot pass (`rev2:93`) | covered manually; see new issue #3 on optional-vs-required wording |

Gaps: none.

### S2

| Acceptance criterion | Test plan | Covered? |
|---|---|---|
| S2-T1: default stats visibility equals default mode == `time` (`rev2:106`) | `tests/ui/test_chart_stack_stats_visibility.py` (`rev2:106`) | covered |
| S2-T2: `fft` / `fft_time` / `order` hide stats strip (`rev2:107`) | Same file (`rev2:107`) | covered |
| S2-T3: returning from `fft` to `time` shows stats strip (`rev2:108`) | Same file (`rev2:108`) | covered |
| S2-T4: returning to time and calling `update_stats({})` shows `"— 无通道 —"` (`rev2:109`) | Same file (`rev2:109`) | covered |

Gaps: none.

### S3

| Acceptance criterion | Test plan | Covered? |
|---|---|---|
| S3-T1: new preset bar slot text is `配置1 / 配置2 / 配置3` (`rev2:130`) | `tests/ui/test_inspector.py::test_fft_time_preset_bar_default_names` (`rev2:130`) | covered |
| S3-T2: reset-to-default keeps new names (`rev2:131`) | Same file (`rev2:131`) | covered |
| S3-T3: legacy override `display_name: '诊断模式'` still displays override (`rev2:132`) | Same file (`rev2:132`) | covered |

Gaps: none.

### S4

| Acceptance criterion | Test plan | Covered? |
|---|---|---|
| S4-T1: unified grep has zero hits (`rev2:213`) | CI / spec acceptance command at `rev2:207` (`rev2:213`) | covered |
| S4-T2: `pytest tests/` green (`rev2:214`) | CI (`rev2:214`) | covered |
| S4-T3: order UI shows only `时间-阶次` / `阶次跟踪` / `取消计算` (`rev2:215`) | Manual + `tests/ui/test_inspector.py::test_order_contextual_buttons_after_rpm_removal` (`rev2:215`) | covered |

Gaps: none against stated criteria. See new issue #1 for stale `rpm` kind literal risk in the implementation instructions.

### S5

| Acceptance criterion | Test plan | Covered? |
|---|---|---|
| S5-T1: four canvases double-click X axis opens AxisEditDialog and calls `set_xlim` (`rev2:417`) | `tests/ui/test_axis_interaction.py` (`rev2:417`) | covered |
| S5-T2: four canvases double-click Y axis opens AxisEditDialog (`rev2:418`) | Same file (`rev2:418`) | covered |
| S5-T3: Spectrogram slice subplot axis double-click works (`rev2:419`) | Same file (`rev2:419`) | covered |
| S5-T4: axis hover sets pointing cursor and tooltip (`rev2:420`) | Same file (`rev2:420`) | covered |
| S5-T5: leaving axis region unsets cursor (`rev2:421`) | Same file (`rev2:421`) | covered |
| S5-T6: mouse-button-down hover does not alter cursor (`rev2:422`) | Same file (`rev2:422`) | covered |
| S5-T7: idle default Pan mode still allows hover (`rev2:423`) | Same file (`rev2:423`) | covered |
| S5-T8: axis-lock state still allows axis hover cursor (`rev2:424`) | Same file (`rev2:424`) | covered |
| S5-T9: TimeDomain dual-cursor mode keeps cursor readout while hovering axis (`rev2:425`) | Same file (`rev2:425`) | covered |
| S5-T10: Pan/Zoom/Save tooltips are Chinese after i18n (`rev2:426`) | `tests/ui/test_toolbar_i18n.py` (`rev2:426`) | covered |
| S5-T11: Back/Forward actions removed (`rev2:427`) | Same file (`rev2:427`) | covered |
| S5-T12: `_find_action(toolbar, 'save')` still works after i18n (`rev2:428`) | Same file (`rev2:428`) | covered |
| S5-T13: time-card segmented buttons use new Chinese text (`rev2:429`) | `tests/ui/test_chart_stack.py` extension (`rev2:429`) | covered |
| S5-T14: toolbar height is less than or equal to baseline (`rev2:430`) | Same file (`rev2:430`) | covered |
| S5-T15: `_TOOL_HINTS['']` contains `双击坐标轴` (`rev2:431`) | Same file (`rev2:431`) | covered |

Gaps: none.

## _find_action ordering — verification

Result: fixed.

- `act.setData(key)` is specified at `rev2:345`.
- `_find_action` reads `act.data()` first and falls back to text at `rev2:364-369`.
- Pan/Zoom hookup uses `act.data()` when present at `rev2:375-379`.
- Ordering is explicit at `rev2:354-359`: `_strip_subplots_action(toolbar)` first, `_find_action(toolbar, 'save')` second, `apply_chinese_toolbar_labels(toolbar)` third, then later `_find_action` calls use `act.data()`.
- This preserves the existing `_strip_subplots_action` position because rev 2 says strip remains before i18n and still text-matches subplots actions at `rev2:480`.

## New issues found in rev 2

1. **S4 uses stale `rpm_order` worker-kind wording where current code uses `rpm`.** Rev 2 says to delete `OrderWorker.run` `kind == 'rpm_order'`, `_dispatch_order_worker` `'rpm_order'`, and `_on_order_result` `result_kind == 'rpm_order'` at `rev2:152`, `rev2:155-156`. Current source uses `elif self._kind == 'rpm'` at `mf4_analyzer/ui/main_window.py:124`, dispatches `_dispatch_order_worker('rpm', ...)` at `mf4_analyzer/ui/main_window.py:1341`, and renders `elif kind == 'rpm'` at `mf4_analyzer/ui/main_window.py:1455-1456`. The spec should say "delete the `rpm` worker/result branch" or explicitly cover both `rpm` and `rpm_order`; otherwise an implementer could remove the method/call sites but leave a stale branch.

2. **§0 prior-spec section references are inaccurate.** Rev 2 cites `§A4` at `rev2:19` and `rev2:169`, and cites `§6.2 / §A4` for RPM counts/argmin/renderer clauses at `rev2:25`. Grep found no `A4` section in `canvas-perf`, and `canvas-perf:450-477` shows §6.2 is `PlotCanvas.plot_or_update_heatmap`. Use the actual sections/lines identified in the §0 verification above.

3. **S1-T5 is both optional and required.** The S1 acceptance table labels S1-T5 as `可选手动` at `rev2:93`, but the summary checklist requires `S1-T1 至 S1-T5 全过` at `rev2:488`. Decide whether screenshot archiving is required for sign-off or optional evidence.

## Affirmations

- Rev 1 critical C1/C2/C3 are fixed in rev 2.
- The S4 deletion scope now explicitly includes `compute_order_spectrum`, `OrderAnalysisParams.rpm_res`, both `spin_rpm_res` surfaces, `转速-阶次`, and `_compute_order_rpm_dataframe`.
- The S5 hover rule now uses a mouse-button-down flag, not toolbar mode, and includes a default-Pan idle hover test.
- Module constants required by this review are present and referenced in implementation steps.
- All stated S1-S5 acceptance criteria have a corresponding automated or manual test slot.
- `_find_action` ordering and `act.data()`-based lookup are specified clearly.

## Verdict

approved with minor revisions

Rev 2 fixes the rev 1 critical blockers and most should-fix items with concrete scope, ownership, and tests. Before turning this into an execution plan, revise the stale `rpm_order` worker-kind wording to match the current `rpm` branch, correct the §0 prior-spec citations, and make S1-T5 either required or optional consistently.
