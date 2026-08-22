# UltraView 稳定性、UI 质量与架构收口 Plan

- 日期：2026-08-22
- 状态：**PARTIAL / OFFSCREEN EXECUTED**
- 说明：Waves 0–5.3 已落地；Wave 6 focused/boundary gate 全绿。Cocoa AXPress / hold 矩阵 / Laser 1×2× 与 full suite / Windows frozen 仍为 `UNVERIFIED`。不得写成 UltraView 已稳定完成。
- 依据 Spec：`docs/analyzer/specs/2026-08-22-ultraview-stability-and-quality-hardening-spec.md`
- 依据 Review：`docs/analyzer/reviews/2026-08-22-ultraview-current-state-comprehensive-review.md`
- 执行原则：先恢复门禁真值，再修 P1/P2，再做小步 seam extraction；不扩作者工具表面

## 0. 执行裁决与优先级

优先级如下：

1. **Wave 0：冻结当前事实并恢复 red gate 的可解释性**；
2. **Wave 1：mixed selection 单事务修复**；
3. **Wave 2：minimap 遮挡与 Pointer 可访问性**；
4. **Wave 3：compact/visual harness 合同修正**；
5. **Wave 4：Cocoa feedback 与 Laser DPR 收口**；
6. **Wave 5：按 owner 小步抽架构 seam**；
7. **Wave 6：稳定快照集成验收**。

禁止做法：

- 不通过扩大 `FROZEN_MUTATION_FUNNEL_EXCEPTIONS` 让结构测试变绿。
- 不把 stale tests 全部删除、skip、xfail 或一键刷新 snapshot。
- 不用新的 timer/`raise_()`/opacity/repaint 补丁处理反馈 surface。
- 不隐藏 Pointer 以恢复 800×560 旧断言。
- 不把 minimap 永久置顶并仅靠透明度减轻遮挡。
- 不在这一轮拆完整 Page/Widgets/Coordinator。

## 1. Wave 0 — 冻结事实与门禁分类

### Task 0.1：记录执行快照

**动作**

1. 记录 `HEAD`、branch、`git status --short`、UltraView relevant diff stat。
2. 保留用户当前 Pointer/Laser 未提交改动；任何 worker/agent 均不得回退或覆盖。
3. 检查是否已有 pytest full gate 在同一 checkout 运行；本计划不并发 full suite。
4. 将临时 probe、截图、录屏放 `.state/ultraview-hardening-2026-08-22/`。

**出口**

- 有一个可复现 worktree fingerprint；后续测试结果能映射到同一 source snapshot。

### Task 0.2：把六个红测试逐项标注为 product / architecture / stale contract

**文件**

- `tests/ui/test_ultraview_sticky_slice.py`
- `tests/ui/test_ultraview_structure.py`
- `tests/ui/test_ultraview_viewport.py`
- `tests/test_verify_ultraview_visuals.py`
- `tools/verify_ultraview_visuals.py`

**分类结果必须冻结**

| 失败 | 分类 | 本计划去向 |
|---|---|---|
| mixed mutation funnel | product + architecture | Wave 1 |
| `_BoardShim` model field write | architecture expression | Wave 1 |
| 800×560 Pointer absent | stale product contract | Wave 3 |
| 2× map 314 px | stale formula | Wave 0.3 |
| schema-3 grid warning | invalid legacy fixture | Wave 0.3 |
| rail/panel visual geometry | stale metric +需新增遮挡事实 | Wave 3 |

### Task 0.3：先修两个确定失真的纯测试夹具

**动作**

1. exact-map expected 使用 micro pitch：`(column_width + gutter) / resolution`。
2. schema-3 fixture 明确写 legacy 12 columns；新增不一致 schema/payload 应 warning 的用例。
3. 不改生产代码，不改变 legalizer warning taxonomy。

**聚焦命令**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_viewport.py::test_zoomed_pixel_map_error_does_not_grow_with_the_cell_index \
  tests/ui/test_ultraview_viewport.py::test_legacy_board_viewport_is_ignored_by_payload_legalizer -q
