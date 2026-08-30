# 五波大提交后的稳定性与可靠性封口实施计划

- 日期：2026-08-30
- 状态：READY FOR IMPLEMENTATION
- 类型：审查后稳定性封口；不包含功能扩张
- 冻结基线：`253ba972c207f0c8e70896a9ef0e9c1ab168b9d5`
- 审查范围：`1ea1a84be3040fae2f434abf45e3404eeea63ca3..253ba972`
- 配套 Spec：
  [`2026-08-30-post-large-commit-stability-closure-spec.md`](../specs/2026-08-30-post-large-commit-stability-closure-spec.md)
- 并行专项：
  [`2026-08-30-ultraview-smart-layout-fixed-point-and-fit-isolation-followup-plan.md`](2026-08-30-ultraview-smart-layout-fixed-point-and-fit-isolation-followup-plan.md)

## 0. 实施结论

本计划是今天五个大提交之后的稳定性封口层，不重新实现已经完成的功能，也不吸收正在
进行的 Smart Layout fixed-point/Card Fit/Board Fit 专项。实施顺序固定为：先冻结红测，
再分别修复 record-eye owner、Qt release 生命周期、验证合同，最后独立关闭继承红基线，
由唯一 integration owner 在稳定快照上执行完整门禁。

四个工作流保持独立提交边界：

1. split secondary record-eye 精确路由；
2. UltraView card release 同步重建后的 native crash；
3. Smart Layout 文案、hint、visual harness 与 diff hygiene；
4. `origin/main` 已存在的四个普通失败。

不得为了让 suite 变绿而修改另一个工作流的 owner、放宽 shrink-only 门禁、增加静默
fallback，或排除 native crash 测试。

## 1. 当前证据与边界

### 1.1 冻结审查结果

- 五个提交、94 个文件，约 `+15,264/-1,339`；
- 已有聚焦证据：`479 passed, 7 skipped`、
  `1539 passed, 5 skipped, 2 deselected`、`44 passed, 1 skipped`；
- 近全量主套件：`8548 passed, 44 skipped, 7 failed, 4 deselected`；
- acquisition 独立套件：`359 passed`；
- `test_card_drag_near_viewport_edge_starts_page_edge_timer` 在冻结 HEAD 和
  `origin/main` 都可 exit 139；
- 两个新增失败是 visual harness 的“自动排版”陈旧断言与 hint 精确队列遗漏；
- 四个普通失败在 `origin/main` 和冻结 HEAD 都存在；
- `tests/ui/test_view_state.py` 有一个 branch diff whitespace finding。

这些数字只代表冻结快照。当前 checkout 中的 fixed-point、版本、帮助资源和本机文件改动
必须保留，但不得纳入本计划提交。

### 1.2 文件 ownership

| 工作流 | 首选 owner | 测试 owner |
| --- | --- | --- |
| record-eye | `mf4_analyzer/ui/main_window/_view_mixin.py` | `tests/ui/test_view_channel_scope.py`、`tests/ui/test_split_focus_routing.py` |
| Qt release | `mf4_analyzer/ui/chart_stack/ultraview/free_grid_board.py` | `tests/ui/test_ultraview_page.py` |
| visual/hint | `tools/verify_ultraview_visuals.py`、既有 hint registry | `tests/test_verify_ultraview_visuals.py`、`tests/ui/test_hint_nudges.py` |
| whitespace | `tests/ui/test_view_state.py` | `git diff --check` |
| baseline debt | 各失败的真实 owner 或测试 fake | 对应现有失败测试 |

只有证据证明现有窄 seam 不足时，才可扩展相邻 owner。不得把新状态写入
`MainWindow`、普通 channel mapping、record store、PreviewStore 或 neutral Smart Layout
core。

### 1.3 与 fixed-point 专项的隔离

本计划不修改：

- `mf4_analyzer/ultraview_core/smart_layout.py`；
- `mf4_analyzer/ultraview_core/native_layout.py`；
- `mf4_analyzer/ultraview_core/grid_geometry.py`；
- `mf4_analyzer/ui/chart_stack/ultraview/card_fit.py`；
- fixed-point 专项新增/修改的 integration tests 与上游 Spec 决策。

