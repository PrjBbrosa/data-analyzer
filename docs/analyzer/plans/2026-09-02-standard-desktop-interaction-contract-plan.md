# TraceLab 常规桌面交互与快捷键统一实施计划

> 2026-09-02 review 状态：本 Plan 已由 Grok 执行，但顶部 File / Edit / View / Help
> 菜单栏产品决定已撤销，且 review 发现 dirty baseline、Undo/save-point、Esc 和 Ctrl+Tab
> 缺陷。后续修复以 `2026-09-02-standard-desktop-interaction-review-remediation-plan.md`
> 为准；本文保留为原始实施记录，不再作为完成证明。

- 日期：2026-09-02
- 状态：READY FOR IMPLEMENTATION（本轮只新增 Spec/Plan，未改产品代码）
- 计划基线：f07b6a7c
- 对应规格：[交互 Spec](../specs/2026-09-02-standard-desktop-interaction-contract-spec.md)
- 交付策略：先冻结冲突和焦点路由，再分 owner 实现；dirty guard 完成前不启用 Quit；
  最终由单一 coordinator 做集成与全量 gate

## 0. 实施结论与依赖图

本功能跨多个 UI surface，但必须按 owner 拆开，禁止形成一个万能键盘 event filter。
先建立可执行交互矩阵和 command registry，再并行修 dialog、局部 Undo/Redo 和键盘可达性；
项目 dirty/关闭保护依赖全局 command seam，最后统一帮助和平台验收。

~~~
T0 冻结现状、冲突矩阵和红测
 ├─→ T1 command registry + File/Edit/View/Help QAction ─┐
 ├─→ T2 dialog Enter / Esc 与安全 default ─────────────┤
 ├─→ T3 Undo/Redo owner 路由 + 图表 camera 迁移 ───────┤
 └─→ T4 搜索、列表、View 的键盘可达性 ────────────────┤
                                                        ├─→ T6 帮助同步与集成门禁
T0 ─→ T5 项目 dirty owner ─→ 保存/替换/退出 guard ─────┘
                                                               └─→ T7 Cocoa / Windows / 交付
~~~

- T1、T2、T3、T4 可在 T0 后由不同 agent 并行，但共享文件必须由 coordinator 串行合并。
- T5 的 holder/serializer seam 可与 T2-T4 并行；close/open/quit wiring 依赖 T1 QAction。
- T6 依赖最终 command ids、文案和 bindings 稳定。
- T7 是唯一 full-suite owner；其他 agent 只运行自己的 focused/boundary tests。

### 0.1 Spec 验收追踪

| Spec ID | 首要实现/红测 Task | 最终证据 |
| --- | --- | --- |
| SDI-A01 | T0、T2 | 三个 dialog 真实 Return key event |
| SDI-A02 | T0、T2 | 危险确认 default/escape 与零 mutation |
| SDI-A03 | T0、T2 | DB cell 与 tool-window 例外回归 |
| SDI-A04 | T0、T2、T3 | modal/inline/workspace 分层 Esc |
| SDI-A05 | T0、T4 | 搜索两阶段 Esc 与 focus return |
| SDI-A06 | T0、T3 | 文本焦点不穿透 owner matrix |
| SDI-A07 | T0、T3 | Markup/UltraView 全部 Qt bindings |
| SDI-A08 | T0、T3 | chart camera Alt+Left/Right 与 Undo 负断言 |
| SDI-A09 | T1、T5 | action 唯一 owner 与单次 signal |
| SDI-A10 | T0、T1 | SaveAs 空 binding fallback |
| SDI-A11 | T1、T6 | registry、menu、tooltip、help 一致 |
| SDI-A12 | T4 | View/list 键盘全路径 |
| SDI-A13 | T4 | focus-visible 与 mouse/keyboard 共用 intent |
| SDI-A14 | T5 | user mutation、save success/failure |
| SDI-A15 | T5 | restore/projection/runtime 状态负断言 |
| SDI-A16 | T1、T5 | quit/open-replace 共用 guard |
| SDI-A17 | T3、T5 | history clean index/save point |
| SDI-A18 | T1、T3、T7 | hide/destroy 生命周期与前台压力验收 |

