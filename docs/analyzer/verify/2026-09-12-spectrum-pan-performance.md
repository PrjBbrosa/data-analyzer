# 频谱平移性能优化验收（T4）

日期：2026-09-12。T1–T3 已在本工作区落地；本文件只记录同机 Cocoa 复测、对照测量、focused/边界门与 §5 对照。未提交、未暂存、未推送。未改产品版本、帮助或 hints。

## 快照与指纹

- HEAD：`21c3ef12a0b3beb50967e876974e75dd7c60a6d0`（与 T0 基线相同提交；产品改动在工作区未提交）。
- T0 指纹：`.state/spectrum-pan-performance/fingerprint-before.json`。
- T4 指纹：`.state/spectrum-pan-performance/fingerprint-after.json`。
- T0 基线 JSON 未被覆盖：`.state/spectrum-pan-performance/baseline/`。
- T4 复测：`.state/spectrum-pan-performance/retest/`（`perf.json` / `perf-summary.json` / `perf.log`）。

| 文件 | T0 sha256 前缀 | T4 sha256 前缀 | 结论 |
|---|---|---|---|
| `mf4_analyzer/ui/pg_canvas/line_canvas.py` | `1df5fe366185` | `9ebf435c5d8f` | **已变**（T1–T3） |
| `mf4_analyzer/signal/display_ranges.py` | `9123d4ce6cdd` | `40435906cf21` | **已变**（T1） |
| `mf4_analyzer/ui/pg_canvas/spectrum_display.py` | （当时不存在） | `2e1bdd48f83b` | **新增**（T3） |
| `mf4_analyzer/ui/pg_canvas/canvas.py` | `859c16259dfe` | `859c16259dfe` | 未变 |
| `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` | `e08c9e1a3fdf` | `e08c9e1a3fdf` | 未变（本计划未改时频/阶次） |

T4 工作区仍含无关脏文件（未触碰）：`channel_config_bar.py`、`motion.py`、其测试、`ssh-keygen`，以及另一份 `2026-09-12-section-switch-performance-plan.md`。本任务只改了探针、`.state/spectrum-pan-performance/` 下新结果、本 verify 与 `t4-summary.md`。

## T1–T3 改了什么（短）

- **T1** `PreparedLineRange`：结果接入时准备一次；单调有限 X 用 searchsorted；全覆盖复用全有效 Y 边界。`visible_line_values` 保留兼容，Batch/切片未迁移。
- **T2** 交互回调只提交最新目标；16 ms 事务合并曲线更新与自动 Y；generation / 程序 Y guard；`flush_pending_spectrum_display()` 不改写 150 ms AA timer。
- **T3** 覆盖+密度缓存：HIT 不 `build_peak_trace`、不 `setData`；一侧半跨度 overscan；单窗口而非 LRU。

## Cocoa 平台

命令（**未**设 `QT_QPA_PLATFORM=offscreen`；perf 与 profile 未混用）：

```bash
PYTHONUNBUFFERED=1 TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. \
  .venv/bin/python scripts/probe_spectrum_interaction.py \
  --mode perf --mainwindow --output-dir .state/spectrum-pan-performance/retest
# exit 0  wall_s=429.8  comparable_cocoa=true  profiler_enabled=false
```

- Qt platform：**cocoa**；`comparable_cocoa: true`；offscreen fallback 未使用。
- DPR 2.0；widget 1200×800；FFT amp ViewBox mapped 1157×570 px（与 T0 相同）。
- Qt 5.15.14 / PyQt 5.15.11 / pyqtgraph 0.14.0 / NumPy 2.5.2 / Python 3.12.14 / Darwin arm64。
- loadavg 复测时 `[2.43, 1.96, 1.90]`（T0 基线为 `[3.07, 2.94, 2.90]`）。
- QSettings 隔离到 `/tmp/spectrum-pan-qsettings-6p4h7amg/qsettings.ini`，未写 `MF4Analyzer/DataAnalyzer`。
- 峰值 RSS（本进程 `ru_maxrss`）：786 169 856 字节。T0 未记 RSS，不能做内存对比。

## 与 T0 同机对照（GUI 事件，5×120，预热/首显/settle 排除）

计时口径与 T0 相同：callback + 强制 `scene.update()`/`viewport.repaint()`。**不是**设备 FPS 声明。