若 Qt crash 修复被证明必须改变上述职责，停止对应 wave，先与 fixed-point owner 合并
设计，不能在两个任务里分别实现。

## 2. Wave 0 — 冻结红测与 source fingerprint

### Task 0.1 — 记录现场

开始前记录：

```bash
git rev-parse HEAD
git status --short --branch
git diff --name-only 1ea1a84b..253ba972
pgrep -af pytest
```

要求：

- 冻结 commit range 是 review baseline；
- 当前 dirty/untracked 清单是实施排除表；
- 不 stash、clean、reset、stage 或删除他人改动；
- target owner 已被其他 agent 修改时先比较 diff，不能安全协调就停止；
- 不先跑 routine full suite，只跑以下 focused red tests。

### Task 0.2 — record-eye 红测

在 `tests/ui/test_view_channel_scope.py` 新增：

```text
test_split_secondary_record_eye_writes_only_secondary_state
test_stale_secondary_record_eye_event_is_zero_mutation
```

第一项必须同时证明：`view_manager.active` 仍是 primary；树投影 secondary；点击只改变
secondary `hidden_curve_binding_ids`；只重绘 secondary index/canvas；primary hidden ids、
普通 `checked` 和另一 View 颜色不变。

第二项先投影 secondary，再切回 primary 后投递旧 payload；必须 zero mutation，只允许树
同步当前 focused View。现有 active-View 测试保留，不能改写成只覆盖 secondary。

### Task 0.3 — Qt release 红测

在 `tests/ui/test_ultraview_page.py` 新增或收紧：

```text
test_card_release_does_not_touch_wrapper_after_sync_rebuild
test_card_drag_near_viewport_edge_starts_page_edge_timer
```

第一项用同步 slot 模拟 `_finish_gesture(commit=True)` 内重建/删除 card，并让 commit 后的
card/event getter 访问立即失败。第二项必须执行完整 edge-pan drag/release，并在 fresh
process 中检查 exit code；不得只断言 timer active 后提前结束。

测试不依赖 sleep、固定顺序或开发者 QSettings。parentless widget 必须显式 owner，结束前
停止 timer/signal 并 drain deferred delete。

### Task 0.4 — 验证合同红线

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_verify_ultraview_visuals.py tests/ui/test_hint_nudges.py

git diff --check 1ea1a84b..253ba972
```

分别记录“自动排版”陈旧断言、hint queue 缺三个 id 和 EOF 空行。若真实失败与冻结证据
不同，先更新证据表，不能按旧输出盲改。

### Wave 0 完成条件

- [ ] 两个 record-eye 测试冻结读写 owner；
- [ ] sync-rebuild 测试冻结 commit 后不得访问 wrapper；
- [ ] native crash 在独立 fresh process 复现并记录 exit code；
- [ ] visual/hint/diff 失败分别归档；
- [ ] 没有运行并发或第二个 full suite；
- [ ] 没有改动 fixed-point 专项 owner。

## 3. Wave A — focused View record-eye 修复

### Task A1 — 一次解析交互目标

在 record-eye handler 入口一次调用既有 `_focused_time_view_state()`，冻结目标 index、
`view_id`、`ViewState` 和 canvas。handler 后续不得再次读取 `view_manager.active`。

payload `view_id` 必须与 focused `view_id` 一致；不一致即按 stale event 拒绝，不能回退
primary。若现有 helper 不返回稳定 index，优先扩展既有 focus holder/coordinator；不得
新增 `_record_eye_target_idx` 或另一个 MainWindow 镜像状态，也不得用
`getattr(..., False)` 隐藏必需 owner。

### Task A2 — 校验并提交单 View 意图

成功路径固定为：

```text
resolve focused index + view once
→ require payload view_id matches
→ locate binding by composite identity
→ require y_ref.kind == wwt_record
→ update only target hidden_curve_binding_ids
→ replot target index/canvas with preserve_xlim=True
→ re-project tree from the same View
```

不得用 display name 查 binding，不改普通 channel `checked`，不把 record visibility 搬到
widget/global store，不调用 active primary 的 plot，也不静默吞 programming error。

### Task A3 — stale event 与生命周期

View 删除、file close、split 切换或 binding 过滤后到达的 payload：

- zero mutation；
- 不重绘错误 canvas；
- tree 仍存在时只从当前 focused View resync；
- 不弹错误框；
- 如需日志，只走既有 throttled diagnostics。

确认 duplicate、save/reopen、close-all/reset 仍由 `ViewState` 单 owner 持久化和清理。

### Task A4 — owner gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_view_channel_scope.py \
  tests/ui/test_split_focus_routing.py \
  tests/ui/test_wwt_import_flow.py

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py
```

