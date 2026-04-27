# Spec Review Rev 3 - 2026-04-26-ui-polish-and-order-rpm-removal-design.md

Line references use:

- `rev3`: `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md`
- `rev2-report`: `docs/superpowers/reports/2026-04-26-ui-polish-and-order-rpm-removal-spec-review-rev2.md`
- `canvas-perf`: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md`

## Rev 2 minor issues — disposition

1. **Issue #1 - stale `rpm_order` worker-kind literal: fixed.**

   Targeted grep found 0 hits for `kind == 'rpm_order'`, `_kind == 'rpm_order'`, and `result_kind == 'rpm_order'` in rev 3.

   Evidence that rev 3 now uses the actual worker kind:

   - `rev3:153`: "`OrderWorker.run` 里 `elif self._kind == 'rpm':` 分支 (lines 124-128) 删 —— **注意：实际字面量是 `'rpm'`，不是 `'rpm_order'`；详见源码 `main_window.py:124`"
   - `rev3:154`: "`do_order_rpm` 整方法 (line 1318+) 删；该方法内调 `self._dispatch_order_worker('rpm', ...)` (line 1341) 一并删"
   - `rev3:156`: "`_on_order_result` 里 `elif kind == 'rpm':` 分支 (lines 1455-1456) 删 —— **同样是字面量 `'rpm'`**"

   Source read confirmed the cited code still matches: `main_window.py:124` is `elif self._kind == 'rpm':`, `main_window.py:1341` is `self._dispatch_order_worker('rpm', ...)`, and `main_window.py:1455` is `elif kind == 'rpm':`.

2. **Issue #2 - inaccurate §0 prior-spec references: partial.**

   Fixed inside §0: rev 3 no longer uses the old `§6.2` citation, and §0 now names the relevant canvas-perf clauses:

   - `rev3:18`: "`OrderAnalyzer.compute_rpm_order_result`（删除）— `canvas-perf` §2.1 Included 第 32-34 行 + §4.6 内层向量化"
   - `rev3:19`: "`OrderAnalyzer.compute_order_spectrum`（删除 — `canvas-perf` §6.1 公共方法保持不变中点名要保留的旧 tuple-API 公共入口；本 spec 与之冲突，以本 spec 为准）"
   - `rev3:22`: "`MainWindow.do_order_rpm` / `MainWindow._render_order_rpm`（删除）— `canvas-perf` §4.3 OrderWorker 第 132+ 行 + §7 验收 #13 第 530 行 imshow 方向校正"
   - `rev3:25`: "`canvas-perf` §2.1 Included 第 33-34 行规定的 `OrderRpmResult.counts` 按帧累加语义、`compute_rpm_order_result` 中 `argmin` 向量化条款全部失效"

   Remaining issue: grep still finds one stale `§A4` reference outside §0:

   - `rev3:170`: "`compute_order_spectrum` legacy facade (line 439+) 删（即使 docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md §A4 曾要求保留，本 spec §0 已 supersede）"

   `canvas-perf` still has no `§A4` hit; the relevant public API clause is `canvas-perf:446-448` under `### 6.1 `OrderAnalyzer` 公共方法保持不变`.

3. **Issue #3 - S1-T5 optional-vs-required contradiction: fixed.**

   Grep for `可选手动` in rev 3 returned 0 hits. Rev 3 now makes screenshot evidence required consistently:

   - `rev3:94`: "`S1-T5 | 4 模式各截一张 PNG 留 `docs/superpowers/reports/2026-04-26-canvas-compactness-screenshots/`（**必选**：Wave 3 sign-off 凭证） | 手动`"
   - `rev3:496`: "`**S1**: S1-T1 至 S1-T5 全过；4 模式截图归档"
   - `rev3:554`: "`4 模式各跑一次 + 截图归档 `docs/superpowers/reports/2026-04-26-canvas-compactness-screenshots/``"

## Carry-forward check

Rev 1 critical and should-fix items remain addressed; no regression found. The only remaining cleanup is the stale non-existent `§A4` citation already counted above under rev 2 issue #2.