## 1. 当前 worktree 保护与基线

计划编写时 main 相对 origin/main ahead 3，且已有大量 tracked/untracked 改动，包括：

- mf4_analyzer/ui/hints.py、quickref.py；
- mf4_analyzer/ui/main_window/window.py、_view_mixin.py、_analysis_mixin.py；
- mf4_analyzer/ui/view_state.py、view_tabbar.py、widgets/channel_tree.py；
- 对应 View/WWT tests、新 popup 和 2026-09-01 View close Spec/Plan。

这些均视为其他工作所有。每个执行 agent 必须：

1. Task 开始前记录 git status --short、owner 文件 diff 和 HEAD；
2. 只修改自己任务声明的文件；不还原、不格式化、不顺手修已有 diff；
3. hints.py、quickref.py、window.py 等重叠文件由 coordinator 最后串行落 hunk；
4. 无法证明 hunk ownership 时停止并协调，不覆盖已有工作；
5. 只按文件/逐 hunk stage，提交前用 cached diff 证明范围。

已完成的分析探针（不是实现验收）发现三个错误 implicit default，并验证当前 macOS Qt5
的 NativeText/Redo/SaveAs 行为。此前 focused 交互探针为 22 passed, 528 deselected；
实施者仍须先创建红测，不能把该结果当作新合同已通过。

## 2. Task 0 — 冻结现状、焦点优先级与红测

**目标：** 在生产代码改动前，把 Spec SDI-A01..A18 映射为可执行测试，并证明当前
冲突确实是红灯。

**Owner 文件**

- 新增 tests/ui/test_standard_desktop_interactions.py
- 扩展 tests/ui/test_dialogs.py
- 扩展 tests/ui/test_chart_stack.py
- 只在确需 owner harness 时窄改后续 Task 对应测试；不改生产代码

**步骤**

1. 建立 focus matrix fixture：QLineEdit、QTextEdit、dialog、chart card、Markup、
   UltraView、MainWindow 分别获取真实 focus，再发送 key click。
2. 用 signal spy/owner fake 记录一次输入调用了哪些 action；失败信息必须列出 active widget、
   shortcut context、命令 id 和调用次数。
3. 新增当前必红断言：
   - ChannelEditor Enter 只确认，不创建通道；
   - ChartOptions Enter 只确定，不打开颜色选择；
   - ChannelConfigManager 搜索框 Enter 不导入；
   - chart Ctrl/Cmd+Z 不 back，Alt+Left 才 back；
   - UltraView/Markup 注册全部 Qt redo bindings；
   - SaveAs 有 fallback；
   - QuickRef 搜索 Esc 先清空再关闭。
4. 冻结正向例外：DB reference cell Enter、UltraViewSheet Return、View inline rename、
   Pg range field Tab/Enter、UltraView 和 Markup layered Esc。
5. 对每个测试标注对应 SDI-Axx，并建立静态检查确保 Spec 所有 acceptance id 至少
   被一个 test 或明确的 foreground gate 引用。

**建议红测名称**

- test_channel_editor_return_activates_confirm_not_create
- test_chart_options_return_activates_ok_not_color_picker
- test_channel_config_search_return_never_activates_import
- test_destructive_dialog_default_is_safe
- test_text_focus_undo_does_not_reach_workspace_or_chart
- test_chart_camera_history_uses_alt_left_right_not_undo
- test_redo_registers_every_platform_binding_without_double_fire
- test_save_as_has_explicit_fallback_when_qt_binding_is_empty
- test_search_escape_clears_then_closes_and_restores_focus

**聚焦命令**

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_dialogs.py \
  tests/ui/test_chart_stack.py -q
~~~

**停止规则**

- 无法用真实 focus/key event 复现，只能直接调用 private slot；先补 harness，不开始实现。
- 同一按键在当前设计下存在两个都合理的 owner；回到 Spec 决策，不用调用顺序掩盖。
- 红测依赖当前机器键名字符串而非 QKeySequence 语义；先改成平台无关断言。

## 3. Task 1 — 统一 command registry、QAction 与菜单

