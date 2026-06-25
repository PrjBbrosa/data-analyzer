# TraceLab 操作反馈系统设计

## 背景

当前 TraceLab 已经有多套反馈机制，但没有一套系统级规范来约束“用户点击后必须得到什么反馈”。结果是一些路径有 toast 或弹窗，另一些路径只有状态栏一闪，甚至直接 `return`。用户在右侧点击「绘图」或计算按钮时，如果前置条件不满足，就会觉得“点了没反应”。

这份 spec 的目标是先补一层统一的操作反馈契约，优先解决高频、低风险的静默 no-op，不重做现有帮助面板、不改变计算逻辑、不扩大到完整新手引导。

## 现有反馈基础设施

### Toast

入口是 `MainWindow.toast(msg, level)`，位于 `mf4_analyzer/ui/main_window/window.py`。实现是 `Toast`，位于 `mf4_analyzer/ui/widgets/__init__.py`。

行为：

- 非模态，浮在主窗口底部。
- 同一时间只显示一条，新消息替换旧消息。
- level 支持 `info`、`success`、`warning`、`error`。
- 停留时间由 level 决定：info/success 约 3.5s，warning 约 5s，error 约 7s。
- 适合“点击已被接住”的强反馈：条件不足、完成、失败、缓存命中、恢复失败。

当前使用分布：

- 主窗口加载/保存/导出/批处理/横坐标更新等路径已有部分 toast。
- FFT / FFT vs Time / Order 的一些无效信号、忙碌、完成、失败路径已有 toast。
- Batch drawer 内部有 `_toast(...)`，会向上找父窗口的 `toast(...)`。
- Markup editor 有自己的局部 Toast。

### Status Bar

入口是 `statusBar.showMessage(...)`，散布在主窗口和分析 mixin 中。

行为：

- 最底部小字，部分调用带 2000ms timeout。
- 可见度弱，容易被底部 hint bar 或快速状态刷新淹没。
- 适合“持续状态 / 次要状态”：正在计算、绘制数量、当前文件摘要、焦点栏位。
- 不适合作为唯一失败反馈。

当前问题：

- 一些旧路径只写 status bar，不 toast。对用户来说几乎等于无反馈。

### QMessageBox

入口是 PyQt 原生 `QMessageBox.warning/information/critical/question`。

行为：

- 模态，用户必须确认。
- 适合不可忽略、可能造成数据丢失、需要用户确认的操作。
- 不适合普通“未选择通道”这类轻提示。

当前使用分布：

- 通道编辑器、导出对话框、批处理结果、overlay 轴太多确认等路径已有弹窗。
- 部分旧路径可能仍存在“应该 warning 但直接 return”的缺口。

### Chart Hint Bar

提示注册表在 `mf4_analyzer/ui/hints.py`，底部 hint bar 在 `ChartStack` / `_ChartCard` 中消费。

行为：

- 面向“怎么操作”的低打扰提示。
- 有 persistent / discovery / context / flash tip 概念。
- 文案有宽度预算，`tests/ui/test_hints.py` 约束 hint 长度。
- 适合快捷键、手势、下一步建议，不适合作为唯一错误反馈。

当前使用分布：

- TimeDomain 底部有 `?` 操作速查入口。
- heatmap slice 无结果/越界会走 `slice_hint_requested -> flash_hint(...)`。
- 部分发现式提示会通过 `QSettings` 记录 discovered。

### Canvas Empty Hint

`PgHeatmapCanvas.show_empty_hint(...)` 已存在，主要用于 FFT vs Time / Order 这类“结果尚未生成”的空状态。

TimeDomain 当前没有统一的空画布说明。`_plot_time_on_canvas(...)` 在无文件、无勾选、无可绘制数据时会清空画布并返回，缺少中间空态和 toast。

## 当前没有系统级规范

目前项目里有局部约定：

- `2026-06-19-compute-feedback-and-cache-key-design.md` 讨论过计算反馈、缓存命中、保存失败等问题。
- `hints.py` 规范了 chart hint 的长度、分层和发现机制。
- 若干 lessons 记录了“状态栏太弱”“silent no-op 不能吞掉”的失败经验。

