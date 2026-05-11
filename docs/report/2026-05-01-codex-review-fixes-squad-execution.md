# Codex Review Fix Squad Execution Report (2026-05-01)

## 背景

针对最近合并的 4 个 PR（#7 COT 迁移 + 坐标轴重构、#8 批处理 axes / FFT-time polish、#9 lightweight publish lesson、#10 图表选项 dialog）做深度 review，输出
`docs/code-reviews/2026-05-01-recent-prs-deep-review.md`，共发现 **3 个 P1 + 4 个 P2**。

## 修复范围与执行

按 planner-executor squad 模式执行，五个 wave 串行，每 wave 通过独立 codex review gate 才能进下一个。

| Wave | Issue | Expert | 文件 | codex gate |
|---|---|---|---|---|
| W1 | P7-L1 Inspector dB↔Linear 切换不重置 z 范围 | pyqt-ui-engineer | `_axis_defaults.py` (NEW), `inspector_sections.py`（仅 OrderContextual + FFTTimeContextual `_on_amp_unit_changed`） | READY（一轮 BLOCK→补 strong RED 测试→READY） |
| W2 | P8-L1 Batch OutputPanel 同源 unit-toggle bug | pyqt-ui-engineer | `output_panel.py`、`test_batch_input_panel.py`（修一条原契约测试） | READY（一轮 BLOCK→澄清 baseline→READY） |
| W3 | P10-L2 ChartOptionsDialog 对数轴非正 limit 静默忽略 | pyqt-ui-engineer | `dialogs.py`（`_apply_axis` + `apply_changes` + `_accept_with_apply` 双入口阻塞 close） | READY（两轮 BLOCK→补 OK 按钮 happy-path 测试 + 复核 spec→READY） |
| W4 | P7-D1 OrderWorker 死代码 | refactor-architect | `main_window.py`（删类 + dispatch + 三 slot），`tests/ui/test_order_worker.py`（整删） | READY |
| W5 | P8-O1 QSS 全局 spinbox selector 污染 | pyqt-ui-engineer | `widgets/compact_spinbox.py`（hoist `no_buttons` helper），`inspector_sections._no_buttons`（thin re-export），`drawers/batch/method_buttons.py`（5 spinbox 走 helper），`style.qss`（selector 全部 `[compact="true"]`） | READY（一轮 sandbox-pytest BLOCK→明确跳过 pytest→READY） |
| Phase 4 终局 | 整体 review | codex | — | **READY TO MERGE** |

## 测试结果

baseline 471 → **489 passed**（净 +18）。

| 增减 | 文件 | 数量 |
|---|---|---|
| +9 | `tests/ui/test_inspector.py`（unit-toggle reset × 2 parametrized + same-unit idempotent + 4 个 strong-RED preset 测试 [legacy dynamic + signal spy 双覆盖]） | 9 |
| +3 | `tests/ui/test_batch_output_panel.py` (NEW)（dB→Linear / Linear→dB / preset round-trip） | 3 |
| +1 | `tests/ui/test_batch_input_panel.py`（reorder 适配 W2 新契约） | 1 |
| +4 | `tests/ui/test_dialogs.py`（log-axis reject / warning blocks close / positive applies / OK button accepts） | 4 |
| +5 | `tests/ui/test_compact_spinbox.py` (NEW)（compact property opt-in 回归套件） | 5 |
| -8 | `tests/ui/test_order_worker.py`（整删，OrderWorker 已 W4 清除） | -8 |

## 关键设计决策

1. **`mf4_analyzer/ui/_axis_defaults.py` 作为单一权威源**：`Z_RANGE_DEFAULTS = {dB: (-30, 0), Linear: (0, 1)}` + `z_range_for(unit)`。Inspector / Batch OUTPUT 三处 `_on_amp_unit_changed` 共用同一行为契约（chk_z_auto first → setValue floor/ceiling → blockSignals 子部件保 emit-once → `_sync_axis_enabled` 落定）。
2. **`widgets/compact_spinbox.no_buttons` hoist 为模块级 helper**：取代分散的 `inspector_sections._no_buttons`（thin re-export 保 caller）和 `method_buttons.py` 5 处 inline `setButtonSymbols`。`CompactDoubleSpinBox.__init__` 也调 `setProperty('compact', True)`，让所有 compact spinbox 透明 opt-in。QSS selector 收敛为 `[compact="true"]`，普通 `QSpinBox / QDoubleSpinBox` 不再被全局规则吃掉 stepper。
3. **ChartOptionsDialog 双入口阻塞**：log-scale + 非正 limit 时 `_invalid_axes` 收集，Apply 按钮 (`apply_changes`) 弹 warning + early return；OK 按钮 (`_accept_with_apply`) 调 `apply_changes` 后再 check `_invalid_axes` 决定 `accept()`。
4. **forward-looking 保留**：W4 删 OrderWorker 时**保留** `OrderContextual.btn_cancel` + `cancel_requested` 信号 + `MainWindow._cancel_order_compute` placeholder slot。当未来加 async COT worker 时，wiring 可直接复用。

