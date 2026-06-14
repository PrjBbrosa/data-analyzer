# FFT 时域预览：右轴对齐网格 + 刻度密度 + 工具栏补齐 — 设计

- 日期：2026-06-14
- 作者：Hang（与 Claude 根因分析后落地）
- 范围：`mf4_analyzer/ui/pg_canvas/line_canvas.py`（`PgLineCanvas` 下方时域预览 `_plot_time`）、`tests/ui/test_pg_line_canvas.py`（回归）；不碰 `signal/`、不碰数值算法
- 状态：设计/计划待实施（已按 2026-06-14 当前仓库代码校准）
- 配套 plan：`docs/superpowers/plans/2026-06-14-fft-time-preview-axis-align-and-toolbar.md`

> 参照实现：时域 overlay 的"共享网格 + 每通道 nice 框定刻度"体系
> （`overlay_axes.py` `_build_overlay_y_grid`/`_repin_overlay_channel_ticks`、
> `tick_density.py` overlay 分支），以及纯函数 `ticks_math.py`
> `_frame_to_nice` / `_fmt_tick`。本 spec 把同一对齐不变量搬到 FFT 时域预览，
> 但因预览主 ViewBox **自身承载第一条曲线**，可直接复用左轴网格、无需额外
> InfiniteLine（比 overlay 更轻）。

---

## 0. 范围与范围决策

图中下方那张是 **FFT 面板的时域预览** `_plot_time`（`PgLineCanvas`，
`chart_stack.py:1902` 以 `_ChartCard(PgLineCanvas(self), annotations=True,
chart_mode='fft')` 建卡）。当预览叠加多于一条曲线时，第 2 条起每条挂到一个
独立 aux ViewBox + 一条彩色右轴（`_add_time_overlay_axis`，
`line_canvas.py:821-840`）。截图里两条右轴（1/0/−1、50/0/−50）即它们。

用户三条反馈（均已代码级确认，见 §1）：

1. 右轴刻度不跟左轴/网格对齐。
2. 刻度密度对右轴无效。
3. 工具栏很多操作对这张图无用（点名"标注、返回"）。

**本批范围（A/B/C 三项）：**

- **A**（问题 1+2）：时域预览所有 Y 轴（左轴 + 各右轴）统一框成 `n` 等分 nice
  刻度并钉死，落在同一组水平网格线上；Y 刻度密度驱动 `n`。
- **B**（问题 3 · 标注）：标注扩展到时域预览图（当前只在上方谱图生效）。
- **C**（问题 3 · 返回/前进）：视图历史在整个 FFT 画布生效（当前完全失效）。

**明确不在本批（非目标，理由见 §2）：** 图表选项对话框、逐通道 Y 拖动/吸附
交互、预览图 Shift+滚轮纵向缩放。

> 范围可裁剪：A 是用户最直接的视觉诉求、强烈建议保留；B 次之；**C（视图历史）
> 改动面最大且与新网格框定有耦合，如想先小步快跑可单独砍到下一批**。落地前请
> 确认是否保留 C。

---

## 1. 根因与已确认事实（代码级，勿推翻）

### A1 — 右轴刻度不跟左轴/网格对齐（问题 1）

- 每条 aux 右轴对应的 `aux_vb` 仅 `enableAutoRange(axis=pg.ViewBox.YAxis,
  enable=True)`（`line_canvas.py:837`），各自按自身数据范围独立取整出刻度，彼此
  无关。
- 网格只画在左+下轴：构造里 `p.showGrid(x=True, y=True, alpha=0.25)` 后
  `getAxis('top').setGrid(False)` / `getAxis('right').setGrid(False)`
  （`line_canvas.py:110-119`）。横向网格线落在**左轴**刻度位置；右轴刻度与左轴
  无关 → 位置对不上、条数也不同（截图左轴 5 条、两右轴各 3 条）。
- **对比 time domain**：overlay 用共享刻度网格 `_build_overlay_y_grid`
  （`overlay_axes.py:569-606`）+ 每条轴 `_frame_to_nice` 框成 `n` 等分并钉死刻度
  `_repin_overlay_channel_ticks`（`overlay_axes.py:608-633`）→ 所有轴刻度条数一致
  且都落在 `k/n` 屏幕位置上、与网格天然重合。FFT 预览**完全没有这套**。