**目标：** 建立一处命令定义和一条全局 action seam，让 toolbar、menu、tooltip 和帮助不漂移。

**Owner 文件**

- 新增 mf4_analyzer/ui/command_registry.py
- 优先新增 mf4_analyzer/ui/main_window/command_coordinator.py 或扩展现有明确 coordinator
- 修改 mf4_analyzer/ui/toolbar.py
- 修改 mf4_analyzer/ui/main_window/window.py（仅窄初始化/wiring hunk，由 coordinator 落盘）
- 新增/扩展 tests/ui/test_standard_desktop_interactions.py
- 必要时扩展 tests/ui/test_main_window_state_holders.py

**实现步骤**

1. 定义稳定 CommandId 和 immutable metadata；bindings 通过 Qt standard keys 的
   keyBindings 获取、去重，SaveAs 空列表时补 Ctrl+Shift+S。
2. 为 Open、Save、Save As、Quit、Undo、Redo、Find、Quick Reference、next/previous View
   创建一个 action owner；toolbar button 和 menu 复用 QAction 或同一 named slot。
3. 新建 File / Edit / View / Help 菜单。不要复制已有打开/保存实现；action 连接现有
   project IO owner seam。
4. action shortcut context 按 Spec 设置。Open/Save 等全局命令在 modal 打开时不穿透；
   Undo/Redo 交给 active edit owner，不直连某个固定 stack。
5. action text、tooltip 和状态栏提示使用 NativeText；对象名稳定，供测试和可访问性使用。
6. Quit action 在 T5 dirty guard 接入前保持 disabled/不发布；禁止先绕过 close protection。

**新增测试**

- test_each_global_command_has_exactly_one_qaction_owner
- test_toolbar_and_menu_trigger_same_named_slot_once
- test_standard_bindings_use_native_qkeysequence_semantics
- test_save_as_fallback_is_registered_once
- test_global_commands_do_not_fire_through_modal_dialog
- test_hidden_or_destroyed_surface_leaves_no_active_shortcut

**边界门禁**

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_main_window_state_holders.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_import_boundaries.py -q
~~~

**停止规则**

- registry 需要 import MainWindow、toolbar widget 或任何 live QUndoStack；拆回 metadata 层。
- 为新状态扩大 state-ownership whitelist；改用现有 holder/coordinator ownership。
- QAction 与 QShortcut 同时注册同一 scope/key 导致 ambiguous activation；保留唯一 owner。
- 必须用 Qt.ApplicationShortcut 才能让局部命令工作；先修 focus/scope，不扩大拦截面。

## 4. Task 2 — Dialog Enter / Esc 与默认按钮安全

**目标：** 修复隐式 autoDefault，并建立可重复使用但不过度抽象的 dialog 审核模式。

**Owner 文件**

- 修改 mf4_analyzer/ui/dialogs/channel_editor.py
- 修改 mf4_analyzer/ui/dialogs/chart_options.py
- 修改 mf4_analyzer/ui/widgets/channel_config_manager.py
- 只在审计发现同类确定性缺陷时修改其他具体 dialog
- 扩展 tests/ui/test_dialogs.py
- 扩展 tests/ui/test_channel_config_manager.py
- 保持 tests/ui/test_db_reference_settings.py、tests/ui/test_ultraview_mode_integration.py 例外门禁

**实现步骤**

1. 在三个已知 dialog 中显式设置唯一 default；其他 buttons 关闭 autoDefault。
2. 保持字段验证 owner。Enter 与点击主按钮必须经过同一 slot，不复制 validate/accept。
3. 审核危险 QMessageBox：default/escape button 显式安全；取消返回零 mutation。
4. 审核搜索、cell editor、多行文本和非模态 tool window，按 Spec §4 建立窄例外测试。
5. 若多个 dialog 确有完全相同设置，可新增只负责 button flags 的 helper；不得建立会吞掉
   任意 keyPress 的全局 Dialog 基类。

**新增测试**

