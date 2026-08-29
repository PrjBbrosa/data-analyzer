# WWT 多 Board、排版贴合与 24 时域 View Spec

- 日期：2026-08-29
- 状态：已实施（offscreen 聚焦+边界通过；Cocoa 前台 UNVERIFIED）
- 基线：`main` @ `377c20d45fe3d1fa4ce6e19a19a84a8ff330b082`
- 配套计划：
  [`2026-08-29-wwt-multi-board-layout-fit-and-24-views-plan.md`](../plans/2026-08-29-wwt-multi-board-layout-fit-and-24-views-plan.md)
- 前置规格（不改写）：
  [`2026-08-28-wwt-winwert-layout-import-spec.md`](2026-08-28-wwt-winwert-layout-import-spec.md) ·
  [`2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md`](2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md)
- 产品范围：WWT 导入确认、时域 View 上限、UltraView Board 分配、毫米→微网格换算、预览到达后 Card Fit

## 1. 一句话结论

打开 WWT 后按**实际成功创建的时域 View 数**决定是否投影：`0/1` 只生成时域 View、不自动加入 UltraView；`≥2` 才投影到专属 Board（优先复用当前空 Board，否则新建）。毫米排版用统一 `px/mm` 再按横/纵网格节距量化，预览到达后用现有 Card Fit 贴合卡片。时域上限改为 24，四个分析区仍为 12。

## 2. 决策

| ID | 决策 |
| --- | --- |
| D1 | 投影阈值看 **实际 `insert_states` 成功数**，不是文件窗口数。容量只剩 1 而被截成单卡时，不创建单卡 Board。 |
| D2 | 单 View 仍允许用户之后手动「加入 UltraView」。导入路径不写 Board，也不改活动 Board。 |
| D3 | 「空 Board」= 无 `placements` / `free_grid` / `unplaced`，且 `author_objects` 为空。复用时改名并切到自由网格。 |
| D4 | 多个 WWT 各自进入不同 Board。最新导入的多 View WWT Board 成为活动 Board。 |
| D5 | Board 名 = WWT 文件名去掉 `.wwt`（保留其余后缀前的 stem）。工作区已有同名则 ` (2)`、` (3)`… |
| D6 | Board 分配、命名、布局作为一次事务。不读调用期间可能变化的活动 Board 作为隐式目标。 |
| D7 | `MAX_UI_BOARDS`（20）已满：保留已创建的时域 Views，不把卡片塞进既有非空 Board，给出可行动提示。 |
| D8 | 确认框：将创建 1 个 View 时写「仅生成时域 View」；将创建 ≥2 个时写「同步到独立 Board」。 |
| D9 | 毫米坐标：先按统一 `px/mm` 映射到像素，再分别除以 `GridMetrics.exact_pitch()` 的横、纵节距并 round 到微网格。相对位置与源顺序保留。完全重叠仍进未放置区。 |
| D10 | 预览到达后用现有 Card Fit（`solve_card_fit`）按 DPR 归一化后的真实图像尺寸改卡片跨度。Fit 碰撞：后到卡片移到曼哈顿距离最近的合法位置，同距时上到下、左到右；不重新缩放已接受卡片。 |
| D11 | 自动贴合受 Board `layout_revision` 保护：用户已移动或缩放对应卡片则取消该延迟任务。缺预览则保留已修正的原生几何。 |
| D12 | 整组导入 + 延迟贴合合并为一个撤销步骤。延迟更新不抢焦点、不反复改 Board 相机。 |
| D13 | 删除 WWT View 固定蓝色 `tab_color`。按最终插入索引走 `default_view_tab_color(idx)`；13–24 循环现有 12 色。只改 View 标签/卡片识别色。WinWert 曲线 RGB、用户后续改色、每 View 颜色持久化不变。 |
| D14 | `TIME_DOMAIN_MAX_VIEWS = 24`。`MAX_VIEWS = 12` 仍是分析区与兼容默认值。WWT 容量读 `view_manager.max_views`。工程保存格式不升级。 |
| D15 | 不新增跨 MainWindow 可变状态。异步贴合由现有 UltraView workspace controller 所有，并在恢复、清空、销毁时对称清理。 |
| D16 | 不改变通用 Card Fit 的手动语义、UltraView schema、曲线颜色合同、原始精确重叠未放置规则。 |

## 3. 接口

### 3.1 默认 View 色

`mf4_analyzer/ui/view_state.py`：

```python
def default_view_tab_color(index: int) -> str:
    """Palette color for a View at ``index`` (0-based). Cycles every 12."""
```

`ViewManager._make` 与 WWT 批量插入共用，禁止复制调色板。

### 3.2 时域上限

```python
MAX_VIEWS = 12                 # analysis + default
TIME_DOMAIN_MAX_VIEWS = 24     # time-domain workspace only
```

`MainWindow` 的 `view_manager` 传 `max_views=TIME_DOMAIN_MAX_VIEWS`。ChartStack 四个分析 manager 继续 `MAX_VIEWS`。

### 3.3 Native layout 换算

`plan_native_layout(items, *, metrics: GridMetrics | None = None)`。

