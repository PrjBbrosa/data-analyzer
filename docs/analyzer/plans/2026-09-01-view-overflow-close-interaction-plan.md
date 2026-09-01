# View 快速关闭与溢出面板实施计划

- 日期：2026-09-01
- 状态：READY FOR IMPLEMENTATION（本轮仅产出 Spec/Plan，未改产品代码）
- 计划基线：`f07b6a7c`
- 对应规格：
  [`2026-09-01-view-overflow-close-interaction-spec.md`](../specs/2026-09-01-view-overflow-close-interaction-spec.md)
- 视觉参考：
  [`2026-09-01-view-overflow-close-panel.html`](../ui-prototypes/2026-09-01-view-overflow-close-panel.html)
- 发布策略：仅增加 View 快速关闭 feature；现有切换、重命名、排序、右键、
  overflow、确认及 section cleanup 不得改变

## 0. 实施结论与任务依赖

本功能应沿现有共享 `ViewTabBar → typed intent → section host → ViewManager` 链路
增量实现。tab 上的 `×` 不是独立布局控件，而是现有色标 icon slot 的绘制/命中状态；
popup 是 presentation surface；批量关闭由 manager 原子事务承担。

```text
T0 冻结现有行为与红测
 ├─→ T1 色标槽位 × 绘制与事件隔离 ─┐
 ├─→ T2 全部 View popup 呈现与意图 ─┼─→ T4 host 集成、确认与 section cleanup
 └─→ T3 ViewManager 原子批量事务 ───┘
                                      └─→ T5 hints / quickref
                                            └─→ T6 集成、Cocoa 与交付验收
```

- T1、T2、T3 可在 T0 红测冻结后并行，但共享文件必须串行落盘。
- T4 依赖 T2 typed intents 与 T3 transaction API 稳定。
- T5 依赖最终可见交互和文案稳定。
- T6 是唯一集成 gate owner；不在并行工作中运行全量测试。

## 1. 当前 worktree 保护

计划编写时 worktree 已有与本功能无关的 tracked/untracked 改动，特别是
`mf4_analyzer/ui/main_window/window.py` 已被其他工作修改。实施者必须：

1. 开始每个 Task 前记录 `git status --short` 与相关文件 diff；
2. 不还原、不格式化、不顺带提交这些既有改动；
3. 若 T4 必须修改 `window.py`，只合入本 feature 的窄 signal wiring hunk，并逐 hunk stage；
4. 若无法证明 hunk 归属，停止并协调 owner，不覆盖现存修改；
5. 原型 HTML 是设计资产，不把其演示性 undo/toast 直接移植为产品功能。

## 2. Task 0 — 冻结既有事件与几何合同（先红测）

**目标：** 在生产代码修改前，先把“新增关闭不能破坏旧交互”变成可执行门禁。

**Owner 文件**

- 修改 `tests/ui/test_view_tabbar.py`
- 必要时修改 `tests/ui/test_view_tabbar_mount.py`
- 不改生产代码

**步骤**

1. 复跑并记录现有切换、rename、reorder、context menu、compact、overflow、24 View
   用例，确认基线不是已有红灯。
2. 新增 geometry harness：保存全部 `tabRect()`、`sizeHint()`、icon slot center 和 rail
   宽度；模拟 normal/hover/press/release 后比较。
3. 新增 signal spy 事件矩阵，分别点击标签 body 与当前色标槽位，覆盖 single、double、
   drag、right click。
4. 新增 stable identity 场景：armed 后 reorder/rebuild/delete，release 必须 fail closed。
5. 新增唯一 View、merge-host 双颜色色标、compact、overflow active relocation 场景。

**现有回归基线**

- `test_switching_other_tab_emits_switch_requested`
- `test_double_click_tab_starts_inline_rename_and_return_emits`
- `test_tab_moved_emits_reorder_requested`
- `test_tab_moved_does_not_emit_switch_requested`
- `test_reorder_does_not_rebuild_tabbar_midflight`
- `test_context_menu_delete_disabled_for_single_view`
- `test_overflow_hides_tail_tabs_with_settabvisible_never_removetab`
- `test_overflow_menu_pick_emits_switch_requested_with_the_view_index`
- `test_switching_to_an_overflowed_view_pulls_it_back_onto_the_strip`
- `test_time_domain_cap_overflow_keeps_active_visible_and_lists_all`