- test_channel_editor_has_one_explicit_confirm_default
- test_chart_options_has_one_explicit_ok_default
- test_channel_config_manager_has_one_explicit_save_default
- test_validation_failure_keeps_dialog_open_and_focuses_first_error
- test_dangerous_confirmation_escape_and_return_are_safe
- test_db_reference_cell_return_does_not_accept_dialog
- test_independent_tool_window_return_does_not_close

**聚焦命令**

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_dialogs.py \
  tests/ui/test_channel_config_manager.py \
  tests/ui/test_db_reference_settings.py \
  tests/ui/test_ultraview_mode_integration.py -q
~~~

**停止规则**

- Enter 要通过按键位置或按钮创建顺序猜 owner；必须改成显式 default/slot。
- 为修一个 dialog 改 QSS/global event filter；回退到具体 dialog owner。
- Return 会关闭独立 tool window，或 cell editor Enter 接受父 dialog；不允许带回归合并。

## 5. Task 3 — Undo/Redo 路由与图表 camera 历史迁移

**目标：** 让 Undo/Redo 只操作 active edit owner，把图表导航完整迁移到 Alt+Left/Right。

**Owner 文件**

- 修改 mf4_analyzer/ui/chart_stack/_helpers.py
- 修改 chart toolbar/action owner 的对应实现文件
- 修改 mf4_analyzer/ui/chart_stack/ultraview/page.py
- 修改 mf4_analyzer/ui/markup/editor.py
- 必要时修改 command coordinator 的 active-owner adapter
- 扩展 tests/ui/test_chart_stack.py
- 扩展 tests/ui/test_ultraview_page.py、tests/ui/test_ultraview_board_history.py
- 扩展 tests/ui/test_markup_editor.py

**实现步骤**

1. chart Back/Forward 改绑 Alt+Left/Right；按钮、history、branch truncation、Home reset
   保持原 owner 和行为。
2. 从 chart scope 完全移除 Undo/Redo bindings，增加负断言，不保留隐式兼容执行。
3. UltraView 注册 keyBindings(Undo/Redo) 的去重集合；所有 shortcut 进入现有文本焦点、
   tool state、selection mutation plan 和 history guard，不创建第二条 Board writer。
4. Markup 使用同一平台 bindings，保持其 QUndoStack；文本 item 正在编辑时按文本 owner，
   crop/paste/group item 继续是一条原子 command。
5. command coordinator 只解析 active owner 和 enablement；实际 undo/redo 仍由 owner 执行。
6. 当 stack 回到 save point 时向 T5 dirty holder 发布 clean transition；programmatic projection
   和 rejected mutation 不发布 history/dirty。

**新增/扩展测试**

- chart：Alt+Left/Right back/forward、new gesture truncates forward、Ctrl/Cmd+Z 零导航。
- UltraView：两类 redo alias 都工作；文本焦点、非法 mixed mutation、空 history 均不改 Board；
  single gesture/smart layout 仍只撤销一次。
- Markup：文本编辑不穿透；delete/move/style/crop/group paste 继续一笔一撤销；空 paste
  不增加 entry。
- 集成：同一 key event 只命中一个 owner；关闭/隐藏 editor 后 owner 对称清除。

**聚焦命令**

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_board_history.py \
  tests/ui/test_markup_editor.py -q
~~~

**适用 lessons 门禁**

- Markup scene traversal 保持 group-child normalization；不能为快捷键另写未规范化选择路径。
- UltraView mixed selection 先形成一份 Qt-free mutation plan，失败时 history/dirty 都不写。
- UltraView viewport router 仅处理 CanvasHost 已定义手势，文本 space 和未处理 key 正常传播。

**停止规则**

- 需要把 chart camera state 塞入编辑 QUndoStack；保持两个历史域分离。
- 一个 mixed operation 产生多条 history，或部分 mutation 失败但另一部分已写入；停线修原子性。
- 为支持 redo alias 在 keyPressEvent 和 QShortcut 各处理一次；只能保留一个执行入口。
- Markup 改动破坏 grouped number/crop/paste 既有测试；先恢复 normalization。

## 6. Task 4 — 搜索、文件/配置列表与 View 键盘可达性

**目标：** 为 mouse-only/drag-only 关键流程提供同 owner 的键盘路径和可见焦点。