- `metrics is None` 时用 canonical 1× 网格：`column_width=GRID_MIN_COLUMN_WIDTH`、`row_height=GRID_ROW_HEIGHT`、既有 gutter/padding/resolution。禁止用当前窗口宽度去拉大 `column_width`，否则同一 WWT 在不同窗口宽度下 GridRect 会漂。
- 调用方可传入当前 Board 的 1× `GridMetrics`（仍是 min-column 1×，不是弹性缩放后的 screen metrics）。
- 算法：
  1. 过滤非法 rect；完全重叠（既有 `_OVERLAP_EPS`）进 unplaced + `exact_overlap`。
  2. 原点：`origin_x = min(x)`，`origin_top = min(y - height)`（WinWert Y 向上）。
  3. `px_per_mm = (GRID_COLUMNS * pitch_x) / total_width_mm`，横纵共用。
  4. 像素边：`left_px = (x - origin_x) * px_per_mm` 等；网格边：`round(px / pitch)`，横用 `pitch_x`、纵用 `pitch_y`。
  5. `clamp_grid_rect`。量化后与已接受卡片网格重叠 → unplaced + `quantized_collision`（保持现有 code）。
- 不变量：对每个已放置卡片，用同一 `metrics` 做 `rect_to_pixels` 后的渲染宽高比，相对毫米宽高比的误差不超过一个微网格（任一边 ±1 cell 的像素）。

旧调用不传 `metrics`，行为改为新换算（这是本波次故意修正，不是兼容旧 GridRect 字面值）。

### 3.4 投影入口

`UltraViewCoordinator.add_time_views_from_native_layout`：

```python
def add_time_views_from_native_layout(
    self,
    items,
    *,
    board_name: str | None = None,
    dedicated_board: bool = False,
    reuse_empty_board: bool = True,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
```

旧调用（只传 `items`）保持：写入**当前活动** Board，不改名、不新建。

`dedicated_board=True` 时由 workspace controller 在一次事务里选定目标 `board_id`：

1. `reuse_empty_board` 且当前 Board 为空 → 改名、切自由网格、应用布局。
2. 否则 `create_board(name=unique_name)`；失败（已满 20）→ 不修改任何既有 Board，返回稳定 warning code `board_limit`。
3. 把该 Board 设为活动 Board，应用 native plan，注册延迟贴合。

Controller 内部可返回 `(board_id, placed_refs, unplaced_refs, warnings)`；façade 继续返回 `(placed_view_ids, warnings)`。

空 Board 判定与 Board 命名是 controller / `board_ops` 的纯函数，不放进 MainWindow。

### 3.5 延迟贴合

Workspace controller 扩展既有 `_pending_auto_aspect` / `layout_revision`：

- native 投影成功的 **placed** 卡片登记 pending fit；token 记录 `board_id`、`ref`、`inserted_rect`、`layout_revision`、以及「同一次导入」合并标记。
- 预览到达走既有 capture 回调 → `solve_card_fit`，image size 按既有 Card Fit 路径做 DPR 归一化（逻辑像素，不是 device pixels）。
- 该 token 的 `layout_revision` 已变，或卡片跨度/位置已与 `inserted_rect` 不一致 → 丢弃。
- 按源顺序处理：先 Fit 跨度（原点钉住，与手动 Card Fit 相同）；若与**本波次已接受**的 Fit 结果碰撞，则保持该跨度、在安全范围内找曼哈顿距离最近的合法 origin；同距选更小的 `(row, column)`。
- 不回头缩小已接受卡片。
- `merge_add=True` 时并入导入那条 undo；不 `set_active` 卡片、不 fit-camera、不切 Board。
- `clear()` / 项目恢复 / `shutdown` 继续清 `_pending_auto_aspect` 与 `_layout_revision`。

### 3.6 WWT 协调器

- `available = view_manager.max_views - len(views) + reusable`，禁止再引用模块级 12。
- 确认后 `insert_states`，再按最终 index 写 `tab_color = default_view_tab_color(idx)`。
- `created >= 2` 才调用投影，并传 `dedicated_board=True`、`board_name=stem`。
- `created <= 1` 不调用投影。
- 确认文案用**将创建数量** `min(kept, available)`，与 D8 一致。
- `board_limit` 进入 outcome warnings，UI toast 说明「时域 View 已创建，Board 已满 20 个，未加入 UltraView；请删除一个 Board 后手动加入」。

## 4. 文案

- Hints：`file.wwt_native_layout` 仍 ≤18 全宽；可改为「WWT 多窗口进独立 Board」，不得声称像素级一致。
- QuickRef「时域 View」：最多 24 个；Alt+1…9 行改为第 10–24 走标签栏或 `»`。
- QuickRef WWT 行：多窗口同步到以文件名命名的独立 Board；单窗口只生成时域 View。
- 时域帮助与用户指南当前产品面改为 24；四个分析区仍写 12。不改写 v7.6/v7.7 历史 release notes。
- `AGENTS.md` / `CLAUDE.md` 产品约束：时域 24、分析 12，上限读 manager。

## 5. 非目标

- 不升级项目 schema。
- 不改 WinWert 曲线 RGB 合同。
- 不改手动 Card Fit / 用户拖放语义。
- 不把单窗口 WWT 自动放进 UltraView。
- 不清理工作区里已有的删除/未跟踪无关文件。
