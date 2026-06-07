# pg_canvases 解耦重构 —— Review 报告 + 目标架构设计

- **日期**: 2026-06-07
- **状态**: 设计待评审（brainstorming 产出，尚未进入 writing-plans）
- **目标文件**: `mf4_analyzer/ui/pg_canvases.py`（5771 行）
- **范围决策**: 全量 5 期（Phase 0–4），渲染/导出红线独立成期、由特征化测试门控
- **核心原则**: 只动结构、不动行为；不上 OpenGL；不改已调优的 AA/cache 预算语义。本次目标是**可维护性与质量可控**，**不是性能**。

---

## 1. 为什么要做（动机，扎根事实）

`pg_canvases.py` 是全仓库最大的单文件，且断崖式领先：

| 文件 | 行数 |
|---|---|
| **mf4_analyzer/ui/pg_canvases.py** | **5771** |
| mf4_analyzer/ui/inspector_sections.py | 3183 |
| mf4_analyzer/ui/main_window.py | 2656 |
| mf4_analyzer/ui/chart_stack.py | 2577 |
| mf4_analyzer/ui/canvases.py | 2502 |

文件内部由三部分构成：

1. **~25 个模块级 helper 函数**（行 134–1232，约 1100 行）：pyqtgraph 右键菜单构建/i18n/网格子菜单（`redesign_pg_context_menu`、`_build_grid_submenu`、`_localize_pg_context_menu` …）、字体（`_pg_chart_font`、`_apply_pg_axis_font` …）、刻度数学（`_nice_per_div`、`_fmt_tick`、`_frame_to_nice`、`_quantize_range_key` …）。
2. **`_ModifierWheelViewBox(pg.ViewBox)`**（行 975，约 287 行）：一个 ViewBox 子类。
3. **`TimeDomainCanvasPG(QWidget)`**（行 1279–5771，**约 4492 行、约 150 个方法**）：God Object，本次重构的核心。

God 类的"不可控"症状是结构性的，不是主观感受：

- `__init__` 约 270 行，初始化 **66 个实例属性**；全类共 **70 个 `self.*` 字段**。约 150 个方法靠这一大坨共享可变状态隐式耦合在一起 —— 改任何一处都难以确定波及面，这正是"质量不可控"的根因。
- 一个文件容纳约 24 个不同职责（见 §3），任何人（包括 AI）都无法一次装进上下文来安全修改。

---

## 2. 现状解剖（Review 主体）

### 2.1 职责分簇

`TimeDomainCanvasPG` 的约 150 个方法可清晰切成 24 个内聚职责簇（按行号区间）：

| 簇 | 职责 | 行号区间 |
|---|---|---|
| A | 构造 / 绘图装配 | 1279–1952（含 `plot_channels` 1550） |
| B | X/Y 范围与视图管理 | 1972–2515 |
| C | 通道绑定 / overlay 轴样式 | 2026–2320 |
| D | overlay Y 网格 / 吸附动画 | 2515–2815 |
| E | 生命周期 clear/reset | 2815–2896 |
| F | 光标系统（单/双/极值标/命中） | 2896–3260 |
| G | 命中测试 / overlay 选择 | 3279–3350 |
| H | 批注 remark | 3351–3723 |
| I | overlay 鼠标拖拽 | 3723–3811 |
| J | 统计 / span 选择 | 3811–3849 |
| K | 刻度密度（x-tick 计算/排版） | 3849–4050 |
| L | 图表选项对话框 | 4050–4114 |
| M | 事件过滤 / 命中 | 4114–4219 |
| N | overlay 视图同步 | 4219–4265 |
| O | 缓存失效 | 4265–4312 |
| P | xrange 监听 / 传播 | 4312–4447 |
| Q | 渲染 / 数据刷新（painter-path） | 4472–4657 |
| R | overlay 强调 / 选择 | 4657–4843 |
| S | 滚轮分发 | 4843–4965 |
| T | 光标 HTML 输出 | 4965–5078 |
| U | 内嵌标签 / 子图标签 | 5078–5356 |
| V | resize | 5356–5425 |
| W | 抗锯齿质量管理 | 5425–5673 |
| X | 导出 grab_pixmap | 5673–5771 |

好消息：这些簇**内部还算内聚**，存在干净的"接缝"可拆。

### 2.2 状态耦合分层（决定可拆性的硬数据）

把 66 个 `__init__` 字段按"被多少个簇读写"分层：

