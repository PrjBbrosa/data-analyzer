# 统一标注 + 热力图 XYZ 显示 设计文档

- **日期**：2026-06-21
- **状态**：草案，待用户复核
- **方案**：B（抽公共件 + 每 canvas 薄适配器）
- **承接**：[[project-fft-order-compute-display-rootfix]]（「参数边界手工维护散落」反模式）、Surface UI 规则 [[project-surface-ui-rules]]

---

## 1. 背景与问题

四个分析 section 的「标注」功能各写各的，视觉与鼠标交互完全不一致：

| Section | Canvas 类（文件） | 标注实现 | 现状 |
|---|---|---|---|
| 时域 | `TimeDomainCanvasPG`（`pg_canvas/canvas.py`） | `AnnotationManager`（`pg_canvas/annotations.py`） | 红点+虚线引线+白色圆角可拖框+笔形光标+48px 屏幕空间吸附+「点击不拖才落点 / 拖动平移 / 右键删最近」 |
| FFT | `PgLineCanvas`（`pg_canvas/line_canvas.py:1664` `add_remark_at`） | 裸 `TextItem("(x,y)")` + 红点 | 默认箭头光标，`sigMouseClicked` 直接落点，不可拖、无引线、无框 |
| FFT vs Time / 阶次 | `PgHeatmapCanvas`（`pg_canvas/heatmap_canvas.py:2256` `add_remark_at`） | 裸 `TextItem("(x,y,z)")` + 红点 | 同上 |

此外，「3D 视图」其实是 FFT vs Time / 阶次的**热力图**（X=时间、Y=频率、Z=幅值用 turbo 色表示，非真 3D）。它缺一个**持续的 XYZ 坐标读数**：当前 hover 只把 `t·f·value` 发到状态栏（`heatmap_canvas.py:2196` `_on_scene_hover`，且仅 `with_slice=True`），既不持久也不显眼；时域那种可拖动的悬浮读数窗 `CursorPill` 在热力图上没接。

### 用户诉求（已确认）
1. 把 FFT / FFT vs Time / 阶次 的标注**统一成时域那种**，含「鼠标特征」。
2. 给热力图加 XYZ 显示，**两者都做**：① 点击留痕的统一标注框（三行）② 实时悬停浮窗。
3. 坐标标签统一用 **`X=/Y=/Z=` 风格 + 单位**，应用到所有 section（含时域）。

---

## 2. 目标 / 非目标

**目标**
- 标注的**视觉**与**鼠标交互**在四个 section 完全一致，且只有一个真源（视觉一处、交互一处、label 一处）。
- 热力图获得统一三行标注框（点击）+ 实时 XYZ 悬浮窗（hover）。
- 所有 section 标注 label 统一为 `X=/Y=/Z=` + 单位。

**非目标**
- 不做真 3D 渲染（热力图仍是 2D 伪 3D）。
- 不改 FFT/阶次的数值算法（`_value_at`、索引反查等已存在，沿用）。
- 不改时域已有的吸附/落点/平移语义（只把它抽出来复用，不改行为）。
- 不重设计 CursorPill 外观（复用，必要时仅扩一个三行渲染入口）。

---

## 3. 有利接缝（设计据此成立）

1. `AnnotationManager` 已通过 `_CanvasBackref` 代理（`pg_canvas/_backref.py`）与 owner 松耦合，owner 接口是声明式的。
2. `PgLineCanvas` 与 `PgHeatmapCanvas` **均已暴露 `axes_list` + `_AxisShim`**（`line_canvas.py:196`、`heatmap_canvas.py:735`），与时域同构。
3. XYZ 浮窗信号链已存在：`cursor_info → ChartStack._on_cursor_info(stack.py:1011) → pill.set_primary/set_detail_html`。缺的只是：(a) 分析卡 `cursor_info` 未连 pill（`stack.py:160 _connect_analysis_card_signals`）；(b) pill 有 `current_mode()=='time'` 门槛（`stack.py:1020`）。

---

## 4. 设计

### 4.1 统一标注架构（新增三个公共件 + 一个 label helper）

在 `pg_canvas/` 下新增（具体文件名由执行专家定，建议 `remark/` 子包或 `remark_artist.py` / `remark_interaction.py`）：

