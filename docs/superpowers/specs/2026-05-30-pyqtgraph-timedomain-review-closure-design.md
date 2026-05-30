# Pyqtgraph TimeDomain Review Closure Design

日期：2026-05-30
分支：`plan/pyqtgraph-timedomain-migration`
范围：收口 Claude 最近 UI 优化后仍遗漏的 TimeDomain pyqtgraph 交互缺陷。

## 当前状态

Claude 最近的本地提交 `c08bf734` 已覆盖：

- 右键菜单浅色圆角、子菜单透明背景、tooltip 遮挡修复。
- 右键菜单的鼠标操作与顶部工具栏状态联动。
- X/Y 轴表单隐藏低频/危险原生行。
- 复制/保存图片走 hi-DPI 抓图，并让单游标 pill 竖向显示多通道读数。

但复验发现以下缺口仍在：

1. overlay 模式右键 `网格` 子菜单默认把 X/Y 都当作 enabled；点击任一项会调用 `showGrid(x=..., y=True)`，重新打开 overlay 禁止的 Y 网格。
2. ChartOptions 的 `显示网格线` 通过 `PgAxisHandle.grid()` 同时设置 X/Y 网格，也会重新打开 overlay 禁止的 Y 网格。
3. 右键 `查看全部` 仍然走 pyqtgraph 原生 ViewBox auto-range，没有复用 `TimeDomainCanvasPG.reset_view_to_data_extents()`，overlay 下不会恢复每条曲线的全量 Y 范围。
4. PG ChartOptions 改曲线颜色只同步 PlotDataItem 和 AxisItem；`TimeDomainCanvasPG.channel_data`、单/双游标 HTML、inside label badge 仍使用旧颜色。
5. PG 单游标 hover 没有保留 matplotlib renderer 的 33ms 节流，连续 mouse move 会连续发 `cursor_info` 和重绘。
6. 本地提交 `1864afb8` 增加了 `.openclaw/`、`.playwright-cli/`、`HEARTBEAT.md` 等 runtime/workspace 产物。它不属于本优化范围；本轮不删除，但合并前需要单独决定是否从分支移除。
7. subplot 第一帧的 X 网格仍可能错位：左轴宽度统一发生在后续 X 范围初始化、tick density 和 GraphicsLayout settle 之前；Y tick 宽度差异较大时，同一个数据 X 会映射到不同 scene X。

## 设计原则

- 只修 TimeDomain pyqtgraph 的真实遗漏，不扩大到频域、阶次、文件导航等路径。
- 保留 Claude 已完成的 UI polish 和现有测试结构。
- 每个缺口先补失败测试，再改实现。
- overlay 模式没有 canonical Y grid；任何入口都只能控制共享 X grid，不能打开 Y grid。
- `查看全部` 对用户语义必须等同顶部 Home：全量 X union + 每通道 raw Y extents。
- PG ChartOptions 的颜色修改必须保持曲线、轴、inside label、游标 HTML 使用同一个颜色源。
- subplot 模式必须在第一帧就共享同一套 X 网格；不能依赖下一轮 Qt event pass 才自愈。
- offscreen Qt 测试只能证明结构和状态；最终仍需保留 live GUI 验证门。

## 设计

### A. Context Menu View All

`TimeDomainCanvasPG._redesign_context_menu_for_viewbox()` 在调用 `redesign_pg_context_menu()` 时传入 `reset_view_to_data_extents`。

`redesign_pg_context_menu()` 在本地化后找到 `查看全部` / `View All` action，断开原生 ViewBox auto-range 连接，并连接到 canvas 的 reset handler。

验收：

- subplot/overlay 下，右键 `查看全部` 会恢复 raw X union。
- overlay 下，每个通道的 Y 范围会恢复自身 raw full min/max。

### B. Overlay Grid Policy

为右键网格菜单增加 `allow_y_grid` 参数。

- subplot/single：X/Y action 初始勾选态来自当前 AxisItem grid 状态，两个 action 都可用。
- overlay：X action 初始勾选态来自 bottom grid；Y action 不勾选且 disabled；任何 X toggle 都必须调用 `showGrid(x=<state>, y=False)`。