但还没有一个横跨主窗口、TimeDomain、FFT、FFT vs Time、Order、Batch 的系统级规则。新增功能时开发者需要自己判断用 toast / statusBar / hint / QMessageBox，容易漏掉早退路径。

## 反馈分级规范

### 阻断型失败

用户点击了明确动作，但前置条件不满足，必须 toast warning 或 error。

例子：

- 点击「绘图」但未加载文件。
- 点击「绘图」但未勾选通道。
- 点击「绘图」后时间范围内没有任何可绘制样本。
- 点击 FFT / FFT vs Time / Order 计算但未选择有效信号。
- 点击导出但没有可导出数据。

规则：

- 不允许只 `return`。
- 不允许只写 status bar。
- 文案必须告诉用户下一步怎么做。

### 执行中状态

动作已开始且可能超过一个瞬间，使用 status bar；长任务可再配合已有 progress/worker UI。

例子：

- 正在计算 FFT vs Time。
- 正在运行批处理。
- 正在导入大文件。

规则：

- status bar 是主通道。
- 不要每次开始都 toast，避免打扰。

### 完成确认

用户主动触发、结果不可见或容易错过时，用 toast success。

例子：

- 已复制到剪贴板。
- 已保存项目。
- 已导出文件。
- 计算完成但结果可能在当前页/当前 pane 不明显。

规则：

- 可见结果已经立即出现在图上时，status bar 可以作为主反馈；如果用户经常误解“没反应”，补轻 toast。

### 轻量状态

不会阻断流程，只是说明当前状态，使用 status bar 或 hint bar。

例子：

- 聚焦主/对比视图。
- 绘制了多少通道。
- 横坐标已更新。

规则：

- status bar 可用。
- 如果这条信息是用户下一步必须知道的，不应只用 status bar。

### 需要确认或不可逆

使用 QMessageBox。

例子：

- overlay 下勾选很多通道会产生很多 Y 轴，需要确认。
- 关闭/删除多个对象。
- 保存失败、导出失败且可能导致数据丢失。

规则：

- 模态弹窗只用于必须停下来的情况。
- 普通条件不足不使用弹窗。

### 学习型提示

使用 hint bar / quickref，不替代错误反馈。

例子：

- Ctrl/Shift 滚轮缩放。
- 右键图表打开轴范围。
- 多选通道右键共轴。

规则：

- hint bar 可以补“下一步”，但不能成为唯一的失败提示。

## P0 范围

P0 只补最影响“点了没反应”的路径。

### TimeDomain 绘图

入口：`MainWindow.plot_time()` -> `_plot_time_on_canvas(...)`。

当前缺口：

- 无文件：清空画布后返回，无 toast。
- 无勾选通道：清空画布后返回，无 toast。
- 构建数据为空：清空画布后返回，无 toast。
- overlay 轴太多确认后用户点 No：直接返回，无反馈。

目标：

- 无文件：toast warning「请先打开数据文件」。
- 无通道：toast warning「请在左侧勾选至少一个通道」。
- 数据为空：toast warning「当前时间范围内无可绘制数据，请调整时间范围或点最大」。
- 用户取消 overlay 多轴确认：status bar「已取消绘图」即可。

约束：

- 自动通道变更触发的 replot 不应频繁 toast。只有用户显式点击「绘图」时才给强 toast。
- 因此需要区分 `plot_time(user_initiated=True)` 和内部自动 replot。

### 显式操作与自动重绘分离

当前很多地方调用 `plot_time()`：

- 右侧「绘图」按钮。
- 通道勾选变化。
- 横坐标变化。
- 文件关闭后重置。
- split/focus/view 恢复。

规则：

- 右侧按钮和用户明确命令走 `user_initiated=True`。
- 自动同步走 `user_initiated=False`，避免无文件/无通道时反复弹 toast。

### Analysis 计算入口抽样收敛