**(a) `RemarkArtist` —— 视觉单一真源**
- 职责：给定 `target_vb`、数据点 `(x, y)`、`label_html`、`color`，创建并持有：红点(`ScatterPlotItem`)、虚线引线(`PlotDataItem`,`Qt.DashLine`)、白色圆角可拖框(`TextItem`,`ItemIsMovable`)；连 `text.sigPositionChanged → 更新引线`；提供 `remove()`。
- **所有样式常量收于此处一份**：红点色 `#dc2626`/8px、框 fill `(255,255,255,210)`、边框宽 0.8、引线宽 1.0 DashLine、圆角。消除视觉漂移。

**(b) `RemarkInteraction` —— 鼠标特征单一真源**
- 职责：持有笔形光标（把 `annotations.py:_annotation_pen_cursor` 迁来共用）；实现「按下/移动/松开」拖拽阈值状态机：左键点击不拖→落点、左键拖动→交还平移、右键→删最近。
- 由各 canvas 把 viewport 事件转发进来（时域已是 `eventFilter`；线图/热力图改为转发，替代现在的 `sigMouseClicked` 直接落点）。

**(c) `RemarkAdapter`（协议/接口）—— 每 canvas 一个薄实现**
- 唯一核心方法：`nearest_remark_point(viewport_pos) -> RemarkPoint | None`，返回 `RemarkPoint(vb, x, y, z?, color, unit_x, unit_y, unit_z?)`。
- 三个实现：
  - `TimeDomainRemarkAdapter`：封装现有 `_nearest_data_point`（遍历 `channel_data` 曲线），含 overlay/aux-vb 分支。**行为不变**。
  - `LineRemarkAdapter`：遍历 `_amp_curves`/`_time_curves` 求屏幕空间最近点；颜色取曲线 pen。
  - `HeatmapRemarkAdapter`：用 `_time_index_for`/`_freq_index_for`/`_value_at` 做栅格吸附；带 `z`；颜色固定红 `#dc2626`（无曲线色）。

**(d) `format_remark_label(point) -> html` —— label 单一真源**
- 统一输出 `X=…[unit]` / `Y=…[unit]`（Y 用 `color` 粗体），热力图多一行 `Z=…[unit]`。
- 有单位才补单位；无单位省略（与已批准预览一致：时域 Y 无单位则不补）。精度沿用 `.4g`。

**装配**：`AnnotationManager` 退化为「时域那一组 `RemarkArtist + RemarkInteraction + TimeDomainRemarkAdapter` 的装配」，对外 `set_remark_enabled`/`clear_remarks` 不变。`PgLineCanvas`/`PgHeatmapCanvas` 用同一组件 + 各自 adapter，删除各自的裸 `add_remark_at`/`remove_remark_near`/`clear_remarks` 实现。

### 4.2 各 section 单位来源

| Section | X 单位 | Y 单位 | Z 单位 |
|---|---|---|---|
| 时域 | s | 通道信号单位（`channel_data` 第 4 项，可能为空） | — |
| FFT | Hz | 幅值单位（entry，可空） | — |
| FFT vs Time / 阶次 | 时间 s（或阶次轴单位） | 频率 Hz | 幅值 dB / 线性单位（随 `amplitude_mode`） |

> 单位**不硬编码**：从 canvas 现有的轴/结果元数据读取（与当前状态栏 hover 同源——`_on_scene_hover` 已算出 `unit`）。阶次 section 的 X/Y 按其自身轴定义，不假定为时间/频率。

### 4.3 鼠标特征（统一语义，四 section 一致）
- 进标注模式 → 笔形光标；退出 → 箭头。
- 左键点击未超过拖拽阈值 → 在吸附点落标注；超过阈值（拖动）→ 不落点、交还 ViewBox 平移。
- 右键 → 删最近标注（标注模式下禁用 VB 右键菜单，沿用现状）。

### 4.4 热力图实时 XYZ 悬浮窗
- **复用 `CursorPill`**，不新造控件（规避 `WA_TranslucentBackground` 让本体 QSS 失效的坑，见 [[project-surface-ui-rules]] / [[feedback-no-gray-bg-embedded-widgets]]）。
- 接线改动：
  1. `ChartStack._connect_analysis_card_signals`（`stack.py:160`）增连分析卡 `cursor_info → _on_cursor_info`。
  2. pill 显示门槛从 `current_mode()=='time'` 放宽到也含 `fft_time`/`order`（即「有 hover 能力的 canvas」）。