验收：

- overlay 初始仍是 X grid on、所有 Y grid off。
- 打开右键菜单再点击 `显示 X 网格` 不会让 left/right/aux Y grid 变 true。
- 程序化触发 disabled Y action 也不会打开 Y grid。

### C. ChartOptions Grid Policy

`PgAxisHandle` 增加 `allow_y_grid` 策略，默认 true。

- 普通 subplot/single handle：`grid(True)` 继续设置 X/Y。
- overlay channel handle 与 X-master handle：`grid(True)` 设置 X on、Y off；`grid(False)` 设置 X/Y off。
- `is_grid_enabled()` 动态读取当前 bottom grid，在 overlay 中代表共享 X grid 状态，避免右键菜单改动后 ChartOptions 读到陈旧缓存。

验收：

- overlay 下打开 ChartOptions 后直接 Apply 不会打开 Y grid。
- overlay 下取消 `显示网格线` 会关闭 X grid，且 Y grid 仍关闭。

### D. PG ChartOptions Color Sync

`PgAxisHandle` 保存 owner canvas，并在 `sync_line_axis_color(line, color)` 后用 line label 找到 channel name，调用 canvas 的 PG 颜色同步方法。

`TimeDomainCanvasPG` 提供内部方法：

- 更新 `channel_data[name]` 中的 color。
- 更新对应 inside label TextItem 的 text color 和 border pen。
- 调用 `draw_idle()`。

验收：

- PG ChartOptions 改色后，line pen、axis pen/textPen、`channel_data` color、单游标 HTML、双游标统计 HTML、inside label badge 颜色一致。

### E. Cursor Hover Throttle

PG `_handle_cursor_mouse_move()` 复用 matplotlib 的 33ms 节流语义：

- 非左键 hover：若距离上次 emit 小于 33ms，消费事件但不更新 HTML/line。
- 达到阈值后更新 `_last_t` 为当前毫秒时间，再发单/双游标信息。
- 左键 mouse move 仍返回 false，不能吞掉 pan/drag。

验收：

- 连续 5 次立即调用 hover move 只产生 1 次 `cursor_info`。
- 将 `_last_t` 人为回拨 40ms 后下一次 hover 会再次产生 emit。
- 左键 move 的既有测试仍通过。

### F. Subplot X Grid First-Frame Alignment

`plot_channels()` 在完成 `_set_xrange_to_data_union()` 和 `_apply_tick_density_to_all_axes()` 后，再调用一次 `_unify_subplot_left_axis_widths()`。

`_unify_subplot_left_axis_widths()` 在 pin 所有 left AxisItem 宽度后，立即 `invalidate()` + `activate()` GraphicsLayout，使 ViewBox 几何在当前调用栈内 settle，而不是等待后续 Qt 事件循环。

验收：

- subplot 下，即使各通道 Y tick 文本宽度差异很大，`plot_channels()` 返回后同一个数据 X 在所有 ViewBox 上映射到同一个 scene X。
- 后续 resize / tick density 仍复用同一个统一入口，不新增独立布局路径。

## 测试范围

新增/更新：

- `tests/ui/test_pg_timedomain_canvas.py`
  - overlay right-click grid does not enable Y grid
  - overlay context menu View All resets raw X/Y extents
  - single cursor hover is throttled
  - subplot X grid geometry is aligned before the first frame
- `tests/ui/test_dialogs.py`
  - overlay ChartOptions Apply preserves x-only grid
  - PG ChartOptions color updates channel data, cursor HTML, and inside label badge
- `tests/ui/test_axis_handle.py`
  - `PgAxisHandle.grid()` respects `allow_y_grid=False`

回归命令：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_dialogs.py \
  tests/ui/test_axis_handle.py \
  tests/ui/test_chart_stack.py -q
```

## 范围外

- 不删除 `1864afb8` 的 workspace/runtime 产物；合并前另开清理决策。
- 不改右键菜单视觉风格。
- 不新增自绘 popup 或底部说明区。
- 不用 offscreen 测试声称 live GUI 已完全验证。