FFT / FFT vs Time / Order 已有部分 toast，但 P0 应补一个审计表，不要求一次改完全部：

- 入口点击无信号必须 toast warning。
- worker 忙碌 re-entry 必须 toast info/warning。
- 全部 source 被跳过必须 toast warning，而不是空白结果。
- 计算完成但全部缓存命中必须 toast info。

这些已有一些实现和测试，P0 只补静默漏点，不重构计算管线。

### Heatmap Slice

已有 `slice_hint_requested` 和 `flash_hint(...)`，P0 不改为 toast。

原因：

- 点击谱图取切片属于图内探索，不是按钮级命令。
- 当前 flash hint 文案「先点计算生成谱图」「点击位置超出谱图范围」已经合适。

## 非目标

- 不重做 QuickRef / 操作速查内容。
- 不新增新手引导流程。
- 不把所有 status bar 都改成 toast。
- 不把所有 QMessageBox 都降级成 toast。
- 不修改计算算法、滤波算法、坐标轴同步逻辑。
- 不一次性审计所有 `return`，只覆盖用户明确点击动作的高频早退路径。

## 建议实现形态

### 统一 helper

在 `MainWindow` 增加一个很薄的 helper：

```python
def _action_feedback(self, message, level="info", *, status=True, toast=True):
    if status:
        self.statusBar.showMessage(message, 3000)
    if toast:
        self.toast(message, level)
```

或者更语义化：

```python
def _warn_action_blocked(self, message):
    self.statusBar.showMessage(message, 3000)
    self.toast(message, "warning")
```

P0 不需要独立服务类，避免过度抽象。

### 绘图入口参数

右侧按钮接入：

```python
self.inspector.plot_time_requested.connect(
    lambda: self.plot_time(user_initiated=True)
)
```

内部调用保持默认：

```python
def plot_time(self, *, user_initiated=False):
    ...
```

`_plot_time_on_canvas(...)` 也接收 `user_initiated`，只在显式点击且 `update_primary_ui=True` 时 toast。

### 空图原因

P0 不要求 TimeDomain 中间画布显示空态，但实现时应把原因集中为枚举/字符串，方便后续加 empty hint。

建议原因：

- `no_files`
- `no_checked_channels`
- `no_plot_data`
- `cancelled_overlay_axis_warning`

## 测试策略

### TimeDomain

新增或扩展 `tests/ui/test_main_window_smoke.py`：

- 点击「绘图」且无文件：捕获 `toast("请先打开数据文件", "warning")`。
- 加载文件但不勾通道，点击「绘图」：捕获 `toast("请在左侧勾选至少一个通道", "warning")`。
- 时间范围裁到无数据，点击「绘图」：捕获 `toast("当前时间范围内无数据...", "warning")`。
- 通道勾选自动触发 replot，在无通道状态下不 spam toast。

### Analysis

复用现有测试模式：

- `tests/ui/test_analysis_multiview_integration.py` 已有 `*_all_cached_emits_info_toast`、`*_reentry_busy_toast` 类测试。
- P0 对新补的静默路径添加 focused tests，不跑全量大测试。

### Hint

如果新增 hint 文案，必须跑：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_hints.py -q
```

P0 原则上不新增 hint registry 文案。

## 验收标准

- 用户显式点击主操作按钮时，没有静默失败。
- 阻断型失败至少有 toast warning。
- 轻量成功/状态不因 toast 过多而打扰。
- 自动 replot 不 spam toast。
- 新增测试覆盖「显式点击」与「自动路径」的差异。
- `git diff --check` 通过。

## 后续 P1

- 建立 `FeedbackReason` 或类似枚举，减少散落字符串。
- 给 TimeDomain 画布增加居中 empty hint，例如「未勾选通道」。
- 给全局 action 按钮建立 affordance 规则：禁用时必须有 tooltip；可点但条件不足时必须 toast。
- 审计所有 `return` / `return False`，只对用户动作入口补反馈，不对内部 guard 滥发提示。
