# PyQtGraph TimeDomain 实时抗锯齿可行性分析

日期：2026-05-30

范围：只评估实时显示“性能 + 美观”的可行方案，重点检查平移、框选缩放、滚轮缩放、游标、叠加通道选择/拖动、复制导出之间是否冲突。本文不包含代码改动。

## 结论

**建议做受控原型：交互中关闭曲线抗锯齿，停手稳定后自动开启轻量抗锯齿。**

**不建议全局永久开启 `antialias=True`。** 这已经被当前回归测试和历史性能计划明确列为 pan/zoom 卡顿主因之一：曲线创建现在默认不传 `antialias=True`，测试要求交互曲线保持 AA off，复制/保存时才临时打开 AA。

用户体验判断：

- **静止阅读 / 截图 / 给别人看图时感知强烈。** 用户截图里“复制图片”明显更细腻，实时图明显粗糙，这类差异在慢速趋势线、斜线、温度线、低噪声曲线上很容易被看出来。
- **拖动 / 框选 / 滚轮缩放过程中感知不如流畅度强。** 交互时用户主要感知跟手性、延迟和是否掉帧。这个阶段关闭 AA 是合理取舍。
- **停手后 120-180 ms 自动变细腻，大概率是正向体验。** 但必须避免游标移动时反复切换，否则会出现线条闪烁、发虚、粘滞感。

推荐方案不是“实时一直 AA”，而是 **Auto Idle AA**：

1. 任意交互开始或范围变化时，立即把曲线 AA 置为 off。
2. 最后一次 pan/zoom/wheel/drag 后，启动单次 idle timer。
3. idle timer 到期时，如果鼠标未按下、没有框选/拖动、没有高频游标移动，并且可见曲线密度不太高，再把曲线 AA 置为 on 并 repaint 一次。
4. 下一次交互开始前再次立即关掉 AA。

## 当前证据

### 已有导出路径已经证明“高质量静态渲染”可行

- `mf4_analyzer/ui/pg_canvases.py:3330-3362` 已有 `_curves_antialiased()`，导出时临时把所有 `PlotCurveItem.opts["antialias"]` 设为 `True`，退出后恢复。
- `mf4_analyzer/ui/pg_canvases.py:3363-3407` 的 `grab_pixmap(scale)` 已经在高 DPI 抓图期间进入 `_curves_antialiased()`。
- `mf4_analyzer/ui/pg_canvases.py:3417-3454` 的 `_grab_widget_scaled()` 在放大渲染时开启 `QPainter.Antialiasing` 和 `SmoothPixmapTransform`。
- `mf4_analyzer/ui/chart_stack.py:9-13` 复制/保存默认请求 2x hi-DPI。
- `mf4_analyzer/ui/chart_stack.py:1378-1395` 复制卡片图片走 hi-DPI 抓图路径。

这说明复制图“完美”的原因不是偶然：当前架构已经支持静态高质量渲染，只是它被刻意隔离在复制/保存期间。

### 当前实时路径明确偏向交互性能

- `mf4_analyzer/ui/pg_canvases.py:1274-1304` 绑定曲线时只创建 `PlotDataItem(..., pen=pen, name=name)`，没有传 `antialias=True`。
- `mf4_analyzer/ui/pg_canvases.py:2577-2624` pan/zoom 后会按可见窗口重新 envelope 并 `setData()`，这是实时热路径。
- `mf4_analyzer/ui/pg_canvases.py:2465-2485` X range 变化先同步兄弟 subplot，再用 40 ms timer 合并刷新。
- `tests/ui/test_pg_timedomain_canvas.py:3372-3391` 有回归测试明确要求曲线在 pan 性能路径上不能开启 AA。
- `docs/superpowers/plans/2026-05-29-pyqtgraph-timedomain-perf-regression-fix.md:5-8` 记录过：`antialias=True`、range-change 标签重排、ghost labels 是 UI 对齐后卡顿的主要新增成本。

因此全局开启 AA 会直接逆转这条性能保护线。

## 候选方案