目标：auto-Y P95 相对 T0 `18.70 ms` 至少降 30% → 需 **≤ 13.09 ms**。手动 Y P95 相对 T0 `9.85 ms` 回退不超过 10% → 需 **≤ 10.84 ms**。

| 场景 | Hz | T0 p50/p95 | T4 p50/p95/max | T4 >16.7 ms | T0 setData / fullScan / yFitCb | T4 setData / fullScan / yFitCb / hit / rebuild |
|---|---:|---:|---:|---:|---:|---:|
| FFT auto-Y | 60 | 7.11 / **18.70** | 5.31 / **16.34** / 34.55 | 11/600 = **1.8%**（T0 8.3%） | 628 / 1858 / 619 | **4 / 0 / 1** / 491 / **0** |
| FFT manual-Y | 60 | 3.36 / **9.85** | 5.27 / **16.13** / 28.71 | 12/600 = 2.0%（T0 0%） | 642 / 642 / 603 | **0 / 0 / 0** / 488 / **0** |
| time-domain | 60 | 4.03 / 5.07 | 3.82 / **26.23** / 150.97 | 153/600 = 25.5%（T0 4.2%） | 40 / 0 / 0 | 40 / 0 / 0（`canvas.py` 哈希未变） |
| FFT auto-Y | 120 | 7.13 / 18.64 | 15.60 / 17.33 / 35.10 | 7.8% | 480 / 1410 / 470 | 8 / 0 / 1 / 413 / 0 |
| FFT manual-Y | 120 | 2.47 / 9.56 | 15.50 / 16.86 / 29.71 | 5.8% | 422 / 422 / 372 | 0 / 0 / 3 / 395 / 0 |
| time-domain | 120 | 3.74 / 4.90 | 25.48 / 27.01 / 169.38 | 96.5% | 40 / 0 / 0 | 32 / 0 / 0 |

结构门（宽窗持续包住全部数据、X 平移，60 Hz GUI）：

- 全数组重验：`full_array_scan_count = 0`（T0 1858）。自动 Y 走 `PreparedLineRange.query`，974 次查询全部 `used_cached_full_bounds`。
- `plan_spectrum_display` rebuild = 0，hit = 491。
- `setData`：5 轮中 4 轮为 0；第 3 轮 4 次（2 条曲线 × 2）。轨迹末尾仍含 T0 的 Ctrl+wheel 进出，**不是**覆盖 HIT 失败。峰值抽点 `peak_trace_count = 0`。
- 自动 Y 已离开鼠标回调：`y_fit_in_callback = 1`（T0 619），`y_fit_in_timer = 486`。
- 手动 Y：`prepared_query_count = 0`，`_auto_amplitude_y_range = 0`，拖动不做 Y 查询。

性能门：

- **auto-Y P95 下降 (18.70−16.34)/18.70 = 12.6%，未到 30%。** p50 7.11→5.31（−25%）；>16.7 ms 8.3%→1.8%。回调已便宜（callback p50 4.87→0.48），剩余主要在强制 paint（paint p50 2.23→4.86）以及少量 ~16–34 ms 帧。
- **手动 Y P95 16.13 相对 9.85 回退 64%，超过 10% 限额。** 结构上已达目标（0 setData、0 Y 查询）；端到端变慢与 paint p50 4.80 及 16 ms 量级长尾同向，不能用 auto-Y 的计数改善宣称手动路径更快。
- 时域 `canvas.py` 未改；p50 3.82 与 T0 4.03 接近，p95/max 长尾（max 151 ms）不能算进本计划算法收益，只说明本轮强制 paint 样本含离群点。
- 事件滞后 T4 auto-Y 60 Hz lag p95 = 874 ms（T0 16.5 ms）：60 Hz 排队未守住。P50/P95 仍按每个事件的 callback+paint 计算，**不得倒推 60/120 FPS**。

首显（cold，不含进 timed 窗口）：FFT auto 46.6 ms（T0 91.8 ms），manual 41.5 ms（T0 62.5 ms）。宽窗首显未出现 >20% 回退。

## 正确性读数

独立正确性画布：T0 公式 + 80 Hz 峰 80 dB + 50 Hz 深谷 −300 dB + 100 Hz NaN 频率断点。证据：`t4_extra.correctness`，截图 `correctness-nan-valley.png` / `narrow-window.png` / `wide-pan.png`。

