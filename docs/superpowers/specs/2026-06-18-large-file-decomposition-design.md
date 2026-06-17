# 大文件结构优化 —— 全局解剖 + 分级分期方案（设计）

- **日期**: 2026-06-18
- **状态**: 设计待评审（用户要"完整分阶段方案再定"——本文是供决策的总体 design，尚未进入 writing-plans）
- **范围**: 全仓库行数最高的若干源文件（见 §1 表），判定"该不该动 / 怎么动 / 风险"，给出排序后的分期路线图
- **核心原则**: 只动结构、不动行为；每文件一个 PR、PR 之间全测必绿；沿用已验证的 `pg_canvases → pg_canvas/` 拆包手法（strangler-fig + 重导出薄壳）。本次目标是**可维护性**，**不是性能、不改任何用户可见行为**。

> 先例：`docs/superpowers/specs/2026-06-07-pg-canvas-decomposition-design.md` + 对应 plan 已把 5771 行的 `pg_canvases.py` 拆成 `pg_canvas/` 包。本文是同一套方法论在**其余大文件**上的推广。

---

## 1. 动机（扎根事实）

`pg_canvases.py` 拆完后，当前 Top 源文件（`wc -l`，已排除测试，2026-06-18 实测）：

| 文件 | 行数 | 形态 |
|---|---|---|
| `mf4_analyzer/ui/main_window.py` | **4624** | 单个 God 类 `MainWindow`（~180 方法） |
| `mf4_analyzer/ui/inspector_sections.py` | **4063** | **8+ 个独立 widget 类同居一文件** |
| `mf4_analyzer/ui/chart_stack.py` | **3008** | **4 大类 + 多组 helper 同居** |
| `mf4_analyzer/acquisition_ui/main_window.py` | **2191** | 单个 God 类 `CockpitMainWindow` |
| `mf4_analyzer/ui/pg_canvas/canvas.py` | 2130 | 单一职责协调器（pg-canvas 拆包产物） |
| `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` | 2026 | 单一职责画布类 |
| `mf4_analyzer/ui/markup/editor.py` | **1884** | **9 个类同居（命令/图元/视图/编辑器）** |
| `mf4_analyzer/ui/canvases.py` | **1791** | **公共 helper + 疑似遗留 matplotlib 画布** |
| `mf4_analyzer/ui/pg_canvas/line_canvas.py` | 1726 | 单一职责画布类 |
| `mf4_analyzer/ui/pg_canvas/overlay_axes.py` | 1225 | 单一职责（pg-canvas 拆包产物） |

**为什么现在做**：

1. **活跃开发期**。最近提交集中在 FFT/order/fft-time 与 Inspector UI——这些正是上面最大两个文件的腹地，导航/改动成本已经在拖慢迭代。
2. **测试网很厚**。`test_pg_timedomain_canvas.py`(5246)、`test_inspector.py`(3443)、`test_main_window_smoke.py`(2313)、`test_chart_stack.py`(1750)、`test_markup_editor.py`(901) 等给重构提供了安全网——这是"能放心拆"的硬前提。
3. **方法已验证**。pg-canvas 拆包跑通了 strangler-fig + 重导出薄壳的全套流程，本次直接复用，风险已被前一次趟平。

---

## 2. 判别标准：大 ≠ 该拆

行数高本身不是问题，**职责混居**才是。三种形态区别对待：

| 形态 | 症状 | 处置 | 风险 |
|---|---|---|---|
| **A. 多类同居** | 一个文件塞了多个**彼此低耦合**的类/helper（import 时只用其中几个） | **按类拆成同名包**，`__init__` 重导出 | 🟢 低（纯搬迁，无共享 `self`） |
| **B. 单类多域** | 一个 God 类塞了多个**领域**（FFT/order/IO…），靠一大坨共享 `self.*` 隐式耦合 | **按域抽 mixin**（类拆多文件、`self` 仍共享） | 🟡 中（需保证 mixin 只用 `__init__` 已建字段） |
| **C. 内聚大类** | 单一职责、状态广播式耦合是结构必然（如统一渲染目标） | **暂不动**，硬拆只会引入跨文件耦合 | ⚪ 不拆 |