| 方案 | 可行性 | 性能风险 | 视觉提升 | 操作冲突 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 全局永久 AA | 低 | 高 | 高 | 中 | 不建议，会重开已修复的 pan 卡顿风险 |
| 只调线宽/透明度 | 高 | 低 | 中低 | 低 | 可做辅助，但解决不了锯齿本质 |
| 交互 off，停手后 idle AA on | 高 | 中低 | 高 | 中，需要严密门控 | 推荐原型 |
| 停手后生成缓存 pixmap 覆盖 | 中低 | 低到中 | 很高 | 高 | 后续高级方案，当前不建议先做 |
| OpenGL / 全局渲染 backend | 低 | 不确定 | 不确定 | 中高 | 不建议，已有报告不推荐引入 |

## 推荐方案：Auto Idle AA

### 状态机

建议新增一个局部状态，不改变数据 envelope、不改变坐标同步、不改变导出逻辑：

- `interactive`: 曲线 AA off。任何 pan、框选、滚轮、Y 轴拖动、replot/range mutation 进入该状态。
- `idle_pending`: 最后一次交互结束后等待 120-180 ms。
- `idle_quality`: 条件满足时曲线 AA on，只触发一次 repaint。

关键规则：

- AA 切换只改 `PlotCurveItem.opts["antialias"]`，不调用 `setData()`，避免干扰 envelope cache。
- 进入交互前必须先关 AA，再让 ViewBox 处理 pan/zoom/range change。
- idle 开启 AA 前必须确认没有鼠标按键按下、没有 `_overlay_dragging`、没有框选矩形拖拽、没有连续游标移动。
- 复制/保存仍使用现有 `_curves_antialiased()`，不要依赖实时 AA 状态。

### 延迟建议

初始建议使用 **150 ms**：

- 比当前可见数据刷新 timer 的 40 ms 更慢，不抢 pan/zoom 热路径。
- 接近 toolbar 历史记录 debounce 的 180 ms，可减少“停手后又马上重绘”的次数。
- 用户通常不会把 150 ms 的静态细化感知成延迟，但会明显感知拖动卡顿。

## 交互冲突分析

### 1. 平移拖动

当前 toolbar pan/zoom 由 `PgNavigationToolbar` 维护模式，pan mode 最终设置 ViewBox `PanMode`（`mf4_analyzer/ui/chart_stack.py:672-689`）。ViewBox 的范围变化会触发 `_on_xrange_changed()`，再同步 sibling xlim 并延迟刷新数据（`mf4_analyzer/ui/pg_canvases.py:2465-2485`）。

冲突点：

- 如果拖动过程中 AA on，会增加每帧绘制成本，风险很高。
- 如果 idle timer 在鼠标仍按下时触发，会出现拖动中突然变细腻又变卡。

处理方式：

- pan 开始或第一次 range change 时立即 AA off。
- idle timer 到期时检查鼠标按键状态；仍按下则延后。

结论：**可兼容，但必须以“拖动中永远 off”为硬规则。**

### 2. 框选缩放

框选缩放由 toolbar zoom mode 设置 ViewBox `RectMode`（`mf4_analyzer/ui/chart_stack.py:691-702`），replot 后还会重新应用当前 mode（`mf4_analyzer/ui/chart_stack.py:468-480`）。

冲突点：

- RectMode 的 rubber band 是 ViewBox 内部鼠标拖拽状态。外部如果在框选过程中切 AA 并 repaint，可能造成框选矩形闪烁或拖拽感变重。
- eventFilter 目前主要处理双击、overlay、cursor，并不完整拥有 ViewBox 的框选拖拽生命周期（`mf4_analyzer/ui/pg_canvases.py:2239-2277`）。

处理方式：

- 不在鼠标左键按下期间启用 idle AA。
- 等 range change 完成并释放鼠标后，再进入 idle_pending。
- 不改 ViewBox mouse mode，不包裹 RectMode 逻辑。

结论：**可兼容，但 idle AA 不能只靠 eventFilter 判断，必须额外检查全局鼠标按钮或 ViewBox 手势状态。**

### 3. Ctrl/Shift/普通滚轮

