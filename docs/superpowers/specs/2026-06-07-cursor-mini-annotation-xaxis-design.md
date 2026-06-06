# 时域视图 4 项交互/视觉调整（双游标 Mini · 并排保留 · X 轴标题 · 标注）

日期：2026-06-07
分支：docs/timedomain-view-tabs-plan
状态：设计已确认，待实现（用户已选定方案，尚未改代码）

## 背景

用户在时域视图（pyqtgraph 后端 `TimeDomainCanvasPG`）提出 4 项调整。经代码核对，
第 ① 项是叠加模式遗漏一行调用，其余三项是新功能/状态。本 spec 记录确认后的方案，
配套可视化设计稿见 `2026-06-06-cursor-mini-and-annotation-mockup.html`。

---

## ① 切换 X 坐标通道时，横坐标标题不更新（多通道/切过分叠后）

### 复现与症状（已用 headless 运行时证据确认）
- 单通道换 X 轴 → 标题正确变成通道名。
- 多通道、且在换 X 前切过「分/叠」模式 → 换 X 后标题**仍是 `Time (s)`**，无任何提示。
- 复现脚本（不入库）：单文件 CSV(time/speed/torque)，勾选 speed+torque，
  `_on_plot_mode_changed('overlay')` 后 `_apply_xaxis()` 选 X=speed →
  `_custom_xlabel == 'Time (s)'`，底轴标题 `'Time (s)'`。

### 已证伪的错误假设
- ❌「叠加模式创建 `_x_master_handle` 时漏调 `set_xlabel`」——**错**。headless 直测
  `plot_channels(..., xlabel='MY_X')` 在单/叠加/子图三模式底轴都正确显示 `MY_X`
  （叠加下 aux handle 与底轴共享同一 `plot_item`，`_bind_channel` 的
  `set_xlabel` 已设到可见底轴）。**画布层无 bug。**
- ❌ 长度校验闸门 / ❌ 下拉框 combo-match 失败——均经打点排除（同文件长度一致、
  无 toast、combo-match 成功 `_custom_ch=speed`）。

### 真正根因（运行时打点证明）
传给 `plot_channels` 的 `xlabel` 本身就是 `"Time (s)"`，因为 `_custom_xlabel` 被污染。
链条：
1. **切「分/叠」**（`main_window.py:749 _on_plot_mode_changed`）重绘走 view 状态往返。
   `capture_axis_opts` 对「时间轴+无自定义标签」视图把 `label` **合成成
   `"Time (s)"`**（`view_bridge.py:24-25`，本应为空串）。
2. restore 时 `_restore_view_axis_opts` 把该 `"Time (s)"` **写进自定义标签输入框
   `edit_xlabel`**（`main_window.py:693`）——默认值被伪装成用户自定义标签。
3. 之后换 X 到通道，`_apply_xaxis` 用 `_custom_xlabel = xaxis_label() or ch`
   （`main_window.py:1181`）；`xaxis_label()` 返回被污染的 `"Time (s)"`（非空），
   于是通道名被覆盖。
- 解释了：单通道好（无需切分叠→不污染）；多通道坏（必切叠加→污染）；无提示
  （apply 成功）；恰好显示 `"Time (s)"`（泄漏的默认值）。

### 方案（让自定义标签框只承载「用户真的输入过」的标签）
任一/组合，优先前两条（治本，去掉默认值泄漏）：
- `view_bridge.capture_axis_opts`：无自定义标签时 `x_axis.label` 存 `""`/`None`，
  不要合成 `"Time (s)"`。
- `main_window._restore_view_axis_opts`：把等于默认 `"Time (s)"` 的 label 视作「无
  自定义标签」，`edit_xlabel` 置空，不回填默认值。
- `main_window._apply_xaxis`(1181)：换通道时，若 `xaxis_label()` 等于默认 `"Time (s)"`
  则忽略，回退到通道名。
- 验收：多通道切叠加后换 X 到某通道，底轴标题立即变成该通道名；切回「自动(时间)」
  恢复 `Time (s)`；中途的分/叠切换不再污染自定义标签框。

### 涉及文件
- `mf4_analyzer/ui/view_bridge.py`（`capture_axis_opts` label 合成）
- `mf4_analyzer/ui/main_window.py`（`_restore_view_axis_opts:693`、`_apply_xaxis:1181`）
- 画布层 `pg_canvases.py` **无需改动**（已证正确）

---