判定到每个文件（§3）。**关键：`pg_canvas/canvas.py`(2130)/`heatmap_canvas.py`(2026)/`line_canvas.py`(1726) 属于 C，不在本次射程**——它们是 pg-canvas 拆包刚定型的单一职责类，再拆只会把同帧渲染状态散到多文件、得不偿失（理由同 pg-canvas spec §2.2 的"21 核心字段广播耦合是结构必然"）。

---

## 3. 全局解剖与分级

### 第一档 —— 多类同居（形态 A，低险高收益，优先做）

#### 3.1 `inspector_sections.py`（4063 → `inspector_sections/` 包）

**内部结构**（按行号区间，9 个顶层单元）：

| 单元 | 行号 | 性质 |
|---|---|---|
| 预设/单位/表单 helper（`_preset_settings`/`_normalize_unit`/`_no_buttons`/`_make_group_header`…） | 47–217 | 纯函数 |
| `_CollapsibleParamSection` | 217–341 | 可折叠容器 widget |
| `_PresetHoverCard` + `PresetBar` | 349–1100 | 预设条 + 悬浮卡（~750 行，自成一体） |
| 表单/轴构建 helper（`_configure_form`/`_fit_field`/`_build_axis_row`/`_make_axis_settings_group`…） | 1100–1703 | 纯函数 |
| `PersistentTop` + `_AxisRangeHost` | 1325–2085 | 顶部常驻区 |
| `TimeContextual` | 2085–2108 | 时域上下文面板（极小） |
| `FFTContextual` | 2108–2643 | FFT 上下文面板（~535 行） |
| `OrderContextual` | 2643–3217 | 阶次上下文面板（~574 行） |
| `FFTTimeContextual` | 3217–4063 | 时频上下文面板（~846 行，最大） |

这些类**彼此几乎不耦合**（各自独立 widget，靠 Inspector 在外层组合），是教科书级的"可拆接缝"。

**对外契约面**（决定拆分安全边界）：
- 应用侧唯一消费者 `ui/inspector.py:17`：`from .inspector_sections import (FFTContextual, FFTTimeContextual, OrderContextual, PersistentTop, TimeContextual)`。
- 测试 `test_inspector.py` 还直接 import：`PresetBar`、`_CollapsibleParamSection`、`_configure_form`；`test_compact_spinbox.py` import `_no_buttons`；并有 `monkeypatch.setattr("mf4_analyzer.ui.inspector_sections.QMenu", ...)`。
- → **迁移硬约束**：拆成包后，`inspector_sections/__init__.py` 必须重导出上述全部公共名，并 `from PyQt5.QtWidgets import QMenu` 让 `inspector_sections.QMenu` 这个 monkeypatch 锚点继续存在。

**目标包结构**：
```
mf4_analyzer/ui/inspector_sections/        # 同名包替换 .py，import 路径零变更
├── __init__.py            # 重导出全部公共名 + QMenu 透传锚点
├── _helpers.py            # 预设/单位 + 表单/轴构建 helper（含 _no_buttons/_configure_form）
├── collapsible.py         # _CollapsibleParamSection
├── presets.py             # _PresetHoverCard + PresetBar
├── persistent_top.py      # PersistentTop + _AxisRangeHost
├── contextual_time.py     # TimeContextual
├── contextual_fft.py      # FFTContextual
├── contextual_order.py    # OrderContextual
└── contextual_fft_time.py # FFTTimeContextual
```
**结果形态**：4063 行 → 9 个 100–850 行的聚焦文件。**纯搬迁，无 `self` 共享，风险最低，导航收益最大——建议第一个做。**

#### 3.2 `chart_stack.py`（3008 → `chart_stack/` 包）

**内部结构**：

| 单元 | 行号 | 性质 |
|---|---|---|
| pixmap/html helper（`_grab_pixmap_hidpi`/`_format_mini_html`） | 20–90 | 纯函数 |
| `CursorPill` + `_QualityStatusIndicator` | 90–328 | 浮层 widget |
| 工具栏 helper（`_apply_mdi_icons`/`_install_nav_shortcuts`…）+ `_TickDensityPopover` | 328–565 | 纯函数 + 弹窗 |
| `PgNavigationToolbar` | 565–1097 | 导航工具栏（~530 行） |
| `_ChartCard` + `TimeChartCard` | 1097–1934 | 图卡（~840 行） |
| `ChartStack` | 1934–3008 | 主容器（~1070 行，本文件核心） |

