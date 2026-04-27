## Critical Issues

1. **Dimension: S5 hover detection conflict states**  
   Problem: the spec says axis hover should short-circuit whenever `toolbar.mode != ''`, but every chart card currently turns Pan on by default, so the hover acceptance criterion can never fire in the default UI state. The conflict is between the hover requirement at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:143-148`, the risk mitigation at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:239-240`, and `_ChartCard.__init__` activating pan at `mf4_analyzer/ui/chart_stack.py:206-210`.  
   Recommended fix: either stop enabling pan by default before implementing hover, or define the hover short-circuit as "actively dragging/panning/zooming" rather than any non-empty toolbar mode; add a test that constructs `ChartStack`, leaves the default toolbar state untouched, and verifies axis hover still changes the cursor.

2. **Dimension: S4 deletion coverage**  
   Problem: the "entire RPM-order chain" deletion scope omits surviving RPM-resolution UI/params and the legacy `compute_order_spectrum` API, leaving dead or contradictory RPM-binned order surfaces after the button/method deletion. The spec's S4 file list covers `btn_or`, signals, `OrderRpmResult`, `compute_rpm_order_result`, batch `order_rpm`, and `_compute_order_rpm_dataframe` at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:61-94`, but `rpm_res` remains user-facing in `mf4_analyzer/ui/inspector_sections.py:1051-1055`, persisted in presets at `mf4_analyzer/ui/inspector_sections.py:1131` and `mf4_analyzer/ui/inspector_sections.py:1145-1146`, exposed in the batch sheet at `mf4_analyzer/ui/drawers/batch_sheet.py:143-146` and `mf4_analyzer/ui/drawers/batch_sheet.py:193`, and carried by `OrderAnalysisParams` at `mf4_analyzer/signal/order.py:30`. The legacy RPM-order tuple API is still `compute_order_spectrum` at `mf4_analyzer/signal/order.py:439-451`; the prior spec explicitly said that API must continue at `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:446-448`, which now conflicts with deletion.  
   Recommended fix: explicitly decide whether `rpm_res`, `spin_rpm_res`, batch `rpm_res`, tests asserting `rpm_res`, and `compute_order_spectrum` are deleted, deprecated with a clear error, or retained for compatibility; if the chain is truly deleted, add those symbols and tests to S4.

