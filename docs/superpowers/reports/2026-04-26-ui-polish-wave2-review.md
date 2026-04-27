## S1 acceptance verification
- S1-1 PASS - `CHART_TIGHT_LAYOUT_KW = dict(pad=0.4, h_pad=0.6, w_pad=0.4)` at `mf4_analyzer/ui/canvases.py:52`.
- S1-2 PASS - `SPECTROGRAM_SUBPLOT_ADJUST` values `left=0.07, right=0.93, top=0.97, bottom=0.09` at `mf4_analyzer/ui/canvases.py:53-55`.
- S1-3 PASS - `AXIS_HIT_MARGIN_PX = 45` at `mf4_analyzer/ui/canvases.py:56`.
- S1-4 PASS - canvases use `tight_layout(**CHART_TIGHT_LAYOUT_KW)` at `mf4_analyzer/ui/canvases.py:508,538,557,1645`; Spectrogram creates colorbar at `mf4_analyzer/ui/canvases.py:1287` then applies `subplots_adjust(**SPECTROGRAM_SUBPLOT_ADJUST)` at `mf4_analyzer/ui/canvases.py:1307`.
- S1-5 PASS - `main_window.py` imports `CHART_TIGHT_LAYOUT_KW` at `mf4_analyzer/ui/main_window.py:26`; FFT/order-track render paths apply it at `mf4_analyzer/ui/main_window.py:1252,1504`.
- S1-6 PASS - SpectrogramCanvas uses `Figure(figsize=(10, 6), ...)` at `mf4_analyzer/ui/canvases.py:1159`.
- S1-7 PASS - SpectrogramCanvas uses `add_gridspec(... hspace=0.18)` at `mf4_analyzer/ui/canvases.py:1265`.
- S1-8 PASS - `rg "find_axis_for_dblclick\([^\n]*45" mf4_analyzer/ui/canvases.py` returned 0 hits; all six call sites use `AXIS_HIT_MARGIN_PX` at `mf4_analyzer/ui/canvases.py:927,963,1398,1415,1749,1761`.
- S1-9 PASS - `tests/ui/test_canvas_compactness.py` covers constants/layout/source guards/spectrogram compactness at `tests/ui/test_canvas_compactness.py:11-31,34-74,77-118,121-162`.

## S2 acceptance verification
- S2-1 PASS - `ChartStack.set_mode` calls `setCurrentIndex`, then `stats_strip.setVisible(mode == 'time')`, then emits at `mf4_analyzer/ui/chart_stack.py:418-420`.
- S2-2 PASS - `ChartStack.__init__` seeds `stats_strip` visibility from `current_mode() == 'time'` at `mf4_analyzer/ui/chart_stack.py:408-409`.
- S2-3 PASS - `tests/ui/test_chart_stack_stats_visibility.py` covers default/time/other-mode/return behavior at `tests/ui/test_chart_stack_stats_visibility.py:4-46`.

## S3 acceptance verification
- S3-1 PASS - builtin storage keys remain `diagnostic`, `amplitude_accuracy`, `high_frequency` at `mf4_analyzer/ui/inspector_sections.py:1497-1524`; display values are `配置1/配置2/配置3` at `mf4_analyzer/ui/inspector_sections.py:1527-1532`.
- S3-2 PASS - top comments/docstrings mention the new names at `mf4_analyzer/ui/inspector_sections.py:96-98` and `mf4_analyzer/ui/inspector_sections.py:1355-1357`.
- S3-3 PASS - `tests/ui/test_inspector.py` covers builtin behavior and new/reset names at `tests/ui/test_inspector.py:193-218,681-697,1021-1064`.

