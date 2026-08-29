# WWT 多 Board、排版贴合与 24 时域 View — 实施计划

- 日期：2026-08-29
- 状态：已实施（offscreen 聚焦+边界通过；Cocoa 前台 UNVERIFIED）
- 规格：[`2026-08-29-wwt-multi-board-layout-fit-and-24-views-spec.md`](../specs/2026-08-29-wwt-multi-board-layout-fit-and-24-views-spec.md)
- 基线：`377c20d45fe3d1fa4ce6e19a19a84a8ff330b082`
- 验证：先跑各 Task 聚焦用例，再跑 import / state / backref 边界。全套两段门禁只在稳定集成点跑一次，由协调者独占。

T1 / T2 / T3 / T4 文件所有权不相交，可并行。T5 集成由协调者在四路落地后执行。

## Task 1 — 时域 24 View 与默认色

**Owner 文件**（只改这些）：

- `mf4_analyzer/ui/view_state.py`
- `mf4_analyzer/ui/main_window/window.py`（`ViewManager(..., max_views=TIME_DOMAIN_MAX_VIEWS)` 与注释）
- `mf4_analyzer/ui/main_window/_frf_mixin.py`（「已达 12 个」改为读 `view_manager.max_views`）
- `AGENTS.md`、`CLAUDE.md` 中时域/分析 View 上限那一句
- 测试：`tests/ui/test_view_manager.py`、`tests/ui/test_view_tabbar.py`、`tests/ui/test_chart_stack.py`、`tests/ui/test_view_state.py`、`tests/ui/test_project_session.py`（24 Views 保存重开；分析区仍 12）

**不要改**：WWT coordinator、UltraView、hints/help。

**步骤**

1. 增加 `TIME_DOMAIN_MAX_VIEWS = 24`，保留 `MAX_VIEWS = 12`。
2. 抽出 `default_view_tab_color(index) -> str`，`_make` 使用它。13–24 循环 12 色。前 6 色顺序不得改。
3. 时间 ViewManager 用 24；分析 manager 不动。
4. 测试：第 24 个可建、第 25 个拒绝；窄窗口溢出 `»`；活动标签可见；重排/复制/删除；24 Views 保存重开；四个分析区仍 12；`default_view_tab_color` 与 `_make` 一致。

**聚焦**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_manager.py tests/ui/test_view_tabbar.py tests/ui/test_chart_stack.py \
  tests/ui/test_view_state.py tests/ui/test_project_session.py -q
```

## Task 2 — 毫米 → 非等距微网格

**Owner 文件**

- `mf4_analyzer/ultraview_core/native_layout.py`
- `tests/ui/test_ultraview_native_layout.py`（更新旧 GridRect 字面值 + 新宽高比/重叠/延迟几何用例中属于纯 plan 的部分）

**不要改**：coordinator、WWT、view_state、docs。

**步骤**

1. `plan_native_layout(items, *, metrics=None)`。默认 canonical 1× `GridMetrics`（`GRID_MIN_COLUMN_WIDTH` / `GRID_ROW_HEIGHT`），不要用 viewport 拉宽 column。
2. 按规格 §3.3 换算。保留相对位置、源顺序、精确重叠 → unplaced。
3. 用 `rect_to_pixels` 断言渲染宽高比相对毫米宽高比只有微网格量化误差。覆盖宽、窄、上下排布、精确重叠。
4. 更新 UCAN 与既有 coordinator 测试里依赖旧等距 scale 的 GridRect 字面值。

**聚焦**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_ultraview_native_layout.py -q
```

## Task 3 — Board 分配、确认框、延迟 Card Fit

**Owner 文件**

- `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- `mf4_analyzer/ultraview_core/board_ops.py`（仅空板判定 / unique name，若需要纯函数）
- `mf4_analyzer/ui/wwt_view_import.py`（删除固定 `#2d7ff9`；颜色在 coordinator 按最终 index 写入）
- 测试：`tests/ui/test_wwt_import_flow.py`、新建 `tests/ui/test_wwt_board_projection.py`（真实 seam，禁止 `lambda items:` 替换投影）、必要时 `tests/ui/test_wwt_view_import.py` 颜色、`tests/ui/test_ultraview_card_fit.py` 不改手动语义

**不要改**：`view_state.py` 的常量（消费 `default_view_tab_color` / `TIME_DOMAIN_MAX_VIEWS`）、`native_layout.py` 的换算公式、hints/help。

**步骤**

1. 扩展 `add_time_views_from_native_layout` 仅限关键字参数；旧调用写活动 Board。
2. dedicated 路径：空板复用或 `create_board`；满 20 返回 `board_limit`、零 Board 变异。
3. `offer_layout`：容量读 `view_manager.max_views`；`created>=2` 才投影；确认文案 D8；stem 作 Board 名。
4. 最终 index 着色；曲线 `state.colors` 仍是 WinWert RGB。
5. 投影后登记 pending Card Fit；预览到达按规格 D10–D12。Retina DPR 与预览延迟到达要有测试。
6. Owner 集成走真实 WWT→UltraView seam（lesson `codex-wwt-ultraview-real-boundary-test`）。合成 WWT 用 `tests/_helpers/wwt_factory.py`；客户样本 skip-guard。

**合成覆盖**：单 View 不改 Board；≥2 复用空板；第二个多 View WWT 新建；拒绝排版；重名 ` (2)`；View 上限 / Board 上限均无部分污染。

**聚焦**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_wwt_import_flow.py tests/ui/test_wwt_board_projection.py \
  tests/ui/test_wwt_view_import.py tests/ui/test_ultraview_card_fit.py -q
```

## Task 4 — 发现性文案与帮助

**Owner 文件**

- `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`
- `tests/ui/test_hints.py`、`tests/ui/test_quickref.py`
- `mf4_analyzer/help/TraceLab-使用说明.html`、`mf4_analyzer/help/time-domain-guide.html`
- `docs/analyzer/user-guide/user-guide.html`
- 若 `tests/test_help_content.py` 钉死「12 个 View」的时域文案则同步；不要改 UltraView「12 列」网格文案，也不要改 v7.6/v7.7 release notes。

**不要改**：运行时代码。Hints ≤18 全宽。

**聚焦**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_hints.py tests/ui/test_quickref.py tests/test_help_content.py -q
```

## Task 5 — 集成（协调者，四路完成之后）

1. 解决并行落地冲突。
2. 连续跑 WWT import、native layout、Card Fit、ViewManager/ViewTabBar、project-session。
3. 边界：`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_pg_canvas_backref_invariants.py`。
4. 不跑全套，除非用户要求。Cocoa 前台验收标 UNVERIFIED。

## 并行纪律

- 工作区已有 `D` / `??` 文件与本任务无关：不修改、不清理、不纳入提交。
- 不新增 MainWindow 多文件写属性。
- 不 `except Exception: pass`。
- 测试命令：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`
- 不要提交 git（协调者稍后统一提交）。