| 耦合层 | 数量 | 代表字段 | 处置策略 |
|---|---|---|---|
| **单簇私有** | ~6 | `_snap_anim_ms`、`_mouse_mode_controller`、`_curve_path_cache_capacity`、AA 常量 | 直接随协作对象搬走，零风险 |
| **2–3 簇共享** | ~39 | `_remarks`(批注)、`_cursor_*_items`(光标)、overlay 样式 6 字段、snap 动画 3 字段、`_annotation_*` | 抽成 manager/facade，**对象自持状态**，canvas 委托读写 |
| **4–11 簇核心** | ~21 | `axes_list`(11 簇)、`_primary_xaxis_ax`(11)、`_glw`(9)、`_overlay_mode`(9)、`_channel_lines`(8)、`_refresh`/`_refresh_timer`(帧合并中枢)、`channel_data`(渲染热路径)、`_x_master_handle`(7) | **必须留在协调器** |

**关键结论（诚实的天花板）**：那 21 个核心字段的"广播式"耦合是**结构必然，不是设计缺陷**——图表是单一统一渲染目标（`_glw` + scene），光标/批注/网格是 overlay、必须与数据**同帧同步**，`channel_data → render` 是同步热路径。把它们外部化（observer/消息队列）只会用掉帧换来"解耦"。

> 因此目标**不是"消灭 God 类"**，而是把它降级成一个持有这 21 个枢纽字段 + 公共 API 的**协调器（coordinator）**，把 6–8 个内聚行为簇抽成独立协作对象。这是本设计的核心立场。

### 2.3 对外契约面（决定重构安全边界）

全仓库**只有一处** import 它：`mf4_analyzer/ui/chart_stack.py:239 → from .pg_canvases import TimeDomainCanvasPG`。

chart_stack 对实例的真实调用面**极小**：

- 信号 3 个：`cursor_info(str)`、`dual_cursor_info(str)`、`dual_cursor_rows(object)`
- 方法 1 个：`full_reset()`
- 构造：`TimeDomainCanvasPG(parent)`

→ **冻结外部契约几乎零成本（🟢）**。

**但**：7 个测试文件（`test_pg_timedomain_canvas.py` 等，合计约 9675 行）直接戳了 **50+ 个私有成员**——`_channel_lines`、`_primary_xaxis_ax`、`_glw`、`_overlay_mode`、`_idle_aa_on`、`_flush_pending_refresh`、`_add_remark`、`_handle_wheel_dispatch` …。这是真正的迁移约束：抽出协作对象后，**必须在 canvas 上保留同名"委托薄壳"**让现有测试继续绿，再择机迁移测试访问点。

### 2.4 红线：渲染→导出链

簇 Q（渲染 4472–4657）/ W（质量 5425–5673）/ X（导出 5673–5771）构成一条脆弱链：

- 与 `_glw`、`_channel_lines`、`_overlay_mode`、`_primary_xaxis_ax`、idle-AA 状态、3 个 QTimer（`_refresh_timer` 40ms / `_idle_aa_timer` 150ms / `_resize_settle_timer` 40ms）深耦合。
- 数据流：`_refresh_visible_data → _build_painter_path(_loop) → setData`；导出流：`grab_pixmap → _export_aa_affordable →（临时开 AA 上下文）→ _grab_widget_scaled`。
- **历史教训**：把渲染改成 OpenGL 曾导致 `grab_pixmap` **导出全白**（见记忆 `project-timedomain-perf-raster-bound`）。
- 现有 AA/密度/HiDPI 测试不少，**但缺"导出像素内容级"特征化测试**：没有断言导出 QPixmap 非全白、与屏幕内容一致、每条曲线都可见。

→ 这条链**必须最后动**，且动前先补 ~5 个特征化测试兜底。

### 2.5 顺手发现的真·腐化

`_channel_name_for_handle` 在 **行 2224 与 3279 各定义一次**，两份函数体逻辑完全相同（仅局部变量名 `candidate`/`axis_handle` 不同），第二个静默覆盖第一个。目前**无害**（行为一致），但正是记忆 `project-ui-files-structural-corruption` 里那条"同名方法重复定义"模式的活样本，应在 Phase 0 顺手清掉。

---

## 3. 目标与非目标

**目标**
- 把 `TimeDomainCanvasPG` 从 ~4500 行/150 方法的 God 类降为 ~40–50 方法的协调器 + 6–8 个 200–500 行的聚焦协作对象。
- 每个协作对象能被独立读懂、独立测试，状态归属清晰。
- 清理结构腐化（重复方法），补齐渲染/导出安全网。