**新增红测（建议名称）**

- `test_hovering_swatch_replaces_only_icon_without_changing_tab_geometry`
- `test_close_slot_click_emits_delete_once_without_switch_or_rename`
- `test_close_slot_double_click_never_enters_inline_rename_or_double_deletes`
- `test_drag_from_close_slot_cancels_without_reorder`
- `test_tab_body_click_and_double_click_keep_existing_switch_and_rename_routes`
- `test_right_click_on_swatch_keeps_existing_context_menu`
- `test_close_ink_is_centered_in_the_existing_icon_slot_at_each_dpr`
- `test_single_view_keeps_swatch_and_has_no_actionable_close_slot`

**预期：** 新 feature 用例因无实现而红；所有现有用例绿。不得先改生产代码再反推断言。

**停线条件**

- 无法从 Qt style/tab geometry 稳定求得 icon slot，而只能用写死坐标；
- 当前基线已出现 switch/rename/reorder 事件污染；
- 测试只能通过调用 private handler，无法走真实 QMouseEvent 路径。

## 3. Task 1 — 色标槽位内绘制居中 `×` 并隔离事件

**目标：** 在不增加像素占位的前提下完成 tab 快速关闭，严格满足 Spec §3。

**Owner 文件**

- 修改 `mf4_analyzer/ui/view_tabbar.py`
- 修改 `tests/ui/test_view_tabbar.py`
- 如逻辑足够独立，可在 `mf4_analyzer/ui/widgets/` 新建一个窄的 tab hit/paint helper；
  不把实现放进 compatibility facade

**实现步骤**

1. 用 private `QTabBar` subclass 或等价的窄 collaborator 统一拥有 icon-slot hit-test、
   hover index、armed `view_id`、paint/icon refresh 和事件消费。
2. 保留 `setIconSize(QSize(12, 12))` 的现有逻辑尺寸；新增 HiDPI-aware close pixmap，
   以 slot center 计算 `×` strokes，不用手调平台 offset。
3. `MouseMove` 只更新受影响 tab 的 icon/paint；不得 rebuild tabs 或改变 density。
4. press 在 slot 内即消费并 arm stable `view_id`；release 只有仍命中同一有效 View
   时才把当下 index 交给既有 `delete_requested`。
5. double-click/right-click/drag 按 Spec 事件表路由；在 leave、focus loss、rebuild、
   destroy 时清空 hover/armed 状态。
6. 唯一 View 禁止 actionable `×`；保留色标和“至少保留一个 View”提示。

**关键禁止项**

- 禁止 `setTabButton(..., RightSide, close_button)` 或给 tab 增加独立 close 列；
- 禁止仅处理 release，任由 press 先触发 currentChanged；
- 禁止以 View 名称为 armed identity；
- 禁止改变 `_set_density()`、roomy/compact/overflow 测量或 merge color 语义；
- 禁止为通过视觉测试写死 HTML 的 27 × 17 或 94 px。

**验证**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_tabbar.py \
  -k 'swatch or close_slot or double_click or tab_moved or switching or context_menu or geometry' -q
