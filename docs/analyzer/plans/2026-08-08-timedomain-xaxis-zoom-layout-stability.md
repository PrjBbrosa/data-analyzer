# TimeDomain 横轴缩放刻度与图框稳定性实施计划

日期：2026-08-08
状态：**已实施；自动化门槛通过，待人工前台手势验收**

## 1. 目标

修复 TimeDomain 横向缩放过程中的两个同源可见问题：

1. 新视窗暂时不包含旧显式刻度时，横轴刻度数字全部消失；
2. pyqtgraph 随之收回刻度文字高度，导致 ViewBox 图框向下扩，静止重算后又上移。

必须同时满足：

- 缩放中横轴仍显示与当前范围匹配的刻度；
- 缩放前、缩放中、静止重算后的底轴高度和图框底边不跳动；
- 保留现有交互静止窗口，不在每个范围事件里重算目标刻度；
- subplot、overlay、单图均一致；
- 不改变数据、曲线、量程、刻度密度设置和持久化语义。

## 2. 已确认现状

当前 `main` 的 offscreen 几何探针在单图、3 行 subplot、3 通道 overlay 上得到一致结果：

| 阶段 | 实际绘出的横轴数字 | 底轴高度 | ViewBox 底边 |
| --- | ---: | ---: | ---: |
| 缩放前 | 9 | 41.6 px | 475.9 px |
| 缩放手势中 | 0 | 23.6 px | 493.9 px |
| 静止后目标刻度恢复 | 7 | 38.1 px | 479.4 px |

机制已经由当前代码和 pyqtgraph 0.14 行为共同确认：

- `TickDensityController._apply_target_x_ticks()` 用 `AxisItem.setTicks(...)` 固定目标刻度；
- `_on_xrange_changed()` 为保护 dense HDF 交互性能，把目标刻度重算推迟到静止刷新；
- 中间帧仍持有旧显式刻度，若旧值全部落到新视窗外，`generateDrawSpecs()` 返回零条文字；
- pyqtgraph 默认 `autoReduceTextSpace=True`，零条文字会把 `textHeight` 降为 0；
- 可见底轴使用自动高度，因此图框跟着底轴高度改变。

现有 `test_target_x_ticks_refresh_after_xlim_change` 在断言前主动调用
`_flush_pending_refresh()`，只覆盖最终目标刻度，没有覆盖静止窗口到期前的中间帧。

## 3. 设计决策

### D1：底轴保留稳定的刻度文字空间

在 TimeDomain 创建 bottom `AxisItem` 时关闭 `autoReduceTextSpace`，保留
pyqtgraph 初始/已扩展的刻度文字高度：

```python
bottom_axis.setStyle(autoReduceTextSpace=False)
```

保留 `autoExpandTextSpace=True`，避免硬编码整条 AxisItem 高度，也允许未来字体确实更高时扩展。
subplot 上方隐藏底轴仍由 `_unify_subplot_bottom_axis_heights()` 固定为约 1 px，
不得恢复隐藏轴的完整留白。

### D2：范围变化期间一次性释放旧显式刻度

由 `TickDensityController` 新增一个小方法，遍历 `_x_tick_axis_handles()`、按 AxisItem
去重，并且仅当 `axis._tickLevels is not None` 时调用现有
`_reset_x_ticks_to_adaptive(axis)`。

从 `_on_xrange_changed()` 调用该方法，而不是只从 `_begin_view_interaction()` 调用，
以覆盖：

- 鼠标拖动；
- 滚轮和轴上滚轮缩放；
- 框选缩放；
- 程序化 `set_xlim`。

第一次范围变化会把显式刻度切为 adaptive；后续同一轮范围事件因
`_tickLevels is None` 自动成为空操作。静止刷新仍由既有
`_apply_target_x_ticks_to_all_axes()` 恢复用户设置的目标刻度数量。

### D3：不在热路径同步重算目标刻度

禁止在每个 `_on_xrange_changed()` 事件中调用 `_compute_target_x_ticks()` 或
`_apply_target_x_ticks_to_all_axes()`。交互期只做一次 `setTicks(None)`；目标刻度拟合、
QFontMetrics 测量和数据刷新继续留在现有静止窗口之后。

### D4：不扩大架构和状态面

- 不新增 `MainWindow` 状态；
- 不新增第二套计时器或刻度算法；
- 不改 `render_profile`、DSP、数据加载和 Batch renderer；
- 不改变 `_unify_subplot_bottom_axis_heights()` 的隐藏轴 1 px 合同；
- 新方法归 `TickDensityController` 所有，并更新 `_delegate_names`，保持 `_CanvasBackref`
  不变量。

## 4. 实施任务

### T1：先补失败回归

修改 `tests/ui/test_pg_timedomain_canvas.py`，增加静止窗口到期前的测试，至少覆盖：