3. **Dimension: Squad wave breakdown**  
   Problem: the proposed waves assign overlapping write ownership, which creates predictable rework. Wave 1 says `refactor-architect` owns "S4 entire chain + S1 constants" while Wave 2 says `signal-processing-expert` owns "S4 signal layer + tests" at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:270-272`; the file impact list puts S4 signal files, UI files, batch files, and tests in the same spec at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:204-214`. Wave 3 then also edits `canvases.py`, `chart_stack.py`, `inspector_sections.py`, and `main_window.py` at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:204-209`, overlapping the Wave 1 S4 UI deletion.  
   Recommended fix: split by file ownership, not feature label: signal expert owns `mf4_analyzer/signal/order.py`, `mf4_analyzer/signal/__init__.py`, `mf4_analyzer/batch.py`, `tests/test_order_analysis.py`, and `tests/test_batch_runner.py`; UI engineer owns `inspector_sections.py`, `inspector.py`, `main_window.py`, `batch_sheet.py`, `chart_stack.py`, `canvases.py`, `style.qss`, and UI tests; refactor-architect should review/coordinate only or own a disjoint constants/doc slice.

## Should-Fix Issues

1. **Dimension: S4 deletion coverage**  
   Problem: the final acceptance grep is weaker than the earlier S4 grep and would miss real leftovers. The fuller deletion grep at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:118` includes `compute_rpm_order_result`, `do_order_rpm`, and `_render_order_rpm`, but the checklist grep at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:251` only checks `rpm_order`, `OrderRpmResult`, `order_rpm_requested`, and `btn_or`. It would miss standalone `order_rpm` hits such as `mf4_analyzer/batch.py:89`, `mf4_analyzer/batch.py:194-196`, `mf4_analyzer/ui/drawers/batch_sheet.py:108`, and `mf4_analyzer/ui/main_window.py:1527`, plus `_compute_order_rpm_dataframe` at `mf4_analyzer/batch.py:280`.  
   Recommended fix: replace both grep commands with one canonical post-delete check that includes `order_rpm`, `rpm_order`, `OrderRpmResult`, `btn_or\b`, `order_rpm_requested`, `do_order_rpm`, `_render_order_rpm`, `compute_rpm_order_result`, `_compute_order_rpm_dataframe`, `compute_order_spectrum`, `rpm_res`, and the Chinese string `转速-阶次` unless any retained item is explicitly justified.

2. **Dimension: S5 architectural soundness of module extraction**  
   Problem: `_find_axis_for_dblclick` can be a module-level helper, but `_edit_axis_dialog` is not a pure function as described in the review task: it opens a Qt dialog, mutates the axes, and currently calls `self.draw_idle()`. The current implementation reads only `self.fig` and event pixels in `_find_axis_for_dblclick` at `mf4_analyzer/ui/canvases.py:1649-1654`, but `_edit_axis` constructs `AxisEditDialog(self.parent(), ax, axis)` at `mf4_analyzer/ui/canvases.py:1706-1709`, mutates limits/labels at `mf4_analyzer/ui/canvases.py:1711-1724`, and redraws via `self.draw_idle()` at `mf4_analyzer/ui/canvases.py:1725`. `AxisEditDialog` itself is a stateful `QDialog` at `mf4_analyzer/ui/dialogs.py:230-270`.  
   Recommended fix: specify `_find_axis_for_dblclick(fig, x_px, y_px, margin=45)` as pure, and specify `_edit_axis_dialog(parent_widget, ax, axis) -> bool` as a side-effecting UI helper; each canvas should call `draw_idle()` only when the helper returns `True`.

3. **Dimension: S5 toolbar i18n / button removal**  
   Problem: clearing action text can break existing toolbar wiring if applied too early. `_ChartCard` finds Save by exact text at `mf4_analyzer/ui/chart_stack.py:169-171` and hooks Pan/Zoom by action text at `mf4_analyzer/ui/chart_stack.py:201-204`; the spec proposes `act.setText("")` at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:152-160` and Back/Forward removal at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:175-178`.  
   Recommended fix: remove Back/Forward and wire Save/Pan/Zoom before clearing text, or preserve the original normalized action name in `act.data()` and make `_find_action`, pan/zoom hookup, and i18n all use that stable key.

4. **Dimension: Hover detection conflict states**  
   Problem: the spec mentions pan/zoom and rubber-band, but not all existing mouse modes. Time-domain cursor placement uses `_cursor_visible`, `_dual`, `_placing`, `_ax`, and `_bx` at `mf4_analyzer/ui/canvases.py:354-364`, places A/B on click at `mf4_analyzer/ui/canvases.py:910-916`, and updates cursor readouts on motion at `mf4_analyzer/ui/canvases.py:931-938`. Time-domain span selection is a `SpanSelector` at `mf4_analyzer/ui/canvases.py:846-852` and is disabled only when axis lock is active at `mf4_analyzer/ui/canvases.py:1025-1029`. Plot remarks are another click mode via `_remark_enabled` at `mf4_analyzer/ui/canvases.py:1442-1445`, `set_remark_enabled` at `mf4_analyzer/ui/canvases.py:1569-1570`, and click handling at `mf4_analyzer/ui/canvases.py:1696-1704`. Spectrogram span-selection is NOT FOUND in repo: `rg -n "SpanSelector|span" mf4_analyzer/ui/canvases.py` only finds the time-domain selector at `mf4_analyzer/ui/canvases.py:846-852`; Spectrogram has click-to-select-time at `mf4_analyzer/ui/canvases.py:1329-1335` and hover readout at `mf4_analyzer/ui/canvases.py:1337-1359`.  
   Recommended fix: document the priority table for hover/double-click across Pan/Zoom, active rubber-band, TimeDomain cursor placement, TimeDomain SpanSelector, PlotCanvas remarks, and Spectrogram time selection; add tests for axis hover while axis lock is selected, while cursor mode is on, and while a Spectrogram slice axis is under the pointer.

5. **Dimension: S1 figsize and layout changes**  
   Problem: S1 does not enumerate every layout call that affects the four displayed modes. Current tight-layout calls are `mf4_analyzer/ui/canvases.py:486`, `mf4_analyzer/ui/canvases.py:516`, `mf4_analyzer/ui/canvases.py:535`, `mf4_analyzer/ui/canvases.py:1246`, `mf4_analyzer/ui/canvases.py:1555`, `mf4_analyzer/ui/main_window.py:1257`, and `mf4_analyzer/ui/main_window.py:1584`; S1 mentions TimeDomain and PlotCanvas at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:31-32` but the FFT and order-track direct calls live in `main_window.py`. The spec also says Spectrogram `figsize=(10, 6)` aligns with other canvases at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:27-30`, but `PlotCanvas` is currently `figsize=(20, 12)` at `mf4_analyzer/ui/canvases.py:1434-1436`.  
   Recommended fix: list every layout call to change, including `main_window.py:1257` and `main_window.py:1584`, and explicitly decide whether `PlotCanvas` should stay `20x12` or move to `10x6`.

6. **Dimension: S1 colorbar and pad risk**  
   Problem: the proposed Spectrogram `subplots_adjust(right=0.97)` leaves the call order and colorbar geometry under-specified. Current Spectrogram creates a colorbar at `mf4_analyzer/ui/canvases.py:1227` and then suppresses `tight_layout` warnings at `mf4_analyzer/ui/canvases.py:1239-1248`; the spec proposes `right=0.97` and `pad=0.015` at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:27-30`, while acknowledging label/colorbar collision risk at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:237-240`.  
   Recommended fix: specify whether `subplots_adjust` runs before or after `fig.colorbar`, and add an assertion on the colorbar axes bounding box as well as `fig.subplotpars`; for `tight_layout(pad=0.4)`, verify actual label/text bounding boxes because y-labels use explicit `labelpad=12` in time-domain paths at `mf4_analyzer/ui/canvases.py:478-480`, `mf4_analyzer/ui/canvases.py:507-510`, and `mf4_analyzer/ui/canvases.py:531-533`.

7. **Dimension: Test coverage**  
   Problem: several acceptance criteria have no corresponding listed test. S1 lists screenshot review and subplotpars assertions at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:248`, but the test plan at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:216-229` has no S1 test file or case. S2 acceptance says visibility in non-time modes and visible on return at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:249`, while the listed test is only `test_stats_strip_visible_only_in_time_mode` at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:223-224`; the earlier S2 text also requires `update_stats({})` to show "— 无通道 —" at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:39`. S3 acceptance includes reset-to-default names at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:250`, but the listed test at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:225-226` only names default slot text. S5 acceptance includes toolbar height and segmented button Chinese text at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:252-258`, but the listed tests at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:216-224` do not cover Back/Forward removal, toolbar height, segmented button text, pan/zoom hover short-circuit, rubber-band hover short-circuit, or Spectrogram slice-axis double-click.  
   Recommended fix: add explicit test names for S1 subplotpars plus colorbar bbox, S2 `update_stats({})` on return to time mode, S3 reset-to-default display names, S4 no `rpm_res`/`order_rpm` leftovers if deleted, S5 Back/Forward removal, Chinese segmented buttons, default-pan hover behavior, axis-lock hover, and Spectrogram main/slice double-click.