```

**完成证据**

- T0 新增 event matrix 全绿；
- hover/pressed 前后所有 tab geometry byte-for-byte 相等；
- DPR 参数化图像中 `×` ink center 误差 ≤ 0.5 logical px；
- body 的单击切换、双击 rename 和拖拽排序现有测试不变。

**停线条件**

- Qt 默认 handler 已在消费前发出 switch/rename/reorder，且无法在 owner 内阻断；
- hover icon refresh 导致 `tabRect()` 或 overflow count 改变；
- merge-host 色标无法在 leave 后精确恢复。

## 4. Task 2 — “全部 View”popup 呈现层

**目标：** 将现有 `»N` 展开面升级为全部 View 管理 popup，但不让 UI 层持有业务状态。

**Owner 文件**

- 新建建议：`mf4_analyzer/ui/widgets/view_overflow_popup.py`
- 修改 `mf4_analyzer/ui/view_tabbar.py`
- 修改 `tests/ui/test_view_tabbar.py`
- 修改 `tests/ui/test_view_tabbar_mount.py`

**实现步骤**

1. 建立 immutable row DTO：`view_id/name/ordinal/color/partner_color/current/closable`。
2. popup 使用 parented `Qt.Popup`/`QFrame`，header、scrollable rows、fixed footer 与真实
   圆角底板；不使用难以可靠承载交互行的堆叠 `QWidgetAction` hacks。
3. 保留现有 `»N` 入口与 count；popup 行主区域发 switch intent，行末按钮发单删 intent，
   footer 发 stable bulk intents。
4. popup 在触发单删或批量确认前先 close；外点、Esc、owner destroy 对称 teardown，
   恢复入口 focus/expanded state。
5. 按可用 screen geometry 夹取位置和最大高度；列表滚动但 header/footer 固定。
6. 完整实现 Spec §4 精确文案、tooltip、accessible names 和唯一 View disabled 状态。

**新增测试（建议名称）**

- `test_overflow_popup_lists_all_views_and_marks_current_by_view_id`
- `test_popup_row_name_switches_without_emitting_delete`
- `test_popup_row_close_emits_existing_delete_intent_without_switch`
- `test_popup_bulk_buttons_emit_typed_intents_and_never_mutate_manager`
- `test_popup_single_view_disables_all_close_actions`
- `test_popup_escape_outside_click_and_destroy_restore_trigger_state`
- `test_popup_clamps_to_available_screen_and_keeps_footer_visible`
- `test_popup_round_surface_paints_an_opaque_center`

**回归要求**

- `»N` count、全部 View 列表、current checked/marked、hidden tail 和 active relocation
  的既有用例语义不变；若 widget 类型变化，只更新测试操作方式，不放宽产品断言。
- mount matrix 中时域/FFT/时频/FRF/阶次都能打开同一 popup，且 section label、Dock、
  UltraView 入口和 rail geometry 不位移。

**停线条件**

- popup 需要 import `MainWindow` 或直接调用 manager mutation；
- 关闭 modal 打开时 popup 仍抢焦点/残留 native wrapper；
- 24 View 时 footer 被滚走、popup 越屏或入口位置改变 rail 测量。

## 5. Task 3 — ViewManager 原子批量事务

**目标：** 提供 retain-only 与 reset 的单 owner、一次发布能力，禁止循环单删。

**Owner 文件**

- 修改 `mf4_analyzer/ui/view_state.py`
- 修改对应 ViewManager owner tests（优先现有 view-state 测试文件；若无合适位置，
  新建 `tests/ui/test_view_manager_bulk_close.py`）

**实现步骤**

1. 新增 stable-id API，建议 `retain_only_view(view_id: str) -> tuple[str, ...]`，返回
   removed ids 供 section cleanup；stale/missing id fail closed 且零 mutation。
2. 在一次 transaction 内保留精确 View 对象、规范化 active index 和 split pairs，
   最终只 emit 一次既有 state change。
3. 审核并复用 `reset_to_single_default()` 作为关闭全部 primitive；补齐返回 removed ids
   或同等可验证 result，但不创建第二套 reset 算法。
4. 定义 0/1 View 防御行为、active/non-active keep、primary/secondary split、24 View、
   duplicate names 和 signal count。

**新增测试（建议名称）**

- `test_retain_only_view_preserves_exact_object_and_stable_id`
- `test_retain_only_view_normalizes_split_pairs_and_emits_once`
- `test_retain_only_stale_id_is_a_zero_mutation_noop`
- `test_reset_to_single_default_returns_removed_ids_and_emits_once`
- `test_bulk_close_never_exposes_zero_views_to_observers`
- `test_duplicate_display_names_do_not_affect_bulk_identity`

**停线条件**

- 只能循环 `delete_view()` 才能保持 split/invariants；
- observers 会看到零 View 或多个中间 active 状态；
- manager 为了 section cache cleanup 需要 import UI/MainWindow。

## 6. Task 4 — Host 集成、确认与 section-specific cleanup

**目标：** 把 popup typed intents 接到时域/分析 owner，保持单删完全兼容，批量一次提交。

**Owner 文件**

- 修改 `mf4_analyzer/ui/main_window/_view_mixin.py`
- 修改 `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- 修改 `mf4_analyzer/ui/main_window/window.py`（仅窄 signal wiring；尊重现有 dirty hunk）
- 修改 `tests/ui/test_view_switch_integration.py`
- 修改 `tests/ui/test_analysis_view_cache_residency.py`
- 必要时新增窄的 analysis/time bulk-close integration tests