**对外契约面**：
- 应用侧 `main_window.py:84`：`from .chart_stack import ChartStack`（其余皆经实例属性 `self.chart_stack.*` 使用，非 import）。
- 测试 `test_chart_stack.py:11/16`：import `ChartStack, _CURSOR_HTML_SEP, _apply_mdi_icons, _MDI_NAV_ICONS`。
- → `__init__.py` 重导出 `ChartStack` + 上述被测 helper/常量即可。

**目标包结构**：
```
mf4_analyzer/ui/chart_stack/
├── __init__.py        # 重导出 ChartStack + _CURSOR_HTML_SEP + _apply_mdi_icons + _MDI_NAV_ICONS …
├── _helpers.py        # pixmap/html/工具栏图标 helper（_apply_mdi_icons/_MDI_NAV_ICONS…）
├── cursor_pill.py     # CursorPill + _QualityStatusIndicator（+ _CURSOR_HTML_SEP）
├── toolbar.py         # PgNavigationToolbar + _TickDensityPopover
├── cards.py           # _ChartCard + TimeChartCard
└── stack.py           # ChartStack
```
**结果形态**：3008 → 最大文件降到 ~1070 行（ChartStack）。`CursorPill`/`PgNavigationToolbar`/`_ChartCard` 与 `ChartStack` 低耦合，属形态 A。`ChartStack` 自身（~1070 行）内聚，**本次不再内拆**。

#### 3.3 `markup/editor.py`（1884，在既有 `markup/` 包内细分）

**内部结构**：

| 单元 | 行号 | 性质 |
|---|---|---|
| 6 个 `QUndoCommand` 子类（`_AddItemCommand`/`_CropCommand`/`_MoveCommand`/`_DeleteCommand`/`_GeometryCommand`/`_StyleCommand`） | 64–160 | 命令对象 |
| 2 个图元（`_ArrowAnnotationItem`/`_TextAnnotationItem`） | 160–271 | QGraphicsItem |
| `_MarkupGraphicsView` | 271–535 | 视图 |
| `MarkupEditor` | 535–1884 | 编辑器主类（~1350 行） |

**对外契约面**：
- 应用侧 `main_window._create_markup_editor`（构造 `MarkupEditor`）；`markup/__init__.py` 导出 `CopyThumbnail`。
- 测试 `test_markup_editor.py`：`from mf4_analyzer.ui.markup.editor import MarkupEditor`；`test_color_swatch_hidpi.py`：`import mf4_analyzer.ui.markup.editor as editor_mod`（按模块名访问内部符号）。
- → 移走的命令/图元/视图类需在 `editor.py` 顶部 `from .commands import *` 等回引，使 `editor_mod.X`、`MarkupEditor` 访问点零变更。

**目标结构**（既有包内新增文件）：
```
mf4_analyzer/ui/markup/
├── __init__.py     # 既有（导出 CopyThumbnail）
├── commands.py     # 6 个 QUndoCommand 子类
├── items.py        # _ArrowAnnotationItem + _TextAnnotationItem
├── view.py         # _MarkupGraphicsView
└── editor.py       # MarkupEditor（瘦身到 ~1350 行）+ 回引移出的名字
```
**结果形态**：移出 ~480 行 + 8 个小类。`MarkupEditor` 仍 ~1350 行（单一职责），可选第二步把其工具栏/样式面板构建（`_build_toolbar`/`_build_style_panel`/图标 helper，~300 行）抽成 mixin，**非必须**。

---

### 第二档 —— 单类多域（形态 B，高收益、中风险，需测试兜底）

#### 3.4 `main_window.py`（4624 → `main_window/` 包 + mixin）

单个 `MainWindow` God 类，~180 方法。按领域分簇（行号区间）：