### A2 — 刻度密度对右轴无效（问题 2）

- `PgLineCanvas.set_tick_density`（`line_canvas.py:772-784`）只对两图的
  `bottom` 和 `left` 轴 `setTickDensity`，**根本没碰** `self._time_overlay_axes`
  （右轴）。调密度时左轴会变、右轴纹丝不动 → 表现为"只对右侧无效"。
- 主窗口确有把密度送到 FFT 画布（`main_window.py:3245`
  `self.canvas_fft.set_tick_density(xt, yt)`），所以不是没接线，是画布内部漏了
  右轴。
- **对比 time domain**：`TickDensityController.set_tick_density`
  （`tick_density.py:45-65`）overlay 分支把 Y 密度转成 `divisions`、重建网格并
  重钉所有轴刻度，右轴随之联动。

### B — 标注只在上方谱图生效（问题 3 · 标注）

- `add_remark_at(which, x, y)` 仅当 `which == 'amp'` 才动作、且只在
  `_plot_amp` 上落点（`line_canvas.py:1251-1276`）；`remove_remark_near` 同理
  （:1278）。
- `_on_click` 只判断 `_plot_amp.vb.sceneBoundingRect().contains(...)`
  （`line_canvas.py:1289-1303`）→ 点在下方时域图上**根本不进标注分支**。
- `set_remark_enabled` 还专门 `self._plot_time.vb.setMenuEnabled(True)`
  （`line_canvas.py:1243`），即标注开启时时域图仍是普通右键菜单。
- 结论：时域预览图左键加不了标注、右键删不了 → "标注对下图无效"实锤。

### C — 视图历史（返回/前进）在 FFT 画布完全失效（问题 3 · 返回）

- 工具栏 i18n 保留了 `back`（上一视图）/`forward`（下一视图）
  （`_toolbar_i18n.py:14-15`，`retain=True`），按钮在。
- 但历史快照/还原 `_snapshot_view`/`_restore_view`
  （`chart_stack.py:743-788`）**遍历 `canvas._channel_lines`**——`PgLineCanvas`
  没有这个属性 → 快照恒为 `{}`、还原恒为空。
- 且 `PgLineCanvas` **没有 `register_replot_callback`**，所以卡片那段
  `if callable(register): register(self.toolbar.rebind_history_capture)`
  （`chart_stack.py:1134-1141`）整段跳过 → `rebind_history_capture` 从未被调用、
  `sigRangeChangedManually` 历史捕获从未绑定、基线也没种下。
- 结论：返回/前进对整个 FFT 画布（含上下两图）零作用。
- **附带确认（不在本批修，仅记录）**：`open_chart_options`
  （`chart_stack.py:1531-1536`）找 `canvas.open_chart_options_dialog`，
  `PgLineCanvas` 无此方法（仅 `canvas.py`/`canvases.py` 有）→ "图表选项"按钮点了
  无反应。

**当前工具栏按钮逐项实况（FFT 卡片）：**

| 按钮 | 现状 | 处置 |
|---|---|---|
| 重置视图(home) | ✅ `reset_view_to_data_extents` 重置两图 | 不动 |
| 上一视图/下一视图 | ❌ 无历史 | **本批 C 修** |
| 拖动平移/框选缩放 | ✅ 经 `_view_boxes()` 覆盖两图 | 不动 |
| 保存图片/复制为图片 | ✅ 抓整图 | 不动 |
| 刻度密度 | ⚠️ 右轴无效 | **本批 A 修** |
| 标注/清除标注 | ❌ 标注仅谱图 | **本批 B 修** |
| 图表选项 | ❌ 无对话框 | 非目标（见 §2） |

---

## 2. 目标 / 非目标

**目标**

- **GA**（A1+A2）：时域预览左轴与每条右轴都按 `n` 等分 nice 刻度框定并钉死，
  刻度落在同一组水平网格线上；Y 刻度密度直接驱动 `n`（3–20）。单曲线时左轴同样
  规整。视觉与 time domain overlay 一致。