**非目标（明确排除）**
- ❌ 不改任何用户可见行为。
- ❌ 不追求性能提升、不上 OpenGL、不改 AA/cache 预算语义（perf 是 CPU 光栅瓶颈，不在本次射程）。
- ❌ 不试图外部化那 21 个核心枢纽字段。
- ❌ 不做与本目标无关的重构。

---

## 4. 目标架构

### 4.1 包结构（`pg_canvases.py` → `pg_canvas/` 包）

```
mf4_analyzer/ui/pg_canvas/
├── __init__.py          # 仅 re-export TimeDomainCanvasPG（外部 import 不变）
├── canvas.py            # 协调器：21 核心字段 + 公共 API + __init__ 装配 + 委托薄壳
├── context_menu.py      # ~20 个右键菜单 / i18n / 网格子菜单 helper      (~810 行, 纯函数)
├── fonts.py             # _pg_chart_font / _apply_pg_axis_font ...        (~140 行, 纯函数)
├── ticks_math.py        # _nice_per_div / _fmt_tick / _frame_to_nice ...  (~110 行, 纯函数)
├── viewbox.py           # _ModifierWheelViewBox                            (~290 行)
├── cursor.py            # CursorController   (簇 F+T)
├── annotations.py       # AnnotationManager  (簇 H)
├── tick_density.py      # TickDensityController (簇 K)
├── overlay_axes.py      # OverlayAxisManager (簇 C/D/R/N)
├── quality.py           # QualityManager    (簇 W)
└── renderer.py          # Renderer/Exporter (簇 Q/X) ← 红线, 最后落地
```

> 兼容性：保留 `mf4_analyzer/ui/pg_canvases.py` 作为一行 re-export 薄壳，或直接改 chart_stack 的那一处 import —— 二选一，Phase 0 决定（倾向保留薄壳，零外部改动）。

### 4.2 协作对象划分与状态归属

每个协作对象**持有自己的私有状态**，通过一个**窄 canvas 接口**读取那 21 个枢纽字段（`axes_list` / `_primary_xaxis_ax` / `channel_data` / `_overlay_mode` …）。

| 协作对象 | 来源簇 | 自持状态（从 canvas 搬出） | 仍向 canvas 读取 |
|---|---|---|---|
| `CursorController` | F + T | `_cursor_*_items`、`_dual`、`_last_t`、`_placing`、极值标 | `axes_list`、`_primary_xaxis_ax`、`channel_data` |
| `AnnotationManager` | H | `_remarks`、`_annotation_enabled`、按压拖拽状态 | `axes_list`、scene、命中接口 |
| `TickDensityController` | K | x-tick 密度配置 | 各 axis handle |
| `OverlayAxisManager` | C/D/R/N | `_overlay_aux_viewboxes`、snap 动画、overlay 样式字段 | `_x_master_handle`、`_overlay_mode`、`_channel_lines` |
| `QualityManager` | W | `_idle_aa_*`、`_idle_aa_timer` | curve items（经 canvas） |
| `Renderer/Exporter` | Q/X | `_curve_path_cache`、`_last_range_key` | `_glw`、`channel_data`、`_channel_lines`、质量状态 |

纯函数模块（context_menu / fonts / ticks_math）与 `viewbox.py` 不持有 canvas 状态，纯搬迁。

### 4.3 结果形态

- 协调器 `canvas.py`：~40–50 方法（公共 API + `__init__` 装配 + 委托薄壳 + 21 枢纽字段）。
- 8 个聚焦文件，各 200–500 行，可独立读懂/测试。
- 单文件 5771 行 → 最大文件预计降到 ~1000 行级别。

---

## 5. 迁移策略：strangler-fig + 测试守门

**核心手法**：每抽出一个协作对象，canvas 上保留**同名委托薄壳**（方法/property），让 50+ 个测试触点透明地继续工作；全测 + perf 测试每期收尾必须绿；行为零变更。

### Phase 0 —— 安全网 + 白捡结构分（极低风险）
- 补 5 个**导出像素特征化测试**（见 §6）。
- 删除重复的 `_channel_name_for_handle`（2224/3279 死代码）。
- 抽 4 个纯模块：`context_menu.py` / `fonts.py` / `ticks_math.py` / `viewbox.py`（**约 1350 行出门**）。
- `pg_canvases.py` 转为 `pg_canvas/` 包 + 兼容薄壳。
- **完成判据**：全测绿；`pg_canvases.py` 仅剩 God 类 + re-export；无行为变更。