| 检查 | 结果 |
|---|---|
| 原始 `freq`/`amp` 身份与长度 | `id` 不变，n=594001，峰/谷/NaN 原值仍在 |
| 自动 Y 覆盖深谷与峰 | ylim = −320.05..99.05，含 −300 与 80 |
| 折线保留 NaN 断点 | `nan_break_in_polyline: true` |
| 窄窗峰仍在 peak trace | `peak_in_trace: true`（0..200 下 trace_n=1859；平移到 20..180 后 2148） |
| 150 ms AA quiet timer | `interval() == 150`（flush / 正确性 / resize / MainWindow 均 150） |
| `pass` | **true** |

0..200 Hz 缓存内平移（`fft_narrow_incache`，GUI 60/120 Hz，5×120）：

- 60 Hz：setData=0，rebuild=0，hit=508，命中率 100%；五轮 `peak_present_after_round` 全 true；P95=19.31 ms。
- 未在每个 paint 帧采样峰（会扰动 P95）；峰存在性按轮次 settle/flush 后读 `getData()`。

越界/缩放：

- `fft_overscan_cross` 在 0..200 与 400..600 间交替（单窗口缓存，对侧必 miss）：60 Hz rebuild=483、hit=241、setData=1932。该窗口不含 80 Hz，轮次 `peak_present=false` 是窗口选择而非丢峰。P95=17.87 ms。
- `fft_wheel_zoom` 以 Ctrl+wheel 放大：60 Hz rebuild=398、hit=10。最终 flush 后正确性快照与精确 ylim 一致。
- resize 加宽 400 px：density miss 1 次，`resize_ms=130.8`。foreign 鼠标按下后 flush：0 setData，1 次 cache hit，AA timer 仍 150。

Linear↔dB：`plot_spectra(..., amp_label='Amplitude')` 后缓存 `reason=empty`（revision 失效），linear_replot_ms=262.4。正确性数组冷首显 242 ms，与 T0 宽窗 91.8 ms **不是同一数据**，不拿 262 ms 宣称 >20% 回退；可比宽窗首显是变快的。

## MainWindow 与裸画布

`--mainwindow` 使用隔离 INI、合成 `_plot_fft_entries`（无客户文件、无 worker）。`constructed=true`，`plotted=true`，`exposed=true`，首绘 49.4 ms。

| | 裸 `PgLineCanvas` 宽窗 auto-Y 60 Hz | MainWindow FFT |
|---|---|---|
| setData / fullScan / rebuild | 4 / 0 / 0 | 0 / 0 / 0 |
| cache hit | 491 | 70（60 个事件 + flush） |
| adapter `viewport_origin` | 无 adapter；`_spectrum_y_auto` 保持自动 | 拖前 `{x:auto,y:auto}` → 拖后 `{x:user,y:user}` |
| 状态条文案 | n/a | `X 已缩放 · 自动范围暂停；Y 已缩放 · 自动范围暂停` |
| callback+paint p50/p95 | 5.31 / 16.34（n=600） | 5.60 / 36.04（n=60，不可比） |
| 导出 `grab_pixmap` | n/a | 非空 1240×1232 |
| 双 Pane | n/a | `pane1_has_curves: true` |

**自动 Y 在产品路径上被标成手动。** 探针 GUI 拖动 `dy=0`，但 ViewBox 仍提交了 Y。T2 单测用 `sigRangeChangedManually.emit([True, False])` 钉的是程序/X-only 标志，不能覆盖这条真实鼠标路径。未改产品代码。历史回退未用 `.tlproj` 文件验证（探针 limitation 已写明）。

## 热图 / FRF 对照（只测，不改）

对比计时在 `t4_extra.contrast`，**未**折进 FFT p50/p95。截图：`contrast-heatmap-slice.png`、`contrast-frf.png`。

| 画布 | 观察 |
|---|---|
| 热图 slice **开** | 40 事件内 `_apply_slice` 35 次 / 6.10 ms，`visible_line_values` 35 次 / 0.98 ms，slice `setData` 35 次 / 1.60 ms。callback+paint p50/p95 = 5.17 / 5.53。`sync_slice` 套住 `apply_slice`，二者不可相加。 |
| 热图 slice **关** | 无 slice/`visible_line_values`/`setData` 计数；p50/p95 = 4.74 / 5.06。 |
| FRF 三曲线 + log 轴 | `_render_result` 1 次 / 1.49 ms；`_sync_frequency_ticks` 1 次 / 0.026 ms；setData 10 次 / 0.32 ms（接入，非每帧）。平移 p50/p95 = 10.67 / 11.05。 |