- **GB**（B）：标注模式下，下方时域预览图也能左键加点、右键删最近点；清除标注
  连带清掉时域图上的标注。谱图既有行为不变。
- **GC**（C）：返回/前进在 FFT 画布生效——能在 pan/zoom/wheel 造成的视图变化间
  前后跳转；首次建图后种下基线，返回有落点。

**非目标**

- 不引入 OpenGL（破坏 `grab_pixmap` 导出，项目既有教训）。
- 不改 FFT 数值算法、不动 `signal/`、不改 `ticks_math.py` 数值（只复用
  `_frame_to_nice`/`_fmt_tick`）。
- **不做**预览图的逐通道 Y 拖动/吸附动画、Shift+滚轮纵向缩放（time domain 的
  `_handle_overlay_*`/`_animate_overlay_snap` 那一大套）。本批预览 Y 是"按数据
  自动框定到 nice 网格、随密度变"，纵向交互留到下一批。
- **不做**"图表选项"对话框：`PgLineCanvas` 无 `open_chart_options_dialog`，新建
  一套 FFT 专用选项对话框工作量与本批不成比例，单列。
- 不动 codex 的折叠/分隔条（`_SplitDivider`）逻辑，仅在其落地基线上做点状修改。

---

## 3. 设计

### 3.1 A — Y 轴 nice 网格框定（对齐 + 密度联动）

**对齐不变量（同 time domain）：** 每条轴都框成恰好 `n` 等分、填满（共享几何的）
ViewBox 高度，刻度钉在 `n+1` 个等分值上 → 每条刻度落在屏幕 `k/n` → 天然重合。
预览里左轴属主 ViewBox（承载第 0 条曲线），其网格即 `k/n` graticule，**右轴只要
也框成 `n` 等分就和它对齐**，无需像 overlay 那样额外画 InfiniteLine。

**新增状态：** `self._time_divisions = 8`（构造里；默认对齐 FFT 卡片 Y8）。

**新增方法 `_reframe_time_y_to_grid()`：**

- 遍历"主轴（曲线 0 / 左轴 / `_plot_time.vb`）+ 每条 aux（右轴 /
  `_time_overlay_vbs[i]` / `_time_overlay_axes[i]`）"，对每条：
  1. 取该曲线当前数据 Y 的有限 min/max（`curve.getData()` → 有限掩码；空则跳过）。
  2. `bottom, top, ticks = _frame_to_nice(lo, hi, self._time_divisions)`。
  3. 该 ViewBox `enableAutoRange(axis='y', enable=False)` 后
     `setYRange(bottom, top, padding=0)`。
  4. 该 AxisItem `setStyle(maxTickLevel=0)` +
     `setTicks([[(v, _fmt_tick(v)) for v in ticks], []])`。
- 主 ViewBox 同时把 Y 交互关掉：`_plot_time.vb.setMouseEnabled(x=True,
  y=False)`（预览 Y 固定在 graticule，左键拖动只平移 X = 选 FFT 窗口，和当前
  "可见 X 范围即 FFT 范围"链路一致）。

**调用点：**

- `_plot_time_preview_entries` 末尾：把原先的
  `self._plot_time.enableAutoRange(axis='y')`（:935）替换为
  `self._reframe_time_y_to_grid()`（建/换曲线后即对齐）。
- `set_tick_density`：改为下面 3.2 的形态（Y → divisions → reframe）。
- `_fit_y_to_visible_x`（当 `plot is self._plot_time`）：保留它按可见 X 拟合数据
  min/max 的逻辑，但末尾追加 `self._reframe_time_y_to_grid()`，把拟合结果再规整到
  网格（镜像 time domain 对 `fit_y_to_visible_x` 的修法，
  `2026-06-07-overlay-grid-tick-realign-design.md` §4.1）。
- `reset_view_to_data_extents` / `_reset_time_preview_to_extents`：设完 X 后调
  `_reframe_time_y_to_grid()`（替换其中的 `enableAutoRange(axis='y')`）。
- `_sync_time_overlay_vbs` 之后无需重框（几何变了刻度比例不变，仍 `k/n`）。

> 注：`_frame_to_nice` 是纯函数、已被 time domain 测试覆盖，零新数值算法。

### 3.2 A — `set_tick_density` 改造