- 内容：热力图 hover 产出三行 `X=/Y=/Z=`（经 `set_detail_html` 排成与标注框一致的三行；如需可加一个 `set_rows(rows)` 薄入口），**与点击标注框风格统一**。
- hover 触发：从「仅 `with_slice`」放宽为「只要载入了结果就发」。
- **状态栏那行保留**（pill 与状态栏并存）。

---

## 5. 数据结构

- `RemarkPoint`：`{vb, x, y, z(可空), color, unit_x, unit_y, unit_z(可空)}`（轻量 dataclass）。
- 标注实体（Artist 持有）：`{vb, dot, text, leader, data_x, data_y, data_z?}` —— 时域现状的超集（多一个可空 `data_z`）。

---

## 6. 测试策略

1. **先补特征化测试锁住时域现行标注行为**（创建 dot/leader/text、label 文本、可拖、删除、笔形光标），再抽件迁移 —— 防回归。
2. 抽件后新增/迁移断言：
   - FFT / 热力图标注现在产出「红点 + 引线 + 圆角框」而非裸文本。
   - label 为 `X=/Y=/Z=` + 单位（含热力图三行）。
   - 标注模式下光标为笔形（三 section 一致）。
   - 点击不拖落点 / 拖动不落点 / 右键删最近（三 section 一致）。
   - 热力图 hover 驱动 pill 显示三行 XYZ；门槛放宽后 `fft_time`/`order` 模式 pill 可见。
3. **验真机渲染**（CLAUDE.md 红线）：四 section 标注 + 热力图 pill 截图/objc 核验，不靠「属性设上了 + 单测过」。

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 抽件弄坏时域 overlay/aux-vb 吸附（最易出错） | 先特征化测试覆盖 overlay/subplot 两路；`TimeDomainRemarkAdapter` 原样封装 `_nearest_data_point` 不改逻辑 |
| 时域 label 多出单位 → 既有期望变更 | 同步更新时域 label 特征化测试期望；单位为空时不补，最小化变更 |
| pill 门槛放宽影响 split / 次 pill（`_pill_secondary`） | 沿用 `_pill_for_canvas` 路由；放宽条件只加模式、不动 split 逻辑 |
| 新浮窗/容器灰底或 QSS 失效 | 复用 CursorPill，不引入新自定义 QWidget 容器 |

---

## 8. 实施分解（供 squad 调度）

| # | 子任务 | 专家 | 依赖 |
|---|---|---|---|
| T1 | 时域标注特征化测试（overlay/subplot/label/cursor/删除） | pyqt-ui-engineer | — |
| T2 | 抽 `RemarkArtist` + `RemarkInteraction` + `RemarkAdapter` 协议 + `format_remark_label`；时域装配迁移、行为不变、T1 全绿 | pyqt-ui-engineer | T1 |
| T3 | `LineRemarkAdapter`：FFT 接公共件，替换裸 `add_remark_at` | pyqt-ui-engineer | T2 |
| T4 | `HeatmapRemarkAdapter`：热力图接公共件，三行 `X=/Y=/Z=` 标注框 | pyqt-ui-engineer | T2 |
| T5 | 热力图实时 XYZ pill：分析卡 `cursor_info` 接 pill + 门槛放宽 + hover 常发 + 三行渲染 | pyqt-ui-engineer | T4 |
| T6 | 真机渲染核验四 section 标注 + pill；回归 `pytest` | pyqt-ui-engineer | T3,T4,T5 |

> 数值反查（`_value_at` 等）若需触碰，转 signal-processing-expert（TDD-first）。预期基本不动数值。

---

## 9. 受影响文件（投资范围）

- 新增：`pg_canvas/` 标注公共件（artist / interaction / adapter / label helper）。
- 改：`pg_canvas/annotations.py`（退化为装配）、`pg_canvas/line_canvas.py`、`pg_canvas/heatmap_canvas.py`、`ui/chart_stack/stack.py`（pill 接线 + 门槛）、可能 `ui/chart_stack/cursor_pill.py`（三行入口）。
- 测试：`tests/` 新增/更新标注与 pill 用例。