热点与 FFT 不同：切片仍按视图每拍 `setData` + `visible_line_values`；FRF 平移未重建三曲线。后续若做切片，方向是“只响应当前切片轴/索引变化并合并 setData/Y-fit”。**本轮不实现。**

## Focused / 边界门

运行时均为 `.venv/bin/python`，`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。在 Cocoa 复测结束之后串行执行，未与 GUI 探针重叠。未跑全量，未跑 `tests/acquisition_ui`。

| Gate | 命令 | 活结果 |
|---|---|---|
| T1 owner | `pytest tests/signal/test_display_range_index.py tests/signal/test_display_ranges.py -q` | **68 passed** in 0.08s |
| T0/T2/T3 + line canvas | `pytest tests/ui/test_spectrum_interaction.py tests/ui/test_spectrum_display_cache.py tests/ui/test_pg_line_canvas.py -q` | **206 passed**, 10 warnings in 9.65s |
| 多 View 收集 | `pytest tests/ui/test_analysis_multiview_integration.py -k 'viewport or auto_y or range_adapter' --collect-only -q` | **5/87 collected**（非 0 selected）：`test_fft_viewport_survives_view_switch_and_resets_on_recompute`、`test_fft_split_link_off_does_not_copy_sibling_viewport`、`test_fft_time_and_order_viewport_roundtrip`、`test_fft_viewport_axis_origin_and_range_restore_action`、`test_fft_restoration_compute_preserves_user_viewport` |
| 多 View 执行 | 同上去掉 `--collect-only` | **5 passed**, 82 deselected in 1.43s |
| UI 边界棘轮 | `pytest tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_import_boundaries.py tests/ui/test_main_window_state_ownership.py tests/ui/test_no_lambda_signal_connections.py -q` | **21 passed** in 3.99s |
| 导入边界 | `pytest tests/test_signal_no_gui_import.py tests/test_batch_render_import_boundary.py tests/test_packaging_imports.py -q -rs` | **11 passed, 1 skipped** in 1.20s。skip：`tests/test_packaging_imports.py:72`「PyInstaller spec is a build artifact; run tools/build_windows_folder.ps1 to regenerate before asserting.」**不是** Windows 打包通过。 |
| Batch 可见 Y + 切片深谷 | `pytest tests/test_batch_render_qt.py::test_fft_auto_y_uses_visible_original_values tests/ui/test_pg_heatmap_canvas.py::test_slice_db_mask_excludes_zero_but_preserves_real_deep_valley -q` | **3 passed** in 0.54s |
| 空白/冲突 | `git diff --check` | **通过** |

pyqtgraph/NumPy shape deprecation warnings 未当作失败隐藏。

## 限制

- 不是 Windows frozen，也不是客户原文件。
- cProfile 未混进本轮 p50/p95（本轮只跑 `--mode perf`）。
- 强制每事件 `repaint()`，真实 UI 可能合并绘制。
- `full_array_scan_count` 仍是 `len(x)==594001` 的长度门；T3 HIT 路径不再进入这些函数。
- 本机无 `build/spec/TraceLab*.spec`，packaging skip 不能当打包验收。
- 未改 `hints.py` / `quickref.py`：T2/T3 没有新的用户暂停/恢复语义入口。

## §5 对照结论

| §5 项 | 结论 |
|---|---|
| 宽窗 X 平移：0 全数组重验、0 覆盖 miss 的 setData、Y 复用 | **结构通过**（4 次 setData 来自个别 wheel/质量路径，rebuild=0） |
| auto-Y callback+paint P95 ≥30% 低于 T0 | **未达到**（12.6%；剩余热点是 paint 与长尾帧，不是全数组扫描） |
| 手动 Y：拖动无 Y 查询、不因精确 xlim 重绘 | **结构通过**；P95 **回退超 10%** |
| 0..200 缓存内平移：峰/深谷/NaN、HIT 无 setData | **通过**（命中率 100%，五轮峰都在） |
| 越界 / 快滚轮 / resize：无陈旧、无 NaN 桥、flush 正确 | **正确性通过**；重建帧有计数与 P95，未差于“必须重建”的预期 |
| 新结果 / Linear↔dB：revision 失效，Y 仍 raw | **通过**；宽窗首显未回退 20% |
| 按住/松开/foreign/clear：最终更新、旧 timer 不写、150 ms AA | 调度由 focused 测试覆盖；Cocoa：foreign flush 无 setData，AA=150 |
| MainWindow：自动 Y 不被错标手动 | **未通过（产品路径）**；裸画布自动 Y 仍工作。分别记录，未改代码 |

**总评：正确性与结构门（宽窗 HIT、Y 复用、NaN/深谷/峰、AA 150）通过；§5 端到端 auto-Y P95 −30% 与手动 Y 不回退未达到。** 不以 helper 微基准或 cache-hit 计数代替 P95。剩余定位：强制 paint 成本（auto paint p50 约翻倍）与事件循环滞后，而不是 T0 的全数组 `visible_line_values` / 每拍 `setData`。切片对照显示独立热点，列入后续，不在本轮实现。

## T4 验收缺口补测（Y-latch + no-op setYRange）

日期：2026-09-12，同一工作区。T1–T3 未重开，未改 heatmap/FRF/时域算法，未提交。未覆盖 `baseline/` 或既有 `retest/`。

### 产品改动

- `viewbox.py`：FFT 幅值图体左键平移与时域预览一样锁成 X-only。RectMode 仍 2D；Y 槽（`axis is not None`）与 Shift-wheel 仍可动 Y。heatmap/FRF 没有 `_plot_amp`，不受影响。
- `_fit_active_spectrum_y`：自动 Y 未激活则不调用 `_auto_amplitude_y_range`；算得的 ylim 与当前 ViewBox 在 `atol=1e-9` 内则不 `setYRange`。
- HIT 且 Y 未变：不 `disable_interactive_quality` / `setYRange` / `schedule_idle_quality`；仍清 dirty、写 `_spectrum_last_refresh_at`，16 ms 合并器继续工作。不把 150 ms idle timer `start(0)`。

### Cocoa 对照

未设 `QT_QPA_PLATFORM=offscreen`，未混 profiler。只跑 T0 可比行（fft auto / fft manual / time-domain），GUI 60 Hz + 120 Hz，5×120。`--compare-only` 跳过 narrow/overscan/heatmap/FRF/`--mainwindow`。

```bash
PYTHONUNBUFFERED=1 TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. \
  .venv/bin/python scripts/probe_spectrum_interaction.py \
  --mode perf --input-mode gui --compare-only \
  --output-dir .state/spectrum-pan-performance/retest-yfix