### Phase 1 —— 抽独立协作对象（低–中风险，逐个推进）
- 顺序：`CursorController`（F+T）→ `AnnotationManager`（H）→ `TickDensityController`（K）。
- 每个：搬方法 + 自持状态 + canvas 留委托薄壳；单个完成即跑全测。
- **完成判据**：三个对象各自独立成文件并被对应测试覆盖；薄壳保旧测试绿。

### Phase 2 —— 抽 overlay 子系统（中风险）
- `OverlayAxisManager`（C/D/R/N）。触及 `_x_master_handle`、`_overlay_aux_viewboxes`、`_overlay_mode`，需小心 Qt 父子关系与视图同步时序。
- **完成判据**：overlay 网格/吸附/强调/视图同步测试全绿，含 `test_overlay_grid_ticks.py`。

### Phase 3 —— 质量 + 渲染/导出（最高风险，红线，门控）
- **前置门控**：Phase 0 的 5 个特征化测试必须已就位且稳定。
- `QualityManager`（W）→ `Renderer/Exporter`（Q/X）。
- 全程不改 AA/cache 预算语义、不上 OpenGL。
- **完成判据**：特征化测试 + perf 测试 + 现有 AA/密度/HiDPI 测试全绿；导出像素与重构前逐字节一致（或在容差内）。

### Phase 4 —— 收尾
- 协调器定型；可选把测试从 `canvas._private` 迁到 `canvas.cursor.x` 等公开接口，逐步撤掉委托薄壳。
- **完成判据**：协调器 ≤ ~50 方法；委托薄壳清单收敛或归零。

> 执行方式：本仓库有 squad（planner-executor split）。各 Phase 的代码改动可作为 `refactor-architect` / `pyqt-ui-engineer` 的任务下发；Phase 3 的渲染数值相关部分涉及 `signal-processing-expert` 的特征化测试。详细任务拆解见后续 writing-plans 产出。

---

## 6. Phase 0 必补的特征化测试（红线前置）

针对"导出全白"历史坑，最少补 5 个像素内容级断言：

1. **导出与屏幕一致**：`grab_pixmap()` 的 QPixmap RGB 字节与显示内容一致（非全白/非全透明）。
2. **AA 启/关导出质量**：affordable 时导出边缘比 1× 更清晰（或至少 AA 上下文确实生效）。
3. **多通道每条曲线可见**：overlay 多通道导出时每条曲线像素都存在，不被 α 混合吃掉。
4. **边界**：空 canvas / 极稀疏（1 点/通道）/ 极密集 下 `envelope + grab` 不崩、fallback 行为正确。
5. **导出与刷新并发安全**：`grab_pixmap` 与 `_refresh_visible_data` 交错时无 torn read。

配套提供 pixelwise assert helper（如 `assert_pixmap_not_blank` / `assert_pixmap_matches`）。

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 50+ 测试戳私有，重构易碎 | strangler-fig 委托薄壳，旧测试零改动通过；Phase 4 再迁移 |
| 渲染/导出回归（全白历史坑） | Phase 0 特征化测试门控；红线独立成 Phase 3 最后做 |
| 21 核心字段误外部化导致掉帧 | 设计明确：核心字段留协调器，只搬行为不搬枢纽状态 |
| overlay 视图同步时序错乱 | Phase 2 单独成期，依赖 `test_overlay_grid_ticks.py` 守门 |
| 误把重构当性能优化 | 非目标明确写死；perf 测试只做"不回归"基线，不追求提升 |

---

## 8. 完成定义（DoD）

- `TimeDomainCanvasPG` 降为协调器（≤ ~50 方法），8 个聚焦协作/纯模块文件就位。
- 外部契约（3 信号 + `full_reset`）零变更；全部 7 个测试文件 + perf 测试绿。
- 重复方法等结构腐化清除。
- 导出/渲染链有像素内容级特征化测试兜底。
- 全程无用户可见行为变更。

---

## 9. 待评审点 / 开放问题

- 兼容薄壳 vs 直接改 chart_stack 的一处 import —— Phase 0 落地时二选一（倾向薄壳）。
- 协作对象与 canvas 之间的"窄接口"具体形态（传 canvas 引用 vs 传 narrow protocol）—— 留给 writing-plans 细化。
- Phase 4 是否真的撤薄壳、迁测试，取决于 Phase 0–3 完成后的收益评估，可暂缓。
