# View 隔离与 P 固定游标两提交审查及加固计划

- 日期：2026-09-19，Asia/Shanghai。
- 状态：**审查完成，决策已定，加固未实施**。本文是实施契约；本次只交付本文件，不修改产品代码。
  2026-09-19 12:31 按"改动最小、与既有 codec / UX 契约一致、不新增全局键、不留死代码"原则定下 §1.1 的五项决策，实施时不再回头问。
- 审查快照：HEAD `a5c10c79`（工作区干净，唯一未跟踪文件为 `ssh-keygen`，见 §5.3）。
- 范围：`f551a87e` feat(ui): isolate time-domain drawing intent per View（+2961/−250，36 文件）与
  `a5c10c79` feat(ui): pin chart readouts with P without leaving the plot（+9860/−190，56 文件）。
- 对应实施契约：[View 状态隔离 followup](2026-09-18-view-state-isolation-followup-plan.md)、
  [P 键固定游标实施计划](2026-09-18-pinned-cursor-implementation-plan.md)。本文按这两份契约逐条核对现状；
  契约里写的"拟实施决策"不代替代码事实。
- 证据等级：**offscreen Qt**（pytest + `/tmp` 探针）与**代码阅读**。macOS Cocoa 前台、Windows 全部
  UNVERIFIED，见 §6。
- 执行方式：单协调者按 §4 顺序实施；不要求并行 agent。P0 修完再动 P1。

## 1. 结论

两个提交**方向正确、分层基本守住**：Qt-free 中立模型子进程投毒通过；`_CanvasBackref` 白名单零写穿；
状态所有权棘轮、lambda 棘轮、import 边界 11 个护栏文件 46 passed / 1 skipped；两提交自带的 28 个 owner
测试文件逐文件全绿；既有回归 22 个文件 21 绿。**不能据此宣称功能完成或零隐藏 bug**——审查发现
**2 项 P0、7 项 P1、约 20 项 P2**，以及一处既有回归测试红。

| 级别 | 数量 | 一句话 |
|---|---|---|
| P0 | 2 | pin 的 fid 重映射保留未知 fid 会在顺序 `f{n}` 体系下**误绑别的来源**；`open_project` 路径不清 pin controller，**旧工程 FFT/FRF pin 会被保存进新工程** |
| P1 | 7 | `pin_feedback` 无消费者、`undo_close` 无入口（提示与撤销是死功能）；应用级 Python eventFilter 让测试会话超线性变慢；`chart_rebuilt` 静默删可持久化意图；空集合 `scope_id` 不可复现导致脏摘要漂移；共轴组 id 重编号让 log/grid 串组；簇标签展开被 `setFixedSize` 钉死；`test_cursor_pill_toggle_stays_pinned_to_top_right_corner` 回归红 |
| P2 | ~20 | 见 §3 各表 |

**总体判断**：软件此前"相对很稳"，这两个提交把 1.28 万行、两套新的持久化字段（schema 4 / analysis
`_SCHEMA` 11）和一个应用级事件过滤器带进了主路径。**在 P0/P1 修完并做一次 Cocoa 前台验收之前，
不建议发版，也不建议在这两个提交之上继续叠新 feature。**

### 1.1 已定决策（实施依据）

| # | 争议点 | 决策 | 理由 |
|---|---|---|---|
| D1 | F-P0-1 未知 fid 的 pin binding：哨兵保留 vs 丢弃 | **丢弃**，与 `remap_view_fids` 其余七类字段同一语义；丢弃项进 `collect_dropped_time_refs` / `collect_dropped_analysis_refs`，随既有"缺失文件"报告一起呈现 | 一个 codec 一种规则最稳；哨兵身份会流进 controller / UltraView facts / 摘要，等于再造一套"半合法 fid"。pin 重按 P 即可重建，代价低。实施计划 §7.4 的"保留不可用意图"改为由**本文**覆盖：源缺失时不保留 |
| D2 | F-P1-1 撤销关闭：接入入口 vs 删除 | **删除** `undo_close` / `_ClosedPin` / `_OwnerState.undo` 及 quickref「可撤销一次」文案；`pin_feedback` 接到既有 `toast` + `statusBar` | 既有 toast 无动作位；再加一个作用域键违反"不新增全局 P 类快捷键"的谨慎原则；误关一张 pin 再按一次 P 就回来。无入口的功能就是死代码 |
| D3 | F-P1-2 面板动作区：按可见按钮打包 (a) vs 改契约 (b) | **(a)**：`_position_title_actions` 只对 `isVisible()` 的动作从右边缘依次排布；`_primary` 右边距仍按最大槽位预留 | 保住 `67fb2df8` 的角落契约与既有红测；预留边距已满足实施计划 §6.9"不跳位"的实质（面板宽度/文字不重排），`+/-` 在 live↔pinned 间移一个槽是角色变化，不是漂移 |
| D4 | F-P1-3 应用级 eventFilter：保留 vs 换 QShortcut | **保留**，只修生命周期与范围：随 host `showEvent` / `hideEvent` 装卸；`eventFilter` 首行 frozenset 早退；去掉 Mouse/HoverMove 记录 | `QShortcut(WindowShortcut)` 会被 `QTreeView` 键盘搜索的 ShortcutOverride 吞掉（正是"勾完通道直接 P"场景），且与 UltraView `WidgetWithChildrenShortcut` P 形成 ambiguous |
| D5 | 版本号 | **v8.3.0**，随 T7 一并扇出 | 工程 codec 升 schema 4 + 三个新交互（P 固定、按 View 的共轴/滤波/颜色、图表外观入 View）不是补丁级；且 `UnsupportedProjectVersion` 需要一个能让用户"升级到 vX"的目标号 |

## 2. 执行结果（本次实际运行）