当前滚轮被 `_ModifierWheelViewBox` 路由到 `_handle_wheel_dispatch()`，Ctrl 改 X、Shift 改 Y、普通滚轮 pan Y（`mf4_analyzer/ui/pg_canvases.py:2926-2975`）。相关测试覆盖 Ctrl X zoom、Shift Y zoom、plain wheel Y pan（`tests/ui/test_pg_timedomain_canvas.py:2584-2669`）。

冲突点：

- 连续滚轮会快速触发范围变化和 repaint。
- 如果每个 wheel 后立刻 AA on，会导致短时间内反复切换。

处理方式：

- wheel dispatch 开头 AA off。
- 每次 wheel 后 restart idle timer，只在最后一次滚轮后开启。

结论：**最容易兼容，适合成为第一批自动化测试入口。**

### 4. 单游标 / 双游标

游标 hover 现在 33 ms throttle，移动时更新 cursor items 和 HTML，再 `draw_idle()`（`mf4_analyzer/ui/pg_canvases.py:1814-1842`）。双游标点击放置也会 repaint（`mf4_analyzer/ui/pg_canvases.py:1845-1872`）。

冲突点：

- 游标移动频率接近 30 FPS。如果 AA 在游标移动期间保持 on，曲线也会随场景 repaint 走 AA，可能造成明显粘滞。
- 如果每次游标移动都关 AA，静止观察时又会经常从 smooth 闪回 jagged。

处理方式：

- 游标移动期间维持 interactive/off。
- 鼠标停止移动超过 200 ms 后，才允许 idle AA。
- 如果游标浮层可见但鼠标静止，可以允许 AA on；否则截图状态和实际阅读状态都会偏粗糙。

结论：**可兼容，但这是最容易产生“闪烁/粘滞”的区域，需要单独验收。**

### 5. 叠加通道选择与 Y 轴拖动

overlay press 会选中最近曲线并开始 Y-only drag；拖动期间禁用 X-master mouse，release 后恢复（`mf4_analyzer/ui/pg_canvases.py:2020-2077`）。测试覆盖选择、空白取消、第一通道拖动、drag 期间禁用 X pan、cursor mode 下 overlay press 不生效（`tests/ui/test_pg_timedomain_canvas.py:1674-1970`）。

冲突点：

- Y drag 需要持续 repaint，AA on 会增加每帧成本。
- overlay hit-test 是按 scene/viewport 坐标找最近曲线，AA 本身不改变数据点，但线宽/透明度变化如果被同时调整，可能影响用户肉眼判断“点中了哪条线”。

处理方式：

- `_handle_overlay_mouse_press()` 开始时 AA off。
- `_overlay_dragging` 为 True 时禁止 idle AA。
- `_handle_overlay_mouse_release()` 后 schedule idle。
- 不在这个方案里调整线宽、pick radius 或选中样式。

结论：**可兼容，前提是不把视觉优化和 hit-test/线宽优化绑在一起做。**

### 6. Home / Back / Forward / Replot

toolbar 的 Home/Back/Forward 会改变 ViewBox range，history capture 通过 `sigRangeChangedManually` + 180 ms debounce 记录（`mf4_analyzer/ui/chart_stack.py:530-572`）。replot 后 toolbar 会重新应用 mouse mode（`mf4_analyzer/ui/chart_stack.py:468-480`）。

冲突点：

- 新建曲线必须默认 AA off，否则会破坏当前性能测试。
- 恢复历史视图后如果立刻 AA on，可能和可见数据 refresh 的 40 ms timer 抢一帧。

处理方式：

- `plot_channels()` 后默认 off。
- 首次稳定帧后再允许 idle AA。
- Home/Back/Forward 先 off，再 schedule idle。

结论：**可兼容，注意不要在 replot 构建阶段开 AA。**

### 7. 复制 / 保存图片

复制/保存已经有独立的 hi-DPI + 临时 AA 路径。测试也要求 `grab_pixmap()` 进入 AA context 后恢复原状态（`tests/ui/test_pg_timedomain_canvas.py:997-1039`）。

冲突点：

- 如果实时 idle AA 已经是 on，导出 context 进入前的 previous state 是 True，退出后应该恢复 True，而不是强制 off。

处理方式：

- 保持 `_curves_antialiased()` 的“保存原值、退出恢复原值”语义。
- 新 idle AA 状态只作为普通实时状态，导出不依赖它。

