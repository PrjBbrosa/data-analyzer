# WWT 导入保真回归修复与 UltraView 投影加固计划

- 日期：2026-08-29
- 状态：已实施（`wwt-hardening-int` @ `14ce32bc`）
- 基线：`main@4247fb78`
- 对应规格：
  [`2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md`](../specs/2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md)
- 前置文档（不改写）：
  [`2026-08-28-wwt-winwert-layout-import-spec.md`](../specs/2026-08-28-wwt-winwert-layout-import-spec.md) ·
  [`2026-08-28-wwt-import-correctness-followup-plan.md`](2026-08-28-wwt-import-correctness-followup-plan.md)

> 审查结论：`4247fb78` 的正确性修复（record store 所有权、claimed 语义、诊断
> 分级、tick 防护）全部有效，**保持不动**。本计划只修它同时引入的产品面回归
> （record-only 曲线、WinWert 颜色、静默丢窗）与三层遗留边界（native tick
> 归属/配对、UltraView 投影不变量、IO 解析防线）。问题分级与实测证据见规格 §2。

## 1. 问题 → 任务映射

| 级别 | 问题（规格章节） | 任务 |
| --- | --- | --- |
| P1 | record-only Y 曲线/整窗静默丢弃（§2.1） | T1 |
| P1 | 投影压既有卡、重开漂移；template 丢卡（§2.4-1/2） | T4 |
| P2 | 共享轴 native tick 被先到者抢占（§2.2） | T2 |
| P2 | 恢复路径轴/tick 按位置 zip 配对（§2.3） | T2 |
| P2 | WinWert 颜色被丢弃（§1、规格 D3） | T3 |
| P2 | membership 202/200、无效 rect 静默消失、原始码 toast（§2.4-3/4/5） | T4 |
| P2 | Zeit 巨大声明点数可触发数十 GB 分配（§2.5-1） | T5 |
| P3 | 哨兵缩放后检测 / 公式截断 / 部分非有限 / aux Pars 不可见 / cohort 误拒 / `_as_1d`（§2.5-2..7） | T5 |
| P3 | 死 meta、宽泛 except、返回值语义、overlap 计数文案、`logger` 缺失（§2.6） | T6 |

依赖：T0 →（T1 → T2 → T3）与 T4、T5 可并行 → T6 → T7。
T1/T2/T3 共享 `wwt_view_import.py` 与渲染链，必须串行；T4（ultraview_core）、
T5（io）owner 文件不相交，可由并行执行者认领，但只跑各自聚焦测试，全套门禁归
T7 协调者独占（CLAUDE.md 测试门禁规则）。

## 2. 任务

### Task 0 — 夹具扩展与红测先行

**文件**：`tests/_helpers/wwt_factory.py`、各 owner 测试文件（只加测试）。

**步骤**

1. 记录 HEAD 与 dirty scope；跑受影响聚焦用例作改前基线（不跑全套）。
2. 扩展合成 profile：
   - 共享轴 profile：未选中评价线（tick=0/grid=0）排在 selected owner **之前**；
   - 无效 rect profile：`right == left` 的畸形显示块；
   - 巨大 `Zeit n` profile（仅头部，声明 ~2×10⁹ 点）；
   - 哨兵 × 非单位 scale 的 `Real` 记录 profile。
   现有 `measurement_plus_record_only_tolerance` / `multi_window_overlap_and_formula`
   复用，不重做。
3. 加入红测（修复前按预期语义失败）：
   - record-only tolerance 生成绑定并渲染、颜色为 WinWert RGB；
   - 整窗 record-only 的窗口生成 View；确认框 N 计文件真实窗口数；
   - 共享轴 `native_y` 事实等于 owner 的 tick/grid；
   - 非空 free-grid / template 看板投影的不变量（见 T4 验收）；
   - membership 200+2 不越界；无效 rect ref 进 unplaced；
   - 巨大 Zeit n 拒绝且不分配。
4. **反转旧合同测试**（同一提交内完成，不留并存断言）：
   `test_measurement_proposal_drops_record_only_tolerance_y`、
   `test_multi_window_proposals_omit_record_only_y_window`、
   `test_native_rows_use_navigator_color_and_exclude_record_only_y`、
   `test_aux_only_overlap_is_omitted_without_yellow_toast`、
   `test_yp_bindings_plot_only_registered_y_when_customer_sample_present`
   等按规格 D1/D2/D3 改写断言。

