# TraceLab 标准桌面交互 Review 修复 Plan

- 日期：2026-09-02
- 基线：`40a7075e`
- 状态：IMPLEMENTED（独立平台门禁见 §11）
- 来源：Grok 实现后代码 review 与针对性交互探针
- 关联 Spec：`docs/analyzer/specs/2026-09-02-standard-desktop-interaction-contract-spec.md`
- 被修复实现：`docs/analyzer/plans/2026-09-02-standard-desktop-interaction-contract-plan.md`

## 1. 目标与产品决定

本 Plan 只收口已确认的交互缺陷，不扩展新功能：

1. 删除主窗口最顶部新增的 File / Edit / View / Help 菜单栏；现有紧凑工具栏和界面层级保持不变。
2. 保留 command registry 与 Open/Save/SaveAs 的单一 QAction owner，继续服务现有工具栏和标准快捷键。
3. 修复项目 clean baseline、Undo 回保存点、Esc 分层和当前 section Ctrl+Tab。
4. 用真实 MainWindow 生产路径验证退出/项目替换保护，不能再用测试环境变量绕过。

非目标：数据计算、绘图数学、WWT 首帧、Batch、UltraView Board 数据模型、全局 QUndoStack 重构、Ctrl/Cmd+W。

## 2. 已确认缺陷与验收

| ID | 缺陷 | 用户影响 | 修复后验收 |
|---|---|---|---|
| SDR-R01 | 无条件安装顶部菜单栏 | 界面多一层且不符合产品要求 | 主窗口无 `menuFile/menuEdit/menuView/menuHelp` 可见 surface，现有工具栏不变 |
| SDR-R02 | 菜单 View/Undo 命令无 handler | 点击无反馈，形成假功能 | 删除可见死入口；保留的 action 必须有 owner 或 disabled |
| SDR-R03 | 打开 B 项目继承 A digest | 刚打开就可能提示未保存 | A save→B open→leave 不提示；B 修改后提示 |
| SDR-R04 | fresh open 无 digest baseline | revision 漏报时无 semantic fallback | restore 完成建立当前 payload baseline |
| SDR-R05 | Undo 回保存点仍 dirty | 退出时错误提示保存 | edit→save→edit→undo clean；redo dirty |
| SDR-R06 | 空搜索框吞 Esc | dialog/搜索 surface 无法按标准方式取消 | 非空先清空；下一次只关闭一层或 dialog reject |
| SDR-R07 | Ctrl+Tab 依赖 tab 焦点 | 图表/Inspector 操作中快捷键失效 | 当前 section 内普通焦点均可切 View；modal/inline editor 不穿透 |
| SDR-R08 | pytest 绕过真实 closeEvent | green tests 无法证明生产退出保护 | 真实 MainWindow closeEvent 覆盖 Save/Discard/Cancel、重入和 teardown 顺序 |

## 3. 依赖波次

~~~
Wave 0  本 Plan + 红测合同
   ├── Wave 1A  command surface / Ctrl+Tab owner
   ├── Wave 1B  dirty baseline / save-point owner
   └── Wave 1C  SearchField / Esc host owner
             ↓
Wave 2  coordinator integration + real MainWindow close test + docs/help sync
             ↓
Wave 3  focused/boundary/integration/foreground gates
~~~

并行 agent 不运行全量 suite，不改同一 owner 之外的文件，不接触预先存在的资产删除和 View overflow 文档修改。

## 4. Wave 1A — Command surface 与当前 section View 快捷键

### Owner