| 域 | 代表方法 | 行号区间 |
|---|---|---|
| 生命周期/装配 | `__init__`/`_init_ui`/`_connect`/`closeEvent` | 32–522, 3895– |
| 视图/分屏管理 | `_on_view_split`/`_render_view_to_canvas`/`_capture_*_view` | 522–757, 1488–1671 |
| 分析 section 编排 | `_analysis_*`/`_recompute_analysis_section`/`_render_analysis_view_from_cache` | 758–1268 |
| 工程/文件 IO | `open/save_project`/`load_file`/`_load_one`/`_close`/`close_all` | 2322–2667 |
| 绘时域 | `plot_time`/`_plot_time_on_canvas` | 2768–2930 |
| 编辑/导出/批处理 | `open_editor`/`_do_export_excel`/`open_batch` | 2930–3171 |
| **FFT** | `do_fft`/`_do_fft_single`/`_fft_compute_arrays`/`_resolve_fft_effective_params` | 3171–3556 |
| **阶次** | `do_order_time`/`_dispatch_order_job`/`_render_order_*`/`_on_order_*` | 3556–3895 |
| **时频(STFT)** | `do_fft_time`/`_dispatch_fft_time_job`/`_fft_time_cache_*`/`_on_fft_time_*` | 3965–4624 |

三个分析域（FFT/阶次/时频）各自带"参数解析→缓存→派发 worker→渲染→回调"的完整链路，是最干净的抽取接缝。`_fft_time_cache_*` 还可进一步抽成独立 `FftTimeCache` 小类（组合，最干净）。

**对外契约面**：应用侧 `app.py` 构造 `MainWindow`；测试 `test_main_window_smoke.py` 等构造实例并戳大量方法。**只要类名 `MainWindow` 与公共方法签名不变，契约即不破**——mixin 化天然满足。

**目标结构**：
```
mf4_analyzer/ui/main_window/
├── __init__.py          # 重导出 MainWindow
├── window.py            # class MainWindow(FFTMixin, OrderMixin, FFTTimeMixin, AnalysisMixin, ViewMixin, ProjectIOMixin):
│                        #   __init__/_init_ui/_connect/生命周期 + 跨域共享 helper
├── _fft_mixin.py        # FFT 计算/缓存/渲染
├── _order_mixin.py      # 阶次分析 + job 派发
├── _fft_time_mixin.py   # STFT/时频 + job 派发（最大簇）
├── _fft_time_cache.py   # FftTimeCache（组合，非 mixin）
├── _analysis_mixin.py   # 分析 section 编排
├── _view_mixin.py       # 视图/分屏管理
└── _project_io_mixin.py # 工程/文件 IO
```
**结果形态**：4624 → `window.py` ~1000 行 + 6–7 个 300–700 行 mixin。**重复方法扫描已确认无死代码**（不像 pg-canvas 当年有 `_channel_name_for_handle` 重复）。
**风险点**：mixin 共享 `self`——每个 mixin 只能假设 `window.__init__/_init_ui` 已建好的字段；抽取时需核对字段依赖（靠 `test_main_window_smoke` 兜底）。

#### 3.5 `acquisition_ui/main_window.py`（2191 → `main_window/` 包 + mixin）

`CockpitMainWindow` God 类（+ 小 `_PlaceholderReviewModal`）。分域：

| 域 | 行号区间 |
|---|---|
| 工具栏构建/溢出 | 341–642（~300 行） |
| 状态机 / UI 同步 | 818–900 |
| 连接尝试 + backend 切换 + 探针(`_probe_*`) | 1012–1184, 2064–2146 |
| 健康/实时轮询 + 自动停止 | 1308–1430 |
| 传输/设置/配置/a2l | 1643–1996 |
| 访问器(`state_machine`/`ring_buffer`/…) | 2146–2191 |

**对外契约面**：`__main__.py` 构造 `CockpitMainWindow`；测试还引用 `_PlaceholderReviewModal`、类常量 `_DROPPED_PROMPT_REARM_S`/`_DROPPED_PROMPT_REARM_DELTA`，并 `monkeypatch ...main_window.QMessageBox`。→ `__init__.py` 重导出两个类、类常量留在类上、包级 `from PyQt5.QtWidgets import QMessageBox` 保锚点。

**目标结构**：`window.py`（CockpitMainWindow + `__init__` + 访问器 + 类常量）+ `_toolbar_mixin.py` / `_connection_mixin.py`（含探针）/ `_polling_mixin.py` / `_settings_mixin.py`（含 a2l）。与 3.4 同手法，体量更小、优先级更低。