8. **Dimension: Consistency with prior spec**  
   Problem: the new spec references the prior spec and says it deletes some prior RPM-order entries at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:7-8`, but it does not explicitly supersede the prior spec's public API guarantee that `compute_order_spectrum` continues working at `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:446-448`.  
   Recommended fix: add a short "Supersedes prior spec" paragraph naming the exact prior clauses now void: `compute_rpm_order_result`, `_render_order_rpm`, `OrderRpmResult`, `do_order_rpm`, RPM-bin tests, and `compute_order_spectrum` if it is removed.

## Nice-to-Have Suggestions

1. **Dimension: S1 figsize and layout changes**  
   Problem: the spec introduces multiple magic numbers without naming them: `figsize=(10, 6)`, `hspace=0.18`, `left=0.07`, `right=0.97`, `top=0.97`, `bottom=0.09`, `pad=0.015`, and `tight_layout(pad=0.4, h_pad=0.6, w_pad=0.4)` at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:27-33`. The current axis-hit margin is also a literal `MARGIN = 45` at `mf4_analyzer/ui/canvases.py:1649-1651`.  
   Recommended fix: define named module constants such as `CHART_TIGHT_LAYOUT_KW`, `SPECTROGRAM_SUBPLOT_ADJUST`, `SPECTROGRAM_COLORBAR_PAD`, and `AXIS_HIT_MARGIN_PX`, then test those behaviorally.

2. **Dimension: S5 toolbar i18n**  
   Problem: the proposed Home tooltip includes a future behavior that the same spec excludes. The tooltip text says Home should mention "or double-click blank area" at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:153-155`, but blank-area double-click reset is explicitly excluded at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:188-191`.  
   Recommended fix: keep Home tooltip to "重置视图" for this iteration, and add the blank-area hint only in the future task that implements it.