## S5 acceptance verification
- S5-1 PASS - `_axis_interaction.py` exists; pure `find_axis_for_dblclick` is at `mf4_analyzer/ui/_axis_interaction.py:18-59`; side-effecting `edit_axis_dialog(...) -> bool` is at `mf4_analyzer/ui/_axis_interaction.py:62-89`.
- S5-2 PASS - `_toolbar_i18n.py` exists; `_ACTION_TOOLTIPS` is at `mf4_analyzer/ui/_toolbar_i18n.py:11-21`; `apply_chinese_toolbar_labels` is at `mf4_analyzer/ui/_toolbar_i18n.py:24-40`.
- S5-3 PASS - four chart modes are TimeDomain/Plot/Spectrogram/Plot at `mf4_analyzer/ui/chart_stack.py:372-375`; dblclick/hover helper call sites are `mf4_analyzer/ui/canvases.py:927,963,1398,1415,1749,1761`.
- S5-4 PASS - drag short-circuit press/release exists for TimeDomain at `mf4_analyzer/ui/canvases.py:404-407,915-919`, Spectrogram at `mf4_analyzer/ui/canvases.py:1180-1185,1388-1392`, and Plot/FFT/order at `mf4_analyzer/ui/canvases.py:1525-1529,1734-1738`.
- S5-5 PASS - `_ChartCard.__init__` orders `_strip_subplots_action`, `_find_action('save')`, then `apply_chinese_toolbar_labels` at `mf4_analyzer/ui/chart_stack.py:159,163,168-169`.
- S5-6 PASS - `_find_action` matches `act.data()` before text at `mf4_analyzer/ui/chart_stack.py:130-134`.
- S5-7 PASS - Pan/Zoom hookup uses `act.data()` when present at `mf4_analyzer/ui/chart_stack.py:211-217`.
- S5-8 PASS - Back/Forward are marked non-retained at `mf4_analyzer/ui/_toolbar_i18n.py:14-15` and removed at `mf4_analyzer/ui/_toolbar_i18n.py:35-36`.
- S5-9 PASS - chart toolbar icon size is `QSize(14, 14)` at `mf4_analyzer/ui/chart_stack.py:158`.
- S5-10 PASS - time-card segmented buttons use `分屏/叠加/游标关/单游标/双游标/不锁/锁X/锁Y` at `mf4_analyzer/ui/chart_stack.py:261-292`.
- S5-11 PASS - idle hint includes `双击坐标轴可设置范围` at `mf4_analyzer/ui/chart_stack.py:113-116`.
- S5-12 PASS - compact chart toolbar QSS selectors are at `mf4_analyzer/ui/style.qss:508-523,581-619`.
- S5-13 PASS - `tests/ui/test_axis_interaction.py` covers helper hit/no-hit and canvas dblclick/hover/drag/slice cases at `tests/ui/test_axis_interaction.py:14-47,50-108,111-178,181-238`.
- S5-14 PASS - `tests/ui/test_toolbar_i18n.py` covers Chinese tooltips, Back/Forward removal, and `act.data()` preservation at `tests/ui/test_toolbar_i18n.py:27-52`.
- S5-15 PASS - `tests/ui/test_chart_stack.py` covers segmented controls/subplots stripping/Chinese labels/hint text at `tests/ui/test_chart_stack.py:86-118,276-294`.

## Subtle breakage scan
- Scan-1 FAIL - executable bare `tight_layout()` still exists: `rg "\.tight_layout\(\)" mf4_analyzer tests` reports `mf4_analyzer/batch.py:350: fig.tight_layout()`.
- Scan-2 PASS - Save lookup is captured before i18n and used after relabel at `mf4_analyzer/ui/chart_stack.py:161-181`; post-i18n action data is preserved at `mf4_analyzer/ui/_toolbar_i18n.py:38`.
- Scan-3 PASS - PlotCanvas dblclick returns before remark handling at `mf4_analyzer/ui/canvases.py:1757-1764`; remark add path starts later at `mf4_analyzer/ui/canvases.py:1781-1785`.
- Scan-4 PASS - TimeDomain hover runs only when not dragging, then rubber-band and cursor-readout logic continue at `mf4_analyzer/ui/canvases.py:955-989`.
- Scan-5 PASS - Spectrogram dblclick handler runs before `_ax_spec` filtering at `mf4_analyzer/ui/canvases.py:1394-1407`; slice-axis test asserts the dialog path at `tests/ui/test_axis_interaction.py:215-238`.
- Scan-6 PASS - `apply_chinese_toolbar_labels` sets retained action data at `mf4_analyzer/ui/_toolbar_i18n.py:38`; test asserts `act.data() == 'save'` at `tests/ui/test_toolbar_i18n.py:47-52`.
- Scan-7 PASS - focused UI subset ran cleanly with repo venv: `.venv/bin/python -m pytest tests/ui/test_axis_interaction.py tests/ui/test_toolbar_i18n.py tests/ui/test_chart_stack.py tests/ui/test_chart_stack_stats_visibility.py tests/ui/test_canvas_compactness.py tests/ui/test_inspector.py -q` => `103 passed in 11.83s`.

## Cross-spec / regression
- PASS - required RPM grep returned no hits: `grep -rn "rpm_order\|order_rpm\|OrderRpmResult\|RpmOrderResult\|rpm_chain\|转速-阶次\|order_track_rpm\|rpm_to_order\|RPMOrder" mf4_analyzer/ tests/` produced no output.

## Verdict
needs rework: refactor-architect, remove/convert the remaining bare `fig.tight_layout()` at `mf4_analyzer/batch.py:350` (or document why the subtle-breakage criterion excludes batch export).