```python
def set_tick_density(self, x, y) -> None:
    try:
        x_n = max(3, int(x)); y_n = max(3, int(y))
    except (TypeError, ValueError):
        return
    x_d, y_d = _tick_counts_to_density(x_n, y_n)
    # 谱图：保持原样（无右轴，无需 graticule）
    for axis, d in ((self._plot_amp.getAxis('bottom'), x_d),
                    (self._plot_amp.getAxis('left'),   y_d)):
        axis.setStyle(maxTickLevel=0); axis.setTickDensity(d)
    # 时域预览：X 仍用密度；Y 改走 graticule 等分
    tb = self._plot_time.getAxis('bottom')
    tb.setStyle(maxTickLevel=0); tb.setTickDensity(x_d)
    self._time_divisions = max(3, min(20, y_n))
    self._reframe_time_y_to_grid()
    self.layout_geometry_changed.emit()
```

### 3.3 B — 标注扩展到时域预览

- `set_remark_enabled(enabled)`：标注开启时下方图也屏蔽默认右键菜单，与谱图一致：
  `self._plot_time.vb.setMenuEnabled(not enabled)`（替换现在恒 `True`）。
- `_on_click`：在现有谱图分支后，补一条"点在 `_plot_time.vb` 内"的分支——
  左键且 `_remark_enabled` → `add_remark_at('time', vx, vy)`；右键且 `_remark_enabled`
  → `remove_remark_near('time', vx)`（坐标用 `_plot_time.vb.mapSceneToView`）。
- `add_remark_at('time', x, y)`：在时域曲线里**按屏幕像素距离**选最近曲线的最近
  采样点（每条曲线点经其所属 vb `mapViewToScene` 投到场景，再比距离——overlay 各
  曲线 Y 尺度不同，必须在屏幕空间比），把 `pg.TextItem` + 红点加到该曲线所属
  plot/vb；`self._remarks.append({'label','dot','plot'/'vb'})`。单曲线时退化为主轴
  最近点。
- `remove_remark_near('time', x)`：在时域 remark 里按 X 选最近、移除。
- `clear_remarks` 已按 `r['plot']` 通删，天然兼容（aux 上的点改存 vb，需在
  `clear_remarks` 里兼容 `r.get('vb')`）。
- `grab_pixmap` 抓整 `_glw`，标注会被收录（期望行为，导出含标注）。

### 3.4 C — 视图历史在 FFT 画布生效

不改工具栏（避免波及 time domain），在 `PgLineCanvas` 侧补齐工具栏所需契约：

- **`register_replot_callback(cb)`**：存进 `self._replot_callbacks`；新增
  `_run_replot_callbacks()`，在 `plot_spectra` / `plot_time_preview` /
  `full_reset` 末尾调用。这样卡片的
  `register(self.toolbar.apply_current_mouse_mode)` 与
  `register(self.toolbar.rebind_history_capture)`（`chart_stack.py:1134-1141`）
  会真正注册并在每次重建后执行。
- **`_channel_lines` 形态契约**：提供
  `self._channel_lines = {'__amp__': (amp_handle, None),
  '__time__': (time_handle, None)}`，其中 handle 是轻量壳，暴露
  `get_xlim/set_xlim/get_ylim/set_ylim` 直接读写对应 vb 的 `viewRange`/`setRange`。
  `_snapshot_view`/`_restore_view` 即可原样工作。
  - `__amp__` handle：X+Y 全量快照/还原。
  - `__time__` handle：**只快照/还原 X**（`get_ylim` 返回当前但 `set_ylim`
    设完后调 `_reframe_time_y_to_grid()` 重规整，避免还原把 Y 拖离网格）。
    简化版可让 `__time__` 的 `set_ylim` 为 no-op，仅恢复 X 窗口（推荐，最稳）。
- 既有 `_view_boxes()`（`chart_stack.py:701-720`）已含两主图 vb，`rebind_history_capture`
  绑 `sigRangeChangedManually` 即可捕获 pan/zoom；wheel 路径
  （`_handle_wheel_dispatch`）是程序化 setRange、不发 `sigRangeChangedManually`，
  与 time domain 一致（wheel 不进历史），可接受。