---

### 第三档 —— 疑似遗留（形态特殊：查证后退役）

#### 3.6 `canvases.py`（1791）—— 公共 helper + 旧 matplotlib 画布

实测构成两段：
- **行 1–506（~505 行）公共 helper**：`build_envelope`(384)、`_is_monotonic_array`、`_compact_axis_label`、`_format_dual_html`、光标取值格式化等。**被大量复用且载荷关键**——`pg_canvas/canvas.py`、`cursor.py`、`_shared.py`、`overlay_axes.py`、`line_canvas.py` 以及 `signal/_envelope_cutils.py` 都 import 它。
- **行 506–1791（~1285 行）matplotlib 画布**：`TimeDomainCanvas`(506) + `PlotCanvas`(1587)。pyqtgraph 迁移（M5 swap）后，**全仓库仅测试在实例化它们**（`test_axis_interaction.py`/`test_canvases.py`/`test_timedomain_pan_perf.py`），应用路径（`app.py`/`main_window`/`chart_stack`）一律走 pyqtgraph 的 `TimeDomainCanvasPG`/`PgHeatmapCanvas`。

**问题**：当前从 `canvases` 取一个纯 helper（如 `build_envelope`）会顺带把 matplotlib + 整套老画布拖进来——pyqtgraph 栈依赖一个名为"canvases"的模块本身就是味道。

**处置（两步，先查后删）**：
1. **抽公共 helper 到中立模块**：纯信号数学（`build_envelope`/`_is_monotonic_array`）→ `signal/envelope.py`；纯 UI 格式化（`_compact_axis_label`/`_format_dual_html`/光标格式化）→ `ui/plot_helpers.py`。`canvases.py` 保留重导出薄壳。**这步零风险、立即解耦。**
2. **查证 matplotlib 老画布是否真为死代码**（仅测试实例化 → 是否还需保留作 parity 基准）。若确认无运行期依赖，则**退役**（删除或移入 `tests/_legacy/`），**可一次性砍掉 ~1285 行**。此步**需先逐一确认引用、再删**，不在本设计里预先承诺删除。

---

### 暂不动（形态 C）

`pg_canvas/canvas.py`(2130)、`heatmap_canvas.py`(2026)、`line_canvas.py`(1726)、`overlay_axes.py`(1225)：均为 pg-canvas 拆包刚定型的单一职责类，状态广播耦合是结构必然。**仅当某类继续膨胀**（如 heatmap 的 slice 面板 `_slice_*`/`select_time_index` 成独立子特征）才考虑局部抽取，本次不动。

---

## 4. 统一迁移策略（沿用 pg-canvas 已验证手法）

1. **同名包替换**：`X.py` → `X/` 包 + `__init__.py` 重导出全部对外名（含测试 monkeypatch 锚点如 `QMenu`/`QMessageBox`），**import 路径零变更**。
2. **形态 A（拆类）**：把类**逐字搬**到新文件，仅补 import；无 `self` 共享，无需薄壳。
3. **形态 B（mixin）**：套用 pg-canvas 的 Recipe R——方法逐字搬进 mixin，`self` 不变（mixin 与协调器同属一个实例）；类名/方法签名不变，故**连委托薄壳都不需要**（mixin 比 pg-canvas 的协作对象更省事，因为 `self` 本就共享）。
4. **测试门禁**：每个 PR 收尾必须 `python -m pytest -q`（offscreen）全绿 + 相关 perf 不回归。
5. **一文件一 PR、独立分支**（如 `refactor/inspector-sections-split`）；当前 branch 与本主题无关，执行前先开专用分支。
6. **squad 路由**：实际改码走 planner-executor split——纯搬迁/包结构 → `refactor-architect`；Qt widget 行为 → `pyqt-ui-engineer`；`main_window` 三个分析域 mixin 涉及数值的部分 → `signal-processing-expert` 复核。

---

## 5. 分期路线图（按 风险↑ / 依赖 排序）

