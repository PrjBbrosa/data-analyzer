# UltraView 逻辑与接线修复实施计划

- 日期：2026-08-13
- 状态：待执行
- 规格：`docs/analyzer/specs/2026-08-13-ultraview-logic-wiring-review-spec.md`
  （问题编号 A1–A7 / B1–B8 / C / D1 / E1–E4 / F1，验收 UVL-A01…A21 均指该文件）

## 0. 执行前置与边界

1. **工作区对账**：当前 worktree 有未提交的 view-rail-dock 入口实现（含未跟踪
   `ui/widgets/ultraview_entry.py`、`tests/ui/test_ultraview_entry.py`）与三对未跟踪
   spec/plan。执行者动手前 `git status --short` 存档，逐文件只碰本计划列出的
   hunks；**不得覆盖或顺带提交在途改动**。若入口改动已被他人提交，按届时 HEAD
   重新定位行号。
2. **基线**：2026-08-13 聚焦套件 227 passed（offscreen）。先复跑记录你自己的
   pre-change 基线，失败先分类（既有 debt vs 本计划前置），不得绕过。
3. 修复统一走「先写 RED 契约测试 → 修代码 → 绿」；**测试红了修代码，不放宽护栏**。
4. Qt 测试环境统一：

   ```bash
   TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <targets> -q
   ```

5. 任务间依赖：Task 2/3 同文件高耦合，顺序执行；Task 1、4、5、7、8、9 相互独立
   可并行；Task 6（残留清理）放在 coordinator 类任务之后，避免 diff 打架；
   Task 10（回归收口）最后。

## Task 1 — 面板落点与 armed 语义（A1/A2/A3/A4 → UVL-A01…A04）

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `tests/ui/test_ultraview_page.py`

**测试先行**

1. 参数化各布局：库有选中 + 点击空槽 X → 收到
   `replace_slot_requested(X, section, view_id)`（空槽时占用者为 None，等价放置）。
2. `BoardGrid` 构造 drop 事件落在 BOARD_PADDING/槽间缝：断言不发任何 intent 信号。
3. armed 后模拟 `kind="card"` 拖拽互换、`kind="tray"` 放置：断言变更执行后
   `replacement_slot()/replacement_ref()` 为 None；随后 `_emit_add` 走纯添加。
4. Board 满 + 托盘「放置」/ 库添加：断言发出一次可见反馈（toast spy 或 hint 文案）。

**实现**

1. `_on_empty_slot(slot_id)` 保留槽位：库有选中 → `replace_slot_requested`；armed
   流程仍优先（`_finish_armed_replacement` 语义不变，但目标槽用点击槽覆盖
   `_replacement_slot` 为 None 的场景需在测试里钉住取舍并写注释）。
2. `BoardGrid.dropEvent`：`slot_id_at` 为 None → return（删除 `slots[0]` 回退）。
3. `_on_ref_dropped`：armed 分支落穿前统一 `clear_replacement_arm()`。
4. 反馈文案走 coordinator toast 路由（Task 4 完成前先经现有 `_toast`，Task 4 会
   自动纠正宿主）。

**Exit gate**：新增契约测试全绿；`test_ultraview_page.py` 既有用例零回归。

## Task 2 — 游标/pill 快照语义（B1/B5 → UVL-A07/A11/A17）

**修改**

- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/main_window/ultraview_runtime.py`
- `tests/ui/test_ultraview_capture.py`（**含改掉 :570-574 被钉错的断言**）

**测试先行**

1. RED：单游标模式 + hover 线可见 → grab 期间该线被隐藏（对照 dual 武装线保持
   可见的既有断言）；hover x 变化不改变 `current_digest_for(ref)`。
2. RED：dual 武装游标 View 捕获后把画布重绑到另一 ref → 原 ref
   `derive_preview_status` 仍 FRESH（几何从 ledger 回读）。
3. RED：pill 可见时捕获 → 隐藏源页（模拟切模式）→ `current_digest_for` 不变、
   状态仍 FRESH（pill 指纹从 ledger 回读，UVL-A17）。

**实现**

1. `_iter_transient_overlay_items`：single 模式的 `_cursor_line_items/_cursor_lines`
   一律并入 transient 集（删除 `_host_is_dual_cursor` 的 dual-only 门控对 hover
   线的豁免）；dual 武装线保持豁免。
2. `_cursor_geometry_from_host`：删除 single 分支（或仅当画布暴露「已武装单游标」
   的显式 API 时保留——当前产品不存在该状态，写注释说明）。
3. `PresentationRuntimeFacts` 增加 `cursor_geometry`、`pill_fingerprint` 字段；
   `_publish_grab` 成功时随 `_facts_from_widget` 一并 commit；`_cursor_payload`
   在 `_bound_widget_for` 为 None 时从 ledger 回读而非返回空。
4. 同步更新 `docs/lessons-learned/ultraview-idle-digest-keeps-armed-cursor.md`
   （其「武装竖线不藏」的表述要限定为 dual）。

**Exit gate**：UVL-A07/A11 测试绿；dual 快照既有契约（读数 pill、武装线）不回归。

## Task 3 — idle 热路径与重试（B2/B3/B4 → UVL-A08/A09/A10）

**修改**

- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `tests/ui/test_ultraview_capture.py` / `tests/ui/test_ultraview_page.py`

**测试先行**

1. 计数探针：sheet 可见时向 bound 画布连发 N 次 `cursor_info` → `_refresh_projection`
   调用次数 O(1)（idle 周期粒度），`current_digest_for` 不在信号同步路径上被调用。
2. `_publish_grab` 遇 `digest-changed` → 断言以新 digest 重新入队且第二次发布成功；
   连续变化时重试有上限。
3. 双画布：A 持续发信号，B 的 pending 在 B 静默 120ms 后完成。

**实现**

1. `schedule_idle_capture` 删除防抖前的 `_push_preview`；状态刷新挪到
   `_on_idle_capture_timeout`。
2. `page.set_preview/set_ref_status`：记录上次值，无变化直接 return；
   `_refresh_projection` 在同一事件循环内合并（0ms singleShot 折叠即可）。
3. `UnplacedTray.set_refs` 增量更新（内容签名相同则跳过重建），消除拖拽期间
   TrayItem 被销毁的 zombie-wrapper 风险。
4. `_idle_pending` 记录每 ref 最近信号时间戳；timeout 只清算已静默满
   `_IDLE_CAPTURE_MS` 的 ref，未满的重新武装 timer。
5. `_publish_grab` 的 `digest-changed` 分支：`request_capture(ref, widget, reason)`
   重入队（带每 key 重试计数，上限 2-3 次后按现状 warn 放弃）。

**Exit gate**：三组探针测试绿；`scripts/` 无需新增性能门禁，但在 PR 描述记录
悬停场景的前后调用计数对比。

## Task 4 — 独立窗反馈面与导航置前（A5/A6/A7 → UVL-A05/A06 + C 附带治理 → UVL-A14）

**修改**

- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/main_window/window.py`（新增公共 `navigate_to_view`）
- `tests/ui/test_ultraview_mode_integration.py`

**测试先行**

1. sheet 可见时 `_toast` 宿主为 sheet（monkeypatch page.window() 返回 sheet 验证
   路由）；sheet 不可见时回落 `MainWindow.toast`。
2. `choose_and_export_png` 的 `QFileDialog` 父窗为 sheet（monkeypatch
   `getSaveFileName` 捕获 parent 参数）。
3. `open_source` 成功切换后主窗 `activateWindow/raise_` 被调用（spy），sheet
   identity 不变、未关闭。
4. focus 单一 owner：`focus_requested` 全链路只产生一次 `show_ref`（spy 计数）。

**实现**

1. coordinator 增加 `_feedback_host()`：sheet 可见 → sheet，否则主窗；`_toast` 与
   文件对话框统一走它。sheet 侧提供轻量 toast 宿主（复用 `ui_kit` 既有 toast 组件，
   若无独立组件则把 `MainWindow.toast` 的绘制逻辑提取为可复用函数——**不要**复制
   第二份实现）。
2. `MainWindow.navigate_to_view(section, view_id) -> bool`：封装现
   `toolbar._set_mode + _switch_view/_on_analysis_switch` 序列 + 末尾
   `raise_()/activateWindow()`；coordinator.open_source 只调用它。
3. coordinator `_on_focus` 不再调 `page.show_focus`（保留 `_store.touch`）。

**Exit gate**：四组测试绿；`test_no_lambda_signal_connections` 棘轮不涨；
`test_main_window_state_ownership` 白名单不涨。

## Task 5 — 结果身份 generation（B6 → UVL-A12）

**修改**

- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `tests/ui/test_ultraview_state.py` 或 `test_ultraview_capture.py`

**步骤**

