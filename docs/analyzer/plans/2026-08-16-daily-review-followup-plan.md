# 2026-08-16 当日评审跟进 · 实施 plan

- 日期：2026-08-16 · 状态：**已定稿，实施待授权，0/16 Task**（C2 已裁决 (a′)，无待决项）
- spec：`docs/analyzer/specs/2026-08-16-daily-review-followup-spec.md`（决策编号 A1–A5 /
  B1–B8 / C1–C5 以它为准）
- 评审：`docs/analyzer/reviews/2026-08-16-codex-cursor-daily-batch-review.md`
- 基线：`8d57ab0e`。开工前 `git log -1` 核对不早于此；工作区必须干净（并行 Codex 会话常在
  动 `ui/chart_stack/ultraview/**`，见 memory「Codex 会话可能并行改工作区」）。
- 建议分支：`claude/daily-review-followup-0816`；三个 Wave 文件集合互不相交，可三路并行；
  worktree 里跑测试要写主仓库 `.venv` 的绝对路径。

> **For agentic workers：** 逐 Task 独立 commit + 聚焦验证。**不跑全量**（只有 Task 16 由
> 协调者跑一次）。任何一步把既有测试改红且 30 分钟定位不到 → revert 该 Task 停下回报；
> 不放宽护栏、不加 skip。改动仅限 Task 列出的文件；顺手重构一律不做。