**Owner 文件**

- 修改 mf4_analyzer/ui_kit/widgets/search_field.py
- 修改 mf4_analyzer/ui/quickref_panel.py
- 修改 mf4_analyzer/ui/file_navigator.py
- 修改 mf4_analyzer/ui/widgets/channel_config_manager.py（与 T2 串行合并）
- 修改 mf4_analyzer/ui/view_tabbar.py（当前有其他 dirty diff，由 coordinator 串行处理）
- 扩展 tests/ui/test_quickref_panel.py
- 扩展 tests/ui/test_file_navigator.py
- 扩展 tests/ui/test_channel_config_manager.py
- 扩展 tests/ui/test_view_tabbar.py

**实现步骤**

1. SearchField 提供 escape_requested/明确 helper：有文本先 clear 并消费；空文本再请求 host
   close。Host 负责 focus return，不让通用 SearchField import QuickRef。
2. 文件行进入 tab/focus chain；Up/Down、Enter/Space、Delete、Alt+Up/Down 发 typed intent，
   复用现有 remove/reorder/open owner，不直接操作 MainWindow session。
3. Channel Config table 和 checkbox 移除不必要的 NoFocus/NoSelection，设计清晰的 row/current/
   checked 区别；Space 切换、Delete 移除草稿项、Alt+Up/Down 重排，一次操作一条 draft history。
4. ViewTabBar 增加 Ctrl+Tab/Shift+Ctrl+Tab 和 F2；复用 manager current/reorder/rename intents，
   不使用显示名作为 identity。
5. 给所有新 focusable item 设置 accessible name、focus reason 和 visible focus QSS；验证鼠标
   路径没有双触发或几何回归。

**新增测试**

- test_search_escape_clears_before_host_close
- test_search_second_escape_closes_and_returns_focus_to_opener
- test_file_rows_are_keyboard_reachable_and_use_existing_intents
- test_file_delete_cancel_is_zero_mutation
- test_alt_up_down_reorder_preserves_stable_identity
- test_channel_table_space_and_delete_modify_draft_only
- test_ctrl_tab_cycles_current_section_views_and_f2_renames
- test_focus_ring_is_visible_for_keyboard_focus

**聚焦命令**

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_quickref_panel.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_channel_config_manager.py \
  tests/ui/test_view_tabbar.py -q
~~~

**停止规则**

- keyboard path 调用与 mouse path 不同的 mutation 实现；改为同一 typed intent/slot。
- focusable row 破坏 close button hit region、View tab geometry 或 overflow；不得扩大布局补偿。
- Delete 在无 focused selection 时仍删除 active/global item；必须 fail closed。
- View 切换或程序化 list projection 被误记为用户 edit/dirty。

## 7. Task 5 — 项目 dirty owner 与保存/替换/退出保护

**目标：** 用一个项目语义 owner 判断未保存状态，并让所有离开路径共用一次安全决策。

**Owner 文件**

- 优先修改 mf4_analyzer/ui/main_window/_state_holders.py，或新增窄的
  mf4_analyzer/ui/main_window/project_dirty.py
- 修改 mf4_analyzer/ui/main_window/_project_io_mixin.py
- 修改 mf4_analyzer/ui/main_window/window.py（仅 guard/closeEvent 窄 hunk）
- 修改真实 project serializer owner；只在 characterization 证明必要时抽取 canonical payload
- 扩展 tests/ui/test_project_session.py
- 扩展 tests/test_project_io.py
- 扩展 tests/ui/test_main_window_state_holders.py
- 新增 tests/ui/test_project_dirty_guard.py（若现有文件无法清晰承载）

**Task 5A：先清点真实持久化语义**

1. 列出当前 project payload 全部稳定字段及写入 owner；区分 project state、用户偏好、
   runtime cache、selection/preview/job state。
2. 为 serializer 建 characterization test：同一语义不同 dict/list 构建顺序 digest 相同；
   runtime-only 状态变化 digest 不变。
3. 优先复用保存路径的 canonical payload。若当前构建内联且含 IO/Qt 对象，先提取一个
   Qt-free semantic snapshot builder，并保持已有 roundtrip 完全一致。