```

**出口**

- 两项用例表达真实 2×/schema-3 语义；不能靠放宽 `<=1 px` 或吞 warning 收绿。

## 2. Wave 1 — Mixed selection 原子事务与结构 funnel

### Task 1.1：先写失败测试

**文件所有者**

- `tests/ui/test_ultraview_author_multiselect.py`
- 新的纯逻辑用例可放 `tests/ui/test_ultraview_author_state.py`
- `tests/ui/test_ultraview_structure.py` 只保留 shrink-only guard，不先改 expected

**新增用例**

1. card+author 正常 nudge：两者都移动，一条 history。
2. card collision：两者都不移动，无 history，一次 warning。
3. card 越 safety bound：两者都不移动。
4. locked + movable author mixed selection：affected count 与产品决定一致，不静默全成功。
5. unknown author 保留；connector endpoint 不悬空。
6. mixed delete/undo/redo/save-reopen 恢复 card tray membership 与 author payload。
7. repeated key nudge 仍按每个 key intent 形成确定 history，不把 rejected intent 写入。

**红门**

- 至少 collision/越界用例必须先在当前实现稳定失败，证明测试命中 review 缺陷。

### Task 1.2：引入纯 `SelectionMutationPlan`

**建议 owner**

- 纯 DTO/Board placement planning：`mf4_analyzer/ui/ultraview_state.py` 或新的 UI-neutral
  `mf4_analyzer/ui/ultraview_edits.py`。
- author patch planning：现有 `author_edits.py` 只接收纯 Board facts，不写 live Board。
- commit/history：Coordinator 中一个明确的 selection mutation funnel。

**实现约束**

1. planning 不修改 live Board。
2. card validation 和 author patches 都成功后，再生成一个 `BoardEditEntry`。
3. 应用 entry 后只执行一次 mark-dirty、history、layout revision、projection refresh。
4. warnings 通过现有 toast taxonomy；不得丢弃 `set_free_grid_rects()` 返回值。
5. `_BoardShim` 替换为 neutral facts/DTO 或纯参数；不通过 AST guard 特判 class 名。

### Task 1.3：把 direct mutators 收回 funnel

**目标方法**

- `_on_selection_nudge`
- `_on_selection_delete`
- `_on_auto_arrange_free_grid`

**出口**

- `test_model_fields_written_only_in_state_module` 通过；
- `test_mutations_end_in_funnel` 通过；
- frozen exception set 不扩大；
- auto-arrange、mixed nudge/delete 的用户文案和 history 未回归。

**聚焦命令**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_author_multiselect.py \
  tests/ui/test_ultraview_author_state.py \
  tests/ui/test_ultraview_board_history.py \
  tests/ui/test_ultraview_placement_history.py \
  tests/ui/test_ultraview_structure.py -q
```

## 3. Wave 2 — Minimap 避让与 Pointer Accessibility

### Task 2.1：冻结 minimap 遮挡测试

**文件**

- `mf4_analyzer/ui/chart_stack/ultraview/floating_layout.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `tests/ui/test_ultraview_floating_layout.py`
- `tests/ui/test_ultraview_selection_toolbar_contract.py`
- `tools/verify_ultraview_visuals.py`

**测试事实**

1. 构造右下 card selection，记录 selection bounds/handles 与 minimap rect。
2. 当前实现先证明 intersection 为 true 或 minimap 未折叠。
3. 修复后要求：minimap moved/folded/hidden，且 handles/toolbar rect 均不相交。
4. gesture active 时 minimap hidden/folded；release 后稳定恢复，不随 pointer sample 抖动。

### Task 2.2：实现 Qt-free candidate policy

**建议**

- 在 `floating_layout.py` 增加输入为 Rect facts 的 minimap placement policy；Page 只负责收集 Qt geometry
  并投影结果。
- 候选优先右下、右上；不得侵入左上 Board Island。无安全候选时返回 `None`，复用 overview action。
- fingerprint 由 stage/safe/chrome/selection/gesture 构成；只在 fingerprint 变化时计算。

**停止条件**

- 若方案需要读取 card preview 像素、每帧遍历全部 QWidget 或写入项目状态，停止并改设计。

### Task 2.3：统一 Pointer 标准 activation

**文件**

- `mf4_analyzer/ui/chart_stack/ultraview/chrome.py`
- `tests/ui/test_ultraview_author_chrome.py`

**动作**

1. 先增加 `button.click()` 只产生一次 `pointer_menu_requested` 的失败用例。
2. Mouse、Space/Enter、standard click 进入同一 handler；防止 mouse release + clicked 双发。
3. 检查 accessible name/role/open property。
4. Page 级用例证明 popup 打开但 selection/pointer mode/history 不变。

**Cocoa 验收**

- 使用 macOS Accessibility Press 打开/关闭 popup；物理点击与键盘行为一致。

## 4. Wave 3 — Compact rail 与视觉 harness 真值恢复

### Task 3.1：重写 800×560 合同，不隐藏 Pointer

**动作**

1. `test_rail_and_sticky_popover_fit_800x560` 改为 Pointer/Sticky/Text/Shapes/Draw 全入口可见、rect 完整。
2. 断言 rail 实际高度不超过 available band；不强制等于 unconstrained `sizeHint`。
3. 如按钮确实被裁切，优先减少 compact group gap/divider clear 或引入明确的 overflow；不缩小 hit target。
4. 检查 badge、底部 spinner、Status Island 的像素间隔。

### Task 3.2：修正大型 Layout panel 锚定指标

**动作**

1. 保留八个模板两列四行、当前态、无历史按钮、Navigation 不被覆盖。
2. trigger center 应落在 overlay 的 visible y span；overlay 与 rail 保持水平邻接。
3. 若 panel 高于可居中空间，允许 safe-rect clamp；记录 clamp reason，而非要求 center error ≤44。
4. 只有几何事实全过后才更新 contact sheet/snapshot。

### Task 3.3：把 minimap/Pointer 状态加入 visual harness

**新增 shots/facts**

- `pointer_popup_800`
- `pointer_popup_1280`
- `selected_bottom_right_with_minimap`
- `selected_shape_format_picker`
- `laser_cursor` 只记录 Qt facts；native cursor 另走 Cocoa evidence

**聚焦命令**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_sticky_slice.py \
  tests/ui/test_ultraview_author_chrome.py \
  tests/ui/test_ultraview_floating_layout.py \
  tests/ui/test_ultraview_selection_toolbar_contract.py \
  tests/test_verify_ultraview_visuals.py -q
```