1. RED：对同一 slot 连续 `notify_result_stored` 两个不同对象、并模拟 id 复用
   （del 后构造，或直接注入相同 `id()` 的 stub 走单元层）→ generation 必须递增。
2. 实现：改为无条件 bump（每次 `notify_result_stored` 即 +1），删除
   `_result_identity`；若调用方存在同对象重复通知的高频路径导致 digest 抖动，
   退而用 `weakref.ref(result)` 存活比较、不可 weakref 类型无条件 bump。先量后选，
   在测试里钉住所选行为。

**Exit gate**：UVL-A12 绿；既有 digest/status 测试不回归。

## Task 6 — 第六模式残留清理（C → UVL-A13）

**修改**

- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/inspector.py` + `mf4_analyzer/ui/inspector_sections/`（对应文件）
- `mf4_analyzer/ui/toolbar.py`（`btn_mode_ultraview`）
- 对应测试（`test_main_window_smoke` / `test_toolbar` / `test_chart_stack` /
  inspector 测试）

**步骤**

1. 先 `rg -n "ultraview" mf4_analyzer/ui/main_window/window.py
   mf4_analyzer/ui/chart_stack/stack.py mf4_analyzer/ui/toolbar.py
   mf4_analyzer/ui/inspector.py` 全量列出 mode 语义引用，与 spec §C 表核对，
   多出的先补进表再动手。
2. 删除：`_on_mode_changed` 两个 ultraview 分支、`enter_ultraview/leave_ultraview`、
   `_left_snapshot` 全部触点、`_copy_card_image` 的 ultraview 早退、
   `hint_bar_for_mode('ultraview')` 分支、隐藏 `btn_mode_ultraview` 及其在
   iconsize/mode-pairs 循环中的引用。
3. `chart_stack.set_mode('ultraview')`：显式拒绝（log warning + no-op），加契约
   测试。`page_ultraview` 仍留在栈内做 sheet 关闭时的归还宿主——**这不是残留**，
   在代码注释里写明。
4. Inspector `UltraViewContextual`：默认整体移除（构造、`contextual_stack.addWidget`、
   coordinator `_connect_inspector` 与 `_sync_inspector` 早退逻辑一并删）。若产品
   决定保留「工具窗内 Inspector」形态，需另开 spec，本任务不做半吊子保留。
5. coordinator `attach()`：幂等门拆分为 `_page_hooks_connected` / stack 钩子独立
   判断（防 page 迟到永不补连）。
6. 帮助/quickref/hints 若有「第六模式」措辞残留一并同步（`/update-hints` 流程）。

**Exit gate**：`rg -n "mode.*ultraview|ultraview.*mode"` 在 `mf4_analyzer/ui` 下只剩
注释与 `page_ultraview` 宿主引用；聚焦套件 + smoke 全绿。

## Task 7 — 分屏「加入总览」绑定正确性（B8 → UVL-A16）

**修改**

- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `tests/ui/test_ultraview_capture.py` 或 `test_ultraview_mode_integration.py`

**测试先行**

1. RED：时域分屏，`manager.active` 指主栏、`focused_canvas()` 返回副栏画布；
   `add_from_source_tab("time", <active view_id>)` → 断言 `bind_canvas` 的目标是
   **主栏画布**、发布像素来自主栏；且 secondary→partner 的既有绑定完整保留。
2. 对称场景：主栏聚焦、加入副栏（partner）View 标签 → 绑定/像素同样按
   ref 所属 pane 解析（现有 `_maybe_capture_time_partner` 路径保持）。

**实现**

`add_from_source_tab` 的时域分支不再用 `_visible_widget_for("time")`（焦点跟随），
改为按 ref 反查其所属 pane：active↔primary（`stack.canvas_time`）、
partner↔secondary（`stack.secondary_canvas()`），与 `_capture_visible_time_refs`
共用同一映射 helper；反查不到就不绑不抓（membership 添加照常）。

**Exit gate**：UVL-A16 两个方向都绿；非分屏路径与分析区路径零回归。

## Task 8 — 生命周期与状态清理（E1–E4 → UVL-A18/A19/A20）

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/page.py`（新增 `clear_runtime_caches()`）
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`（E3 去重）
- `tests/ui/test_ultraview_page.py` / `test_ultraview_project_session.py`

**步骤**

1. RED（E1）：publish 若干预览 → `reset_project_state()` → 断言 page 的
   `_previews/_statuses/_ref_exists` 为空、卡片回 missing；restore 同理。
2. 实现 `page.clear_runtime_caches()`；coordinator 在
   `reset_project_state/restore_project_state/shutdown` 调用。
3. RED（E2）：焦点层打开时 `restore_project_state` → 焦点层关闭、arm/演示复位。
   实现：restore 复用 reset 的 `page.reset_sheet_session()` 调用。
4. E3：restore warnings 只在 coordinator 侧 `logger.warning`，`_project_io_mixin`
   去掉重复循环（或反之，二选一并写注释）。
5. RED（E4）：绑定画布 → 销毁它 → 断言 `_bindings/_hooked_ids/_unstable` 无死条目；
   新画布可重新 hook。实现：`_ensure_stability_hooks`/`bind_canvas` 挂
   `destroyed` 清理（注意用 `QObject.destroyed` + id 捕获，不留 lambda——走
   `functools.partial` 或具名方法，遵守 lambda 棘轮）。

**Exit gate**：UVL-A18/A19/A20 绿；`test_ultraview_lifecycle_subprocess.py` 不回归。

## Task 9 — 批处理运行中主窗关闭护栏（F1 → UVL-A21）

**修改**

- `mf4_analyzer/ui/main_window/window.py`（closeEvent 的 `_batch_sheet` 分支）
- `mf4_analyzer/ui/drawers/batch/sheet.py`（暴露「运行中/请求停止并等待」查询）
- `tests/ui/test_batch_compact_contract.py` 或新增子进程级测试

**测试先行**

1. runner 运行中 `MainWindow.close()`：确认对话取消 → closeEvent ignore、主窗
   仍在、runner 未受影响。
2. 确认停止 → runner 收到 stop、等待其结束（有限超时）后主窗才关；无
   「回调进已删 widget」类 RuntimeError（子进程跑一遍完整退出路径）。

**实现**

`MainWindow.closeEvent` 先询问 BatchSheet：`sheet.is_running()` → 走 sheet 自己的
确认流（复用其 closeEvent 的对话，不写第二份文案）；被拒绝则 `event.ignore()`
返回。禁止在 runner 存活时继续 super().closeEvent。批处理内核「不许静默失败」
纪律不变——停止路径的异常要留痕 `batch.py` logger。

**Exit gate**：UVL-A21 绿；正常（无运行）退出路径不弹对话、不变慢。

## Task 10 — 回归与护栏收口

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_ultraview_page.py tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_capture.py tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_job_isolation.py tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_project_session.py tests/ui/test_ultraview_lifecycle_subprocess.py \
  tests/ui/test_chart_stack.py tests/ui/test_main_window_smoke.py \
  tests/ui/test_batch_compact_contract.py -q

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py -q
```