路径已变化时先用 `rg --files` 定位真实 owner，并记录替代命令，不得伪造 pass。

### Wave A 停止条件

- 需要新增第二份 focused state；
- 需要修改 record store、普通 channel identity 或所有 View；
- stale click 只能通过吞异常处理；
- secondary replot 必须切换 primary tab；
- ownership/no-lambda ratchet 只能靠放宽 whitelist 通过。

## 4. Wave B — UltraView Qt release 生命周期修复

### Task B1 — commit 前冻结纯值

在 `FreeGridBoard.handle_card_mouse_release(card, event)` 内、任何可能 emit/刷新 projection
的调用之前冻结：stable `UltraViewRef`、board-local/global release `QPoint`、button、
modifiers、gesture/resize intent 与必要 primitive geometry。

冻结结果只包含 immutable DTO/primitive/值类型；不得保存 `card`、`event`、其 parent 或
bound Qt method。

### Task B2 — commit barrier

把 `_finish_gesture(commit=True, ...)` 视为同步 destruction barrier。返回后不得访问旧
`card`、`event` 或 wrapper graph。cursor restore、edge-pan stop、ghost cleanup 只能用
预先冻结的 board-local position、stable ref 的重新解析或 board owner 自身状态。

若 board 本身也进入 teardown，cleanup 幂等结束；不得通过 `sip.isdeleted()` 继续操作旧
card，也不得 broad `except Exception`。

### Task B3 — 精确一次清理

覆盖 move、resize、group move、非法 drop、move-to-unplaced 和 edge-pan：

- stop coalesce/edge-pan timers；
- release mouse grab；
- 清 ghost/dim/chrome 与 gesture state；
- 恢复 cursor；
- `drag_finished`、geometry intent、history mutation 各最多一次。

复用既有 `_finish_gesture`/feedback owner，不复制第二条 cleanup 或 emit/record 路径。

### Task B4 — crash gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_page.py::test_card_release_does_not_touch_wrapper_after_sync_rebuild

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_page.py::test_card_drag_near_viewport_edge_starts_page_edge_timer

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_qsettings_isolation.py
```

fresh process 有正常 summary 且 exit 0 才算通过。exit 139、abort、timeout 或只跑完前半段
均为 `UNVERIFIED/FAIL`。

### Wave B 停止条件

- 需要 skip/xfail/deselect/sleep/test order；
- commit 后仍需旧 card/event 才能完成 UX；
- 需要改变 placement、Smart Layout、Card Fit 或 Board Fit 语义；
- cleanup 被拆成两个可能重复 emit/record 的 owner；
- 只能靠 broad exception 或进程级 handler 隐藏 crash。

## 5. Wave C — 验证合同与差异卫生

### Task C1 — visual harness 使用当前动作

在 `tools/verify_ultraview_visuals.py` 和对应测试中，把已退休的用户文案“自动排版”换为
当前合同：`智能排版`（size + position）、`紧凑排列`（position-only）、`按原图比例`
（single-card）、`适应内容`（camera-only）。

测试必须确认 harness 走真实生产入口。内部兼容 signal 即使仍名为
`auto_arrange_requested`，也不得把旧词显示给用户。

### Task C2 — hint 精确队列

读取 registry 的真实 `priority + order`，再把以下 id 加入
`tests/ui/test_hint_nudges.py` 的 exact queue：

```text
file.wwt_batch_choice
time.custom_x_paths
time.wwt_native_home
```

不得把 exact-list 放宽成集合包含，不得为了通过测试调整 hint priority。

### Task C3 — 文档双面同步审计

```bash
rg -n '自动排版|智能排版|紧凑排列|file\.wwt_batch_choice|time\.custom_x_paths|time\.wwt_native_home' \
  mf4_analyzer/ui mf4_analyzer/help docs/analyzer tools tests