**接受条件**：干净 checkout 上红测因语义失败而非夹具/Qt 生命周期失败；
真实样本断言全部 skip-guarded。

### Task 1 — 恢复 record-only 曲线与丢弃可观察（P1）

**文件**：`mf4_analyzer/ui/wwt_view_import.py`、
`mf4_analyzer/ui/main_window/wwt_import_coordinator.py`；
测试：`tests/ui/test_wwt_view_import.py`、`tests/ui/test_wwt_import_flow.py`、
`tests/ui/test_wwt_native_render.py`。

**步骤**

1. 删除 `build_wwt_view_proposals` 的 record-only `continue`
   （`wwt_view_import.py:275`），record-only 行按规格 D1 生成绑定：
   不进 `checked`/`ylims`，参与 D6 轴规划。
2. 真实降级（unknown record、全行不可解析）改产 `dropped_curve` /
   `dropped_window` 稳定 code，进入 `collect_wwt_import_issues` 聚合。
3. `layout_dialog_text` 的 N 改为文件中结构合法且含可见 Y 的窗口数；
   proposals < N 时正文写差额；overlap 文案用真实计数、列出全部重叠对
   （规格 D2 与 §2.4-6）。
4. 确认渲染链无需改动：`bound_time_plot_rows()` 的 record 路径已支持
   （既有测试守护），只做集成断言。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_view_import.py tests/ui/test_wwt_import_flow.py tests/ui/test_time_curve_bindings.py -q
```

**接受条件**：本机真实样本 smoke 达到规格 §6.2 字面值
（YP 2 曲线、D6-CSER 7 proposals、EO3 7 proposals、NLTNP 4 曲线）；
所有丢弃均有 code，无新的静默 `continue`。

### Task 2 — native tick 归属与身份配对（P2）

**文件**：`mf4_analyzer/ui/wwt_view_import.py`、
`mf4_analyzer/ui/main_window/_view_mixin.py`、
`mf4_analyzer/ui/time_curve_bindings.py`（死 meta 处置）、
必要时 `mf4_analyzer/ui/pg_canvas/`（axis_id → AxisItem 查找暴露，走既有
backref 声明，不新增未声明写穿）；
测试：`tests/ui/test_wwt_native_render.py`、`tests/ui/test_wwt_view_import.py`、
`tests/ui/test_pg_timedomain_canvas.py`（回归护栏）。

**步骤**

1. `native_y[axis_id]` 只由 selected owner 行写入（删除全同 if/elif）。
2. `_view_mixin` 改按 axis_id 配对：native_ticks y 表键 = axis_id，
   轴槽侧按 axis_group 反查 AxisItem；任一侧缺失走 adaptive（§17.5
   all-or-nothing 不变）。禁止继续位置 zip。
3. 处置死 meta（规格 D4 第三条）：`native_axis` 无消费者则删；
   `native_xy_full_range` 接入 View plot issue 详情或删除，二选一。
4. 回归护栏：View restore 顺序（xlim → ylims → ticks → settle）与
   `TestViewRestoreSettlement` / `TestDiscreteSettle` 不动。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_native_render.py tests/ui/test_wwt_view_import.py tests/ui/test_pg_timedomain_canvas.py -q
```

**接受条件**：共享轴事实 = owner；取消勾选一条 channel-backed Y 后其余轴
tick 仍命中正确轴；无半应用轴。

### Task 3 — WinWert 颜色契约（P2）

**文件**：`mf4_analyzer/ui/wwt_view_import.py`、必要时
`mf4_analyzer/ui/main_window/window.py`（`channel_colors` 覆盖顺序）；
测试：`tests/ui/test_time_curve_bindings.py`、`tests/ui/test_wwt_view_import.py`。

**步骤**

1. `binding.color` 恢复 `#rrggbb`（恢复被删除的 `_rgb_hex`）。
2. record-only 行直接用 binding 色渲染（现有
   `test_record_only_binding_keeps_compatibility_color` 改断言 WinWert 色）。
3. channel-backed 行把 WinWert 色种子进**新建 View 的** `ViewState.colors`；
   先用测试证明该写入不改其他 View 与全局 swatch（`4247fb78` 注释声称的
   污染路径需实测）。若证实污染：保留 record-only 侧，channel-backed 侧记录
   偏差回写规格 D3，不静默。
