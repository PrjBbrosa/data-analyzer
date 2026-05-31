# Pyqtgraph TimeDomain 回归工作报告

日期：2026-05-29  
范围：`TimeDomainCanvasPG` follow-up 修复后的交互卡顿与 Y 轴标题显示问题  
当前状态：**NOT RESOLVED / 暂停合入**

## 结论

当前问题没有闭环。虽然本轮补丁在 offscreen Qt 单测、截图几何和程序化 pan 探针里通过，但用户在真实 GUI 中继续反馈：

- 更新后拖动图面仍然卡；
- 勾选通道开始就卡；
- Y 轴标题乱窜问题仍存在。

因此，测试绿灯只能说明“部分代码路径没有失败”，不能说明真实交互已经可用。后续不应继续用离屏截图或 `set_xlim()` 探针替代 live GUI 验证。

## 已做改动

### 1. 多轴 overlay 与 X 范围

- `plot_channels()` 在 overlay 模式中为每个通道创建独立 `PgAxisHandle` / `ViewBox` / Y 轴，代码位于 `mf4_analyzer/ui/pg_canvases.py:402-415`。
- 构图后统一调用 `_set_xrange_to_data_union()`，把所有轴的 X 范围设为原始数据并集，代码位于 `mf4_analyzer/ui/pg_canvases.py:430-437`。

目的：修复 overlay 初始 X 轴停在 `0..1`、通道勾选后第一帧范围异常的问题。

### 2. Tick density 止血

- `set_tick_density()` 已从固定 `setTickSpacing(major, minor)` 改为 `AxisItem.setTickDensity()`，代码位于 `mf4_analyzer/ui/pg_canvases.py:1008-1024`。
- `_apply_axis_tick_density()` 会清掉固定 `_tickSpacing`，并限制 `maxTickLevel=0`，避免 minor tick/grid/label 爆量绘制。

目的：避免通道勾选和拖动时生成过密 tick、grid、label 导致 repaint 卡顿。

### 3. 初始绘制点数

- `_bind_channel()` 初始 envelope 不再固定用 `MAX_PTS=8000`，改为 `_initial_bind_pixel_width(axis_handle)`，代码位于 `mf4_analyzer/ui/pg_canvases.py:542-581`。

目的：避免每个通道首帧先塞 8000 点到 Qt painter，降低勾选通道后的第一帧压力。

### 4. Subplot inside label

- 4 个及以上子图强制进入 inside badge，避免旋转 Y 轴标题堆叠，判断位于 `mf4_analyzer/ui/pg_canvases.py:1969-1999`。
- inside badge 改为 scene overlay，按 `ViewBox.sceneBoundingRect()` 定位，并监听 `sigRangeChanged` / `sigResized`，代码位于 `mf4_analyzer/ui/pg_canvases.py:2009-2117`。

目的：避免 label 绑定数据坐标导致 pan/zoom 后位置漂移。

## 已补测试

新增或调整的主要回归测试：

- dense subplot 使用 inside badge：`tests/ui/test_pg_timedomain_canvas.py:1288-1304`
- inside badge pan/zoom 后保持视口锚定：`tests/ui/test_pg_timedomain_canvas.py:1306-1342`
- overlay 初始 X 范围使用 raw data extent：`tests/ui/test_pg_timedomain_canvas.py:1383-1395`
- 初始 bind 使用 viewport 宽度而非 8000 点：`tests/ui/test_pg_timedomain_canvas.py:2228-2249`
- tick density 不安装固定 spacing，且限制 tick level：`tests/ui/test_pg_timedomain_canvas.py:2269-2291`

## 已跑验证