## ② 并排 view 双游标模式下，切到另一图时图 1 的双游标框消失

### 现状与根因
- 读数框 `CursorPill` 是 **ChartStack 的全局单例**（`self._pill`，`chart_stack.py:1631`），
  `_reposition_pill()`（`chart_stack.py:2376`）按 `_active_cursor_card`（最后驱动读数的
  面板）重新锚定。分屏时只有一个 pill，焦点/操作切到图 2 后 pill 跟着移到图 2，图 1
  就没框了。
- 另一层：切 view 重绘走 `canvas.clear()`（`pg_canvases.py:2619`），把
  `_cursor_a_items/_cursor_b_items` 等可视线清空但**保留** `_ax/_bx`；之后只有鼠标
  移动/点击才会经 `_ensure_cursor_items()` 重建，没人在重绘后主动按 `_ax/_bx` 重建。

### 方案（用户选定：每面板独立 pill）
- 分屏(`enter_split`)时，为**每个画布面板各自维护一个 `CursorPill`**，不再共用单例。
  - 每个 pill 锚定自己所属 canvas 的右上角；各自记录 `_user_placed` 拖放位置。
  - `_on_dual_cursor_info` / `_on_cursor_info` 按来源 canvas 路由到对应面板的 pill，
    而不是统一写单例。
- 重绘后恢复游标线：在 `_render_view_to_canvas` 完成 replot 后，若该 canvas 的
  `_ax`/`_bx` 已设置，调用 `_ensure_cursor_items()` + `_set_cursor_items_pos()` 重建并
  定位 A/B 竖线（避免必须晃鼠标才出现）。
- 退出分屏时回收次要面板的 pill。
- 验收：分屏下图 1 放好 A/B 并出框后，去图 2 操作（含放置图 2 自己的 A/B），图 1 的
  双游标框与 A/B 线均保持显示。

### 涉及文件
- `mf4_analyzer/ui/chart_stack.py`（pill 由单例改为每面板一个；定位/路由/快照恢复）
- `mf4_analyzer/ui/pg_canvases.py`（replot 后按 `_ax/_bx` 重建游标线的钩子）
- 可能涉及 `mf4_analyzer/ui/main_window.py`（`_render_view_to_canvas` 调用恢复钩子）

---

## ③ 双游标面板 Mini 版（用户选定：Mini A 堆叠）

### 现状
- `CursorPill`（`chart_stack.py:63`）：`QVBoxLayout`，`_primary`（A/B/ΔT/频率 一行）+
  `_detail`（每通道 Min/Max/Avg/△ 的 RichText 表）。detail 由
  `canvas._format_dual_html()`（`canvases.py:291`）/ pyqtgraph 端
  `_emit_dual_cursor_html()`（`pg_canvases.py:4399`）生成。**当前无 mini/折叠状态。**

### 方案
- 给 `CursorPill` 增加 `mode` 状态：`"full"` | `"mini"`，默认 `"full"`。
- **右上角切换按钮**（QToolButton/QPushButton，绝对定位在 pill 右上角，objectName 入 qss）：
  - Full 态显示 `[−]`：点击 → 切到 Mini。
  - Mini 态显示 `[+]`：点击 → 切回 Full。
  - 与现有拖动手柄共存（按钮区域不触发拖动）。
- **Mini A 内容**（堆叠式）：
  - 保留 `_primary` 第一行：A / B / ΔT / 1/ΔT（频率）。
  - 通道区只显示**每通道一行**：`色点 + 通道名 + △差值`（丢弃 Min/Max/Avg）。
  - 需要 detail 的「mini 版 HTML」生成：可在 `_emit_dual_cursor_html` 同时算出
    `full_html` 与 `mini_html`（或让 CursorPill 持有结构化 rows，按 mode 自渲染——优先
    后者，避免双份字符串拼接漂移）。
- 切换 mode 后 `adjustSize()` + `_reposition_pill()`，保持右上角/用户拖放位置不跳。
- 状态可考虑随 ViewState/全局记忆持久化（次要，先做切换本身）。
- 验收：双游标出框后点 `[−]` 收成 Mini A（仅第一行 + 每通道 △），点 `[+]` 复原；
  内容随 A/B 移动实时刷新。

### 涉及文件
- `mf4_analyzer/ui/chart_stack.py`（`CursorPill` 增 mode/按钮/mini 渲染）
- `mf4_analyzer/ui/pg_canvases.py` 与 `canvases.py`（dual 读数改为可产出 mini 内容/结构化 rows）
- `mf4_analyzer/ui_kit/style.qss`（`#cursorPill` 角标按钮样式）

