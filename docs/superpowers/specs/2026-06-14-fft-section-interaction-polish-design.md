# FFT Section 交互与视觉打磨 — Spec

日期：2026-06-14
状态：已分析（4 项根因均经探针/渲染实证，见 §1 证据列）
配套 plan：`docs/superpowers/plans/2026-06-14-fft-section-interaction-polish.md`

## 0. 范围

FFT section（`mf4_analyzer/ui/pg_canvas/line_canvas.py` 的 `PgLineCanvas` = 上方谱图 `_plot_amp` + 下方时域预览 `_plot_time`；数据流经 `main_window.py` / `analysis_section_page.py`）的四个用户反馈，全部限定在 FFT 这一节，互相独立：

1. 标注模式文字是宋体，没跟随应用字体。
2. 时域预览顶部有"两条线"（边框 + 网格叠加），需打磨。
3. 拖动下方时域曲线应是「框选一段范围 → 用该范围做 FFT」，而不是平移/缩放。
4. 拖动卡顿——怀疑拖动时 AA 没被取消。

## 1. 根因与已确认事实（不要推翻）

### R1 标注字体 = 宋体

- 应用**从未调用 `QApplication.setFont(...)`**。字体仅经两条途径设置：`ui_kit/style.qss` 的 `font-family`（**只对 QWidget 生效**）与 `ui_kit/fonts.py:setup_chinese_font()`（**只配 matplotlib**）。
- 标注是 `pg.TextItem`（`line_canvas.py` `add_remark_at`），属 **QGraphicsItem**，二者都不吃 → 只能用 `QApplication.font()` 的平台默认字体；Windows 上落到宋体/SimSun。stale banner（`line_canvas.py` `_show_stale_banner`）同理。
- **已确认（实证）**：在 macOS 探针下 remark label 字体 = `.AppleSystemUIFont`；模拟全局 `app.setFont(family)` 后，remark `TextItem.textItem.font().family()` 与 line canvas 坐标轴（`tickFont=None`，本就继承 app 字体）**双双跟随**新 family。
- **代码库不一致点**：时域 canvas（`pg_canvas/canvas.py:715`、`overlay_axes.py`）**已**用 `pg_canvas/fonts.py` 的 `_apply_pg_axis_font` / `_apply_pg_text_item_font` 显式修字体；而 **line canvas 与 heatmap canvas 完全没调这些 helper** → 它们的坐标轴**和**标注在 Windows 上都是宋体（用户只注意到标注）。全局 setFont 正好一次覆盖这些漏网画布。

### R2 时域预览顶部双线

- `line_canvas.py` 构造里 `p.showGrid(x=True, y=True, alpha=0.25)` 把网格开到了**全部 4 条轴**（探针实测 left/right/top/bottom 均 `grid=63`）。横向网格线由 left+right 两轴各画一次 → **重复过绘**，看起来更重。
- 顶部"两条线" = **顶边框线**（`_apply_neutral_axis_frame` 给 top 轴的 frame_pen）+ **最高 Y 刻度的网格线**；**空状态**下 pyqtgraph 把无数据 Y 范围**硬置为 `(0,1)`**（`setDefaultPadding` 对空数据无效，探针实测范围仍为 `(0.0000, 1.0000)`），刻度 1.0 正好贴顶边框。
- **已确认（10× 放大 A/B/C 渲染）**：仅关 top/right grid（B）改善有限；关 top/right grid + 空状态 Y 留白（C）后顶部为干净单线。
- 备注：**有数据**时 autorange 自带 ~0.088 padding，最高刻度本就离顶边框有距离，双线主要是**空状态**伪影；执行期需对照用户截图最终确认主导子因（不排除叠加了 codex 新加的两图间距问题）。

### R3 时域预览拖动语义

- 现状：`_plot_time` 用 `_ModifierWheelViewBox`，默认 **PanMode**，左键拖动 = 平移。平移改变可见 X 范围 → `time_preview_range_changed`（`line_canvas.py`）→ `main_window._on_fft_preview_range_changed` → `inspector.top.set_range_from_span(lo, hi)`。即"当前可见范围"已被当作 FFT 范围，但交互是**平移**（视图被拖走、看不到全貌），不直观。
- 用户要：左键拖动 = **画一段选区**（`pg.LinearRegionItem`），把选区 `[t0,t1]` 当 FFT 输入范围，**视图不平移**。

### R4 拖动卡顿 = AA 没真正取消

- `line_canvas.py` `_set_curve_aa` **只改父 `PlotDataItem.opts["antialias"]`**，没传到真正负责绘制的子 `PlotCurveItem`（pyqtgraph 0.14：antialias 只在 `PlotDataItem.updateItems()` 里经 `curve.setData(antialias=...)` 流到子 curve）。
- **已确认（实证）**：`disable_interactive_quality()` 后，被渲染的 `curve.curve.opts["antialias"]` 仍为 **True**。
- 为何时域 section 没事：时域热路径平移**每帧都 `setData`**，顺带把新 opts 刷进子 curve；FFT 时域预览的 envelope 曲线**一次算好、平移不重新 setData** → opts 永远到不了子 curve → 平移全程都在重栅格化 AA 曲线（谱图 nfft/2 点 + 叠加多通道）→ 卡顿。
- 次要嫌疑：平移每帧 `time_preview_range_changed` → `set_range_from_span` 刷 inspector 输入框，可能也有抖动（R3 改成"框选不平移"后此路自然消失；保留为观察项）。

## 2. 目标 / 非目标