- `mf4_analyzer/ui/main_window/command_coordinator.py`
- `mf4_analyzer/ui/main_window/window.py` 的 command 初始化窄 hunk
- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/view_tabbar.py`
- `tests/ui/test_standard_desktop_interactions.py`
- 必要时 `tests/ui/test_open_and_save_entry.py`、`tests/ui/test_view_tabbar.py`

### 实现合同

1. MainWindow 不调用或不创建顶部菜单栏；不得用隐藏空白 menu bar 代替删除。
2. command registry 保持 Qt-metadata-only；Open/Save/SaveAs/Find/QuickRef/Quit 的现有快捷键 owner 不重复。
3. 删除菜单后清理 `_menus_installed`、菜单列表等无用投影代码；若兼容测试需要 API，API 必须 no-op 且不得创建 QWidget。
4. Ctrl+Tab/Shift+Ctrl+Tab 在当前可见 section 的 host scope 路由到既有 `_switch_view` / `_on_analysis_switch`。
5. modal dialog、View inline rename、销毁/隐藏 surface、IME 输入期间 fail closed；一次按键只切一次。
6. F2 和 Alt+Up/Down 可继续由 ViewTabBar 局部 owner 管理，不借机全局化。

### 红测

- `test_main_window_does_not_install_top_menu_bar`
- `test_no_visible_enabled_action_is_unrouted`
- `test_ctrl_tab_cycles_current_section_from_chart_focus`
- `test_ctrl_shift_tab_cycles_current_section_from_inspector_focus`
- `test_ctrl_tab_does_not_escape_modal_or_inline_rename`
- `test_ctrl_tab_switches_once_with_hidden_sections`

### 停止规则

- 需要 ApplicationShortcut 抢占 modal/text owner；退回 section/window scope重新设计。
- 为 Ctrl+Tab 复制 View switch 状态变更；必须复用既有 intent owner。
- 删除菜单导致现有工具栏 Open/Save/SaveAs 不再共用 QAction；先修绑定，不恢复菜单。

## 5. Wave 1B — Project clean baseline 与 Undo/save-point

### Owner

- `mf4_analyzer/ui/main_window/project_dirty.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`（仅确有需要）
- `tests/ui/test_project_dirty_guard.py`
- 必要时 `tests/ui/test_project_session.py`

### 实现合同

1. 新增显式“采用已恢复 clean session”入口，原子重置 revision/save point/path/digest/token；不能用多处字段直写。
2. `open_project` 在 restore payload、fid remap、View/analysis/UltraView 状态完成后，依据当前可保存 payload 建立 baseline；A 的 digest 不能进入 B。
3. render/project projection 在 restore guard 内不计用户 mutation；不得改变 deferred analysis recompute 次序。
4. leave decision 在有 baseline 时使用同一 canonical serializer 复核。revision 漏报不能静默放行，revision 已变但 payload 回到保存态不能假 dirty。
5. Undo/Redo reconciliation 不进入 paint/replot；UltraView rejected mutation、空 history、selection-only 都不写 dirty。
6. save cancel/failure、degraded restore health 和 Save-As 行为保持原合同。

### 红测

- `test_open_b_replaces_a_clean_digest_and_revision_session`
- `test_fresh_open_seeds_canonical_digest_baseline`
- `test_open_then_leave_without_edit_is_clean`
- `test_edit_save_edit_undo_to_same_payload_is_clean`
- `test_redo_after_reconciled_save_point_is_dirty`
- `test_rejected_ultraview_undo_does_not_change_dirty`
- `test_restore_projection_does_not_advance_revision`

### 停止规则

- 需要在 paint/replot 热路径计算项目 digest；停止并回到低频 reconciliation。
- 需要复制或近似 project serializer；必须调用 canonical save-path payload。
- 为修 dirty 改变 analysis restore/compute、fid identity 或 UltraView Board history 模型；缩回 owner seam。

## 6. Wave 1C — SearchField 与 Esc 分层

### Owner

- `mf4_analyzer/ui_kit/widgets/search_field.py`
- `mf4_analyzer/ui/quickref_panel.py`
- `mf4_analyzer/ui/dialogs/channel_editor.py`
- `mf4_analyzer/ui/widgets/channel_config_manager.py`
- 其他 SearchField host 仅在真实红测证明需要时修改
- 对应 focused tests

### 实现合同

1. 非空 SearchField 按 Esc：只清空、保留焦点、接受事件。
2. 空 SearchField 按 Esc：交给明确 host 解除下一层；QDialog reject，QuickRef close+restore opener，嵌入式搜索没有可关闭层时 no-op。
3. 同一次按键不能既清空又关闭宿主；宿主关闭后不能继续穿透到项目/MainWindow。
4. Enter 仍留在搜索域，不触发邻近 Import/Create/Save/default button。
5. 不新增全局 key filter，不改变独立 UltraView/Batch tool-window Return 例外。

### 红测

- `test_channel_editor_empty_search_escape_rejects_dialog`
- `test_channel_config_empty_search_escape_rejects_dialog`
- `test_quickref_escape_clears_then_closes_exactly_one_layer`
- `test_embedded_search_empty_escape_is_safe_noop`
- `test_search_return_does_not_trigger_dialog_default`

### 停止规则

- 需要 SearchField 猜测任意祖先类型或直接调用 MainWindow；改用显式 host contract。
- 一次 Esc 同时产生 clear 和 reject/close；拆回两阶段。
- 修复一个 dialog 却让其他共享 SearchField host 吞键；补 host matrix 后再继续。

## 7. Wave 2 — 集成与真实关闭路径

协调者串行完成：

1. 合并三条 owner patch，先跑每条 focused tests，再解决共享 `window.py`/测试文件冲突。
2. 删除 `closeEvent` 对 `PYTEST_CURRENT_TEST` 的产品行为分支。测试通过 monkeypatch prompt/guard owner 避免 modal，不改变生产代码路径。
3. 用真实 `MainWindow.closeEvent` 验证：clean 直接 teardown；dirty+Cancel 零 teardown；Save failure 保持窗口；Discard teardown 一次；重入被拒绝。
4. 修订原 Spec §2/§10/§12：菜单栏要求被本次产品决定取代；帮助只描述真实可达入口。
5. 更新 `ui/hints.py`、`ui/quickref.py` 与 HTML help；不得保留“Help 菜单同时可达”等陈旧文案。
6. 修复 EOF 空行并运行 `git diff --check`。

## 8. 验证门禁

### Owner focused

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_project_dirty_guard.py \
  tests/ui/test_quickref_panel.py \
  tests/ui/test_dialogs.py \
  tests/ui/test_channel_config_manager.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_open_and_save_entry.py
~~~

### Boundary

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_main_window_state_holders.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_view_switch_reentrancy.py \
  tests/ui/test_wwt_initial_view_contract.py \
  tests/ui/test_ultraview_author_state.py \
  tests/ui/test_ultraview_author_multiselect.py
~~~

全量 suite 只由协调者在稳定 snapshot 上运行一次；记录 run 前后 HEAD 与 relevant dirty scope。异常退出、运行期间相关文件变化或重复并发 full gate 均为 `UNVERIFIED`。

## 9. 前台验收

macOS Cocoa 必须逐项验证：

1. 主窗口顶部无新增菜单栏，原工具栏高度和入口不变。
2. chart、Inspector、普通搜索焦点下 Ctrl+Tab/反向切换当前 section；dialog/inline rename 不穿透。
3. Channel Editor、Channel Config、QuickRef 的 Esc 每次只退一层。
4. A save→B open→直接退出无假提示；B 修改后有提示。
5. UltraView 修改→保存→修改→Undo 回保存态，退出无提示；Redo 后重新提示。
6. Save/Discard/Cancel 在窗口关闭和打开替换中行为一致，Cancel 发生在 worker/timer/tool-window teardown 前。

Windows Full/Lite frozen 是独立门禁；没有真实构建证据时明确写 `UNVERIFIED`，不得用 offscreen Qt 替代。

## 10. 完成定义

- SDR-R01～R08 均有会在旧实现失败、在新实现通过的行为测试。
- 用户可见顶部菜单栏消失，且无失效/重复快捷键。
- canonical dirty baseline 与 Undo/save-point 合同通过连续项目和真实关闭测试。
- owner focused、boundary、`git diff --check` 全绿。
- Cocoa 前台通过；Windows 状态明确。
- diff 仅包含本 Plan owner 文件，未夹带预存 dirty work。

## 11. 2026-09-02 执行记录

### 已合入 owner changes

- Wave 1B：`92dde88d` — fresh canonical project baseline、Undo/Redo save-point reconciliation。
- Wave 1C：`f7c8df23` — SearchField host 的 clear-first / close-second Esc。
- Wave 1A：`6826458c` — 删除顶部菜单投影、当前 section 的 Ctrl+Tab 路由。
- Wave 2：真实 MainWindow closeEvent 不再按 pytest 环境变量绕过；协调者测试和文档收口。

### 已通过证据

- dirty/Esc owner set：`137 passed, 18 warnings`。
- command/View owner set：`122 passed, 38 warnings`。
- 真实 MainWindow dirty close：`25 passed, 24 warnings`。
- project/session、state ownership、import、no-lambda、UltraView boundaries：`164 passed, 194 warnings`。
- WWT initial-view contract：`7 passed, 20 warnings`。
- 原生 Cocoa widget-path probe：`platform=cocoa menus=0 central_top=0 ctrl_tab=0->1 esc=clear_then_close close_guard=cancel_then_discard`。
- `git diff --check`：PASS。

### 独立未闭合门禁

- `tests/ui/test_view_switch_reentrancy.py`：单独运行在第 2 个测试 PASS 后 teardown 停滞；机器上已有四组同文件 pytest 进程停滞超过 14 小时。本次新进程只终止自身，结果记 `UNVERIFIED`，未把已输出 PASS 当套件通过。
- full suite：因同一 checkout 已存在上述并发 pytest，按项目“不重叠 full gate”规则未启动，记 `UNVERIFIED`。
- Cocoa 完整人工前台矩阵与 Windows Full/Lite frozen：`UNVERIFIED`；不能由 offscreen 或上述 Cocoa 核心探针替代。