- C1 hover conflict remains fixed: `rev3:277` says "`toolbar.mode != ''` 短路条件会让 hover 永远不触发。改用"actively dragging"判定", `rev3:296-298` defines `_is_actively_dragging`, and `rev3:431` keeps S5-T7: "`Pan 模式空闲（默认状态）下 hover 仍生效`".
- C2 / SF-1 S4 deletion coverage remains fixed: `rev3:208` keeps the canonical grep including `rpm_order`, `order_rpm`, `OrderRpmResult`, `compute_rpm_order_result`, `compute_order_spectrum\b`, `_render_order_rpm`, `do_order_rpm`, `order_rpm_requested`, `btn_or\b`, `_compute_order_rpm_dataframe`, `rpm_res`, and `转速-阶次`; `rev3:221` says "`上述 grep 0 命中`".
- C3 squad wave overlap remains fixed: `rev3:510` says "按 **文件归属** 切分", with signal ownership at `rev3:514-517` and UI ownership at `rev3:518-521`; `rev3:547` explicitly sequences the later `main_window.py` edit as "时间上 W2 在 W1 之后无冲突".
- SF-2 axis helper extraction remains fixed: `rev3:232` says "Pure axis-hit detection + side-effecting axis-edit helper", `rev3:249-254` makes `edit_axis_dialog` side-effecting and caller-owned for `draw_idle`, and `rev3:264-266` shows `self.draw_idle()` only after accepted edit.
- SF-3 toolbar ordering remains fixed: `rev3:353` says `act.setData(key)`, `rev3:355` says "do NOT setText(\"\")", `rev3:365-367` preserves the ordering, and `rev3:372-376` makes `_find_action` match `act.data()` first.
- SF-4 hover priority table remains fixed: `rev3:303-314` covers Pan/Zoom idle, TimeDomain cursor modes, SpanSelector, PlotCanvas remarks, Spectrogram time selection, and outside-window behavior; tests remain at `rev3:427` and `rev3:431-433`.
- SF-5 / SF-6 S1 layout coverage remains fixed: `rev3:55-62` lists Spectrogram, TimeDomain, PlotCanvas, FFT, and order_track layout decisions, including `main_window.py:1257`, `main_window.py:1584`, and keeping PlotCanvas `(20, 12)` unchanged. `rev3:90-93` keeps subplotpars, colorbar bbox, and ylabel-vs-ytick bbox tests.
- SF-7 acceptance coverage remains fixed: rev 3 still lists S2 `update_stats({})` at `rev3:110`, S3 reset-to-default at `rev3:132`, S4 grep/UI tests at `rev3:221-223`, and S5 toolbar/segmented-button tests at `rev3:434-439`.
- SF-8 supersedes remains substantively fixed in §0 via the corrected §2.1 / §4.3 / §6.1 / §7 references quoted above.

## New issues found in rev 3

None beyond the carried-forward stale `§A4` citation already recorded under rev 2 issue #2.

## Affirmations

- The new S4 `'rpm'` literal grep is correctly scoped. Rev 3 uses `grep -rnE "_kind == 'rpm'|kind == 'rpm'|_dispatch_order_worker\\('rpm'" mf4_analyzer/ui/main_window.py` at `rev3:215`, which matches exact worker-kind comparisons/dispatches and not generic names such as `rpm_factor`, `rpm_min`, or `rpm_res`. A sample grep against those strings matched only `kind == 'rpm'`, `_kind == 'rpm'`, and `_dispatch_order_worker('rpm'`.
- Rev 3 still separately deletes RPM parameter leftovers through the canonical grep and explicit scope: `rev3:171` says "`rpm_res` / `rpm_min` / `rpm_max` / `rpm_bins` 局部变量随方法一起删", and `rev3:208` includes `rpm_res`.
- §0 correctly preserves non-RPM order paths: `rev3:29-31` keeps `compute_order_spectrum_time_based`, `compute_time_order_result`, `extract_order_track_result`, and time-order/order-track canvas-perf clauses.

## Verdict

approved with minor revisions

Plan-writing may proceed after replacing the remaining S4 `§A4` citation with the accurate `canvas-perf` §6.1 reference. No rev 1 critical or should-fix regression was found.