结论：**兼容性高，现有设计已经适合扩展。**

## 用户感知评估

### 感知强的场景

- 静止查看趋势线、温度线、缓慢斜率曲线。
- 复制图和实时窗口并排比较。
- 高 DPI / Retina 屏上近距离看线条边缘。
- 多 subplot 下每个通道 label、grid、曲线颜色都较细时，曲线锯齿会显得更突兀。

### 感知弱或不值得牺牲性能的场景

- 正在 pan/zoom/框选拖动时。
- 红色摩擦类高频/裁剪/跳变曲线，AA 会让边缘变柔，但不一定提升分析可读性。
- 数据密度远高于像素宽度时，envelope 本身已经是视觉聚合，AA 可能更像“模糊”而不是“准确”。

### 可能的负体验

- 停手后线条突然“跳一下变细腻”。如果只发生一次且稳定，通常可接受。
- 游标移动时反复粗/细切换。这个不可接受，必须用 idle debounce 和鼠标移动门控避免。
- 曲线太细导致高频信号看起来发虚。必要时可用 density guard：密集曲线继续 off，低密度曲线才 on。

## 实施建议

第一阶段只做 Auto Idle AA，不同时改线宽、grid、label 或 OpenGL：

1. 增加曲线 AA 状态 helper：收集 curve items，统一 set/get。
2. 增加 `disable_interactive_quality()`：任何交互开始、range change、wheel、overlay drag、replot 调用。
3. 增加 `schedule_idle_quality()`：最后一次变化后 150 ms 单次 timer。
4. 增加 `try_enable_idle_quality()`：确认鼠标未按下、未 overlay drag、未框选拖拽、最近没有 cursor move、曲线密度未超阈值，然后开启 AA。
5. 保持 `grab_pixmap()` 的临时 AA context 不变。

第二阶段再考虑视觉细调：

- 将默认线宽从 `1.7` 轻微下调到 `1.4-1.5` 试验，可能降低“不 AA 时很粗糙”的感知。
- 针对高密度曲线保持 AA off，低密度曲线 AA on。
- 只有当 Auto Idle AA 仍不够，再评估 idle cached pixmap overlay。

## 验收标准

必须同时满足：

- 平移拖动过程中曲线 AA 保持 off，拖动手感不能回退到历史卡顿。
- 框选缩放矩形不闪、不丢、不被 idle timer 干扰。
- Ctrl/Shift/普通滚轮连续操作时不抖动，最后停手后静态线条变平滑。
- 单游标/双游标移动时不卡、不闪；鼠标停住后可以恢复静态细腻。
- overlay 通道选择和 Y 拖动不改变选中逻辑，不误触发 X pan。
- 复制/保存图片仍然高质量，且不会把实时 AA 状态永久改坏。
- 现有 `test_curves_are_not_antialiased_for_pan_perf` 仍能表达“交互阶段必须 off”，新测试应改为验证“idle 后可 on，而交互开始立即 off”。

建议新增测试：

- idle timer 到期后曲线 AA on。
- wheel/pan/range change 后曲线 AA 立即 off。
- overlay dragging 时 idle timer 到期也不能 AA on。
- cursor 高频移动期间不能反复 AA on。
- `grab_pixmap()` 在实时 AA on/off 两种状态下都能恢复原值。

必须保留一轮真实 GUI 验证：

- 使用用户截图里的 `tiaodamping` 数据或同等 4-5 通道数据。
- 分别验证 subplot、overlay、单游标、双游标、框选缩放、拖动 pan、滚轮缩放、复制图片。
- 记录至少两张截图：交互中 AA off、停手 150-200 ms 后 AA on。

## 风险结论

**全局 AA：不通过。**

它和当前性能回归修复方向冲突，用户会先感知到拖动变卡，再感知到线条变美。

**Auto Idle AA：通过可行性评估，建议进入小范围原型。**

它把用户感知最强的“静止画面粗糙”变好，同时把用户最敏感的“拖动不跟手”保护住。核心风险不在算法，而在交互门控：必须确保框选、拖动、游标这些连续操作期间不会被 idle repaint 插入。