4. 建立 restore guard：project load/View apply/widget projection 期间 intent handlers fail closed，
   恢复完成后只设 save point，不发布 user mutation。

**Task 5B：dirty state holder**

1. holder 显式初始化 revision/save point/path/restore depth；reset/clear/load/save 对称。
2. 已有明确 mutation funnels（ViewManager、UltraView workspace、analysis settings、markup/project
   annotations 等）发布 semantic mutation；禁止在每个 widget setter 里散写 dirty=True。
3. successful save 更新 save point；失败、取消不更新；Undo/Redo 根据 stack clean index 或
   canonical digest 更新。
4. 在 close/open-replace 决策点做 canonical digest 低频复核，防止漏接旧 mutation seam；
   不在 paint/replot hot path 计算 digest。

**Task 5C：共用 guard**

1. 实现一个返回明确枚举/result 的 guard：PROCEED_SAVED、PROCEED_DISCARDED、CANCELLED。
2. window close、Quit QAction、打开另一个项目都调用同一 guard；guard 自身不销毁窗口。
3. Save 需要路径时调用 Save As；picker cancel/IO failure 返回 CANCELLED 并保留当前工作区。
4. closeEvent 先 guard，接受后才执行当前 worker/timer/tool-window teardown。防止 reentrant
   close 和双 dialog。
5. “不保存”必须是用户明确动作；default 是保存，Esc/cancel 为取消。

**新增测试**

- test_user_project_mutation_marks_dirty_once
- test_programmatic_view_projection_does_not_mark_dirty
- test_selection_render_preview_and_job_progress_do_not_mark_dirty
- test_successful_save_sets_clean_save_point
- test_failed_or_cancelled_save_keeps_dirty_and_current_project
- test_undo_to_save_point_is_clean_and_redo_is_dirty
- test_open_replacement_uses_same_save_discard_cancel_guard
- test_close_cancel_happens_before_workers_or_tool_windows_stop
- test_reentrant_close_shows_one_prompt_and_tears_down_once
- test_canonical_digest_matches_project_roundtrip_and_excludes_runtime_keys

**聚焦命令**

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_project_dirty_guard.py \
  tests/ui/test_project_session.py \
  tests/test_project_io.py \
  tests/ui/test_main_window_state_holders.py \
  tests/ui/test_view_switch_reentrancy.py \
  tests/ui/test_wwt_initial_view_contract.py -q
~~~

若未新建 test_project_dirty_guard.py，从命令中删除该路径并在执行记录中说明测试落点。

**适用 lesson 门禁**

- programmatic View projection 不是 user intent。恢复事务内的 widget signals 不能 capture、
  replot 或 dirty；真实交互 merge/split 仍正常发布一次。
- UltraView mutation 只有成功写入 live Board/history 后才 dirty；rejected plan 零 dirty。

**停止规则**

- 只能靠散布到多个 mixin 的 dirty 标志才能覆盖功能；先建立 single owner/funnel。
- canonical digest 与实际保存 payload 不是同一语义来源；不得维护平行 serializer。
- restore/load 会产生 dirty 闪烁或覆盖半应用状态；先修 projection guard。
- close cancel 后已有 worker/timer/tool window 被停止或关闭；调整事务顺序后再继续。
- 需要扩大 test_main_window_state_ownership.py whitelist；修 ownership，不放宽 ratchet。

## 8. Task 6 — Hints、QuickRef、菜单文案与集成门禁

**目标：** 让实际 binding、平台显示和用户帮助由同一 command metadata 投影，并完成跨 owner
冲突检测。

**Owner 文件**

- 修改 mf4_analyzer/ui/hints.py（当前 dirty，由 coordinator 合并）
- 修改 mf4_analyzer/ui/quickref.py（当前 dirty，由 coordinator 合并）
- 必要时修改主帮助 deck 的现行交互页；不重写 dated historical docs
- 扩展 tests/ui/test_hints.py、tests/ui/test_hint_nudges.py
- 扩展 tests/ui/test_quickref.py、tests/test_help_content.py
- 扩展 tests/ui/test_standard_desktop_interactions.py