1. 零计算探针（job isolation）必须全绿——本计划所有改动不得引入任何
   `do_plot/do_fft/.../submit` 调用。
2. 收尾按仓库规则分两进程跑主套件与 `tests/acquisition_ui`；crash/timeout 记
   `UNVERIFIED`。
3. **真机验收（含 D1）**：Board 开着悬停源画布（验 B1/B2 修复的体感）、复制/导出
   反馈出现在 Board 窗、「打开原 View」置前主窗；同场景补 view-rail-dock 的
   UVR-A15 前台截图（宽/窄、合并、双 pane、上限溢出、重复打开置前），证据登记进
   两份 plan。offscreen 不能替代。
4. lessons：B1（hover 线烙印）与 B5（绑定丢失误报 stale）合并为一条新 lesson
   「presentation-only 事实必须走 runtime ledger，不得依赖 live 绑定」；B7 补写进
   既有 digest lesson 的误差面。

## 验收映射

| 验收项 | Task | 证据 |
|---|---:|---|
| UVL-A01…A04 | 1 | page 契约测试 |
| UVL-A07/A11/A17 | 2 | capture 测试 + lesson 更新 |
| UVL-A08/A09/A10 | 3 | 计数探针 + 双画布测试 |
| UVL-A05/A06/A14 | 4 | toast/dialog/navigate spy |
| UVL-A12 | 5 | generation 单元测试 |
| UVL-A13 | 6 | rg 清单 + 契约测试 |
| UVL-A16 | 7 | 分屏绑定双向测试 |
| UVL-A18/A19/A20 | 8 | 生命周期/子进程测试 |
| UVL-A21 | 9 | 关闭护栏子进程测试 |
| UVL-A15 + D1 | 10 | 聚焦/护栏套件 + 真机截图 |