| 期 | 目标文件 | 形态 | 风险 | 主要门禁测试 | squad 主责 |
|---|---|---|---|---|---|
| **A** | `inspector_sections.py` → 包 | A | 🟢 低 | `test_inspector.py`、`test_compact_spinbox.py` | refactor-architect |
| **B** | `markup/editor.py` 包内细分 | A | 🟢 低 | `test_markup_editor.py`、`test_color_swatch_hidpi.py` | pyqt-ui-engineer |
| **C** | `chart_stack.py` → 包 | A | 🟢 低-中 | `test_chart_stack.py` | refactor-architect + pyqt-ui-engineer |
| **D** | `canvases.py` helper 抽离 + 老画布查证退役 | 特殊 | 🟡 中（步1零险，步2需查证） | `test_canvases.py`、`test_axis_interaction.py`、packaging | refactor-architect |
| **E** | `main_window.py` → 包 + mixin | B | 🟡 中 | `test_main_window_smoke.py` 等 | pyqt-ui-engineer + signal-processing-expert |
| **F** | `acquisition_ui/main_window.py` → 包 + mixin | B | 🟡 中 | `tests/acquisition_ui/*` | pyqt-ui-engineer |

**排序理由**：A/B/C 是纯搬迁、立竿见影、零行为风险，先收割导航收益、同时把团队对"同名包+重导出"流程练熟；D 的步骤1顺手解耦、步骤2可能一次砍千行；E/F 是 God 类 mixin 化，留到最后在最厚的 smoke 测试网下做。各期相互独立，可随时叫停或调序。

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 拆包后测试 import 路径/monkeypatch 锚点失效 | `__init__.py` 重导出全部对外名 + `QMenu`/`QMessageBox` 等锚点透传；每期"对外契约面"已逐条列出 |
| mixin 误用未初始化字段 | 抽取时核对字段只来自 `__init__/_init_ui`；`test_*_smoke` 构造即跑兜底 |
| `canvases.py` 老画布误删 | 步骤2 先逐一确认无运行期引用再删，本设计不预先承诺删除 |
| 把重构做成行为变更 | 非目标写死（§7）；每 PR 全测必绿、逐字搬迁 |
| 一次摊子铺太大 | 一文件一 PR、一期一独立分支，可随时停在任意期 |

---

## 7. 非目标（明确排除）

- ❌ 不改任何用户可见行为、不改信号/公共方法签名。
- ❌ 不追求性能、不上 OpenGL、不改 AA/cache 语义。
- ❌ 不动形态 C 的内聚画布类（`pg_canvas/canvas.py` 等）。
- ❌ 不在本设计阶段删除 `canvases.py` 老画布（留到 D 期查证后单独决策）。
- ❌ 不做与"拆分/解耦"无关的逻辑重写。

---

## 8. 完成定义（DoD）

- 每期：目标文件降为同名包（或包内细分），最大文件落到目标量级；对外契约零变更；`pytest -q` 全绿 + 相关 perf 不回归；行为零变更。
- 程序级：第一档三文件（A/B/C）全部拆包，单文件最大行数从 4624 降到 ~1300 量级（`main_window/window.py` 完成 E 期后）；`canvases.py` 公共 helper 已中立化。

---

## 9. 开放问题 / 待评审点

1. **先做哪几期、做到哪**：建议先批 A（最低风险、最高导航收益）跑通，再决定节奏；也可一次性批 A+B+C（三个纯搬迁包）。
2. **D 期老画布退役**：是否接受"查证确认仅测试使用后删除 ~1285 行"？还是保留作 parity 基准、仅做步骤1的 helper 抽离？
3. **包命名**：统一用"同名包替换 `.py`"（import 路径零变更，推荐），还是学 pg-canvas 用新包名 + 旧名 shim？倾向前者。
4. **E/F mixin 粒度**：分析三域是否各自独立 mixin（推荐，便于 signal-processing-expert 单独复核），还是合并为一个 `AnalysisMixin`。

---

## 10. 执行交接

本文是**供决策的总体设计**。一旦某期获批，再为该期产出 pg-canvas plan 同款的 **task-by-task 实施 plan**（`docs/superpowers/plans/2026-06-18-<file>-decomposition.md`，含逐任务 Files/Steps/测试命令/commit、重导出名清单、Recipe），并走 squad runbook 落地。

> 建议起步：**A 期（`inspector_sections.py` 拆包）**——纯搬迁、零行为风险、4063 行立即变 9 个聚焦文件。