**实现步骤**

1. 单项 tab/popup close 继续走既有 `delete_requested` handler；不改当前时域确认 copy，
   不给分析单删凭空增加 modal。
2. 增加时域与各分析 bar 的 bulk intent wiring，禁止 `.connect(lambda ...)`；使用
   named slot/`partial` 的既有合规方式，并不新增散落 MainWindow state。
3. “关闭其他”在 dialog 前解析当前 stable `view_id` 和计数；confirm 后调用 manager
   原子 retain-only。Dialog 文案逐字匹配 Spec §5.1。
4. “关闭全部”confirm 后调用单点 reset。Dialog 文案逐字匹配 Spec §5.2。
5. 把分析单删已有 pending restore、pin、FRF pane cache cleanup 提取成可接收
   `removed_view_ids` 的窄 helper；单删与批量共用，禁止复制第二套 cleanup。
6. 时域在 mutation 前沿用当前 capture/commit 次序；confirm cancel 不 capture、不 render。
7. 每次 confirm transaction 只做一次最终 tab refresh、canvas projection 和通知。

**新增/扩展测试**

- 时域：单项取消仍零变化；单项确认仍沿现有路径；关闭其他保留 current id；关闭全部
  得到空白 View；每项 signal/render 次数精确为一。
- 分析：批量删除后的 results 可驱逐，restore pending、pins、FRF pane caches 无 stale id；
  单删现有 `test_delete_view_unpins_so_results_become_evictable` 不回归。
- 所有 section：confirmation cancel 零 mutation；stale id 零 mutation；唯一 View disabled
  与 handler guard 双保险。
- 文案：两个批量 dialog 的 title/body/warning 与 Spec 完全一致。

**聚焦命令**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_switch_integration.py \
  tests/ui/test_analysis_view_cache_residency.py \
  tests/ui/test_view_tabbar_mount.py -q
```

**停线条件**

- 分析 bulk cleanup 无法复用单删 owner，或任何 removed id 仍被 cache/pin 引用；
- confirm 后产生逐 View modal、逐 View render 或 observable 中间状态；
- 为 wiring 扩大 `test_main_window_state_ownership.py` whitelist；
- 无法从现有 dirty `window.py` 中隔离本 feature hunk。

## 7. Task 5 — 发现性文案与帮助同步

**目标：** 让用户能发现两个入口和关键限制，不用猜 `×` 是否会影响原操作。

**Owner 文件**

- 修改 `mf4_analyzer/ui/hints.py`
- 修改 `mf4_analyzer/ui/quickref.py`
- 修改 `tests/ui/test_hint_nudges.py`
- 修改 `tests/ui/test_quickref.py`

**建议 copy**

- 更新/新增 hint：`悬停 View 色标可快速关闭；名称区仍用于切换和双击重命名`
- 更新时域 View quickref：`最多 24 个；窄窗口先显示编号，悬停看全名；用「»」展开全部 View，可逐项关闭或关闭其他/全部`
- 保留既有 `View 标签右键` 条目，不把复制、颜色、split 等操作从帮助中删掉。
- 明示：`至少保留一个 View；关闭其他保留当前，关闭全部后留下一个空白 View。`

**验证**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_hint_nudges.py tests/ui/test_quickref.py -q
```

**停线条件**

- 为新 feature 删除/替代已有右键入口说明；
- 文案暗示 `×` 覆盖整个 tab、关闭全部进入零 View 或提供了实际不存在的撤销。

## 8. Task 6 — 集成、视觉与交付验收

**目标：** 在稳定 snapshot 上证明事件、几何、Qt 生命周期和 section cleanup 都闭环。

### 8.1 聚焦 owner gates

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_tabbar_mount.py \
  tests/ui/test_view_switch_integration.py \
  tests/ui/test_analysis_view_cache_residency.py \
  tests/ui/test_hint_nudges.py \
  tests/ui/test_quickref.py -q