## Squad state

- `docs/lessons-learned/.state.yml` `top_level_completions` 34 → **36**（W1-W3 + W4-W5 两个 top-level 任务，各 +1）
- `last_prune_at = 21`，gap = 36 - 21 = 15 < 20，本轮不触发 prune
- **rework lessons**：零。W1-W3 全派 pyqt-ui-engineer，W4 派 refactor-architect、W5 派 pyqt-ui-engineer。W5 触及 `inspector_sections.py` 但仅改 `_no_buttons` helper + W4 specialist flagged 的 stale comment block，未 conflict W1 的 `_on_amp_unit_changed`。无 cross-expert file 重叠。

## 提交与发布

两次 commit 已落 `origin/main`：

| Commit | 内容 |
|---|---|
| `7dc4e17` | `fix(ui): codex review P1+P2 sweep` — W1-W5 全部代码 + tests + spec/plan/decomposition/review 文档 + .state.yml（24 文件，+2230/-563） |
| `276a0f0` | `chore(lessons): codex lessons system maintenance` — 会话前独立 drift（hooks 配置 + check.py doctor 扩展 + 新 lesson 注册），5 文件 |

工作区 clean。

## Deferred P2（本次未处理，作 future-watch）

按 user 决策，下面两条不入本次 squad，不阻塞使用，记此备查。

### P7-O1 — `mf4_analyzer/ui/main_window.py:1501` stale 注释

- **现状**：`_render_order_time` 之上的注释仍描述 `OrderContextual` 暴露 `dynamic ∈ {'30 dB', '50 dB', '80 dB', 'Auto'}` 旧枚举。但 W3-of-PR#7 已经把 `OrderContextual.current_params()` 改为返回 `x/y/z_auto + z_floor/z_ceiling`，不再返回 `dynamic`；紧随其后的实际渲染调用也读新键。
- **运行时影响**：**零**。纯文档漂移。
- **维护风险**：低。新人按注释复活旧路径会被 inspector / canvas 测试拦下，但浪费 5-10 min 翻代码确认 schema。
- **触发频率**：仅维护时偶发，不触达用户。
- **建议处理时机**：下一次任意改 `main_window.py` 时顺手清。

### P10-L1 — `mf4_analyzer/ui/widgets/searchable_combo.py:289` 空模型 `addItem` 覆盖 lineEdit 查询

- **现状**：`SearchableComboBox.addItem()` 直接调 `super().addItem()`。当 combo 为空且 `lineEdit().text()` 已是用户输入时，Qt 把新插入的第一个 item 设为 currentItem，line edit 内容被覆盖。
- **触发链路**：(a) combo 当前为空 + (b) 用户已在 lineEdit 输入过滤文本 + (c) 代码异步 / 延迟 `addItem` 填第一条候选。三个条件**同时**满足才踩到。
- **当前代码状况**：通道/信号 combo 一般是 “打开文件 → 同步一次性填充 combo → 用户 typing 过滤”。这种使用模式下三条件不会同时成立，**实际不会触发**。
- **未来风险窗口**：如果加 “多 MF4 流式合并 / 实时通道发现 / live channel rescan” 等异步通道刷新功能，combo 模型可能在 typing 期间被异步 `addItem`，此时 P10-L1 才成 user-visible bug。
- **建议处理时机**：与 “异步通道刷新” 类功能开发同 PR 处理。修复点小（10 行内）：在 `addItem` 内 save lineEdit text + currentIndex，super 调用后 restore。

## 非目标（明确不在本次 scope）

- 不引入 async COT worker（保留 placeholder 但不实现）
- 不重构 `_no_buttons` 与 `CompactDoubleSpinBox` 关系（仅允许 helper hoist）
- 不动 `Inspector QSpinBox` 之外的非 spinbox 全局 QSS selector
- 不动 `batch_preset_io._migrate_axis_keys`（codex 已确认幂等；建议补单测但不在本次）

## 文档清单

| 类别 | 路径 |
|---|---|
| 原始 review | `docs/code-reviews/2026-05-01-recent-prs-deep-review.md` |
| W1 re-review 历史 | `docs/code-reviews/2026-05-01-w1-rereview.md` |
| Phase 4 终局 review | `docs/code-reviews/2026-05-01-phase4-final-review.md` |
| Spec — P1 | `docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md` |
| Plan — P1 | `docs/superpowers/plans/2026-05-01-codex-review-fixes.md` |
| Spec — P2 | `docs/superpowers/specs/2026-05-01-codex-p2-cleanup-design.md` |
| Plan — P2 | `docs/superpowers/plans/2026-05-01-codex-p2-cleanup.md` |
| Decomposition — P1 | `docs/lessons-learned/orchestrator/decompositions/2026-05-01-codex-review-fixes.md` |
| Decomposition — P2 | `docs/lessons-learned/orchestrator/decompositions/2026-05-01-codex-p2-cleanup.md` |