通过的验证：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
# 85 passed

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py tests/ui/test_axis_handle.py tests/ui/test_chart_stack.py -q
# 90 passed

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py -q
# 42 passed

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py::test_timedomain_pan_refresh_pg_canvas -q -s
# p50_ms=0.480, p95_ms=0.563
```

额外程序化探针结果：

```text
PG_INTERACTIVE_PROBE mode=subplot build_ms=108.2 pan_mean_ms=7.2 pan_max_ms=7.9
PG_INTERACTIVE_PROBE mode=overlay build_ms=62.0 pan_mean_ms=7.4 pan_max_ms=9.0
```

截图几何测试也通过，并生成：

- `/tmp/pg_parity_subplot_5ch.png`
- `/tmp/pg_parity_overlay_5ch.png`

## 为什么验证仍不足

这些验证不能替代用户当前看到的问题，原因如下：

1. **没有启动真实 GUI。**  
   所有测试都是 `QT_QPA_PLATFORM=offscreen`，无法覆盖 macOS/Qt 实际窗口组合器、鼠标连续拖动、真实 repaint 节奏。

2. **pan 探针是程序化 `set_xlim()`。**  
   用户拖动图面会走 `ViewBox` 的鼠标事件、scene update、axis layout、hover/cursor/filter 等完整路径；当前探针只覆盖 `set_xlim -> envelope -> setData`。

3. **截图是静态帧。**  
   截图只能证明某一帧不为空、布局大致可见，不能证明拖动过程中没有 layout thrash 或 repaint storm。

4. **真实数据规模与通道组合未知。**  
   目前探针使用合成 5 通道数据；用户实际文件可能有更多通道、更长时间轴、更多右轴、长文件名前缀、自定义 X 轴或范围筛选。

5. **多 ViewBox overlay 仍是高风险结构。**  
   当前 overlay 每个通道都有独立 `ViewBox` 和右侧 Y 轴，构图位置在 `mf4_analyzer/ui/pg_canvases.py:402-415`。这个结构比原来的单 ViewBox 重很多，即使程序化探针过关，也可能在真实拖动中触发更高的 scene/layout 成本。

## 当前风险判断

优先级最高的剩余风险：

1. **真实鼠标拖动路径发生 repaint/layout storm。**  
   需要对 `ViewBox.mouseDragEvent`、`sigXRangeChanged`、`_propagate_xlim_to_siblings()`、`_refresh_visible_data()`、AxisItem paint 次数做现场计数。

2. **scene overlay label 仍可能参与过多 scene update。**  
   inside badge 虽然脱离数据坐标，但现在是 `scene.addItem(text_item)`，在连续拖动/resize 下仍可能增加 scene repaint 压力。

3. **overlay 多右轴在真实 GUI 中过重。**  
   每个通道独立右轴会增加 tick/label/layout 成本。超过 5 通道时，现有警告只提示拥挤，并没有降级渲染策略。

4. **当前修复没有 live profile 证据。**  
   用户反馈优先级高于 offscreen 结果。现阶段不能继续声明“已修复”。

## 建议下一步

### A. 立即止血方案

在继续优化前，建议先提供一个可切换回稳定路径的开关：

- 临时把 TimeDomain 画布切回 matplotlib `TimeDomainCanvas`；
- 或提供环境变量 / 设置项，例如 `TRACELAB_TIME_CANVAS=mpl|pg`；
- 默认先回退到稳定渲染，避免用户继续卡在不可用状态。

### B. Live GUI 复现与 profiling

必须补一个真实 GUI 调试脚本，不再只用 offscreen：

- 加载用户同类文件或合成等量数据；
- 自动勾选 1、3、5、8 个通道；
- 自动拖动图面 3 秒；
- 统计每秒：
  - `sigXRangeChanged` 次数；
  - `_propagate_xlim_to_siblings()` 次数；
  - `_refresh_visible_data()` 次数；
  - `PlotDataItem.setData()` 次数；
  - `AxisItem.paint()` / `generateDrawSpecs()` 次数；
  - frame/pan 延迟分布。

### C. 若继续保留 pyqtgraph

建议分阶段降级复杂度：

1. subplot 优先可用：只保留 subplot 多轴，禁用 overlay 多右轴；
2. overlay 临时回到单 ViewBox / 单 Y 轴，先保证拖动流畅；
3. 多 Y 轴 overlay 后续单独做 profile，不和其它 UI parity 一起改。

## 最终判定

**当前不能合入，也不能再声明已修复。**

下一步应先做 live GUI 复现与 profile，或者先切回 matplotlib 作为止血方案。只有真实 GUI 拖动和通道勾选验证通过后，才能重新把 pyqtgraph TimeDomain 作为默认路径。