3. **Dimension: S5 module extraction / new files**  
   Problem: the proposed helper modules and new test files are NOT FOUND in repo at review time. `rg --files mf4_analyzer/ui | rg "_axis_interaction|_toolbar_i18n"` returned 0 lines, and `rg --files tests` returned existing files such as `tests/ui/test_chart_stack.py`, `tests/ui/test_inspector.py`, and `tests/ui/test_order_worker.py` but no `tests/ui/test_axis_interaction.py`, `tests/ui/test_toolbar_i18n.py`, `tests/ui/test_chart_stack_stats_visibility.py`, or `tests/ui/test_inspector_presets.py`.  
   Recommended fix: this is expected pre-implementation, but the plan should create the modules before wiring imports and should either create the named test files or state which existing test files will be extended.

4. **Dimension: S5 toolbar padding**  
   Problem: the spec says to add `QToolBar#chartToolbar { spacing: 1px; padding: 1px; }` at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:170-173`, while current QSS targets `NavigationToolbar2QT, QWidget#chartToolbar` at `mf4_analyzer/ui/style.qss:508-512` and chart choice buttons at `mf4_analyzer/ui/style.qss:571-579`.  
   Recommended fix: verify the selector actually matches `NavigationToolbar2QT`; using both `QToolBar#chartToolbar` and `QWidget#chartToolbar` would be safer across Qt style resolution.

## Affirmations

1. **Dimension: S4 deletion coverage**  
   Verified: the required-symbol grep across `mf4_analyzer/` and `tests/` produces the following complete hit list at review time:

   ```text
   tests/test_order_analysis.py:32:def test_rpm_order_counts_are_per_frame_not_per_nonzero(monkeypatch):
   tests/test_order_analysis.py:33:    """compute_rpm_order_result 的 counts 应按帧数累加，而非按非零幅值次数。
   tests/test_order_analysis.py:71:    result = OrderAnalyzer.compute_rpm_order_result(sig, rpm, params)
   tests/test_order_analysis.py:165:    """compute_time/rpm_order_result 与 extract_order_track_result 都必须
   tests/test_order_analysis.py:194:    r_rpm = OrderAnalyzer.compute_rpm_order_result(sig, rpm, p_rpm)
   tests/test_order_analysis.py:230:def test_metadata_records_nyquist_clipped_at_median_rpm_orders():
   mf4_analyzer/signal/__init__.py:3:from .order import OrderAnalysisParams, OrderAnalyzer, OrderRpmResult, OrderTimeResult, OrderTrackResult
   mf4_analyzer/signal/__init__.py:12:    'OrderRpmResult',
   mf4_analyzer/batch.py:195:                df = self._compute_order_rpm_dataframe(sig, rpm, fs, preset.params)
   mf4_analyzer/batch.py:280:    def _compute_order_rpm_dataframe(cls, sig, rpm, fs, params):
   mf4_analyzer/batch.py:281:        result = OrderAnalyzer.compute_rpm_order_result(
   mf4_analyzer/signal/order.py:44:class OrderRpmResult:
   mf4_analyzer/signal/order.py:292:    def compute_rpm_order_result(sig, rpm, params, progress_callback=None, cancel_token=None):
   mf4_analyzer/signal/order.py:351:        return OrderRpmResult(
   mf4_analyzer/signal/order.py:448:        result = OrderAnalyzer.compute_rpm_order_result(
   mf4_analyzer/ui/inspector.py:43:    order_rpm_requested = pyqtSignal()
   mf4_analyzer/ui/inspector.py:132:        self.order_ctx.order_rpm_requested.connect(self.order_rpm_requested)
   mf4_analyzer/ui/inspector_sections.py:974:    order_rpm_requested = pyqtSignal()
   mf4_analyzer/ui/inspector_sections.py:1069:        self.btn_or = QPushButton("转速-阶次")
   mf4_analyzer/ui/inspector_sections.py:1070:        self.btn_or.setProperty("role", "primary")
   mf4_analyzer/ui/inspector_sections.py:1072:        two_btns.addWidget(self.btn_or)
   mf4_analyzer/ui/inspector_sections.py:1112:        self.btn_or.clicked.connect(self.order_rpm_requested)
   tests/ui/test_order_worker.py:136:def test_render_order_rpm_uses_correct_extent_and_matrix_orientation(qtbot, tmp_path):
   tests/ui/test_order_worker.py:141:    from mf4_analyzer.signal.order import OrderRpmResult, OrderAnalysisParams
   tests/ui/test_order_worker.py:146:    result = OrderRpmResult(
   tests/ui/test_order_worker.py:158:    win._render_order_rpm(result)
   tests/ui/test_inspector.py:82:    with qtbot.waitSignal(oc.order_rpm_requested, timeout=200):
   tests/ui/test_inspector.py:83:        oc.btn_or.click()
   mf4_analyzer/ui/main_window.py:125:                r = OrderAnalyzer.compute_rpm_order_result(
   mf4_analyzer/ui/main_window.py:304:        self.inspector.order_rpm_requested.connect(self.do_order_rpm)
   mf4_analyzer/ui/main_window.py:1318:    def do_order_rpm(self):
   mf4_analyzer/ui/main_window.py:1456:            self._render_order_rpm(result)
   mf4_analyzer/ui/main_window.py:1501:    def _render_order_rpm(self, result):
   ```