```

新交互需同步 `ui/hints.py` 与 `ui/quickref.py`，并检查 help/用户指南。历史 spec/plan/review
保留历史措辞，不为让 grep 清零而重写。

### Task C4 — diff hygiene 与 focused gates

清理 `tests/ui/test_view_state.py` 已确认的 EOF 空行，只处理冻结 range 的差异。

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_verify_ultraview_visuals.py \
  tests/ui/test_hint_nudges.py \
  tests/ui/test_view_state.py

git diff --check 1ea1a84b..HEAD
git diff --cached --check
```

branch-wide finding 位于并行任务文件时，分别报告 scoped 与 branch-wide 结果，不顺手改
其他 agent 文件。

### Wave C 停止条件

- 要恢复旧“自动排版”才能通过；
- 要放宽 hint exact-list 或改 priority；
- 要重写历史文档；
- 要修改 fixed-point core/Card Fit；
- diff finding 位于无法协调的并行 owner。

## 6. Wave D — 独立关闭继承红基线

本 wave 单独 commit。每项先在 `origin/main` 对照快照证明失败，再在集成快照修复；不得
描述为五个提交引入的 regression。

### Task D1 — FFT-time fake probe

目标失败：

```text
test_fft_time_dispatch_key_equals_lookup_key_for_each_pane
test_fft_time_single_path_uses_same_key_builder_as_main_path
```

读取真实调用链与 fake 的接口差异。优先让 fake 实现真实窄 seam
`_clear_analysis_view_viewports`；不得在 production 增加 `hasattr/getattr` 静默 fallback。

### Task D2 — TimeDomain hotpath fake

目标失败 `test_disabled_stats_strip_skips_full_array_statistics`。让 fake 显式实现
`_active_time_curve_bindings` 的真实空语义，保持“禁用 stats 时不扫描完整数组”的原目标；
不得绕开 hotpath guard。

### Task D3 — QSS palette shrink-only

目标失败 `test_distinct_hex_literals_may_only_shrink`。定位第 212 个 literal，复用既有
palette/token 或删除无意重复；不得把 ceiling 从 211 抬到 212，不做无关 QSS 大清理。

### Task D4 — focused gates

用 `pytest --collect-only` 与 `rg` 解析以上四项真实 node id，再连同
`tests/ui_kit/test_qss_border_shorthand.py` 运行。实施记录必须保存实际命令；不得把占位符
当作已运行证据。

### Wave D 停止条件

- 失败无法在 `origin/main` 对照复现；
- fake 修复要求 production fallback；
- hotpath 修复改变真实统计行为；
- QSS 只能靠抬 ceiling 或大范围换色；
- target owner 正由未完成的并行任务修改。

## 7. Wave E — 集成与验收

### Task E1 — changed-file 审计

唯一 integration owner 运行：

```bash
git status --short --branch
git diff --stat 253ba972c207f0c8e70896a9ef0e9c1ab168b9d5..HEAD
git diff --name-only 253ba972c207f0c8e70896a9ef0e9c1ab168b9d5..HEAD
git diff --check 253ba972c207f0c8e70896a9ef0e9c1ab168b9d5..HEAD
pgrep -af pytest
```

逐个 commit 确认只含对应 owner。若 stage 中出现资产删除、版本、SSH key、本机报告或
客户 `testdoc/`，立即移出提交范围，但不得删除或回滚用户文件。

### Task E2 — 边界门禁