---

## 4. 需求清单与验收（每项 = 新增回归测试 + 既有套件全绿 + 必要视觉验证）

### A1/A2 验收
- 叠加 ≥2 条曲线 + `plot_spectra` 后：左轴与每条右轴的 major 刻度数都 = `n+1`；
  各轴刻度 `(value-bottom)/(top-bottom)` 序列 ≈ `[k/n]`（与左轴同比例 → 对齐）。
- `set_tick_density(x, y=6)` 后 `_time_divisions == 6` 且各右轴刻度变为 7 条；
  `y=12` 变 13 条（右轴随密度变 = 问题 2 修复）。
- `_fit_y_to_visible_x(_plot_time)` 后各轴刻度仍落在 `k/n`。

### B 验收
- `set_remark_enabled(True)` 后 `_plot_time.vb.menuEnabled()` 为 False。
- 模拟左键点击落在 `_plot_time.vb` 内（标注开启）→ `self._remarks` 多一条且其
  plot/vb 属时域图；右键最近删除后减一条。
- `clear_remarks()` 清掉时域图标注（`_remarks` 归零）。
- 谱图标注路径行为不回归（既有用例全绿）。

### C 验收
- `canvas.register_replot_callback` 可调用且 `plot_spectra` 后回调被触发。
- 建一个挂了 `PgNavigationToolbar` 的卡片/画布：`plot_spectra` 后
  `toolbar._view_stack` 有基线；模拟一次 `sigRangeChangedManually` +
  `_commit_pending_view` 后栈增长；`back()` 还原前一视图（`_plot_time.vb` X 范围
  回到前值），`forward()` 再前进。
- time domain 卡片的历史用例不回归。

---

## 5. 协调约束（重要）

- 早前 `2026-06-14-fft-section-interaction-polish` spec 记录 codex 在改
  `line_canvas.py`（折叠三角 + `_SplitDivider`）。**本 spec 基于的当前代码已含
  `_SplitDivider` / AA 子 curve 下沉 / top-right 网格关闭**（即那批多已落地）。
  实施前仍须 `git log --oneline -5` + `git status` 确认 `line_canvas.py` clean、
  codex 无在途改动，避免同文件撞 hunk（遵循
  `workflow-parallel-codex-same-worktree` 教训）。
- 本文行号为 2026-06-14 快照，会漂移；执行时**以函数/符号名定位**。

## 6. 风险

- **A 行为面**：预览主图改 `setMouseEnabled(y=False)` 后，左键拖动不再纵向平移
  （只平移 X）。这是与 time domain 对齐的有意改动；如不希望锁 Y，可改为"Y 仍可
  拖、但 settle 后重框"（更多代码、刻度拖动中会瞬时漂移）——默认取锁 Y 方案，落地
  时目视确认。
- **A 数值**：`_frame_to_nice` 对单点/零跨度曲线有兜底（`ticks_math.py:81-87`），
  空曲线在 `_reframe_time_y_to_grid` 里跳过；需测一条恒定信号（min==max）不抛错。
- **B overlay 最近点**：跨不同 Y 尺度必须在屏幕空间比距离，别在数据空间比（否则
  右轴大尺度曲线永远"最近"）。
- **C 与 A 的耦合**：还原 `__time__` 的 Y 会和 graticule 打架——故 `__time__`
  只还原 X（见 §3.4）。这也意味着"返回"只回退 X 窗口与谱图 Y，不回退预览 Y（预览
  Y 本就自动框定，可接受）。
- **C 工具栏面**：只在 `PgLineCanvas` 侧加属性/方法，不改 `PgNavigationToolbar`
  与 time domain 画布 → 对既有历史逻辑零侵入。

## 7. 实施约束

属 UI 子系统改动 → 按 `CLAUDE.md` 走 squad runbook，主实施
**pyqt-ui-engineer**；A 复用纯函数 `_frame_to_nice`/`_fmt_tick`，无需
signal-processing-expert（除非要改 `ticks_math.py` 数值，本批不改）。TDD 先红后绿，
A/B 改完按"Verify UI visually"经验对照用户截图做一次截图复核（右轴刻度条数=左轴、
落在网格线上；下图可加标注）。