2. **Dimension: S1 figsize and layout changes**  
   Verified: the current Spectrogram values match the spec's baseline claim: `Figure(figsize=(12, 8))` at `mf4_analyzer/ui/canvases.py:1104-1106`, `hspace=0.28` at `mf4_analyzer/ui/canvases.py:1205`, `fig.colorbar(..., pad=0.01)` at `mf4_analyzer/ui/canvases.py:1227`, and suppressed `tight_layout()` at `mf4_analyzer/ui/canvases.py:1239-1248`.

3. **Dimension: S2 StatsStrip visibility**  
   Verified: `ChartStack` mounts `stats_strip` at the bottom at `mf4_analyzer/ui/chart_stack.py:377-379`, and mode changes are centralized through `ChartStack.set_mode` at `mf4_analyzer/ui/chart_stack.py:398-403`. A targeted grep shows the chart stack itself only calls `self.stack.setCurrentIndex(idx)` at `mf4_analyzer/ui/chart_stack.py:402`; external mode switching routes through `self.chart_stack.set_mode(mode)` at `mf4_analyzer/ui/main_window.py:371`.

4. **Dimension: S3 preset display names**  
   Verified: `_BUILTIN_PRESET_DISPLAY` currently contains the three old names at `mf4_analyzer/ui/inspector_sections.py:1542-1548`, and the stale explanatory comment says the bar reads as "诊断模式 / 幅值精度 / 高频细节" at `mf4_analyzer/ui/inspector_sections.py:91-99`. Existing tests also assert the old names at `tests/ui/test_inspector.py:683-699`, so the spec is correct that tests must update.

5. **Dimension: S5 architectural soundness of axis hit detection**  
   Verified: the current axis-hit logic is already independent of PlotCanvas-specific state except `self.fig`; it reads pixel coordinates at `mf4_analyzer/ui/canvases.py:1649`, iterates `self.fig.axes` at `mf4_analyzer/ui/canvases.py:1653`, and returns `(ax, 'x'|'y')` at `mf4_analyzer/ui/canvases.py:1675`. Extracting this part to `_find_axis_for_dblclick(fig, x_px, y_px, margin=45)` is achievable.

6. **Dimension: S5 dblclick priority**  
   Verified: PlotCanvas already prioritizes double-click axis editing before remark add/remove logic: the double-click branch is at `mf4_analyzer/ui/canvases.py:1677-1683`, right-click remark deletion is at `mf4_analyzer/ui/canvases.py:1696-1698`, and left-click remark addition is at `mf4_analyzer/ui/canvases.py:1700-1704`.

7. **Dimension: Batch export after S4 deletion**  
   Verified: `BatchRunner._write_image` has no special `order_rpm` branch; it handles `fft` at `mf4_analyzer/batch.py:342-345`, `order_track` at `mf4_analyzer/batch.py:346-349`, and all heatmap-like data via the generic `else` at `mf4_analyzer/batch.py:350-367`. Removing `order_rpm` from `_run_one` should not require a dedicated image-export deletion.

8. **Dimension: Consistency with prior spec**  
   Verified: the new spec does reference the prior order-canvas performance spec and says it deletes the `compute_rpm_order_result` / `_render_order_rpm` / `OrderRpmResult` / `do_order_rpm` entries at `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:7-8`. Non-RPM pieces of the prior spec still survive deletion, including `PlotCanvas.plot_or_update_heatmap` from `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:117-130` and current code at `mf4_analyzer/ui/canvases.py:1476-1561`, order-track envelope from prior spec `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:315-329` and current code at `mf4_analyzer/ui/main_window.py:1548-1584`, `build_envelope` at `mf4_analyzer/ui/canvases.py:149-205`, and `OrderWorker` generation/cancel infrastructure at `mf4_analyzer/ui/main_window.py:80-145` and `mf4_analyzer/ui/main_window.py:1390-1458`.

## Verdict

needs revision before plan

The spec is directionally sound, but S4's deletion scope is incomplete and S5's hover plan conflicts with the app's default Pan state. Revise the deletion grep/scope, toolbar ordering, hover priority table, tests, and squad ownership before turning this into an implementation plan.