## 5. Wave 4 — Cocoa feedback 与 Laser DPR

### Task 4.1：补齐 feedback observation seam

**保留现有设计**

- latest pointer sample；
- candidate fingerprint；
- viewport-sized feedback surface；
- viewport-change-only reprojection。

**只补可观测事实**

- planner call count；
- frame present count；
- surface paint count；
- gesture id/generation/layout revision；
- release/cancel 后 timer/grab/frame 是否清空。

不得把 diagnostics 写入 persisted state，也不得在 hot path 逐事件日志刷屏。

### Task 4.2：真实 Cocoa 手势矩阵

在 `testdoc/222.tlproj` 执行：

1. card click/release；
2. move：hold 0/100/500/2000 ms；
3. resize east/south-east：同样 hold；
4. adjacent collision：blue regular target + amber warning；
5. edge-pan 后静止；
6. release 与 Esc cancel；
7. Sticky/Shape geometry，确保共享 surface 没有覆盖编辑器。

**通过标准**

- target、handles、badge 从越过阈值到 release 全程可见；
- stationary hold 不重复 planner/present；
- chart preview 不白屏；
- release 后真实 card、selection 和 toolbar 一次 settle，无双闪。

### Task 4.3：Laser cursor 按 DPR 缓存

**文件**

- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py` 或新的小型 cursor helper；
- `tests/ui/test_ultraview_author_tools.py`。

**动作**

1. 先冻结 1×/2× pixmap backing、logical hotspot 和 cache identity 测试。
2. cache key 包含 DPR/size/palette version；生成 backing pixmap 后设置 DPR。
3. screen change/reset/presentation/leave FreeGrid 对称重设或 unset cursor。
4. Cocoa 观察 1×/2×；若只有 Retina 设备，1× 标记 `UNAVAILABLE`，不得假造。

## 6. Wave 5 — 小步架构收口

### Task 5.1：冻结依赖图和 public seam

**动作**

1. 记录 Coordinator/Page/Widgets 当前调用点、signals、public imports、monkeypatch seams。
2. 为要移动的 owner 先写 parity/boundary tests。
3. 每次只移动一个责任，不以行数为拆分理由。

### Task 5.2：完成 SelectionMutationService 提取

Wave 1 若先在 Coordinator 内闭环，此任务再把纯 plan/commit owner 提出；不得重新设计内部算法。

**出口**

- Coordinator 不直接组合 card placement 与 author patches；
- structure guard 缩小或保持，不扩大；
- tests/harness 不复制生产 mutation 流程，改用同一 public seam。

### Task 5.3：完成 FloatingChromePolicy 提取

**目标**

- Page 收集 facts；policy 计算 rail/panel/minimap/selection toolbar 的安全 rect；CanvasHost 应用 stacking。
- Page 不再读取 toolbar `_body_layout` 或 FreeGrid `_author_geometry_session`；改为 public
  `interaction_facts()` / `layout_hint()`。

### Task 5.4：评估 capture coordinator 分离

按以下边界分离，且一次只做一个：

1. `UltraViewCaptureCoordinator`：PreviewStore、digest、capture timers、sidecar；
2. `UltraViewWorkspaceController`：workspace intents、history、dirty、Board lifecycle；
3. existing `UltraViewCoordinator` 暂作 compatibility facade/aggregator。

**停止条件**

- 如果需要新增 MainWindow state writes、改变 project payload、打破 public imports 或同时修改多个 manager，
  本轮停止，另写 refactor spec。

**边界门禁**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_structure.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py -q
```