4. 用户 Navigator 改色仍覆盖（`channel_colors` 优先级不变）。

**聚焦验证**：同 T1 命令 + `tests/ui/test_view_channel_scope.py`。

**接受条件**：YP smoke 中 `Tol_oben` 为红、测量线为 WinWert 深蓝；
改色/切 View/save-reopen 后颜色行为与普通 View 一致。

### Task 4 — UltraView 投影不变量与 warning 出口（P1+P2）

**文件**：`mf4_analyzer/ultraview_core/board_ops.py`、
`mf4_analyzer/ultraview_core/native_layout.py`、
`mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`、
`mf4_analyzer/ui/main_window/wwt_import_coordinator.py`（消费返回值）；
测试：`tests/ui/test_ultraview_native_layout.py`、
`tests/ui/test_wwt_import_flow.py`、`tests/ui/test_ultraview_compatibility.py`。

**步骤**

1. `apply_native_layout`：placed 项对 `board.free_grid` 既有卡做
   `_grid_overlaps` 检查，冲突进 unplaced + warning，不重排既有卡。
2. template 模式先 `template_to_free_grid(board)` 再投影。
3. membership 触顶改「warning + `continue`」，对齐 `add_ref`；断言任何路径
   membership ≤ 200。
4. `native_layout`：无效 rect 的 ref 进 unplaced + `invalid_rect: N` warning，
   与全无效分支一致。
5. warning 出口单点化：`apply_native_layout_plan` 返回本次放置结果与 warnings，
   不再直接 toast 本路径原始码；coordinator 消费返回值并入 import summary，
   `_SILENT_CODES` 生效；placed 触顶复用 `grid_full` 文案或补映射。
6. `apply_native_layout_plan` 返回值改为本次 `plan.placed` 实际落位 ref；
   同步 `test_ultraview_compatibility.py` 冻结清单说明。
7. 集成测试至少一条走真实投影 seam 且捕获/断言 items（lesson
   `codex-wwt-ultraview-real-boundary-test`）；现有 `lambda items: ()` stub
   改为捕获断言。
8. 顺手修同文件 `logger` 未定义（§2.6-4，单独小 commit 注明先于本范围引入）。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_native_layout.py tests/ui/test_wwt_import_flow.py tests/ui/test_ultraview_compatibility.py tests/ui/test_ultraview_structure.py -q
```

**接受条件**：非空/template 看板投影后 save→reopen 布局逐项一致；
UCAN smoke 导入不再弹 `exact_overlap: 7 -> 6` 原始码；两 cap 触顶各只有
一条中文 warning 且状态不越界。

### Task 5 — IO 解析防线（P2+P3）

**文件**：`mf4_analyzer/io/wwt_document.py`、`mf4_analyzer/io/wwt_formula.py`；
测试：`tests/test_wwt_document.py`、`tests/test_wwt_format.py`。

**步骤**（细则见规格 D6）

1. `Zeit` 物化前校验声明点数；超限走既有截断错误路径。测试断言拒绝且不
   触发大分配（可 monkeypatch `np.arange` 计数）。
2. 哨兵检测移到缩放前 raw 域。
3. `Pars` 公式要求 NUL 终止；否则 `unsupported_formula`。
4. 部分非有限追加 `formula_nonfinite_values` 诊断（`errstate` 保持 ignore）。
5. `_as_1d` 改抛 `WwtFormulaError`。
6. 辅助 cohort 已物化 `Pars` 进 `wwt_auxiliary_records`。
7. 公式 cohort 判据对齐分组键 `(declared_n, dt, t0)`。
8. 补 §2.7 IO 盲区：IO 层 `unknown_record`、load 路径公式失败端到端、
   AST 白名单参数化（Subscript/Lambda/keyword/Pow/comprehension/字符串）、
   Pars 重名改名、`parse_wwt_document` store 附着、尾块 `count==0/>4096`。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_wwt_document.py tests/test_wwt_display.py tests/test_wwt_format.py -q
```

**接受条件**：全部新边界用例通过；真实样本解析结果（groups/records/windows
计数与锚点值）与改前一致。

### Task 6 — 卫生清理（P3）

**文件**：`mf4_analyzer/ui/main_window/window.py`、
`mf4_analyzer/ui/pg_canvas/canvas.py`。