**目标**
- G1（R1）：FFT/heatmap 画布的所有 pg 文本（标注、banner、坐标轴）跨平台跟随应用中文字体，Windows 上不再出现宋体。**只改 family、不改字号**，避免全局控件尺寸漂移。
- G2（R2）：时域预览（空状态与有数据）顶部不再出现边框+网格的"双线"，读作一条干净边框 + 正常内部网格。
- G3（R3）：FFT 时域预览左键拖动 = 框选时间区间并驱动 FFT 范围；视图不被平移。提供清除/复位选区入口。
- G4（R4）：FFT section 平移/缩放期间 AA 真正关闭（被渲染的子 curve `antialias=False`），空闲后恢复；拖动明显跟手。

**非目标**
- 不引入 OpenGL（破坏 `grab_pixmap` 导出，项目已有教训）。
- 不改 FFT 数值算法、不动 `signal/`。
- 不重写 codex 正在做的折叠三角 / 可拖分隔条（`_SplitDivider`）逻辑——仅在其落地后于同文件做点状修改。
- R3 不做多选区 / 区间持久化到 view state（本批仅单选区 + 即时驱动 FFT 范围）。

## 3. 需求清单（每项验收 = 新增回归测试 + 既有套件全绿 + 必要的视觉验证）

### R1 全局 setFont（仅改 family）
- 在 `pg_canvas/fonts.py` 新增 `apply_global_chart_font(app=None)`：用现有 `_pg_chart_font().family()` 解析 CJK family，`base=app.font(); base.setFamily(family); app.setFont(base)`（family 不同才设，保留字号）。
- 在 `app.py` `app = QApplication(sys.argv)` 之后调用一次。
- 验收：`apply_global_chart_font(qapp)` 后 `qapp.font().family() == _pg_chart_font().family()`；新建 `pg.TextItem("x").textItem.font().family()` 等于该 family。

### R2 网格/边框去双线
- 构造 `_plot_amp` / `_plot_time` 时，`showGrid` 之后对 **top、right 轴 `setGrid(False)`**（保留 left+bottom）。
- 空状态（`full_reset` 与 `_plot_time_preview_entries` 的空分支）：把两图 Y 设为带 padding 的范围（如 `setYRange(0.0, 1.0, padding=0.08)`），使边界刻度网格线不贴顶边框。
- 验收：构造后 `getAxis('top').grid is False` 且 `getAxis('right').grid is False`，`left/bottom` 仍开；`full_reset` 后空状态时域 Y 视图上界 `> 1.0`（边界刻度与边框分离）。视觉验证：渲染空画布顶部对照用户截图，单线。

### R3 时域预览框选范围做 FFT
- 在 `_plot_time` 内放一个 `pg.LinearRegionItem`（横向、半透明），默认隐藏/覆盖全宽。
- `_plot_time` 的 ViewBox 左键拖动从"平移"改为"建立/调整选区"：拖出 `[t0,t1]` → 设 region → 发 `time_preview_range_changed.emit(lo, hi)` 喂 FFT 范围（沿用现有 `main_window._on_fft_preview_range_changed` 链路，无需改 main_window）。
- 提供清除选区：右键菜单项或双击空白复位（复位 = region 覆盖全数据范围 / 清除约束）。
- X 平移改由其他修饰键或保留滚轮缩放（`_handle_wheel_dispatch` 现有 Ctrl/Shift 滚轮不变）。
- 验收：在 `_plot_time` 上模拟左键拖动 `[t0,t1]` 后，`time_preview_range_changed` 以 `(t0,t1)`（容差内）发射，且 `_plot_time.vb.viewRange()[0]`（X）**未平移**；清除入口可把选区复位。

### R4 AA 真正下沉到子 curve
- `_set_curve_aa(curve, on)`：在设父 `opts` 后，取 `child = getattr(curve, "curve", None)`，`child.opts["antialias"] = on; child.update()`（不重新 setData，便宜）。
- 验收：`disable_interactive_quality()` 后**每条** `_interactive_curves()` 的 `curve.curve.opts["antialias"]` 均为 `False`；`_enable_idle_quality()`（空闲）后恢复为各自的稳态 AA。

## 4. 与 codex 并行作业的协调约束（重要）

- 当前工作树里 **codex 正在改 `line_canvas.py` / `heatmap_canvas.py`**（折叠三角 + 可拖分隔条 `_SplitDivider`），**尚未提交**。R2/R3/R4 都落在 `line_canvas.py`，与之高度重叠。
- **R1** 落在 `app.py` + `pg_canvas/fonts.py`（codex 未碰）→ 可独立先行、随时提交。
- **R2/R3/R4** 必须**等 codex 的分隔条改动提交到 main 后**，在干净基线上做点状修改，避免同文件撞 hunk（遵循 `workflow-parallel-codex-same-worktree` 教训）。
- 本 spec/plan 内引用的行号为 2026-06-14 分析时快照，codex 落地后会漂移，执行时以符号/函数名定位为准。

## 5. 风险

- R1 全局 setFont 即便只改 family，仍可能轻微影响个别自定义绘制控件的字形度量——执行时跑全套 UI smoke + 目视主窗口。
- R2 空状态显式 Y 范围需确认不破坏"有数据时 autorange"路径（只在空分支设）。
- R3 改拖动语义会与现有 PanMode/RectMode 工具栏交互、`_ModifierWheelViewBox.mouseDragEvent` 的 RectMode 分支耦合，需保证：选区模式只作用于 `_plot_time`，谱图 `_plot_amp` 行为不变；且不破坏导出（region 是 chrome，不应进 `grab_pixmap` 的数据像素——确认 LinearRegionItem 是否被 grab 收录，必要时导出前隐藏）。