**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q`
**`OVERLAY` =** `tests/test_view_overlay_state.py tests/ui/test_view_state.py tests/ui/test_view_bridge.py tests/ui/test_pg_timedomain_remarks.py tests/ui/test_pg_cursor_placement.py tests/ui/test_project_session.py`
**`BACKREF` =** `tests/ui/test_pg_canvas_backref_invariants.py`
**`POLLUTE` =** `tests/test_verify_ultraview_visuals.py tests/ui/test_pill_switch.py tests/ui/test_ultraview_chrome.py tests/ui/test_ultraview_entry.py tests/ui/test_chart_stack.py tests/ui/test_batch_output_panel.py`（评审 §5 的复现组合，顺序不能换）
**`STRUCT` =** `tests/ui/test_ultraview_structure.py`

| Wave | Task | 决策 | 结果 |
|---|---|---|---|
| A 持久化收口 | 1 pill 路由门禁 | A1 | |
| A | 2 标注意图层 + 收口投影 | A2 | |
| A | 3 落点单一真相 | A3 | |
| A | 4 护栏改判据 + 帮助句 + 原 spec 修订 | A4 A5 | |
| B 门禁稳定 | 5 `tests/conftest.py` 样式隔离 | B1 | |
| B | 6 QSS↔Python 几何三处 + 生产 QSS 护栏 | B2 | |
| B | 7 五处测试时序探针 + fitter 观察 | B3 | |
| B | 8 视觉 harness / LOD 用例对齐 | B4 | |
| B | 9 d491d41e 三条红 + 托盘文案 | B5 | |
| B | 10 router 顺序污染 | B6 | |
| C UltraView 收尾 | 11 画布背景 DPR | C1 | |
| C | 12 相机改会话内记忆、不进工程 | C2 (a′) | |
| C | 13 日志分级 / eventFilter 早退 / 护栏泛化 / D2.3 / zoom 结构钉 / edge-pan 断言 | C3 | |
| C | 14 文档同步 + lessons | C4 | |
| 收尾 | 15 基线文档更正 | B7 | |
| 收尾 | 16 全量一次 + Cocoa 走查 | B8 C5 | |

---

## Wave A · 时域 View 标注 / 双游标收口（P0，阻塞真机验收）

### Task 1 · pill 路由按发信卡片在屏门禁（A1）

**Files:** `mf4_analyzer/ui/chart_stack/stack.py`（`_on_cursor_info` / `_on_dual_cursor_info` /
`_on_dual_cursor_rows` / `_on_frequency_cursor_rows`）；`tests/ui/test_project_session.py`；
`tests/ui/test_split_routing.py`（若现有用例依赖旧路由）。

- [ ] Step 1（红着提交）：`test_project_session.py` 新增
  `test_reopen_with_frf_view_keeps_time_dual_cursor_pill`：工程 = 时域 View（dual + A/B 落点）
  + 一个带 source 的 FRF View（`_write_frf_csv` 已有）；`open_project` 后
  `_drain_analysis_restore`；断言 `cursor_pill_visible()`、`dual_cursor_rows` 最后一次行数 ==
  可见通道数、A/B items visible。再加 `test_switch_to_frf_and_back_keeps_time_pill`。
- [ ] Step 2：抽 `ChartStack._cursor_source_on_screen(source) -> bool`：
  `card = _card_for_canvas(source)`；`source is None` → True；secondary card → `current_mode()
  == 'time'`；否则 `getattr(card, '_chart_mode', None) == current_mode()`。四个 handler 开头
  `if not self._cursor_source_on_screen(source): return`。
- [ ] Step 3：核对 FFT / FRF 自己在屏时清读数仍生效（`tests/ui/test_frf_canvas.py -k cursor`、
  `tests/ui/test_pill_*.py`）。

Run：`PYTEST tests/ui/test_project_session.py tests/ui/test_split_routing.py tests/ui/test_split_per_pane_controls.py tests/ui/test_pill_switch.py -q`
（+ `-k cursor` 于 `tests/ui/test_frf_canvas.py tests/ui/test_pg_line_canvas.py`）。
commit：`fix(chart-stack): 分析画布不在屏时不得清共享游标 pill`

### Task 2 · 标注意图层 + plot 收口投影（A2）

**Files:** `mf4_analyzer/ui/pg_canvas/annotations.py`、`mf4_analyzer/ui/pg_canvas/canvas.py`
（`clear()` 与 `plot_channels` 收口）、`mf4_analyzer/ui/main_window/_view_mixin.py`
（`_render_view_onto_canvas` 调用位置）、`mf4_analyzer/ui/view_bridge.py`、
`mf4_analyzer/ui/view_overlay_state.py`（`merge_remarks_for_capture` deprecated）、
`tests/ui/test_pg_timedomain_remarks.py`、`tests/ui/test_view_bridge.py`、
`tests/test_view_overlay_state.py`、`BACKREF`。

- [ ] Step 1（红着提交）：`test_pg_timedomain_remarks.py` 新增：overlay 加点 → 取消勾选另一
  通道触发 `plot_time` → `remark_count()==1` 且 `snapshot_remarks()` 仍含该点；subplot 同；
  隐藏该点所在通道 → `remark_count()==0` 但 snapshot 仍含 → 显示回来 → `remark_count()==1`；
  用户 `_remove_remark_by_index` → snapshot 不含。`test_view_bridge.py`：capture 后
  `state.remarks` == snapshot（不再合并推断）。
- [ ] Step 2：`AnnotationManager._intent`；`_add_remark` / `_remove_*` / `clear_remarks` /
  新 `_drop_remark_projection` / `_project_remarks` / `snapshot_remarks`（回读活投影的
  offset）/ `restore_remarks`（替换 + 投影）。`_owned_names` 若增，同步 `BACKREF` 白名单
  （只许是 manager 自己的属性，不写穿宿主）。
- [ ] Step 3：`canvas.clear()` 改调 `_drop_remark_projection()`；`plot_channels` 收口处紧邻
  `_restore_dual_cursor_items()` 调 `_project_remarks()`。
- [ ] Step 4：`_render_view_onto_canvas`：`restore_remarks(state.remarks)` 挪到
  `_plot_time_on_canvas` 之前；settle 之后的调用删除。`capture_controls_into` 改为
  `state.remarks = normalize_remarks(snapshot)`；`merge_remarks_for_capture` 标 deprecated
  且不再被调用（`test_view_overlay_state.py` 对它的用例改为「仍可调用、语义为直通」或删除，
  写清原因）。
- [ ] Step 5：`test_view_switch_does_not_leak_remarks_across_time_views` 与
  `test_project_roundtrip_restores_remarks_and_dual_cursor` 必须继续绿。

Run：`PYTEST OVERLAY BACKREF tests/ui/test_pg_timedomain_canvas.py -k "remark or Restore or Settle" -q`
commit：`fix(annotations): 标注意图列表为画布真相，任何重绘收口自动重投影`

### Task 3 · 落点单一真相（A3）

**Files:** `mf4_analyzer/ui/pg_canvas/cursor.py`、`mf4_analyzer/ui/view_overlay_state.py`
（`normalize_cursor_placement`）、`mf4_analyzer/ui/view_state.py`、`mf4_analyzer/ui/view_bridge.py`、
`tests/ui/test_pg_cursor_placement.py`、`tests/test_view_overlay_state.py`、
`tests/ui/test_view_state.py`、`tests/ui/test_view_bridge.py`、`tests/ui/test_project_session.py`。

- [ ] Step 1（红着提交）：跨 View 泄漏用例（View A 放 A/B → 新 View B off → B 开 dual → 无
  A/B、pill 主文本 「Click A」）；off → save → reopen → dual → A/B 回来且 rows 重算；
  `snapshot_placement()` 在 off 返回落点；`ViewState.to_dict` 在 `cursor_mode='off'` 仍写
  `cursor_placement`；`from_dict` 读回。
- [ ] Step 2：`snapshot_placement` 去 `_dual` 门禁；`restore_placement(None/非法)` 清
  `_ax/_bx`、隐藏 A/B 与极值标记、`_placing="A"`、dual 时 emit 一次；`normalize_cursor_placement`
  的 `cursor_mode` 参数只保留签名；`to_dict/from_dict/capture_*` 同步。
- [ ] Step 3：现有用例里断言「off 时 placement 为 None」的条目改为新语义并在 docstring 写明
  D3 修订。

Run：`PYTEST OVERLAY -q`
commit：`fix(cursor): 双游标落点不看模式持久化，View 恢复时空落点必清`

### Task 4 · 护栏判据 + 帮助句 + 原 spec 修订（A4 A5）

**Files:** `mf4_analyzer/help/TraceLab-使用说明.html`（「工程里存了什么」一句）、
`tests/test_help_content.py`（若钉了旧句）、
`docs/analyzer/specs/2026-08-16-view-markup-and-cursor-persistence-spec.md`（D3 / D4 / D5 /
D11 加「2026-08-16 修订：见 daily-review-followup-spec §A」）、同名 plan 状态头。
纯文档 + 一句 help：不需要运行时测试；跑 `PYTEST tests/test_help_content.py -q` 钉 help 契约。

commit：`docs(views): 持久化 spec D3/D4/D5/D11 按 08-16 评审修订，help 补一句`

## Wave B · 全量门禁稳定

### Task 5 · `tests/conftest.py` app 样式快照-还原（B1）

**Files:** 新建 `tests/conftest.py`；`tests/ui/conftest.py`（`_isolate_app_style` **保留**，
docstring 补一句指向新 fixture 说明为何两层都要）；`tests/test_conftest_autouse_scope.py`
（确认新增目录 conftest 不影响根 conftest 的节点去重契约）。

- [ ] Step 1：先跑 `PYTEST POLLUTE -q` 记下红名单（预期 10 条，与评审 §5 逐一对上）。
- [ ] Step 2：写 fixture（styleSheet / style objectName / palette / font 四项，无 app 时基线为
  「空 / 默认」，teardown 只在变了时还原）。
- [ ] Step 3：`PYTEST POLLUTE -q` 全绿；`PYTEST tests/test_conftest_autouse_scope.py
  tests/ui/test_qsettings_isolation.py -q` 绿。

commit：`test: 目录级 conftest 快照-还原 app 样式，堵住 verify_ultraview_visuals 的 QSS 污染`

### Task 6 · QSS ↔ Python 几何三处 + 生产 QSS 护栏（B2）

**Files:** `mf4_analyzer/ui_kit/style.qss`（:4469-4472 / :4702 / :4425）、
`mf4_analyzer/ui/chart_stack/ultraview/chrome.py`（仅当选择「去 Python 侧写」时）、
`tests/ui/test_ultraview_chrome.py`（新增 `TestChromeGeometryUnderProductionQss`）、
`tests/ui_kit/test_qss_border_shorthand.py` / `test_qss_palette_ratchet.py` / 
`test_qss_selector_liveness.py`（护栏必须仍绿）。

- [ ] Step 1（红着提交）：新用例在 `load_stylesheet(qapp)` 后实例化 `ToolRail` /
  `LayoutPicker`，`show()` + `processEvents()`，断言 rail 按钮 == `RAIL_BUTTON_SIZE`、
  warning dot 8×8、layout thumb `minimumHeight ≥ 104`、`minimumWidth ≥ 168`。
- [ ] Step 2：三处 QSS 改（内容尺寸 = 常量 − 2×border − padding，注释写常量名；layoutThumb
  删 `min-*:0`）。
- [ ] Step 3：`PYTEST tests/ui/test_ultraview_chrome.py tests/ui_kit -q` 绿；把
  `style.qss` 其余与 Python `setFixed*` 重复的 `min-*/max-*` grep 成清单写进
  `docs/analyzer/verify/2026-08-16-daily-followup/qss-python-size-inventory.md`（不修）。

commit：`fix(ui_kit): UltraView rail 按钮 / 警告点 / 布局缩略图在生产 QSS 下回到设计尺寸`

### Task 7 · 五处测试时序探针 + fitter 观察（B3）

**Files:** `tests/ui/test_pill_switch.py`、`tests/ui/test_batch_output_panel.py`、
`tests/ui/test_chart_stack.py`、`tests/ui/test_ultraview_entry.py`；
`mf4_analyzer/ui/widgets/ultraview_entry.py`（rail fitter；仅当观察证实为产品 bug 才改）。

- [ ] Step 1：按 spec B3 逐条改；每条改完在 `POLLUTE` 顺序下单独验证（不靠 Task 5 的 fixture
  掩盖——临时把 fixture 关掉跑一次证明测试自身在生产 QSS 下也稳）。
- [ ] Step 2（观察转结论）：真实 ChartStack rail + 生产 QSS 下压窄宿主，`entry.is_compact()`
  是否能变 True；不能 → 改 fitter 判据（`<=` 或 host 最小宽口径）并补用例；能 → 在用例
  docstring 记录原因。

Run：`PYTEST POLLUTE -q`（fixture 开 / 关各一次）
commit：`test(ui): 几何用例在生产 QSS 下也稳——settle 后再读、探针不画窗口背景`

### Task 8 · 视觉 harness / LOD 用例对齐 8d57ab0e（B4）

**Files:** `tools/verify_ultraview_visuals.py`（`card_context_1280` 场景 + `assert_geometry`
判据）、`tests/test_verify_ultraview_visuals.py`、`tests/ui/test_ultraview_viewport.py`
（`test_title_only_lod_hides_preview_body_and_empty_backing`）。

- [ ] Step 1：场景抓图前 `set_workspace_show_card_actions(True)`（与 hover 契约一致，harness
  记录当前偏好）；`assert_geometry` 的判据改成三者之一。
- [ ] Step 2：LOD 用例前提改为 `show_card_actions=True` 或断言 hover 后可见。

Run：`PYTEST tests/test_verify_ultraview_visuals.py tests/ui/test_ultraview_viewport.py -q`
commit：`test(ultraview): 视觉 harness 与 LOD 用例对齐卡片操作 hover 可配置契约`

### Task 9 · d491d41e 三条红 + 托盘文案（B5）

**Files:** `tests/ui/test_ultraview_page.py`（两条）、`tests/ui/test_ultraview_capture.py`、
`mf4_analyzer/ui/chart_stack/ultraview/page.py` 或 `feedback.py`（托盘场景文案）。

- [ ] Step 1：两条 page 用例按「打开即 Fit」重写前提（先把 zoom 设为能容纳目标列，或直接
  断言 toast 文本），删掉 8d57ab0e 加的 deselect。
- [ ] Step 2：capture 用例更新文案；产品对「从托盘放置」场景改为「画布已放置 24 张，仍在
  未放置区 · 打开」。

Run：`PYTEST tests/ui/test_ultraview_page.py tests/ui/test_ultraview_capture.py tests/ui/test_ultraview_feedback.py -q`
commit：`fix(ultraview): 满板放置文案区分托盘来源；page 用例按打开即 Fit 重写`

### Task 10 · router 顺序污染（B6）

**Files:** 定位后决定（候选：`tests/ui/test_ultraview_capture.py` 的窗口 / grab 清理、
`mf4_analyzer/ui/chart_stack/ultraview/viewport_router.py::_is_active`）。

- [ ] Step 1：`PYTEST tests/ui/test_ultraview_capture.py tests/ui/test_ultraview_viewport_router.py -q`
  复现；再二分 capture 文件内哪一条是污染源。
- [ ] Step 2：修根因（未关顶层窗 / 未释放 mouseGrab / activeWindow 残留），不加 skip；若是
  产品侧 `_is_active` 判据脆弱，改判据并补用例。

commit：`fix(ultraview): 视口手势路由器不受前序用例窗口残留影响`（按定位结果改题）

## Wave C · UltraView 收尾

### Task 11 · 画布背景 DPR（C1）

**Files:** `mf4_analyzer/ui/chart_stack/ultraview/chrome.py`（`CanvasHost._build_canvas_background`
/ `paintEvent` / 缓存键 / DPR 变化失效）、`tests/ui/test_ultraview_chrome.py`。

- [ ] Step 1（红着提交）：用例断言 `_background.devicePixelRatioF() == host.devicePixelRatioF()`
  且物理尺寸 == 逻辑尺寸 × dpr；改 dpr 后缓存重建。
- [ ] Step 2：实现；Cocoa 截图对比留到 Task 16。

commit：`fix(ultraview): 画布背景按 DPR 栅格化，Retina 不再放大模糊`

### Task 12 · 相机改为会话内记忆、不进工程（C2，已裁决 (a′)）

**Files（删持久化）：** `mf4_analyzer/ui/ultraview_state.py`（`viewport` 字段、
`set_board_viewport`、`_legalize_viewport` / `_viewport_payload` / `_try_viewport_float` /
`_viewport_finite_or_warn`、`copy_board` 的 `viewport=dict(...)`、`to_payload` /
`from_payload` 相关分支）、`mf4_analyzer/ui/chart_stack/ultraview/page.py`
（`viewport_changed` 信号与全部 `_persist_viewport_to_board` 调用点）、
`mf4_analyzer/ui/main_window/ultraview_coordinator.py`（`_on_viewport_payload`、
`_connect_page` 里的连接、`set_board_viewport` import）、
`mf4_analyzer/ui/chart_stack/ultraview/viewport.py`（`NEW_BOARD_ZOOM_MAX` /
`default_board_zoom` / `initial_viewport` 兼容壳）。
**Files（加会话相机）：** `page.py` 的 `_session_camera` 与 `_restore_viewport_from_board`。
**Tests:** `tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_elastic_workspace.py`、
`tests/ui/test_ultraview_project_session.py`、`tests/ui/test_ultraview_state.py`、`STRUCT`。

- [ ] **Step 1（红着提交，判据全是用户可见量）：**
  ① A/B 两板，在 A 缩放平移 → 切 B → 切回 A：断言 `zoom()` 与两个滚动条 `value()` 与离开时
  一致（不是断言内部 dict）；② 在 A 加一张卡触发 extent rebase → 切 B → 切回 A：断言回到
  Fit（`zoom()` == fit zoom）；③ `.tlproj` payload **不含** `viewport` 键；④ 读一个含
  `viewport`（含非法值）的旧工程：`restore_project_state` 返回的 warnings 里没有 viewport
  条目，不弹「N 项无法识别」toast；⑤ `close_all` / 切换工程后切回原板：回到 Fit。
- [ ] **Step 2（删持久化）：** 按上面 Files 逐处删除；确认 `_legalize_viewport` 这条 warning
  源随之消失（Step 1 ④ 转绿）。
- [ ] **Step 3（会话相机）：** `page` 自持
  `_session_camera: dict[str, tuple[float, tuple[float, float], tuple]]`；离开板时写入，
  `_restore_viewport_from_board` 改为「签名一致 → 恢复 zoom+center，否则 `fit_on_open()`」；
  签名取 `GridBounds` 的 `(column, row, columns, rows)`；`close_all` / 切换工程 / page 重建
  清空。**不进模型**：不得写 `UltraViewBoardState` / `UltraViewWorkspaceState` 任何字段。
- [ ] **Step 4（护栏同步，单独一个提交）：** `STRUCT` 白名单缩小——mutator 冻结集去
  `set_board_viewport`、U4 例外去 `_on_viewport_payload`。**只缩不扩**；不要和 spec C3 的
  护栏泛化混在同一提交里（那是 Task 13）。
- [ ] **Step 5（与 Task 13 对账）：** 确认 `_on_viewport_payload` 已删 → 评审 §2-1 的
  unknown-board WARNING 噪声消失 → 通知 Task 13 只剩 `_iter_viewboxes` 一处日志要改。
- [ ] **Step 6（回写文档）：** `docs/analyzer/plans/2026-08-16-ultraview-elastic-canvas-ux-plan.md`
  的 §3.4 / Task 2 / UX-01 / UX-08 / UX-11 / 状态头改成本合同（打开 / 首次进板 / 跨会话 Fit；
  会话内切板往返恢复；相机不进工程）。高水位 extent 在 Fit / 切板 reset 到内容包围盒 + halo
  （评审 §3-8）。

**边界（spec C2 已否决，不要顺手做）：** 不把相机写回 `.tlproj`；不把 center 改成有符号格
坐标（本 Task 靠签名判等规避 rebase，不需要它）；谁将来要放宽签名判据，必须先做坐标改造。

Run：`PYTEST tests/ui/test_ultraview_viewport.py tests/ui/test_ultraview_elastic_workspace.py tests/ui/test_ultraview_project_session.py tests/ui/test_ultraview_state.py STRUCT -q`
commit：三个——`refactor(ultraview): 删除只写不读的 viewport 持久化与漏斗` +
`feat(ultraview): 会话内切板恢复该板相机，extent 变化即回到适应` +
`test(ultraview): 结构护栏白名单随 viewport 漏斗删除缩小`

### Task 13 · 接缝加固收尾（C3）

**Files:** `ultraview_coordinator.py`（`_on_viewport_payload` 分级；`_iter_viewboxes` 空画布
判据）、`viewport_router.py`（`eventFilter`
早退）、`tests/ui/test_ultraview_structure.py`（泛化 + zoom 结构钉）、
`tests/ui/test_ultraview_chrome.py`（D2.3 回退 == sizeHint）、`chrome.py`（导航岛回退值改为
计算）、`tests/ui/test_ultraview_elastic_workspace.py`（edge-pan 位移断言）。

- [ ] Step 1：日志分级两处 + `caplog` 用例（open_project 不再有 unknown-board WARNING；空
  时域画布抓图不告警；`_plotx` 伪造仍告警）。
- [ ] Step 2：`eventFilter` 先 `event.type() in _HANDLED_TYPES` 早退；`test_ultraview_viewport_router.py`
  全绿。
- [ ] Step 3：护栏泛化（接收者无关的字段写匹配、目录通配、`setMinimum*` / `resize` /
  `QRect`）；泛化后若白名单出现新条目，**逐条判定**：是本批之前就有的漏检 → 记入白名单并注
  释；是新引入 → 修代码。加 zoom 路径结构钉。
- [ ] Step 4：D2.3 用例补 `回退 == 真实 sizeHint()`；导航岛第二份数值消除。
- [ ] Step 5：edge-pan 用例补 `horizontalScrollBar().value()` 位移与 ghost 位置断言。

Run：`PYTEST STRUCT tests/ui/test_ultraview_viewport_router.py tests/ui/test_ultraview_chrome.py tests/ui/test_ultraview_capture.py tests/ui/test_ultraview_elastic_workspace.py tests/ui/test_ultraview_project_session.py -q`
commit：分 2–3 个提交（日志分级 / 过滤器早退 / 护栏泛化与契约）

### Task 14 · 文档同步 + lessons（C4）

**Files:** `mf4_analyzer/help/ultraview-guide.html`（schema 4 一句）、`tests/test_help_content.py`
（若钉）、`docs/analyzer/user-guide/`（发版说明若有当期条目）、`CLAUDE.md`（版本备注
v7.9.9 → v8.0.0，只改那一处）、`docs/lessons-learned/pyqt-ui/2026-08-16-qss-polish-overrides-
python-fixed-size.md`、`.../2026-08-16-shared-pill-needs-section-gate.md`、
`.../2026-08-16-tools-installing-app-qss-pollutes-test-session.md`、`docs/lessons-learned/INDEX.md`。
纯文档：只跑 `PYTEST tests/test_help_content.py -q`。

commit：`docs: schema 4 迁移说明、CLAUDE.md 版本备注、三条 lessons`

## 收尾

### Task 15 · 基线文档更正（B7）

**Files:** `docs/analyzer/verify/2026-08-15-ultraview-seam-hardening/baseline.txt`、
`docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6、
`docs/analyzer/plans/2026-08-15-ultraview-seam-hardening-plan.md` Task 0 执行记录。
纯文档。commit：`docs(verify): 3 条「独立红」更正为 1 独立 + 1 污染 + 1 已修`