1. `window.py` active view 查询的 `except Exception` 收窄为实际可能的异常
   （或改用 manager 的安全访问器）；`canvas.py` logical DPI 的
   `except Exception` 同理。
2. 确认 T2 已处置死 meta；`rg -n 'native_axis' mf4_analyzer` 无残留生产死代码。

**聚焦验证**：T1/T2 的 owner 测试 + 
`tests/ui/test_main_window_state_ownership.py`。

### Task 7 — 集成验证与文档收口（协调者独占）

1. 连续列出全部 WWT/UltraView owner 测试单进程跑（参数不离开再进入同目录）。
2. 边界门禁：backref invariants、import boundaries、state ownership、
   no-lambda、signal no-GUI、batch render boundary、native import boundaries、
   packaging imports。
3. 真实样本 smoke（本机）与规格 §6.2 字面值核对。
4. 全套两段门禁按 CLAUDE.md 规则至多一次；跑前 `pgrep -fl pytest`，
   记录前后 HEAD 与 dirty scope；异常退出记 `UNVERIFIED`，不得由已完成
   部分推断通过。上一轮已知的主套 segfault
   （`test_ultraview_page.py::test_card_drag_near_viewport_edge_starts_page_edge_timer`）
   与两条既有红先比对既有红清单，不算到本轮头上。
5. 真实前台验收（Cocoa）：YP 红色公差线、UCAN 布局、非空看板导入、
   save→reopen 布局一致——逐项执行或显式记 `UNVERIFIED`。
6. 文档收口：本计划状态勾选；规格若有 D3 偏差证据则回写；
   `git diff --check`。UI 交互如有文案变化跑 `/update-hints` 检查
   `ui/hints.py` / `ui/quickref.py`（预期无变化：确认框文案属既有面）。

### Task 7 记录（2026-08-29，协调者，`14ce32bc`）

- 改前 HEAD：`14ce32bc`；工作区干净（testdoc/WWT 为 gitignored symlink）。
  无并发 pytest。
- Owner UI + UI 边界（`tests/ui` 连续）：**627 passed**, 1 deselected, 43.68s。
- IO + 非 UI 边界：**91 passed, 7 skipped**, 4.67s。
- §6.2 本机样本（非 skip）：YP 1 View / 2 曲线（`Tol_oben` `#ff0000` +
  `Druckstückspiel` `#000080`）；D6-CSER 7 proposals；EO3 7 proposals
  （9 窗 − 2 空窗）；NLTNP 4 曲线。
- `git diff --check` 通过；`native_axis` 生产代码无残留。
- `ui/hints.py` / `ui/quickref.py` 无文案变更（确认框仍为既有面）。
- 全套两段门禁与真实前台 Cocoa：**UNVERIFIED**（本轮未跑全套；已知主套
  `test_ultraview_page.py::test_card_drag_near_viewport_edge_starts_page_edge_timer`
  segfault 不记入本轮）。

## 3. 停止条件

1. 恢复 record-only 渲染需要给 record 记录发明时间轴或伪造 Navigator 身份。
2. 颜色种子被证明必然污染全局 swatch 且无 per-view 替代路径（此时按 D3
   记录偏差收窄，不硬做）。
3. 投影碰撞修复需要重排用户既有卡片。
4. 任何修复需要扩大 `test_main_window_state_ownership.py` 白名单或新增
   跨 mixin 散状态。
5. 工作区出现与 owner 文件重叠的并发编辑。

## 4. 完成定义

- [x] T0 红测全部先红后绿；旧合同测试已反转，无并存断言。
- [x] 真实样本 smoke 达到规格 §6.2 字面值（本机）。
- [x] UltraView 五项不变量成立；membership 任何路径 ≤ 200；投影后碰撞卡进
      未放置区（避免保存/重开漂移）。真实前台 save→reopen 记 `UNVERIFIED`。
- [x] 所有丢弃/降级有稳定 code 且单次报告；确认框计数如实。
- [x] IO 防线七项落地；巨大 Zeit n 不再可触发大分配。
- [x] 死 meta 清理、宽泛 except 收窄、`logger` 补齐。
- [x] 聚焦 + 边界门禁绿（owner UI 627 passed；IO+非 UI 边界 91 passed /
      7 skipped）。全套与真实前台 Cocoa 记 `UNVERIFIED`（见 Task 7）。
- [x] `git diff --check` 通过；规格 D3 已回写隔离证据，无偏差。