- `subplot` 单行；
- `subplot` 三行，检查最后一行可见底轴；
- `overlay` 三通道，检查 X-master 底轴。

每个场景按以下顺序断言：

1. 初始目标刻度已设置，记录可见底轴高度与 ViewBox 底边；
2. 进入 held interaction，设置一个不包含旧显式刻度的窄 X 范围；
3. 在 `_flush_pending_refresh()` 之前强制一次 paint；
4. 断言绘出的横轴文字非空；
5. 断言底轴高度与 ViewBox 底边相对初始值误差不超过 0.5 px；
6. 结束并 flush，断言显式目标刻度恢复且几何仍不变。

另加一个小测试证明同一轮连续范围变化只从显式切 adaptive 一次，避免把
`setTicks(None)` 变成每帧写操作。

### T2：稳定 bottom AxisItem 的文字留白

修改 `mf4_analyzer/ui/pg_canvas/canvas.py::_add_plot_item()`：

- 只对 TimeDomain bottom axis 设置 `autoReduceTextSpace=False`；
- 保留现有 `maxTickLevel=0`、字体、pen、frame 和隐藏 subplot 底轴逻辑；
- 不固定完整 `setHeight(...)`。

### T3：交互期使用 adaptive ticks

修改 `mf4_analyzer/ui/pg_canvas/tick_density.py`：

- 添加 `_use_adaptive_x_ticks_during_range_change()`；
- 复用 `_x_tick_axis_handles()` 与 `_reset_x_ticks_to_adaptive()`；
- AxisItem 去重；
- 仅显式刻度存在时执行重置；
- 将方法加入 `_delegate_names`。

修改 `mf4_analyzer/ui/pg_canvas/canvas.py::_on_xrange_changed()`：

- 在范围传播和 paint 之前调用该方法；
- 不改变静止计时器、数据刷新、coarse refresh 和 sibling X 同步顺序的其余部分。

### T4：验证与视觉门槛

先跑定向用例，再跑边界和性能门槛：

```bash
TMPDIR=/tmp XDG_CONFIG_HOME=/tmp/tracelab-timedomain-axis-tests \
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_timedomain_hotpath_perf.py \
  tests/ui/test_pg_dense_raster.py \
  tests/ui/test_pg_canvas_backref_invariants.py

git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

视觉证据分级报告：

- offscreen 几何/paint 回归必须通过；
- macOS Cocoa 前台应至少检查单图、subplot、overlay 各一轮横向缩放；
- 若本轮未跑前台，明确标记为 `UNVERIFIED`，不得用 offscreen 代替。

## 5. 验收标准

- [x] 缩放中可见底轴至少绘出一个当前范围刻度数字；
- [x] 缩放前/中/后底轴高度误差不超过 0.5 px；
- [x] 缩放前/中/后 ViewBox 底边误差不超过 0.5 px；
- [x] subplot 单行、多行和 overlay 全覆盖；
- [x] 上方隐藏 subplot 底轴仍不超过既有约 1–4 px 门槛；
- [x] 静止后恢复 Inspector 目标刻度数量语义；
- [x] 同一轮范围变化不重复重置 adaptive ticks；
- [x] hotpath、dense raster、backref 和现有 TimeDomain 测试通过；
- [x] 无无关文件修改，`git diff --check` 通过；
- [ ] 前台 Cocoa 验收状态单独报告。

## 6. 回退策略

改动仅涉及 TimeDomain AxisItem 样式、交互期刻度模式切换和回归测试。
如 adaptive 交互刻度引入不可接受的前台性能或网格跳变，可独立回退 D2，保留 D1
先消除图框位移；但该状态仍会短暂丢数字，只能作为临时降级，不能视为完整验收。

## 7. 实施证据（2026-08-08）

- TDD RED：新增 4 个 case 在生产修复前为 `4 failed`；三种绘图模式的缩放中间帧
  均没有横轴数字，burst adaptive 重置次数为 0。
- TDD GREEN：D1+D2 实施后新增 case 为 `4 passed`。
- 独立 offscreen 组合门槛：`482 passed, 1 deselected in 26.02s`，覆盖完整
  `test_pg_timedomain_canvas.py`、hotpath、dense raster 和 backref invariants。
- 原生 macOS Cocoa 自动化几何/paint 门槛：`4 passed in 0.68s`，覆盖
  subplot-1、subplot-3、overlay-3 与 burst 去重。
- 主应用已能以 Cocoa 和独立临时配置启动；本轮没有人工持续操作前台缩放手势，
  因此最后一项仍保持未验收，不以自动化 Cocoa 测试替代人工前台体感确认。
- `git diff --check` 通过；lesson requirement 已提升为
  `timedomain-xaxis-interaction-keeps-layout-stable` 并清零。