## 7. Wave 6 — 稳定快照集成验收

### Task 6.1：UltraView focused owner gate

在 source snapshot 稳定后运行一次：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_*.py \
  tests/ui_kit/test_ultraview_style.py \
  tests/test_verify_ultraview_visuals.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py -q
```

**要求**

- 运行前后记录 `HEAD` 与 relevant dirty scope；期间相关文件变化则结果为 `UNVERIFIED`。
- 六个历史失败必须全部有明确关闭记录。

### Task 6.2：真实前台验收

至少覆盖：

- 800×560、1280×720；
- Pointer popup mouse/key/AXPress；
- Mouse/Laser selection/drag/resize；
- mixed selection nudge success/reject/undo；
- minimap 右下冲突；
- move/resize/collision/edge-pan stationary hold；
- project reset、Board switch、presentation enter/exit。

### Task 6.3：项目 full gate（仅在 merge/release 需要时）

本计划不在每一波跑 full suite。只有稳定 integration milestone 且准备 merge/release 时执行一次：

1. 主 suite：`--ignore=tests/acquisition_ui`；
2. 主 suite 完成后，新进程单独运行 `tests/acquisition_ui`；
3. 两者绝不并发；
4. abnormal exit、crash、timeout 或运行中 source 变化均为 `UNVERIFIED`。

Windows Full/Lite frozen 与 macOS Cocoa 是独立 gate；未执行就明确写 `UNVERIFIED`。

## 8. 提交与回退纪律

建议提交顺序：

1. `test(ultraview): repair microgrid and legacy fixtures`
2. `fix(ultraview): make mixed selection edits atomic`
3. `fix(ultraview): keep minimap off active selection chrome`
4. `fix(ultraview): route pointer accessibility activation`
5. `test(ultraview): restore compact and visual harness contracts`
6. `fix(ultraview): make laser cursor dpr aware`
7. `refactor(ultraview): extract one declared owner seam`

规则：

- 每个提交只 stage 本任务文件；保留用户其他 dirty worktree。
- 产品行为、测试和最少必要文档可同 commit；大批原始截图不与产品 commit 混装。
- 前台证据默认 `.state/`；若需 durable 入库，先写 README、选择最少代表图，再独立 docs commit。
- 任一 wave 可独立回退；不得依赖之后的“大整理”才能恢复可运行状态。

## 9. 完成检查表

- [x] mixed nudge/delete 不再部分提交
- [x] structure mutation funnel 与 model-field guard 全绿且白名单未扩大
- [x] minimap 不遮挡 active card/author handles、toolbar、editor（offscreen；Cocoa 前台 `UNVERIFIED`）
- [x] Pointer mouse/key/standard click 行为一致（AXPress Cocoa `UNVERIFIED`）
- [x] 800×560 保留全入口且无裁切
- [x] Layout panel 八项可达、锚定合同可满足
- [x] 2× micro-grid 与真实 schema-3 tests 表达正确语义
- [ ] move/resize Cocoa hold 矩阵通过 — **UNAVAILABLE**
- [x] Laser cursor DPR/跨屏/reset 生命周期通过（offscreen；Cocoa 1×/2× `UNAVAILABLE`）
- [x] Coordinator/Page/Widgets 只完成已声明的小步 seam，没有大爆炸重构（5.4 capture split STOP）
- [x] focused/boundary gate 在稳定 snapshot 上全绿（1315 passed, 1 skipped；HEAD `b71a118d`）
- [x] full suite/Windows frozen 若未执行，明确标记 `UNVERIFIED`

完成上述检查前，状态保持 **PARTIAL / NEEDS REVISION**；不得写成“UltraView 已稳定完成”。