owner tests 全绿后运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py
```

路径不存在时先用 `rg --files` 校正。异常退出、无 summary 或 source 运行中变化都为
`UNVERIFIED`。

### Task E3 — 唯一 full gate

只在稳定 snapshot、无其他 pytest、focused/boundary 全绿后运行一次：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

两个 fresh process 顺序运行，主 suite 不带 deselect。前后记录 HEAD 与 dirty fingerprint；
若 target source 或 fingerprint 变化，本轮只记 `UNVERIFIED`。

### Task E4 — macOS Cocoa 前台

用 committed synthetic WWT fixture 验证：单栏 eye、split 两栏各自 eye、stale click、
UltraView edge drag/release、resize、group move、move-to-unplaced、Undo/Redo、保存重开、
四动作隔离，以及 WWT open → fixed-point settle → Board Fit → Smart Layout → release。

真实客户 WWT 仅作可选 smoke，不作为 core test 唯一 fixture。记录前台版本、fixture、步骤、
hidden intent、crash/stuck cursor/ghost/timer 和必要截图。

### Task E5 — Windows Full/Lite frozen

分别验证 split secondary eye、edge-pan release、Smart Layout 文案/动作隔离、Undo/Redo、
保存重开以及 125%/150% DPI。无环境时明确 `UNVERIFIED`；源码、offscreen、Cocoa 均不能
替代。

## 8. 并行与提交策略

Wave A 与 B 在 owner 不交叉时可并行；Wave C 等 fixed-point 最终用户文案冻结后执行；
Wave D 可在独立 worktree/commit 中进行；Wave E 只有一个 integration/full owner。

推荐原子提交边界：

```text
test(ui): freeze split record eye ownership
fix(ui): route record eye through focused time view
test(ultraview): freeze release sync-rebuild lifecycle
fix(ultraview): stop using card wrappers after release commit
test(verification): sync smart-layout visuals and hints
chore(tests): restore branch diff hygiene
test(baseline): align narrow fakes with owner contracts
style(ui): reuse existing palette token
```

测试与修复可按项目惯例成对合并，但不得把四个工作流压成一个大提交。本计划不授权
commit、push 或 merge；获得授权后仍需审计 stage scope。

## 9. Definition of Done

- [ ] Spec `SCR-01` 至 `SCR-11` 均有实现或可执行证据；
- [ ] split secondary eye 只写/画 secondary，stale eye zero mutation；
- [ ] release commit 后零 card/event wrapper 访问；
- [ ] edge-pan crash test fresh process exit 0；
- [ ] move/resize/group/unplaced cleanup 精确一次；
- [ ] visual harness 使用当前动作并走真实入口；
- [ ] hint exact queue 纳入三个新 id；
- [ ] EOF whitespace 与 scoped diff check 清零；
- [ ] 四个继承普通失败独立关闭；
- [ ] state/import/backref/QSettings/no-lambda/QSS 门禁全绿；
- [ ] fixed-point 专项与本计划无 owner 冲突；
- [ ] main suite 无 deselect 正常完成；
- [ ] acquisition fresh process 正常完成；
- [ ] full gate 前后 HEAD/dirty fingerprint 一致；
- [ ] Cocoa、Windows Full/Lite 各有证据或明确 `UNVERIFIED`；
- [ ] unrelated dirty/untracked 文件未被修改、删除、stage 或提交；
- [ ] lessons status 与 changed-file scope 已审计。

## 10. 总停止规则

出现任一条件即停止当前 wave，不扩大范围：

1. 必须改 Smart Layout core/Card Fit/fixed-point owner；
2. 必须新增 MainWindow 镜像状态或扩宽 ownership whitelist；
3. 必须用 display label 代替 composite identity；
4. 必须用 broad exception、silent fallback、sleep、skip、xfail 或 deselect；
5. 必须抬高 shrink-only QSS/lambda/state ceiling；
6. target owner 有无法协调的并发修改；
7. 同一 checkout 已有 full pytest 运行；
8. full gate 期间 HEAD 或相关 dirty fingerprint 变化；
9. 测试只能依赖本机客户文件或真实 QSettings；
10. offscreen、Cocoa 与 Windows 结果矛盾；
11. staged scope 包含资产删除、版本、SSH key、本机报告或其他无关文件；
12. 修复引入普通 channel、record store、PreviewStore 或 Board model 的第二 owner。