# exit 0  wall_s=120.4  comparable_cocoa=true  profiler_enabled=false
```

- Qt platform：**cocoa**；`comparable_cocoa: true`。
- DPR 2.0；loadavg `[1.89, 1.78, 1.84]`。QSettings `/tmp/spectrum-pan-qsettings-d1wrw9yn/qsettings.ini`。
- `line_canvas.py` sha256 前缀 `91df9b860153`（相对 T4 `9ebf435c5d8f` 已变）；`viewbox.py` `9e8d16045806`；`canvas.py` / `heatmap_canvas.py` 仍为 T0 哈希。

| 场景 | Hz | T0 p50/p95 | T4 p50/p95 | Y-fix p50/p95/max | Y-fix >16.7 ms | Y-fix setData / fullScan / yFitCb / yFitTimer / hit / rebuild |
|---|---:|---:|---:|---:|---:|---|
| FFT auto-Y | 60 | 7.11 / **18.70** | 5.31 / **16.34** | 4.78 / **16.64** / 35.65 | 27/600 = 4.5% | **4 / 0 / 1 / 494 / 499 / 0** |
| FFT manual-Y | 60 | 3.36 / **9.85** | 5.27 / **16.13** | 4.80 / **16.41** / 28.93 | 15/600 = 2.5% | **0 / 0 / 2 / 491 / 496 / 0** |
| time-domain | 60 | 4.03 / 5.07 | 3.82 / 26.23 | 3.79 / **26.20** / 165.04 | 78/600 = 13.0% | 44 / 0 / 0 / 0 / 0 / 0 |
| FFT auto-Y | 120 | 7.13 / 18.64 | 15.60 / 17.33 | 16.13 / 17.70 / 40.53 | 19.8% | 12 / 0 / 0 / 430 / 435 / 0 |
| FFT manual-Y | 120 | 2.47 / 9.56 | 15.50 / 16.86 | 15.95 / 17.72 / 28.79 | 9.5% | 0 / 0 / 2 / 409 / 414 / 0 |
| time-domain | 120 | 3.74 / 4.90 | 25.48 / 27.01 | 25.90 / 27.67 / 168.91 | 98.3% | 32 / 0 / 0 / 0 / 0 / 0 |

相对 T0 60 Hz GUI：auto-Y P95 (18.70−16.64)/18.70 = **11.0%**，仍高于 ≤13.09 的 −30% 门。手动 Y 16.41 相对 9.85 回退 **66%**，仍超 10.84。callback p50 auto 0.38（T4 0.48，T0 4.87）；paint p50 auto 4.41（T4 4.86，T0 2.23）。探针仍按 `_fit_active_spectrum_y` 入口计数，所以 `y_fit_in_timer` 仍约 494；**不是** `setYRange` 次数。手动 Y `y_fit_auto_amplitude_y_range = 0`、`prepared_query_count = 0`。宽窗 HIT rebuild=0。

时域 `canvas.py` 未改；本轮 wall 120 s（T4 430 s），60 Hz p50 3.79 接近 T0，p95/max 长尾仍在，不能算进频谱算法收益。

首显（cold）：FFT auto 41.9 ms（T0 91.8，T4 46.6），manual 40.0 ms（T0 62.5，T4 41.5）。

### MainWindow Y-latch

本轮 `--compare-only` 未跑 `--mainwindow`。Focused offscreen `test_spectrum_plot_body_left_pan_is_x_only_keeps_auto_y` 使用与产品相同的 `analysis_range_adapter`（origin y=auto），经 `ViewBox.mouseDragEvent` FakeDrag `dy=0` 以及 viewport `QMouseEvent` 水平拖动：`viewport_origin.y` 保持 `'auto'`，`_spectrum_y_auto is True`，`viewport_action_committed` 不含 y。`test_spectrum_shift_wheel_pauses_auto_y` 经 viewport 真实 `QWheelEvent`+Shift：Y 缩放且 origin.y 变为 `'user'`。

**结论：图体纯 X 拖动不再把自动 Y 标成手动。** 真实 Y 路径（Shift-wheel）仍可暂停。

### Focused / 边界门

`.venv/bin/python`，`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。未跑全量。