```

若 Task 3 新建 owner test，必须加入上面命令。

### 8.2 边界护栏

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_qsettings_isolation.py -q
```

新增 popup 若跨入 widget lifecycle/shared surface，再按触及范围补
`tests/ui/test_import_boundaries.py`；不得机械运行全部 `tests/ui` 代替 owner gate。

### 8.3 macOS Cocoa 前台验收

在真实运行路径启动：

```bash
./.venv/bin/python -m mf4_analyzer.app
```

使用至少 8 个 View 和一个 24 View 时域场景逐项验证：

1. hover 色标，色标原位变 `×`；录制 normal/hover 切换，tab/编号无 1 px 位移；
2. `×` 的 ink 中心与原色标槽位中心重合，active/inactive/merge-host 均检查；
3. 点标签 body 切换、双击名称 rename、拖动 body reorder、右键色标开菜单；
4. 点/双击/拖出 `×` 不触发 switch/rename/reorder，合法 click 只删一次；
5. popup header/list/footer、滚动、外点、Esc、焦点回归、屏幕边缘夹取和底板不透；
6. 时域单删确认取消/确认；分析单删；关闭其他；关闭全部；唯一 View disabled；
7. popup 和 modal 反复开关 20 次，无 stale wrapper、crash、残留 expanded/armed 状态。

截图/录屏归档到 `docs/analyzer/verify/`，记录 APP_VERSION、HEAD、dirty scope、macOS/Qt
版本和 DPR。HTML 视觉参考不能作为这一步的替代证据。

### 8.4 交付卫生

```bash
git diff --check
git status --short
git diff --name-only
```

仅 stage 本计划 owner 文件。若 relevant source 在测试期间变化，测试结果标记
`UNVERIFIED` 并在稳定 snapshot 重跑。此 scoped feature 默认不跑 full suite；只有出现
order/teardown 污染、跨边界重构或发版验收时，才由单一 coordinator 按项目规定运行
一次主套件和一次 acquisition suite，二者不得并发。

## 9. 提交拆分建议

1. `test(ui): freeze View close hit-region and event routing`
2. `feat(ui): close Views from the existing swatch slot`
3. `feat(ui): add the all-Views close popup`
4. `feat(ui): close other or all Views atomically`
5. `docs(ui): explain View quick-close interactions`
6. `test(ui): close View popup lifecycle and Cocoa regressions`

如果 T1/T2 实际共用 `view_tabbar.py` 且无法安全拆分，允许合并 2/3，但测试提交必须先于
实现提交。任何提交都不得夹带现有 dirty worktree 的资产删除、channel-tree、WWT 或
`window.py` 非本 feature hunk。

## 10. 回滚与完成定义

### 回滚边界

- 呈现/事件回归：可独立回退 T1/T2，既有 `delete_requested`、context menu 和旧 overflow
  语义仍可工作。
- 批量事务回归：隐藏 footer 两个 bulk intents 并回退 T3/T4，不得回退现有单删。
- 不通过改变 tab 宽度、关闭整个 tab click、禁用 rename/reorder 或放宽测试来“修复”。

### Definition of Done

- [ ] `×` 只在色标槽位出现，居中，normal/hover/pressed geometry 不变；
- [ ] 单击切换、双击重命名、拖拽排序、右键菜单现有用例全绿；
- [ ] `×` 的 press/release/double-click/drag 事件无 switch/rename/reorder 泄漏；
- [ ] popup 列出全部 View，行主区/关闭按钮/bulk actions 命中互斥；
- [ ] 单删沿用现有 section 语义；关闭其他/全部一次确认、一次 transaction、一次 render；
- [ ] analysis removed-view caches/pins/restore state 清理完整；时域 capture/confirm 不回归；
- [ ] 唯一 View 始终保留，关闭全部得到一个干净默认 View；
- [ ] hints 与 quickref 同步，未删除既有右键和 overflow 能力说明；
- [ ] owner/boundary tests、`git diff --check` 与 Cocoa 前台验收均有稳定 snapshot 证据；
- [ ] 交付 diff 只含本 feature，未覆盖或提交任何预先存在的 unrelated dirty change。