### Task 16 · 全量一次 + Cocoa 走查（B8 C5）

**协调者独占。** 前置：Task 1–15 全部合入、工作区干净、`pgrep -fl pytest` 无人在跑。
- [ ] Step 1：记 `HEAD` 与 `git status`；两条命令、串行、前台：
  `PYTEST --ignore=tests/acquisition_ui` → `PYTEST tests/acquisition_ui`；跑完再记一次
  `HEAD` / `git status`，不一致则结论 `UNVERIFIED` 重跑。
- [ ] Step 2：目标主体 0 failed（`test_gen_help_screenshots` 环境性除外）；每一条剩余红都
  要在本 plan 追加 Task 名字，不得记为「既有」。
- [ ] Step 3：Cocoa 一次走查，产出 `docs/analyzer/verify/2026-08-16-daily-followup/
  cocoa-walkthrough.md`：手势路由五起点；钛金琥珀 + 背景锐度截图（Task 11 前后对比）；
  edge-pan 手感；hover 操作条；A1–A3 三条验收判据 + 原持久化 plan Wave 3 两条。
- [ ] Step 4：spec 状态改「已实施」，本表填结果。

## 显式不做（本 plan 结束仍不做）
- 相机跨会话落盘持久化（C2 备选 (a) 已否决）。
- 分析 View 标注 / 频率双游标持久化；pill mini/full 与拖位持久化。
- 拆 page / coordinator；每画布独立 pill。
- ink / AA / 离散结算常量。
- `tools/verify_ultraview_visuals` 的 test-only 分支。