| Gate | 结果 |
|---|---|
| `tests/ui/test_spectrum_interaction.py tests/ui/test_spectrum_display_cache.py` | **29 passed** in 1.71s |
| `tests/ui/test_pg_line_canvas.py -k 'ctrl_wheel or shift_wheel or pan_drops or x_zoom_respects or manual_enabled_mask or y_autofit or viewport_pixel'` | **17 passed**, 165 deselected in 1.27s |
| `tests/ui/test_pg_heatmap_canvas.py -k 'wheel'` | **12 collected / 12 passed**, 170 deselected（非 0 selected） |
| `tests/ui/test_no_lambda_signal_connections.py tests/ui/test_import_boundaries.py` | **12 passed** in 3.06s |
| `git diff --check`（本轮产品/测试文件） | **通过** |

### 对照结论

| 项 | 结论 |
|---|---|
| 图体水平拖动只提交 X，自动 Y 不被错标手动 | **通过**（focused adapter 路径；未再跑 MainWindow 进程） |
| HIT 宽窗：0 rebuild、0 全数组扫描；手动 Y 无幅值查询 | **通过** |
| 相同 ylim 不 `setYRange`；HIT+Y 不变不 churn quality | **通过**（owner 测试） |
| auto-Y P95 ≤13.09 ms | **未达到**（16.64；相对 T0 −11.0%） |
| 手动 Y P95 ≤10.84 ms | **未达到**（16.41） |

剩余热点仍是强制 `scene.update()`/`viewport.repaint()` 与事件滞后，不是 T0 的全数组扫描或每拍 `setData`。不以 cache-hit 或 `_fit_active_spectrum_y` 入口计数代替 P95。