命令统一为 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider …`。

| 组 | 结果 | 备注 |
|---|---|---|
| 机械护栏 11 文件（`test_main_window_state_ownership` · `test_no_lambda_signal_connections` · `test_pg_canvas_backref_invariants` · `test_import_boundaries` · `test_signal_no_gui_import` · `test_batch_render_import_boundary` · `test_native_import_boundaries` · `test_packaging_imports` · `test_qss_border_shorthand` · `test_conftest_autouse_scope` · `test_qsettings_isolation`） | 46 passed, 1 skipped, 17 s | 全部护栏守住 |
| 子进程投毒 `sys.modules['PyQt5']=None` 后 import `pinned_cursor_state` / `cursor_display_model` | 通过 | 两个中立模块确实 Qt-free |
| 两提交 owner 用例 28 文件**逐文件** | 全绿，总和约 4.5 min | `test_project_session.py` 56 passed 需 118 s；`test_pinned_cursor_geometry.py` 23 s |
| 同 28 文件**合成一个进程** | **>22 min 未结束，被终止，记 UNVERIFIED** | 见 §3.1 F-P1-3 的采样与探针 |
| 既有回归 owner 22 文件逐文件（游标 / 分屏 / FRF / FFT / 时域画布 / 滤波 / 对话框 / UltraView 会话） | 21 绿，**1 红** | `tests/ui/test_chart_stack.py::test_cursor_pill_toggle_stays_pinned_to_top_right_corner`，`assert 24 <= 6`；不在既有红清单（`reviews/2026-08-15-post-v8-batch-review.md` §6、`plans/2026-08-13-guideline-hardening-followup-plan.md` §5）中 |
| 全量 suite | **未跑** | 按 CLAUDE.md 门禁，全量留给 P0/P1 修完后的稳定快照，由实施协调者唯一执行 |

## 3. 发现清单

编号规则：`F-P{级别}-{序号}`。每条给出位置、证据、为什么是问题、修法。位置行号以 `a5c10c79` 工作区为准。

### 3.1 P 固定游标（`a5c10c79`）

#### P0

**F-P0-1 fid 重映射保留未知 fid → 顺序分配体系下误绑别的来源**
- 位置：[`pinned_cursor_state.py:291-298, 636-640`](../../../mf4_analyzer/ui/pinned_cursor_state.py#L291) `remap_collection_fids` 对 `fid_map` 中不存在的 fid 原样保留；[`project_io.py:518-522, 629-631, 693-695`](../../../mf4_analyzer/ui/project_io.py#L518) `_remap_pinned_cursors` 沿用。同一函数里 `checked` / `hidden_channels` / `colors` / `ylims` / `overlay_primary` / `remarks` / `curve_bindings` **全部是"fid 不在 map 就丢弃"**。
- 证据：fid 是会话内顺序整数——[`_project_io_mixin.py:628`](../../../mf4_analyzer/ui/main_window/_project_io_mixin.py#L628) `fid = f"f{self._fc}"`，[`window.py:255`](../../../mf4_analyzer/ui/main_window/window.py#L255) `self._fc = 0`；[`_restore_project_file_refs`](../../../mf4_analyzer/ui/main_window/_project_io_mixin.py#L2300) 对缺失文件 `continue`，**不消耗序号**。冷启动打开工程：旧 `f0` 缺失 → 旧 `f1` 分到新 `f0`；pin 里"保留"的旧 `f0` 现在指向另一个文件。controller 按 `(fid, channel)` 求值，EPS 批次里 `Rack Force` 之类同名通道普遍存在，pin 会**把别的来源的读数当固定值显示**。`tests/test_pinned_cursor_state.py:504-530` 与 `tests/test_project_io.py` 的 `test_remap_rewrites_known_pin_fids_keeps_unknown_…` 把这一行为钉成了契约。
- 违反：实施计划 §7.4「工程源暂缺时保留不可用意图/诊断，**不能误绑同名来源**」；AGENTS「Never invent … channel match」。
- 修法（D1）：与 `remap_view_fids` 其余字段一致——未知 fid 的 binding **丢弃**；一条记录的 binding 全部丢弃则丢整条记录；Custom-X `axis_identity` 的 fid 缺失则丢整条记录（不能把另一来源的 X 值当同一轴）。丢弃项进 `collect_dropped_time_refs` / `collect_dropped_analysis_refs`。`test_remap_rewrites_known_pin_fids_keeps_unknown_…` 与 `tests/test_pinned_cursor_state.py:504-530` 改为断言丢弃。

**F-P0-2 `open_project` 的会话替换不清 pin controller → 旧工程 FFT/FRF pin 写进新工程**
- 位置：[`_project_io_mixin.py:2397-2404`](../../../mf4_analyzer/ui/main_window/_project_io_mixin.py#L2397) `open_project` 在 `_restoring_project=True` 下调 `close_all(force=True)`；`close_all` 的逐 fid 循环（`:2644-2650`）**不调** `_drop_pinned_cursor_identities`（单文件关闭路径 `:1931` 有调），只靠末尾 `_reset_empty_workspace_session`（`:2039-2045` `controller.clear_all()`）；而该函数在 `_restoring_project / _opening_project / _applying_view` 任一为真时 `return False`（`:1973-1978`）。
- 运行时复现（`/tmp` 探针，真实 `MainWindow` + `_load_one` 一个 CSV）：往 FFT canvas 装 1 条 pin → `_restoring_project=True; close_all(force=True)` → **`files=[]` 但 FFT pins=1，fid 仍为 `f0`**；对照组交互式 `close_all` → pins=0。随后 `_restore_project_file_refs` 把新工程首文件分到 `f0`，旧 pin 恰好"命中"。
- 链路继续：[`_analysis_mixin.py:670-689`](../../../mf4_analyzer/ui/main_window/_analysis_mixin.py#L670) `_capture_analysis_overlay` 以 `page._overlay_session_bound` 门控，该标志置 True 后**从不复位**；保存工程时 [`_project_io_mixin.py:2199`](../../../mf4_analyzer/ui/main_window/_project_io_mixin.py#L2199) 对每个 section `_capture_active_analysis_view` → `capture_overlay_from_canvas` 把旧会话的 FFT/FRF pin 集合写入新工程 PaneState。`undo_close(canvas=None)` 也能复活旧工程记录。
- 修法：`close_all` 逐 fid 调 `_drop_pinned_cursor_identities(fids=(fid,))`，并在循环结束后无条件 `controller.clear_all()`（不依赖 `_reset_empty_workspace_session` 的门控）；会话替换时把各 page 的 `_overlay_session_bound` 复位。补 `test_project_session.py` 用例：旧工程有 FFT pin → `open_project` 新工程 → 保存 → 新工程文件里 `pinned_cursors.records == []`。

#### P1

**F-P1-1 `pin_feedback` 无任何消费者；`undo_close` 无任何产品入口**
- 位置：[`pinned_cursor_controller.py:130`](../../../mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py#L130) 定义；[`stack.py:94, 343`](../../../mf4_analyzer/ui/chart_stack/stack.py#L94) 仅转发。全仓 `rg pin_feedback` 在 `mf4_analyzer/` 内只有这三处；`undo_close`（`:662-705`）只被 `tests/ui/test_pinned_cursor_panels.py:109` 直接调用。
- 后果：`P3 已固定 · t=…`、`先放置 B，再按 P 固定`、`P1 已在此位置`、`已关闭 P2`、`无法撤销：数据已更新` 全部发进虚空；用户双游标只放了 A 时按 P 是**静默无反应**。「撤销关闭」是死功能，但 [`quickref.py:424`](../../../mf4_analyzer/ui/quickref.py#L424) 已写「× 关闭可撤销一次」。
- 违反：实施计划 §3.3、§5「撤销关闭」行；AGENTS「fallback must remain observable」。
- 修法（D2）：`window.py` 建完 `chart_stack` 处一次性 `chart_stack.pin_feedback.connect(self._on_pin_feedback)`（bound method，不增 lambda），槽内 `self.toast(msg, 'info')` + `statusBar.showMessage(msg, 3000)`；失败类文案（`先放置 B…`、`无数据`）用 `'warning'` 级。**删除**撤销：`undo_close`、`_ClosedPin`、`_OwnerState.undo` 及其在 `set_collection / clear_all / drop_closed_identities / close_record` 中的写点、`close_record` 里"已关闭 Pn"文案改为不暗示可撤销；`quickref.py:424` 去掉「可撤销一次」；`tests/ui/test_pinned_cursor_panels.py:109` 的撤销用例删除，改为断言关闭后 `pin_feedback` 发出且记录不可恢复。

**F-P1-2 `pin_feedback`/hint 之外的 UI 回归：live 面板 `+/-` 右侧常驻 22 px 空带**
- 位置：[`cursor_pill.py:502-516`](../../../mf4_analyzer/ui/chart_stack/cursor_pill.py#L502) `_position_title_actions` 固定四槽 `[P 提示][pin][+/-][×]`；`:563-564` live 角色隐藏 pin/×，但 `+/-` 仍占第三槽。
- 证据：`test_cursor_pill_toggle_stays_pinned_to_top_right_corner` 红，`right_inset_full == 24`。该测试由 `67fb2df8 fix(ui): pin cursor pill toggle to the top-right corner` 写下，是明确的产品契约；本提交没有改测试、没有在提交信息里声明契约变更。
- 修法（D3）：`_position_title_actions` 只对 `isVisible()` 的动作从右边缘依次排布（`×` → `+/-` → `pin` → `P` 提示，隐藏者不占槽）；`_primary.setContentsMargins(0,0,_TITLE_ACTION_RESERVE,0)` 保持不变，面板宽度与首行文字在 live↔pinned 间不重排。补 `test_chart_stack.py` 一条 pinned 角色的对偶用例：`×` inset ≤ 6、`+/-` 紧邻其左；既有 `test_cursor_pill_toggle_stays_pinned_to_top_right_corner` 不改。

**F-P1-3 应用级 Python `eventFilter` 让每个事件都进 Python；测试会话超线性变慢**
- 位置：[`pinned_cursor_controller.py:141, 446`](../../../mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py#L446) `QApplication.installEventFilter(self)`；`:410-439` 每个事件先 `isinstance(watched, CursorPill)` + `event.type()`。
- 证据：28 文件合跑 >22 min 被终止，逐文件总和 4.5 min。`sample` 主线程栈：`QApplication.setStyleSheet → QApplication::setStyle → … → sendThroughApplicationEventFilters → sipQObject::eventFilter`。`/tmp` 探针（8 个 `ChartStack` 存活，`setStyleSheet` 往返）：0 个 Python 应用级 filter **445 ms**，1 个 **585 ms**，8 个 **1428 ms**——**线性 +~120 ms/filter**。host 真正销毁时 filter 会卸载（`host.destroyed → _remove_application_filter` 核实有效，无硬泄漏）；但 pytest 里被引用/未 `deleteLater` 的 host（探针 variant 2 复现 1 个存活）会让 filter 累积，整个 session 越跑越慢。生产单 host 时每事件多一次 Python 调用，交互 benchmark 尚未复测。
- 权衡：改成 `QShortcut(WindowShortcut)` 会在焦点位于 `QTreeView`（键盘搜索接受 ShortcutOverride）时失效，正是"勾完通道直接按 P"的场景；且会与 UltraView 的 `QShortcut(Key_P, WidgetWithChildrenShortcut)`（[`ultraview/page.py:712`](../../../mf4_analyzer/ui/chart_stack/ultraview/page.py#L712)）形成 ambiguous。**app filter 是可辩护的设计**，问题在生命周期与范围。
- 修法（D4）：controller 监听 host 的 `showEvent`/`hideEvent`（ChartStack 已是 QWidget，用 `host.installEventFilter(self)` 只收 Show/Hide 两类，或让 ChartStack 显式调 `controller.set_host_visible(bool)`）——可见时 `app.installEventFilter`，隐藏/销毁时卸载；`eventFilter` 首行 `if event.type() not in _P_EVENT_TYPES: return False`（frozenset，含 ShortcutOverride/KeyPress 与 pill 的 Enter/Leave/Focus*），去掉 `MouseMove/HoverMove` 记录（`_mouse_global()` 已有 `QCursor.pos()` 回退）。`tests/ui/conftest.py` 加一条 session 级哨兵：每个 item teardown 后断言 `gc` 中存活且 `_application_filter_installed` 的 `PinnedCursorController` 数 ≤ 1，超出即 fail 并报出持有者测试名（这同时会暴露既有的 host 泄漏）。修后用 §2 同一 28 文件合成单进程复测，并跑 `scripts/benchmark_timedomain_interaction.py --assert-standards` 真机对比。

**F-P1-4 `chart_rebuilt` 路径静默删除可持久化意图，且不走脏标记**
- 位置：[`pinned_cursor_controller.py:1375-1382`](../../../mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py#L1375) `_on_chart_rebuilt → _reproject_now(drop_unbound=True)`；`:1584-1605` binding 不在 bound 也不在 hidden 就删，全删则丢记录；`:1478-1479` 直接写 `owner.collection`，不 `_mark_user_intent()`。
- 后果：(1) 用户在导航器**取消勾选**（非隐藏）一个通道 → binding 永久删除，重新勾选也不回来——计划 §7.3 只把「显式删除绑定/来源关闭」列为删除条件；(2) 切 View 首帧若 `chart_rebuilt` 先于全部通道绑定完成发出，会在正常切换中误删（代码推断，见 §6）；(3) 未走 `intent_changed`，下次 capture 才进 `to_dict`，脏摘要与 revision 不一致。
- 修法：`chart_rebuilt` 只把未绑定 binding 标 `unavailable`（与 hidden 同法：面板行显示「未勾选」/`—`，隐藏其点与线），**删除只发生在** `_drop_pinned_cursor_identities`（来源关闭）与 D1 的工程装载丢弃这两条显式路径；`_reproject_now` 去掉 `drop_unbound` 参数。补 lifecycle 用例：取消勾选→pin 行标 unavailable 且工程不脏→重新勾选→行恢复 ready。

**F-P1-5 空集合 `scope_id` 不可复现；controller 多处自行铸造 UUID → state/controller 分叉、脏摘要漂移**
- 位置：`bind_canvas :146-160`、`collection_for(create=True) :186-190`、`set_collection :196-197`、`clear_all :213-231` 都 `empty_collection()` 铸新 UUID；[`view_bridge.py:217-220`](../../../mf4_analyzer/ui/view_bridge.py#L217) / [`analysis_view_bridge.py:83-86`](../../../mf4_analyzer/ui/analysis_view_bridge.py#L83) capture 无条件用 controller 集合覆盖 state；[`project_io.py:518-522`](../../../mf4_analyzer/ui/project_io.py#L518) `_remap_pinned_cursors(None)` 每次铸新 UUID，`remap_view_fids` 不幂等。
- 后果：什么都没做的 View 在一次 capture 后 `scope_id` 变化 → `ViewState.to_dict()` 变化 → `_canonical_session_digest` 与基线不等 → 关闭时误弹「未保存」。`_reset_empty_workspace_session` 里 `reset_to_single_default()` 后再 `clear_all()` 是确定性复现点。
- 修法（不改序列化格式）：controller 全程不铸造 scope_id——`bind_canvas` 初始集合由首次 `set_collection` 提供，之前 `collection_for` 返回 `None` 而非新集合；`clear_all` 用 `clear_collection(owner.collection)`；bridge capture 遇 controller 为 `None` 或无记录时保留 state 原集合（`replace(state.pinned_cursors, records=(), next_ordinal=…)` 只在确有变化时替换）；`_remap_pinned_cursors(None)` 返回 `None`，由 `from_dict` 的默认值补空集合，使 `remap_view_fids` 幂等。补 `test_project_session.py` 的 save→clean→切 View / 新建空 View→不脏用例，及 `remap_view_fids` 两次调用结果相等的用例。

**F-P1-6 簇标签悬停展开后尺寸被 `setFixedSize` 钉死，成员按钮 3–4 px 不可读**
- 位置：[`pinned_cursor_overlay.py:401`](../../../mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py#L401)（非展开分支 `setFixedSize`）、`:463` `enterEvent` 展开只 `adjustSize()`。
- 证据：离屏实测 8 成员簇 chip 48×16，展开后 `size()` 仍 48×16，`layout().sizeHint()` 660×14，8 个按钮宽 3/4/3/4 px。`test_pinned_cursor_geometry.py:350-376` 只断言按钮数为 8。
- 修法：展开前 `setMinimumSize(0,0); setMaximumSize(QWIDGETSIZE_MAX,…)` 再 `adjustSize()`，收起时钉回；测试断言每个按钮 `width() >= fm.horizontalAdvance(text)`。

**F-P1-7 `_hit_owner` 不校验前台窗口；非模态 `MarkupEditor` 活跃时 P 被抢**
- 位置：[`pinned_cursor_controller.py:712-757`](../../../mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py#L712) 只查 `activeModalWidget / activePopupWidget / is_text_input_widget / page_ultraview`。`MarkupEditor` 是 `QWidget(parent, Qt.Window)` 非模态（[`markup/editor.py:112`](../../../mf4_analyzer/ui/markup/editor.py#L112)），编辑器不遮住图表时鼠标常停在主窗口图上；按 P 选画笔 → `widgetAt(QCursor.pos())` 命中主窗口 viewport → 创建 pin 并吞键。
- 修法：`_hit_owner` 开头加 `canvas.window() is app.activeWindow()`；顺带把文本输入判定改为 `focus.testAttribute(Qt.WA_InputMethodEnabled) or is_text_input_widget(focus)`（覆盖 `QAbstractSpinBox` / 可编辑 `QComboBox` 的焦点代理与 IME）。

#### P2

| ID | 位置 | 问题 | 修法 |
|---|---|---|---|
| F-P2-1 | `pinned_cursor_controller.py:486-515` | 单游标 P 只刷 pill 不移 canvas 的 `_cursor_line_items`，**hover 实线留在节流前旧 x**，pin 虚线在新 x，一帧错位（计划 §4 反向情形） | `_refresh_live_from_sample` 里同步游标线位置（给 canvas 补窄接口 `sync_single_cursor_line(x)`） |
| F-P2-2 | 同文件 `:559-580, :606-635` | 单游标「取消固定后再 P 沿用编号」几乎不可达：P 用鼠标 x，与候选 x 不 `coords_equal` | 取消固定后到下一次有效 hover 更新前，P 用候选 x（`owner.reserved_intent.x`）而非鼠标 x；用现有 `dual_hidden_placement`/`live_suppressed` 标记"候选未变"，让这两个只写不读的字段真正有读者 |
| F-P2-3 | 同文件 `:1363-1397`；`canvas.py:1682-1683` | replot 某些路径先 `chart_rebuilt` 再 `presentation_content_invalidated` → ready→pending→ready，20 pin = 40 次采样 + 60 次 QTextDocument 布局，面板闪一帧「更新中」 | `_on_content_invalidated` 比对 generation 相同则跳过；或只订阅 `chart_rebuilt` + 数据 revision |
| F-P2-4 | `stack.py:609-632` | 用 `partial` **覆写 `AnalysisSectionPage.enter_split/exit_split` 实例方法**做 pane 挂钩；形成 page→partial→page 环，类属性调用绕过 | `AnalysisSectionPage` 加 `pane_added(canvas)` / `pane_removing(canvas)` 信号，stack 用 bound method connect |
| F-P2-5 | `pinned_cursor_controller.py:1822-1837` | FFT binding identity 退化为**显示名**（`fid = source_label`），`_key_in :1628-1632` 空 fid 时按 channel 名兜底匹配 | line_canvas 事实出口带 `(fid, channel[, binding_id])`；拿不到复合身份就留空 binding，不用显示名冒充；删 `_key_in` 的空 fid 分支 |
| F-P2-6 | `pinned_cursor_overlay.py:655-686, 882-889, 994-1001, 1067-1095` | pan/zoom 热路径：K 个 linked vb 各触发一次完整 `reproject`（无合并）；每帧对 N×K 条 `InfiniteLine` `setPen`（pyqtgraph 无条件 `update()`）；`_sync_extrema` 每帧两次 `setData` 并新建 QPen/QBrush；引线每帧 remove+新建 `QGraphicsLineItem` | 几何信号走轻路径（layout + leaders）；0 ms 单发合并 K 次；`setPen` 只在 highlight 变化时；引线 `setLine` 复用 |
| F-P2-7 | `pinned_cursor_controller.py:1984-2017`；`overlay :216-218` | 簇 key 含成员集合，密集区平移时簇并入/拆出 → `PinnedAxisLabel` 逐帧 `deleteLater`+构造（含两次 connect） | key 按槽位序号；或 label 池按需 `apply_geom` |
| F-P2-8 | `cursor.py:962-1007` vs `stack.py:2339-2382` | `_cursor_display_channel_from_dual_row` 逐字复制，两份 DualCursorRow→CursorDisplayChannel 映射会静默漂移 | 搬到 `cursor_display_model.py`（Qt-free）为模块级函数，两侧 import |
| F-P2-9 | `pinned_cursor_overlay.py:805-817, 1028-1030` | FRF 对数 X 下**非正频率被标成「◀ 视野外（左）」**而非「不可用」 | `view_x is None` 与 `< lo` 区分，新增 `unrepresentable` 状态 |
| F-P2-10 | 同文件 `:1035-1036`；controller `:2019-2026` | dual 只有一个端点视野外时**整条记录/整张 pill** 标 offscreen（计划 §6.7 要求按端点） | `offscreen_ids` 改端点粒度，pill 只在全部端点不可见时整卡标记 |
| F-P2-11 | `pinned_cursor_state.py:152-155`；`view_state.py:536`；`analysis_view_state.py:327` | 丢弃记录的 `DroppedPinnedCursor` 诊断**没有任何生产消费者**，坏 payload / 未知 version 全静默 | `from_dict` 改用 `normalize_collection` 并逐条 `logger.warning` |
| F-P2-12 | `pinned_cursor_state.py:540-545`；controller `:252-254, :1573-1574` | `bindings=()` 的记录合法且任何关闭都清不掉 | `_parse_intent` 要求 ≥1 有效 binding |
| F-P2-13 | `view_bridge.py:304-306`；controller `:192-205` | 时域恢复顺序是「安装意图→**立即对旧画布曲线求值投影一帧**→重绘→再投影」，不是计划 §7.4 的"数据就绪后投影一次" | `set_collection` 只安装 + 标 pending，等 `chart_rebuilt` 再投影 |
| F-P2-14 | `_project_io_mixin.py:93-105`；`_view_mixin.py:643, 1083`；`_analysis_mixin.py:683` | 每次 View 渲染都用 `Qt.UniqueConnection` + `except TypeError: pass` 做幂等连接，热路径上以异常做控制流，且 `pass` 无注释 | window 建完 `chart_stack` 后连接一次，删三处 `ensure` |
| F-P2-15 | `_project_io_mixin.py:96, 113, 2043` | MainWindow 直接摸 `chart_stack._pinned_cursors` 私有属性 | `ChartStack` 暴露 `pinned_cursor_intent_changed` 信号与 `filter_pinned_identities()` |
| F-P2-16 | `pinned_cursor_controller.py:135, 1237-1244` | `_owners` 以 `id(canvas)` 为键，`_owner()` 不校验身份（计划 §7.1 明文禁止用 QObject 地址识别异步目标） | `_owner` 内 `owner.canvas is not canvas` 则 drop & rebind；或 weakref 键 |
| F-P2-17 | `analysis_section_page.py:278-282`；`stack.py` `pinned_cursor_fingerprint` | `except (RuntimeError, TypeError): pass` / `return ()` 把编程错误吞成"无 pin"，导出图与 UltraView 摘要静默少内容 | 至少 `logger.warning`；`TypeError` 不一起捕 |
| F-P2-18 | `project_io.py:76-77, 342-346` | 外层 schema 升 4（上一提交）后，**已安装的 v8.2.5 打开新工程直接 `UnsupportedProjectVersion`**，报错为英文；`APP_VERSION` 未升、帮助 changelog 无条目 | 见 §4 T7（D5）：升 v8.3.0 + changelog；`UnsupportedProjectVersion` 携带 `schema_version`，`_project_io_mixin` 捕获后弹中文可操作提示「该工程由更新版本的 TraceLab 保存（工程格式 v4），请升级到 v8.3.0 或更高」 |

#### P3 / Nit（合并列出，实施时顺手处理）

`pending_epoch` 递增从未被读（`:122, 1344, 1353`）、`_pin_key_armed` 死状态（`:139, 429-436`）、`_OwnerState.dual_hidden_placement` 只写不读、`_in_data_viewport` 的 `mapped` 未使用；`_hit_owner` 作为谓词却有 `bind_canvas` 副作用（`:734-737`）且一次 P 计算三遍；`_sample_matches_generation` 在同步实现下恒真；teardown 期 `QObject::disconnect: No such signal QWidget::chart_rebuilt()` 噪声（`_on_canvas_destroyed` 对已退化为 `QWidget` 的对象 disconnect，应先 `sip.isdeleted` 判定）；`_cursor_data_revision` 只随 `invalidate_custom_x_path_cache` 递增（`cursor.py:279`），语义耦合脆弱；pin 求值仍白做 HTML 字符串（`cursor.py:882-936`）；FFT/FRF pinned 线 z=800 压在活动线 z=50 之上；`PinnedAxisLabel` 声明 `TabFocus` 但无焦点高亮；FRF facts 测试只做子串包含、缺 A=B 用例；`_finite_float` 接受 `"1.5"` 字串；`PinnedCursorSample.domain="custom"` 与 `PIN_DOMAINS` 的 `"channel"` 不一致；hover 每帧两轮 QSS unpolish/polish（`stack.py:2457-2465`）；`resizeEvent` 对每张 pin 面板完整 QTextDocument 重排无合并；~~`undo` 的 intent 不随 `drop_closed_identities` 过滤~~（随 D2 删除撤销一并消失）；状态回退行 `data_revision` 恒 None 与 live 行不一致造成 UltraView 摘要误判变化；`collect_dropped_*_refs` 未纳入 pin 引用。

**2109 行 controller 的结构方向（不在本轮重构，记录供后续）**：按现有 `# ----` 分节可直接切成 `PinKeyRouter`（filter + 命中 + 上下文排除）、`PinCaptureTransaction`、`PinSampleEvaluator`（纯逻辑，可 Qt-free 单测）、`PinPanelProjector`、`PinUndoStack`，HTML 格式化挪到 `cursor_display.py`。最值得先抽的是 `_evaluate*/_reconcile_sample/_identity_key` 那段纯逻辑。

