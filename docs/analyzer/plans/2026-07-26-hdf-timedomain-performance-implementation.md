# HDF 时间域交互性能恢复 — Implementation Plan

日期：2026-07-26
报告：`docs/analyzer/reviews/2026-07-26-hdf-timedomain-performance-regression-report.md`

## Goal

恢复 v7.5/v7.6 级别的 HDF 分屏交互响应，同时保留 v7.8 的 CRC 位图、buffer、
generation、通道状态和数据保真契约，并建立能阻止后续回退的 plot 性能准则。

## Global Constraints

- 所有数值/行为改动先写失败测试；时间阈值不进入普通 CI，调用次数/对象身份进入；
- raw arrays 是 cursor/stat/FFT/filter/export 唯一数据源；位图只负责显示；
- 缓存只在 plot generation 或真实数据变化时失效；
- 不扩大到 GPU、新绘图库或全局画质降级；
- 复杂 overlay/axis-group/companion/log 拓扑不满足前置条件时显式 full rebuild；
- 不触碰 `.playwright-cli`，不自动 commit/push。

## Stage 0 — 基线与红灯

### Task 0.1 — 固化真实文件基线

在 opt-in Cocoa benchmark 中记录 parse、六通道 plot、八步 pan、八步 resize、
warm add/remove 的 p50/p95/max，以及 raw-X scan、setData、PlotItem 创建次数。

### Task 0.2 — raw-X consumer 红灯

在 `tests/ui/test_timedomain_hotpath_perf.py` 增加：

- 共享时间轴只扫描一次；
- 连续 pan/resize 不重复扫描；
- generation rebuild 后只重新扫描一次；
- NaN/all-NaN/不同时间轴保持原 union 语义。

### Task 0.3 — resize quiet-window 红灯

证明 resize burst 会取消旧 coarse/data settle，timer 只在最后事件之后触发，且
最终只做一次 settled refresh；旧 generation timeout 不得修改新曲线。

### Task 0.4 — subplot selection identity 红灯

普通无分组分屏增加、移除、恢复一条通道时：

- 未变化 PDI/ViewBox identity 不变；
- xlim、cursor、颜色、render profile 不变；
- removed row 不占高度、不绘制；
- restored row 复用原对象；
- 新通道只新增一个 PlotItem/ViewBox；
- complex topology 返回可审计 fallback reason。

## Stage 1 — O(1) raw-X bounds

**Owned files**

- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `tests/ui/test_timedomain_hotpath_perf.py`

实现 generation-scoped `_raw_x_bounds_cache`：

1. 用 array fingerprint/identity 去重同一时间轴；
2. 每个唯一数组只计算一次 finite min/max；
3. `_data_x_union()` 之后只做缓存结果的 O(通道数) 合并，或直接返回 generation
   union；
4. `clear()`、新 bind、source revision 改变时精确失效；
5. 不在 range/resize/timer replay 中清除。

Stop gate：NaN、非单调时间轴、多个 data_id 的 union 语义任一变化即停止。

## Stage 2 — 真正的 resize 静默窗口

**Owned files**

- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `tests/ui/test_timedomain_hotpath_perf.py`
- `tests/ui/test_pg_timedomain_canvas.py`

1. 每个 resize event 立即进入 interactive quality；
2. 停止旧 `_refresh_timer`、`_coarse_timer` 和 pending coarse target；
3. 以最后一个 resize event 为起点重新开始 quiet timer；
4. quiet timer 到期后一次完成 label/tick/layout 与 settled data refresh；
5. 不再启动第二层 100 ms data timer；
6. dense raster 只在最终 geometry 上重建一次。

Stop gate：首次显示、程序化 resize 或导出后最终图形不完整即停止。

## Stage 3 — 普通分屏的对象复用 delta

**Owned files**

- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/main_window/window.py`
- `tests/ui/test_pg_timedomain_canvas.py`
- `tests/ui/test_timedomain_hotpath_perf.py`

普通 subplot（无 axis group、无 companion、线性轴）采用 retained rows：

1. 已绑定但取消选择的 PlotItem 隐藏并将 layout 高度折叠为 0；
2. re-check 恢复保存的 height constraints 和同一对象；
3. 新通道只 append/bind 一个 row；若请求顺序要求中间插入则 full rebuild；
4. `axes_list`、X listeners、bottom-axis、label specs 仅投影 active rows；
5. 空选择优先 delta-hide，避免 `MainWindow` 直接 `clear()` 丢失 warm model；
6. mode/context/source/axis-group/companion 不兼容时保留明确 reason。

> **2026-07-30 zero-active 加固修订：** 上述 retained-row 规则仅适用于变更前后至少一行 active 的非空→非空 transition。第 5 条“空选择优先 delta-hide”已被 `docs/superpowers/specs/2026-07-30-pg-subplot-zero-active-hardening-design.md` 取代：zero-active 必须 canonical clear，恢复 non-empty 时 full rebuild；不得继续要求跨 zero-active 保留 PlotItem/ViewBox identity。

Stop gate：行顺序、底部 X 轴、saved View 或 cursor 任一错误时不扩展到 overlay。

## Stage 4 — 条件化 dense-continuous 显示后端

只有 Stage 1–3 后真实 Cocoa pan/resize 仍高于准则才执行。

**Owned files**

- `mf4_analyzer/ui/pg_canvas/dense_raster.py`
- `mf4_analyzer/ui/pg_canvas/quality.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `tests/ui/test_pg_dense_raster.py`

候选必须同时满足：subplot、至少两条高密度行、`general` profile、raw
samples / plot width 超阈值、finite、linear axes、solid pen、内存预算可容纳。
复用现有 DPR-aware pixmap、generation、source revision、color/size/signature、
16 MiB item / 64 MiB global caps 和 native fallback。

低密度 smooth、overlay、log、NaN-gap、dashed companion 保持 native path。

Stop gate：视觉 envelope、NaN gap、raw/display 分离或 dense-discrete 专项回退。

### Execution decision — rejected after measurement

Stage 1–3 后确实执行了最小候选试验，但真实六行 HDF/Cocoa 的 DPR2 pixmap 合成
使 held-pan p95 升至 `179.9 ms`、resize p95 升至 `359.8 ms`，均劣于 native
vector。该实验没有保留任何生产代码；新增负向测试锁定 `general` 连续曲线不得
自动进入 CRC raster。最终架构保持原 renderer，仅保留 Stage 1–3 的低风险修复。

## Stage 5 — 性能准则与 benchmark

新增：

- `docs/analyzer/specs/2026-07-26-plot-performance-standards.md`
- `scripts/benchmark_timedomain_interaction.py`
- benchmark 单元测试/fixture（不提交真实 49 MiB 文件）

默认 synthetic fixture 覆盖 6 × 1,188,000 shared-time rows；`--hdf PATH`
使用真实文件。输出 machine-readable JSON，包含环境、DPR、尺寸、模式、样本数、
阶段、p50/p95/max、scan/setData/object-create counts。

普通 CI 只运行确定性 guard；macOS release candidate 运行 Cocoa threshold；Windows
EXE 使用同一场景做 packaged gate。

## Stage 6 — 验证和回填

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_timedomain_hotpath_perf.py \
  tests/ui/test_pg_dense_raster.py \
  tests/ui/test_pg_timedomain_canvas.py
```

已运行真实 HDF Cocoa benchmark（`--assert-standards`）并通过全部绝对/确定性
门禁；回填结果见报告 7.3。验证结果：hotpath `16 passed in 7.61s`、dense-raster
`23 passed in 8.74s`、完整 pg-canvas `362 passed, 1 deselected in 90.65s`。最后
执行 `git diff --check` 与 lessons completion gate。Windows EXE 仍作为独立后续门禁。

## Definition Of Done

- raw-X scan、resize quiet、selection identity 的确定性测试全绿；
- 普通 HDF 分屏增减不再全图 clear/rebuild；
- 真实 Cocoa pan/resize/warm checkbox 达到性能准则；
- dense-discrete/CRC、cursor、stats、export、颜色和 View 状态无回退；
- benchmark JSON 可由后续版本重复对比；
- 报告区分 offscreen、macOS live、Windows packaged 的证据等级；
- 未验证 Windows EXE 时明确写 `Windows pending`，不宣称跨平台完成。

## Execution Outcome

- Stage 0–3：完成；raw-X generation cache、resize quiet window、普通 subplot
  retained-row delta 均有确定性回归覆盖。
- Stage 4：完成评估并否决；无 raster 生产改动遗留。
- Stage 5–6：完成；可复现 JSON benchmark、macOS Cocoa 门禁、报告回填、完整
  pg-canvas 回归和 lesson promotion 均已完成。