**精确文案要求**

- 图表：Alt+Left / Alt+Right：视角后退 / 前进；Ctrl/Cmd+Z 保留给编辑撤销。
- 撤销：说明只作用于当前编辑区域；无 history 时不回退图表。
- 搜索：Esc 先清空搜索，再按一次关闭。
- 文件/列表：保留鼠标入口，同时补 Enter/Space、F2、Alt+Up/Down 的可发现提示。
- 保存保护：只说明“有未保存更改时可保存、不保存或取消”；不要承诺未实现的全局撤销。

**静态/行为验证**

1. 搜索旧 back=Ctrl+Z、Ctrl+Shift+Z 单一 redo 声明和散落快捷键文本；除兼容迁移说明/
   测试 fixture 外不得残留冲突语义。
2. 对 registry 每个 user-visible command，比较 QAction shortcuts、tooltip NativeText、hint
   token 和 quickref token。
3. 运行 focus matrix，证明 modal/text/local workspace/chart/global 的一次执行与优先级。

**聚焦命令**

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_hints.py tests/ui/test_hint_nudges.py \
  tests/ui/test_quickref.py tests/ui/test_quickref_panel.py \
  tests/test_help_content.py -q
~~~

**停止规则**

- QuickRef 宣称运行时未注册的 key，或 tooltip 与 QAction 不一致；以 runtime registry 修正，
  不放宽文案测试。
- 为简化文案删除入口、关键限制或异常提示；保留这些，详细矩阵移入帮助页。
- hints.py/quickref.py 当前 dirty hunk 无法归属；停止并交 coordinator 逐 hunk 合并。

## 9. Task 7 — 集成、平台前台与交付验收

**目标：** 在稳定 snapshot 上证明键盘路由、dirty 事务、Qt 生命周期和跨平台显示闭环。

### 9.1 聚焦 owner gate

~~~
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_dialogs.py tests/ui/test_channel_config_manager.py \
  tests/ui/test_chart_stack.py tests/ui/test_markup_editor.py \
  tests/ui/test_ultraview_page.py tests/ui/test_ultraview_board_history.py \
  tests/ui/test_quickref_panel.py tests/ui/test_file_navigator.py \
  tests/ui/test_view_tabbar.py tests/ui/test_project_dirty_guard.py \
  tests/ui/test_project_session.py tests/test_project_io.py \
  tests/ui/test_hints.py tests/ui/test_hint_nudges.py \
  tests/ui/test_quickref.py tests/test_help_content.py -q
~~~

按实际测试落点删去不存在的新文件，但不得因此漏掉对应 SDI-Axx。

### 9.2 边界护栏

~~~
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_state_holders.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_ultraview_structure.py \
  tests/ui/test_ultraview_viewport_router.py -q
~~~

### 9.3 单一 full-suite milestone

本改动跨 MainWindow、dialog、chart、Markup、UltraView 和 persistence，属于跨边界集成，
在相关 source 不再变化后由 T7 coordinator 运行一次 full gate。先记录 HEAD 和 dirty
fingerprint，确认同 checkout 无其他 pytest；按仓库规定顺序执行且不得并发：

~~~
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
~~~

运行后再次记录 HEAD 和 relevant dirty scope。测试期间 source 变化、异常退出、segfault、
timeout 或中断均记 UNVERIFIED，不能按已完成用例推断 pass。

### 9.4 macOS Cocoa 前台清单

使用真实入口：

~~~
./.venv/bin/python -m mf4_analyzer.app
~~~

逐项录屏/记录：

1. 三个已知 dialog 中 Enter 的 default focus ring 和实际动作一致；危险确认默认安全；
2. 中文 IME、QLineEdit、QTextEdit、表格 cell 中 Enter/Esc/Undo/Redo 不穿透；
3. chart Option+Left/Right 导航且 Command+Z 不导航；Markup/UltraView 的 Undo 和两类
   redo binding 按 Qt 结果工作且不双执行；