### 3.2 View 状态隔离（`f551a87e`）

#### P1

**F-V1-1 普通共轴组 id 重编号 + 已解散组的外观 spec 不清理 → 同 View 内 log/grid 串到无关组**
- 位置：[`channel_tree.py:3101-3128`](../../../mf4_analyzer/ui/widgets/channel_tree.py#L3101) `_prune_and_renumber_ordinary_projection` 把存活 id 压成 `1..n`；`:3073-3083` `_new_axis_group_id` 取 `max+1`，解散后 id 复用；[`view_state.py:341-362`](../../../mf4_analyzer/ui/view_state.py#L341) 组解散只把 `y_scale/grid` 下放成员，**不删** `["g","N"]` spec，且 `if gkey in axes: continue` 让残留 spec 压过新成员共识；[`_view_mixin.py:398-401`](../../../mf4_analyzer/ui/main_window/_view_mixin.py#L398) `_appearance_key_for_handle` 优先取 `handle.axis_group`。
- 场景：组1={A,B}(grid off)、组2={C,D}(log)。拆 A → 组1 解散 → 组2 重编号为 "1" → `["g","1"]` 仍是旧组1 的 spec → C/D 显示旧组1 外观，旧 g2 spec 变孤儿。
- 修法：普通组 id 停止重编号/复用（单调序号或 uuid 字串）；或 `inherit_chart_appearance_for_group_change` 里 pop 解散组 key 并按重编号映射改写 `["g",…]`。补 `test_view_appearance_isolation.py` 用例覆盖上述场景。

#### P2

| ID | 位置 | 问题 | 修法 |
|---|---|---|---|
| F-V2-1 | `time_filter.py:228-239`；`window.py:4511-4515, 3902-3907` | `capture_payload` 无论 kind 都写 `cutoff/cutoff_lo/cutoff_hi`（低通时 lo/hi 是控件默认 100/2000），击穿 `filt_enabled = (cutoff>0) or (lo>0 and hi>0)`——**低通 0 Hz 现在被判为启用**，`nyquist_guard` 钳到 1e-6 画出 `LP 1e-06Hz` 伴随线；提交前 `fp.filter_spec()` 只填 kind 相关字段，0 Hz 是"不画"（已对比 HEAD~2 `window.py:4432-4437`）。`test_restore_payload_keeps_zero_cutoff` 把 0 钉成合法值 | `filt_enabled` 按 kind 只看相关截止，或先按 kind 投影成 `FilterSpec` 再判 |
| F-V2-2 | `_view_mixin.py:205-207` | 分屏**非聚焦**画布改色无条件 `navigator.set_channel_colors`，导航器投影的是聚焦 View，下一次 capture 把它当聚焦 View 的 override 采走；同文件 `:355-357` Custom-X 标签路径已用 `_canvas_owns_shared_projection` 门控，改色漏了 | 加同一门控；`state.colors` 写入保留 |
| F-V2-3 | `_axis_handle.py:51`；`_view_mixin.py:229, 408, 512, 527` | 新增 5 处宽泛 `except Exception` 静默降级 | 收窄为 `AttributeError/RuntimeError` 并注释为何安全 |
| F-V2-4 | `_view_mixin.py:222-263, 301, 393, 403, 414, 441, 493, 519-520` | MainWindow mixin 大量越界读画布私有属性（`_companion_names` `_channel_lines` `_channel_data_id` `_x_master_handle` `_inside_label_items` `_overlay_mode` `_primary_xaxis_ax`），`_resolve_companion_source_key` 末尾退回 display name 前缀匹配 | `TimeDomainCanvasPG` 暴露 `appearance_key_for_handle(handle)` / `companion_source_key(ck)` |
| F-V2-5 | `_view_mixin.py:420-429` | record-only 绑定的外观键按 fid **首个匹配**，同一 WWT 文件两条 record-only 曲线会错配 | 按画布复合键 ↔ binding_id 精确匹配 |
| F-V2-6 | `channel_tree.py:1063, 2577-2595, 3078, 3172-3174, 3187-3238` | `_axis_groups` 双写路径未退役干净：仍读/清/prune 一个永远为空的 dict；`_axis_group_seq` 写后立即被 `_renumber_axis_groups` 重置（dead write） | 整段删除 |
| F-V2-7 | `channel_tree.py:3301-3307` | `preserve_imported_axis_seed=False` 时任何带 `window-*-axis-*` id 的成员都并入 `_imported_axis_group_seed`；用户把普通通道并入 WWT 组后一次 View apply 就把它变成"文件级 WWT 身份" | 种子只由 `wwt_view_import` 路径写 |
| F-V2-8 | `project_io.py:461-476`；`_project_io_mixin.py:2422-2424` | schema ≤3 且 `views` 为空 → 顶层 filter 丢失；`_channel_scope_mixin.py:501-508` 应用通道配置时把 `state.colors`/`chart_appearance` 裁到勾选集，与"未勾选 override 保留"冲突 | 明确两处意图并补测试 |
| F-V2-9 | `view_state.py:363-375` | 每次合并都生成 `{"y_scale":"linear","grid":True}` 组 spec，使 `is_reusable_blank_view` 提前为 False 并强制 `grid(True)` | 仅当至少一个成员有显式 spec 时才生成 |
| F-V2-10 | `io/file_data.py:252, 424-425` | 行为变更：只持久化 override 后，非覆盖通道颜色依赖重载时 `file_index`；重开工程若某文件缺失，后续文件调色板整体偏移（提交前勾选通道存绝对色） | 至少写进 changelog；或 remap 时记录原 index |

#### P3 / Nit

`_project_filter_payload` / `_restore_project_filter` 已无生产调用（`_project_io_mixin.py:2555-2590`）；UltraView `_filter_payload` 不做 `normalize_time_filter`，`order` "4"/4 指纹不同；`_strip_rendered_xaxis_label` 直接 `fd.data.columns`；`_build_time_plot_data` 回退链不一致（滤波→`_focused_view_idx`，`hidden_binding_ids`→`view_manager.active`）；`_prune_and_renumber_ordinary_projection` 的 `Counter` 把 "01" 与 "1" 分开计数；`test_view_appearance_isolation.py:329-332` 断言接受 `None`；两个测试向 CWD 下 `.state/view-state-isolation` 落 PNG 并互相 import。

### 3.3 跨提交 / 仓库卫生

| ID | 位置 | 问题 | 修法 |
|---|---|---|---|
| F-X-1 | 仓库根 `ssh-keygen`（未跟踪，`file` 判定 OpenSSH private key，484 B） | 私钥躺在 repo 根目录，不在 `.gitignore`；`git add -A` 会带进历史。9 月 17 日 review 已注意到但未处理 | **移出仓库**（不要加 .gitignore 了事）；若曾被任何分支/远端提交过，按泄露处理并轮换 |
| F-X-2 | `canvas.py:492, 2405, 4929`（来自 `b0b3fcf7`，非本轮提交） | `hideEvent → _invalidate_presentation_paint_ack → self._presentation_paint_ack_epoch += 1` 在探针 teardown 中抛 `AttributeError`（属性尚未/不再存在）。PyQt 虚函数里的异常会进全局 hook 或被 qFatal | `_invalidate_presentation_paint_ack` 对未初始化/已拆除状态早退；补一个构造/析构期 `hideEvent` 不抛的用例 |
| F-X-3 | 帮助页 / `app_meta.py` | 两个提交都改了用户可见行为（P 固定、共轴/滤波/颜色按 View、工程 schema 4），帮助正文已改但 **`meta.version`/changelog 未动，`APP_VERSION` 仍 v8.2.5** | 随 §4 T7 一起升版 |

## 4. 加固计划

按顺序实施；每个 Task 写明 owner 测试与边界护栏。**默认聚焦，不跑全量**；全量只在 T8 由协调者对稳定快照跑一次。

### T0 — 冻结失败用例（先红后修）

为 F-P0-1、F-P0-2、F-P1-1、F-P1-4、F-P1-5、F-P1-6、F-V1-1、F-V2-1 各写一条**失败**的 focused 用例，放进已有 owner 文件：
`tests/test_pinned_cursor_state.py`（remap 丢弃未知 fid；`remap_view_fids` 幂等）、`tests/ui/test_project_session.py`（open_project 不带旧 pin；save→clean→切 View / 新建空 View 不脏）、`tests/ui/test_pinned_cursor_interaction.py`（真实 MainWindow 下按 P 后 `toast` 文案出现——用 `qtbot.waitSignal(win.toast_shown)` 或读 toast label）、`tests/ui/test_pinned_cursor_lifecycle.py`（取消勾选→unavailable 且不脏→重勾选恢复）、`tests/ui/test_view_appearance_isolation.py`（解散组不串 spec）、`tests/ui/test_time_filter_overlay.py`（低通 0 Hz 不画伴随线）、`tests/ui/test_pinned_cursor_geometry.py`（簇展开每个按钮 `width() >= horizontalAdvance(text)`）。
把 `/tmp` 探针 B2 的场景固化为测试；filter 累积探针固化到 `tests/ui/conftest.py` 的 session 哨兵（见 T2）。
Gate：只跑这些文件，确认新用例红、其余绿。无需边界护栏。

### T1 — P0：持久化身份与会话替换

- Owner：`ui/pinned_cursor_state.py`、`ui/project_io.py`、`ui/main_window/_project_io_mixin.py`、`ui/main_window/_analysis_mixin.py`。
- 做：F-P0-1（D1：未知 fid 丢弃 + dropped refs 报告）、F-P0-2（`close_all` 逐 fid 调 `_drop_pinned_cursor_identities` + 循环后无条件 `controller.clear_all()` + `open_project` 开头复位各 page `_overlay_session_bound`）、顺带 F-P2-11（`normalize_collection` + 逐条 `logger.warning`）、F-P2-12（≥1 binding 才合法）。
- 与实施计划的差异要在本文 §1.1 D1 之外再写进 `2026-09-18-pinned-cursor-implementation-plan.md` 顶部一行"§7.4 源缺失保留意图 → 被 2026-09-19 plan D1 取代"，避免两份权威。
- Gate：T0 新用例转绿；`tests/test_pinned_cursor_state.py` · `tests/test_project_io.py` · `tests/test_project_io_analysis_views.py` · `tests/ui/test_project_session.py` · `tests/ui/test_pinned_cursor_lifecycle.py` · `tests/ui/test_session_reset_on_last_close.py`；护栏 `test_main_window_state_ownership.py`。

### T2 — P1：事件过滤器生命周期与测试会话健康

- Owner：`ui/chart_stack/pinned_cursor_controller.py`、`tests/ui/conftest.py`。
- 做：F-P1-3（show/hide 安装卸载、`eventFilter` 早退、去掉鼠标记录）、F-P2-16（owner 身份校验）、P3 的 `disconnect` 噪声与死状态清理、F-P2-14（一次性连接）。
- Gate：`tests/ui/test_pinned_cursor_interaction.py` · `test_pinned_cursor_panels.py` · `test_pinned_cursor_lifecycle.py`；**重跑 §2 那 28 文件的合成单进程**，目标：总时长与逐文件之和同量级（≤ 1.5×）；护栏 `test_no_lambda_signal_connections.py`。真机：`scripts/benchmark_timedomain_interaction.py --assert-standards` 前后对比，读数记入 `docs/analyzer/verify/`。

### T3 — P1：用户反馈、撤销、面板动作区

- Owner：`ui/main_window/_view_mixin.py`（或 `window.py` 建 `chart_stack` 处）、`ui/chart_stack/cursor_pill.py`、`ui/quickref.py`、`ui/hints.py`。
- 做：F-P1-1（D2：接 `toast` + `statusBar`，删除撤销及其文案）、F-P1-2（D3：按可见动作打包）、F-P1-7（前台窗口 + `WA_InputMethodEnabled` 判定）、F-P2-1（同步游标线）、F-P2-2（候选未变时 P 用候选 x，让"取消固定再 P 沿用编号"在单游标下真正可达；`dual_hidden_placement` 就用于这个判定，不再是只写不读）。
- hints/quickref 同步：`cursor.pin_*` 三条保持；删「可撤销一次」；新增一条「P 的提示在底部状态条」不必——toast 自解释，不加文案。
- Gate：`tests/ui/test_chart_stack.py`（当前红的 corner 用例**不改测试**转绿 + 新增 pinned 角色对偶用例）· `test_cursor_pill_formatting.py` · `test_cursor_table_geometry.py` · `test_pinned_cursor_interaction.py` · `test_pinned_cursor_panels.py` · `test_hints.py` · `test_quickref.py` · `test_quickref_status_hints.py`；护栏 `tests/ui_kit/test_qss_border_shorthand.py`、`test_no_lambda_signal_connections.py`。

### T4 — P1：意图失效语义与 scope_id

- Owner：`pinned_cursor_controller.py`、`view_bridge.py`、`analysis_view_bridge.py`、`project_io.py`。
- 做：F-P1-4（`chart_rebuilt` 只标 unavailable）、F-P1-5（不铸造 scope_id）、F-P2-13（安装不投影，等数据就绪）、F-P2-3（generation 相同跳过 pending）。
- Gate：`test_pinned_cursor_lifecycle.py` · `test_view_bridge.py` · `test_analysis_view_bridge.py` · `test_project_session.py` · `test_view_state.py` · `test_analysis_view_state.py`。

### T5 — P1/P2：View 隔离修补

- Owner：`widgets/channel_tree.py`、`view_state.py`、`_view_mixin.py`、`inspector_sections/time_filter.py`、`window.py`、`_axis_handle.py`。
- 做：F-V1-1（普通组 id 改单调序号不复用，`inherit_chart_appearance_for_group_change` 解散时 pop 组 spec）、F-V2-1（`filt_enabled` 按 kind 投影成 `FilterSpec` 后再判；`test_restore_payload_keeps_zero_cutoff` 保留"控件值 0 可往返"但新增"0 Hz 不画伴随线"）、F-V2-2、F-V2-3、F-V2-5（正确性 bug，小改）、F-V2-6、F-V2-7、F-V2-9；F-V2-4（越界读私有属性）是结构问题，留 T9。
- Gate：`test_view_state_isolation.py` · `test_view_appearance_isolation.py` · `test_channel_axis_groups.py` · `test_subplot_shared_axis.py` · `test_time_filter_overlay.py` · `test_time_filter_panel.py` · `test_view_switch_integration.py` · `test_channel_widget_setters.py` · `test_axis_handle.py`；护栏 `test_main_window_state_ownership.py`。

### T6 — P2：画布侧几何与性能

- Owner：`pg_canvas/pinned_cursor_overlay.py`、`pg_canvas/cursor.py`、`cursor_display_model.py`、`chart_stack/stack.py`、`analysis_section_page.py`。
- 做：F-P1-6、F-P2-6、F-P2-7、F-P2-8、F-P2-9、F-P2-10、F-P2-4、F-P2-5、F-P2-17。
- Gate：`test_pinned_cursor_geometry.py` · `test_pinned_cursor_facts.py` · `test_pinned_cursor_capture.py` · `test_pg_cursor_placement.py` · `test_custom_x_cursor_contract.py` · `test_pg_line_canvas.py` · `test_frf_canvas.py` · `test_split_*.py`；护栏 `test_pg_canvas_backref_invariants.py`、`test_pg_timedomain_canvas.py::test_frame_paint_backstop_is_installed_on_real_canvas`。真机：20 pin × 6 子图连续拖动 p50/p95 与 `_project_axis_labels` 调用次数（计划 §11.1），offscreen 量不出。

### T7 — 版本与文档

- 做：F-P2-18、F-X-3、F-X-2。`APP_VERSION` 升 **v8.3.0**（D5），按 CLAUDE.md 扇出面同步 README · `docs/analyzer/README.md` Current Product Baseline · 五个帮助页 `meta.version`/`versionLabel`/`updated` + changelog 条目 · user-guide · `tools/build_windows_folder*.ps1` `$Version` · `tools/run_windows_exe.bat` `APPNAME` · `acquisition/runbooks/stage-8-pr4-bench.md` 构建路径 · 四个版本契约测试；`UnsupportedProjectVersion` 中文可操作文案；changelog 写明：P 固定、共轴/滤波/颜色/图表外观按 View 保存、工程格式 v4（旧版本无法打开新工程）、F-V2-10 非覆盖通道颜色改为按载入顺序取默认色。
- 版本升级放在 T1–T6 之后、T8 之前：先修完再升，避免带着 P0 发版。
- Gate：`tests/test_help_content.py` · `test_windows_build_script.py` · `test_packaging_imports.py` · `tests/ui/test_project_session.py`；`git diff --check`。纯文案部分不需要运行时测试。

### T8 — 集成门与平台验收

- 前置：T1–T7 全部完成且工作区稳定。先 `ps aux | rg pytest` 确认无并行全量；记录 HEAD 与脏范围。
- 全量：两条命令串行前台——`--ignore=tests/acquisition_ui` 主体 + 单独 `tests/acquisition_ui`。异常退出记 UNVERIFIED。见红先对既有红清单。
- macOS Cocoa 前台（人工，记录截图/几何）：A01/A02/A12（勾完通道不点击直接 P；<33 ms 移动后 P 线值同点；MarkupEditor 活跃时 P 不抢）、A09（取消固定→再 P 沿用编号；× 关闭后 toast 出现且 quickref 无撤销文案）、A10（20 pin 密集簇悬停展开可读）、A13（对数 FRF 非正频率显示"不可用"）、live 面板 `+/-` 在角落 / pinned 面板 `×` 在角落；View 隔离：A/B 同文件共轴解散不串 log/grid、低通 0 Hz 不画伴随线、分屏非聚焦改色不写聚焦 View；工程：v8.2.5 打开 v8.3.0 工程看到中文升级提示（用旧构建验）。
- Windows 100%/150%/200%：source 检查 + Full/Lite frozen，未执行记 UNVERIFIED。

### T9 — 结构治理（本轮不做，另立 spec/plan）

`PinnedCursorController` 五单元拆分（§3.1 末）、`_view_mixin` 越界读画布私有属性（F-V2-4/5）收口为画布公开 API、`hover` 每帧 QSS polish 与 resize 无合并（P3）。按 `docs/analyzer/specs|plans/2026-08-04-*` 的 spec+plan 范式走。

## 5. 不做的事 / 边界

1. 不修改 DSP、采样/插值、FFT 吸附、FRF 相位差定义（沿用两份实施契约的排除项）。
2. 不为了让 `test_cursor_pill_toggle_stays_pinned_to_top_right_corner` 通过而放宽阈值或改该测试（D3 已定按可见动作打包）。
3. `ssh-keygen` 私钥文件：本文只记录风险，**不读取内容**、不移动——由用户处理（F-X-1）。
4. 不在本轮把应用级 eventFilter 换成 QShortcut（D4），只修生命周期与范围。
5. 不做撤销关闭（D2）；不给 pin 引入哨兵 fid（D1）；不加任何新的全窗口快捷键。
6. 不因这两个提交把全量 suite 当例行门跑；T8 一次。
7. 不动 `docs/analyzer/specs|plans/` 历史文档正文；只在 `2026-09-18-pinned-cursor-implementation-plan.md` 状态行加一句"§7.4 源缺失保留意图 / §5 撤销关闭 → 被本文 D1/D2 取代"，与 followup plan 更新状态行的既有做法一致。

## 6. 未验收项（明确标 UNVERIFIED / UNKNOWN）

- macOS Cocoa 前台：ShortcutOverride 仲裁、`activeWindow` 语义、pin 线与活动线 1 px 对齐、簇标签/引线可见性、对数 FRF 显示、View 切换真实几何——**全部 UNVERIFIED**（offscreen 只当排版草稿）。
- Windows：ShortcutOverride 在 Windows 平台插件的派发、100%/150%/200% DPI——**UNKNOWN**。
- 性能：单 host 下应用级 filter 对 `benchmark_timedomain_interaction --assert-standards` 的影响；20 pin pan/zoom p50/p95——**未测**。
- UltraView 已缓存与冷重绘像素一致（上一计划自认 UNVERIFIED，本轮未推进）。
- `chart_rebuilt` 在一次 `plot_channels` 内是否只发一次、发时所有 checked 通道已在 `_bound_identity_keys`（F-P1-4 在正常切 View 时是否会误删）——代码推断，未运行时复现。
- 全量 suite 对当前快照的结果——**未跑**。

## 7. 本次交付边界

只交付本文件。审查用到的探针（filter 累积计时、open_project pin 泄漏）放在 `/tmp`，未入库；T0 要把它们固化为测试。已核对文档引用、文件/符号行号、分级一致性与 `git diff --check`。