---

## ④ 顶部 toolbar 标注按钮（用户选定图标：③ 标签+引线）

### 现状与可复用资产
- **matplotlib 后端已有完整标注**（`canvases.py:1645-2012`）：`set_remark_enabled` /
  `_add_remark`（`ax.annotate` 气泡 + 引线 + 红点）/ `_remove_remark_at`（右键就近删）/
  `clear_remarks`。`chart_stack.py` 已有 `set_annotation_enabled` / `clear_annotations`
  与 `_annotation_btn` 模式。
- **pyqtgraph 后端 `TimeDomainCanvasPG` 没有**对应实现，需新建（这是当前默认后端）。
- 图标体系 `icons.py`：QPainter 手绘矢量、`@classmethod` 返回 `QIcon`，
  `_line_icon(draw, color)` 模板；调色板 `BLUE=#1769E0 / GRAY=#475569`。
- toolbar 按钮套路（`toolbar.py:28-54`）：`QPushButton` + `setIcon(Icons.xxx())` +
  `setIconSize(16×16)` + `clicked` 信号。
- 右键菜单重设计 `redesign_pg_context_menu()`（`pg_canvases.py:729-791`）可挂「删除标注 /
  删除全部标注」。

### 方案
- **图标**：在 `icons.py` 新增 `Icons.annotate()`（③ 标签+引线）——左下数据点圆 +
  斜引线 + 右上小标签矩形（含两条文本线）。线宽 `1.45`、默认 `GRAY`、激活/选中态走
  现有按钮 `:checked` 蓝色逻辑。draw() 几何对照设计稿 SVG 的 viewBox(0..20)。
- **toolbar 按钮**：在时域工具区加一个**可勾选**的「标注」按钮（QPushButton checkable），
  勾选=进入标注拾取模式；连到 `chart_stack.set_annotation_enabled`。
- **pyqtgraph 标注实现**（移植 matplotlib 语义 + 新增可拖动）：
  - 数据结构：每条标注 = `{viewbox/handle, x, y, text_item(pg.TextItem 带 fill/border),
    dot(ScatterPlotItem), leader_line}`，存 `self._remarks`。
  - 左键点击（标注模式开启时）：拾取最近曲线数据点 → 在该点加红点 + 引线 + 文本气泡。
  - **可拖动标注内容位置**：TextItem 做成可拖（自定义 draggable TextItem 或包一层
    QGraphicsItem，`mouseDragEvent` 更新 anchor/offset，引线起点跟数据点、终点跟文本框）。
  - **右键单独删除**：就近命中某标注则删它（接入 `redesign_pg_context_menu` 或场景点击）。
  - **删除全部**：右键菜单「删除全部标注」+（可选）toolbar/卡片按钮 → `clear_remarks()`。
- 验收：开标注 → 曲线上点选生成带引线标签 → 可拖动标签位置 → 右键删单个 / 菜单删全部。

### 涉及文件
- `mf4_analyzer/ui_kit/icons.py`（新增 `annotate()` 图标）
- `mf4_analyzer/ui/toolbar.py`（标注按钮）
- `mf4_analyzer/ui/pg_canvases.py`（pyqtgraph 标注：增删/拖动/右键、菜单项）
- `mf4_analyzer/ui/chart_stack.py`（按钮接线，复用/扩展 `set_annotation_enabled`）

---

## 实现注意事项

- 本分支已知 UI 文件存在同名方法重复定义（最后一个生效）——定点改前先核对/去重
  （见记忆 `project-ui-files-structural-corruption`）。
- TimeDomain 卡顿是 CPU 光栅 bound——标注/双 pill 的重绘别放进 per-drag-tick 热路径
  （见记忆 `project-timedomain-perf-raster-bound`）。
- UI/视觉项必须**真机截图验证**（置灰、Mini 切换、标注拖动、X 标题更新、分屏双框保留），
  不能只靠「属性设上了 + 单测过」就判定修好（见记忆 `feedback-verify-ui-visually`）。

## 执行

4 项均为 UI 工作，由 `pyqt-ui-engineer` 专家实现，不涉及数值算法。
建议落地顺序：① X 轴标题（最小）→ ③ Mini 切换 → ② 分屏双 pill → ④ 标注（最大）。