4. Open、Save、Save As、Quit 的 menu label、tooltip 和运行时一致；
5. QuickRef 搜索 Esc 两阶段、Ctrl+Tab View 切换、F2、Space、Alt+Up/Down 和 focus ring；
6. dirty 项目分别执行 Save、Discard、Cancel，再测试打开替换与系统窗口关闭；Cancel 后
   worker、工具窗和项目原状保留；
7. Markup、UltraView、popup、dialog 重复开关 20 次，无 stale shortcut、双 dialog、
   QAction ambiguous warning、crash 或后台窗口抢键。

证据写入 docs/analyzer/verify/，记录 APP_VERSION、HEAD、dirty scope、macOS/Qt 版本、
输入法和键盘布局。Offscreen 结果不能替代该证据。

### 9.5 Windows frozen 清单

分别验证 Full 与 Lite 新构建：

- Ctrl labels、menu accelerators 和实际按键一致；
- Ctrl+Y 与 Ctrl+Shift+Z redo bindings 按 Qt 平台结果工作且不双执行；
- Alt+Left/Right 不被系统菜单或 Web-like navigation 抢占；
- native file dialog cancel 后 dirty/current project 保留；
- Alt/F10 菜单键、Tab、Space、F2、Delete 和 focus rectangle 可用；
- 退出/替换 Save/Discard/Cancel 与 macOS 语义相同。

只做 source-level packaging 检查不能替代 fresh frozen acceptance。

### 9.6 交付卫生

~~~
git diff --check
git status --short
git diff --name-only
git diff --cached --name-only
~~~

仅 stage 本计划 owner 文件。若交付需要 commit/push，按 Task 分批提交并验证 cached diff
和 remote convergence；不得夹带计划开始前的资产删除、View close、WWT 或其他 dirty work。

## 10. 建议提交拆分

1. test(ui): freeze standard desktop interaction routing
2. feat(ui): centralize standard commands and menu actions
3. fix(ui): make dialog return and escape behavior explicit
4. feat(ui): route undo redo to the active edit owner
5. feat(ui): add keyboard paths for search lists and Views
6. feat(project): guard unsaved work on replace and quit
7. docs(ui): align hints and quick reference with runtime shortcuts
8. test(ui): close cross-platform shortcut and dirty-state gates

共享 dirty 文件无法安全拆分时允许 coordinator 合并相邻实现提交，但测试冻结提交必须先于
实现；任何提交均不得带入预先存在的 unrelated changes。

## 11. 回滚边界

- command/menu 回归：回退 T1 action projection，保留原 toolbar slots；不得恢复 chart Ctrl+Z
  冲突来补偿。
- dialog 回归：逐 dialog 回退 explicit default hunk，不动其他 owner。
- Undo 路由回归：局部关闭新增 bindings，保留既有 owner history 数据；不得清空用户历史。
- keyboard reachability 回归：关闭新增 typed intents，不删除原鼠标路径。
- dirty guard 回归：禁止发布 Quit/replace 新入口，保留保存能力；不得通过默认为 Discard 绕过。
- 帮助回归：以实际 runtime registry 为真修正文案，不保留不存在的快捷键承诺。

## 12. Definition of Done

- [ ] SDI-A01..A18 每项有自动化或明确前台证据，Spec/Plan/test 映射无缺口；
- [ ] dialog Enter/Esc 全部显式，三个已知 implicit default 缺陷关闭，既有例外不回归；
- [ ] Undo/Redo 只到 active edit owner，chart camera history 已迁移到 Alt+Left/Right；
- [ ] Open/Save/SaveAs/Quit/menu/toolbar 各只有一个 action owner，无双执行；
- [ ] 文件、配置、搜索、View 关键流程有键盘路径、visible focus 和 accessible name；
- [ ] project dirty 单 owner，save point、restore guard、退出/替换事务测试全绿；
- [ ] hints.py、quickref.py、tooltip、menu 与 runtime NativeText 一致；
- [ ] focused tests、边界 ratchets、单次稳定 full gate 通过；
- [ ] macOS Cocoa 与 Windows Full/Lite frozen 验收分别有证据，未验证项明确标 UNVERIFIED；
- [ ] final diff 只含本 feature，未覆盖或提交任何预先存在的 unrelated dirty change。
