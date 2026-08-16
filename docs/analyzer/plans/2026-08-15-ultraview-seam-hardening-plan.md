# UltraView 接缝加固（结构护栏 + 五处接缝）· 实施 plan

- 日期：2026-08-15 · 状态：**实施完成；1 条 Cocoa 前台门禁待解锁后补验** · 实施 9/9 Task
- 执行记录（2026-08-16）：Task 0 当时记下的三条失配已由用户明确接受为
  接缝范围外基线，随后继续执行。B7 更正（当日评审跟进）：那不是「3 条独立红」，
  而是 1 独立（视觉 harness/card-context）+ 1 污染（LayoutPicker 缩略图，单跑绿）
  + 1 已修（QSS palette ratchet，64dbab74）。详情见
  `docs/analyzer/verify/2026-08-15-ultraview-seam-hardening/baseline.txt` 与
  `docs/analyzer/specs/2026-08-16-daily-review-followup-spec.md` B7。
- spec：`docs/analyzer/specs/2026-08-15-ultraview-seam-hardening-spec.md`（决策编号 D0–D8 以它为准）
- 历史基线：`c2502de1`；Task 0 已在 `f85f2323` 重锚，原在途的 View 库几何/材质批不再是
  本计划的前置条件。
- 建议分支：`claude/ultraview-seam-hardening`

> **For agentic workers:** 逐 Task 执行，每 Task 独立 commit + 验证。本批的成功标准是
> **护栏白名单缩小、投影次数下降、几何字面量归零**，不是行数减少；**禁止超出 spec 的
> 「顺手重构」**（不拆 page、不拆 coordinator、不合并模块、不改视觉）。任何一步把既有
> 测试改红且 30 分钟内定位不到 → revert 该 Task 停下回报。
> 若在 worktree 里跑：`.venv` 不在 worktree 内，`PYTEST` 里的解释器要写**主仓库的绝对路径**；
> 开工前 `git log -1` 核对 HEAD 不早于 Task 0 记录的基线，落后就 `git merge --ff-only`。

**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider`
**`UV` =** `tests/ui/test_ultraview_*.py`（Task 0 历史基线 581 passed；本批收尾不通配重跑）
**`STRUCT` =** `tests/ui/test_ultraview_structure.py`（Task 1 新建）
**收尾门禁（按当前 `AGENTS.md` 与用户指示）：** 仅跑各 Task 的 owner 用例与适用边界；
不跑主体全量、`tests/acquisition_ui` 或整组 `UV` 通配集。全量只留给发布/合并验收、
跨边界重构或用户显式要求。

| Task | 结果 | 证据 |
| --- | --- | --- |
| 0 | 完成；三条非本批红已接受为新基线 | `baseline.txt`、`inventory.md` |
| 1 | 完成 | `16d91003`，结构护栏 |
| 2 | 完成 | `868e0e4b`，zoom 广播单点 |
| 3 | 完成 | `bda69148`，状态 owner 收口 |
| 4 | 完成 | `2ddd8abc`，六卡投影 7 → 1 |
| 5 | 完成 | `0d3abf90`，几何常量单点 |
| 6 | 完成 | `a56df8bd`，viewbox 落空告警 |
| 7 | 代码/自动验收完成；Cocoa 待补 | `7912d8a7`、`gesture-router-cocoa.md` |
| 8 | 完成 | 本次收尾文档与 lesson |

---

## Task 0 · 锚定 + 清查 + 基线（失配即停）

**结果（2026-08-16）：** 清查和三路历史基线已完成。三条失配曾使本 Task 阻塞，
随后由用户明确接受为接缝范围外基线；其 owner 不在本计划范围，故继续执行而不改写那些测试。
B7 更正：1 独立（harness）+ 1 污染（layout picker）+ 1 已修（palette），不是 3 条独立红。

**Files:** 新建 `docs/analyzer/verify/2026-08-15-ultraview-seam-hardening/inventory.md`
（清查全表）与 `baseline.txt`（测试基线）；spec 行号如有漂移直接改 spec（标注「Task 0 重锚」）。

- [ ] **Step 1（前置核对）：** `git status --short` 里 `mf4_analyzer/ui/chart_stack/ultraview/*`
  与 `ultraview_coordinator.py` 必须干净（在途批已提交）。不干净 → 停，别在别人半成品上锚定。
- [ ] **Step 2（锚点重定位）：** 逐条核对 spec §1.3 与 D1–D6 引用的行号，漂移就更新。重点：
  `_after_board_mutation` / `refresh_page` / `_push_preview` / `apply_preview_and_status` /
  `_prune_runtime_caches` / `_persist_viewport_to_board` / `_page_of` 及其 16 个调用点 /
  zoom 三件套 4 处 / `_iter_viewboxes`。
- [ ] **Step 3（清查脚本，放 scratchpad 不入库）：** AST 扫描产出以下清单，全部写进 inventory：
  a. `ultraview_state` 的 mutator 集合（按 spec D0-U1 规则收集）——**这份清单进 Task 1 的冻结表**；
  b. `page.py` / `widgets.py` / `chrome.py` 中对上述 mutator 的调用（预期 0）与
     `self._board.<x> = ` / `self._workspace.<x> = ` 属性写（预期 1：`_persist_viewport_to_board`）；
  c. coordinator 中 `page._<x>` 访问（预期 1：`_select_ref`）；
  d. `_page_of(...)` 结果上访问的属性名集合（预期 11 个）与所在类；
  e. coordinator 中「调 mutator 但函数体内无 `_after_board_mutation` / `_commit_grid_change` /
     `_apply_grid_snapshot`」的方法名（U4 白名单，逐条写为什么合法）；
  f. `ultraview_state.py` 之外对 `UltraViewBoardState` / `UltraViewWorkspaceState` 字段的属性赋值
     （预期：page 1 + coordinator 3，即 `board.name` / `show_titles` / `show_sources`）；
  g. `chrome.py` / `page.py` / `widgets.py` 里与浮层几何相关的裸字面量残留（D2 集合：
     40/48/56/196/233/268/240/116/200 出现在 `setFixed*` / `QSize` / `_hint` 回退里的位置）；
  h. `"ultraViewPage"` 字面量出现位置（预期 2）。
- [ ] **Step 4（D1 假设核实）：** grep `page._previews` / `_statuses` / `_ref_exists` 的全部读点，
  确认没有消费者读**非活动 Board** 的 ref（`show_focus` / `_refresh_open_focus` / tray /
  overview / 导出合成）。结论写 inventory §D1；有例外则 Task 4 保留全量推送、只做批处理。
- [ ] **Step 5（基线）：** `PYTEST UV -q | tail -5 > baseline.txt`；再跑两条全量把汇总行追加进去。
  记下失败清单（既有顺序污染那 9 条见 `docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6，
  不算本批）。

Run: 无（清查 + 基线）。commit：`docs(ultraview): 接缝加固 Task 0 清查与基线`。

## Task 1 · D0 结构护栏（先立法，后施工）

**Files:** Create `tests/ui/test_ultraview_structure.py`；Modify `mf4_analyzer/ui/ultraview_state.py`
（加 `ULTRAVIEW_PAGE_OBJECT_NAME`）、`page.py:226`、`widgets.py:144`（U5 只是把字面量换成常量，
不改行为）。

- [ ] **Step 1：** 照 `tests/ui/test_main_window_state_ownership.py` 的 AST 手法写六条：
  - `test_view_layer_calls_no_state_mutators`（U1，冻结集合来自 Task 0 Step 3a，运行时再从
    `ultraview_state` 按规则收集一次并与冻结表比对——新增 mutator 未入表即红）；
  - `test_model_fields_written_only_in_state_module`（U1b，白名单 = Step 3f 的 4 条，只许缩）；
  - `test_page_has_no_back_reference`（U2）；
  - `test_page_of_surface_is_frozen`（U3，白名单 = Step 3d 的 11 个名字）；
  - `test_mutations_end_in_funnel`（U4，白名单 = Step 3e）；
  - `test_page_object_name_is_shared_constant`（U5）；
  - `test_coordinator_uses_page_public_api_only`（U6，白名单 = `{"_select_ref"}`）；
  - 附带两条 lint 占位：`test_zoom_broadcast_single_site`（D5：`_grid.set_zoom` /
    `_free_grid.set_zoom` 在 `page.py` 各出现次数冻结为当前值 4，目标 1）、
    `test_floating_geometry_literals_live_only_in_floating_layout`（D2：白名单 = Step 3g 残留）。
  文件头注释写清「白名单只许缩小；改护栏先改 spec」。
- [ ] **Step 2：** U5 落地：`ultraview_state.py` 加 `ULTRAVIEW_PAGE_OBJECT_NAME = "ultraViewPage"`
  （与 `ULTRAVIEW_REF_MIME` 同址）；`page.py` / `widgets.py` 改引用。
- [ ] **Step 3：** `PYTEST STRUCT UV -q` 全绿；commit。

Run: `PYTEST STRUCT -q && PYTEST UV -q`

## Task 2 · D5 zoom 广播单点（热身）

**Files:** Modify `page.py`（四处三件套 → `_broadcast_zoom(zoom)`）；`STRUCT` 白名单 4 → 1。

- [ ] **Step 1：** 抽 `_broadcast_zoom(zoom: float) -> None`：`_viewport.set_zoom` +
  `_grid.set_zoom` + `_free_grid.set_zoom`；四处调用点替换。注意 `_restore_viewport_from_board`
  里 `restore_payload` 之后那一对原本没调 `_viewport.set_zoom`（payload 已把 zoom 设进
  `_viewport`）——
  保持语义：给 `_broadcast_zoom` 一个 `viewport: bool = True` 形参或在该处先 `restore_payload`
  再广播，二选一，写注释。
- [ ] **Step 2：** `test_zoom_broadcast_single_site` 目标改 1；`PYTEST STRUCT tests/ui/test_ultraview_viewport.py -q`。

Run: `PYTEST STRUCT tests/ui/test_ultraview_viewport.py tests/ui/test_ultraview_page.py -q`

## Task 3 · D3 越界写收口

**Files:** Modify `ultraview_state.py`（新 mutator `set_board_viewport` / `set_presentation_flags`）、
`page.py`（`viewport_changed` 带 payload、`select_ref` 公开）、`ultraview_coordinator.py`
（`_on_viewport_payload`、`rename_board`、`set_presentation_flags`、`page.select_ref`）；
`tests/ui/test_ultraview_state.py`（新 mutator 单测）、`tests/ui/test_ultraview_page.py` /
`test_ultraview_capture.py`（切板落库顺序用例）。

- [ ] **Step 1（模型先行）：** `set_board_viewport(board, payload) -> list[str]`：经
  `_legalize_viewport` 合法化后写 `board.viewport`，非法值回退并返回 warnings；
  **不**调 `mark_workspace_mutated`（spec D3：视口是 digest 外呈现态，不脏工程）。
  `set_presentation_flags(board, *, show_titles=None, show_sources=None) -> list[str]`。
  单测：合法/非法 payload、None 不改、`opaque_payload` 不被清。
- [ ] **Step 2（page）：** `viewport_changed = pyqtSignal(str, dict)`（`board_id`, payload）；
  `_persist_viewport_to_board` 改为算 payload → `emit(self._board.board_id, payload)`，
  **删掉** `self._board.viewport = ` 那行。当前 6 处
  `viewport_changed.emit()` 都各自紧跟在一次 `_persist_viewport_to_board()` 之后——把 emit
  收进 `_persist_viewport_to_board` 内部成为唯一 emit 点，外面 6 处裸 emit 删掉（切板那次
  `set_board` 里的 persist 也随之发信号，这正是 Step 4 要守的顺序）。
  `select_ref(ref)` 公开包装 `_select_ref`。
- [ ] **Step 3（coordinator）：** `_connect_page` 里 `viewport_changed` 改连
  `_on_viewport_payload(board_id, payload)`：**按 `board_id` 查板**（找不到就丢弃并 log），
  调 `set_board_viewport(board, payload)`，warnings 走既有 toast/log 路径，然后
  `self._focus_timer.start()`（沿用原 `_on_viewport_changed` 语义）。**不许用 `active_board()`**
  （spec D3-1 说明了切板时活动板已是新板的时序陷阱）。**不调 `_after_board_mutation`。** `:1358` 改 `page.select_ref(ref)`；`:1703` 改
  `rename_board(...)`（注意它返回 warnings、且是 workspace 级函数——核对签名）；
  `:1879/:1883` 改 `set_presentation_flags`。
- [ ] **Step 4（顺序用例）：** 两板 A/B，A 上缩放平移后经 coordinator 切到 B：断言
  `coordinator.workspace()` 里 **A** 的 `viewport` 是刚才的值、**B** 的 `viewport` 没被 A 覆盖
  （这是 board_id 参数存在的理由）；再切回 A 精确恢复；`workspace_to_payload` → 重开工程后
  `_restore_viewport_from_board` 精确恢复。测试里若有直接读 `page._board.viewport` 的地方改读
  coordinator。
- [ ] **Step 5：** `STRUCT` 白名单：U1b 4 → 0、U6 1 → 0；`PYTEST STRUCT UV -q`。

Run: `PYTEST tests/ui/test_ultraview_state.py STRUCT -q && PYTEST UV -q`

## Task 4 · D1 投影批处理 + 两处双触发

**Files:** Modify `page.py`（批处理 API + 两处双触发）、`ultraview_coordinator.py`（`refresh_page`
包批 + 推送范围）；`tests/ui/test_ultraview_page.py` / `test_ultraview_capture.py`（spy 用例）。

- [ ] **Step 1（spy 先行，红着提交）：** 用 monkeypatch 计数 `page._refresh_projection`：
  a. N=6 张卡的 Board 切入 → 记录当前次数（预期 7）；b. `_on_board_name` 改名一次 → 记录；
  c. `apply_preview_and_status` 单独调用一次（record 变化）→ 必须 ==1（既有语义，作为回归锚）。
  先把 a/b 的期望写成目标值（1 / ≤1），此时红。
- [ ] **Step 2（page 批处理）：** `projection_batch()` contextmanager（或 begin/end 对）：
  批内 `_refresh_projection` 只置 `_projection_dirty=True`；退出时若脏则投影一次。
  嵌套安全（计数）。`set_library_rows` 在批内同样延后到退出（它本就有 `_pending_library_rows`
  的拖拽延后机制——复用同一出口，别再开一条）。**注意 `_drag_kind` 期间的既有延后
  （`_board_widgets_dirty`）优先级更高**：批退出时若仍在拖拽，只置脏不投影，交给
  `_flush_deferred_drag_refresh`。
- [ ] **Step 3（coordinator）：** `refresh_page` 整段 `with page.projection_batch():`；
  推送范围按 Task 0 Step 4 结论：默认只推活动 Board 的 `membership_set`；`_refresh_library`
  不变（它自己从 store 算状态）。`_push_preview` 内 `_refresh_open_focus` 不受批影响
  （它刷的是 focus 层不是投影）——确认。
- [ ] **Step 4（双触发）：** `page.py:2426` 直接 `_refresh_minimap()` 删除（靠 `rangeChanged`）
  ——若删掉后 `test_ultraview_viewport.py` 里 minimap 用例在 offscreen 下拿不到 rangeChanged
  （尺寸未变时不发），改为「批退出时若投影过则刷一次 minimap」，别回到直调。
  `_select_ref` 里第二次 `_refresh_card_context()` 删除。
- [ ] **Step 5：** spy 转绿；`PYTEST UV -q` 全绿；对比切板耗时（offscreen 量不出 paint，
  只记 `_refresh_projection` 次数与 wall-clock，写 inventory）。

Run: `PYTEST tests/ui/test_ultraview_page.py tests/ui/test_ultraview_capture.py tests/ui/test_ultraview_viewport.py -q && PYTEST UV -q`

## Task 5 · D2 几何常量单一事实源

**Files:** Modify `chrome.py`、`page.py`、（如有）`widgets.py`；`tests/ui/test_ultraview_chrome.py`
（widget ↔ 常量契约）；`STRUCT` 的 D2 lint 白名单 → 空。

- [ ] **Step 1：** 按 Task 0 Step 3g 清单逐处替换为 `floating_layout` 常量：`chrome.RAIL_MIN_HEIGHT`
  删除改用 `RAIL_CONTENT_HEIGHT`；`setFixedWidth(48)` / `QSize(48, …)` → `RAIL_WIDTH`；
  四个岛 `setFixedHeight(40)` → `ISLAND_HEIGHT`；`page._hint` 回退元组由
  `(BOARD_ISLAND_MAX_WIDTH, ISLAND_HEIGHT)` 等组装（`navigation_island` 回退 232 vs 常量 268
  的分歧：以真实 widget `sizeHint()` 为准决定用哪个常量，写注释）。
- [ ] **Step 2（契约测试）：** 实例化 `ToolRail` / `BoardIsland` / `GlobalIsland` / `StatusIsland` /
  `NavigationIsland` / `BoardPopover`，断言固定尺寸或 `sizeHint()` 与常量一致；
  `page._hint` 的回退值 == 对应 widget 的 `sizeHint()`（用一个已 `show()` 的 page 逐项比）。
- [ ] **Step 3：** D2 lint 白名单清空；`PYTEST STRUCT tests/ui/test_ultraview_chrome.py tests/ui/test_ultraview_floating_layout.py -q`。

Run: `PYTEST STRUCT tests/ui/test_ultraview_chrome.py tests/ui/test_ultraview_floating_layout.py tests/ui/test_ultraview_page.py -q`

## Task 6 · D6 源画布探测落空补日志

**Files:** Modify `ultraview_coordinator.py`（`_iter_viewboxes` 落空 → throttled warning）；
`tests/ui/test_ultraview_capture.py`（特征化用例）。

- [ ] **Step 1：** 在探测 host 的调用处（不是生成器内部）判定「一个 viewbox 都没找到」，经
  `diagnostics.throttled` 打 `logger.warning("ultraview: no viewbox found on %s (%s)", …)`，
  节流键 `(section, type(host).__name__)`。不改返回值、不抛。
- [ ] **Step 2：** 用例：伪造 host 把 `_plot` 改成 `_plotx`，`caplog` 断言 warning 出现且抓图返回
  None；正常 host 不出 warning。
- [ ] **Step 3：** `PYTEST tests/ui/test_ultraview_capture.py -q`。

Run: `PYTEST tests/ui/test_ultraview_capture.py -q`

## Task 7 · D4 视口手势路由集中（放最后；唯一需要真机验收的 Task）

**结果（2026-08-16）：** `ViewportGestureRouter` 已由 Page 持有并随 show/hide/deactivate
安装和卸载；五个 widget 的旧转发均已删除，U3 从 11 收敛为 4。offscreen 最终 router
用例 **29 passed**，最终适用 owner/boundary 组合为 **543 passed, 103 warnings**。尝试真实
Cocoa 操作时本机锁屏，因而前台清单保持 **UNVERIFIED**，记录在
`docs/analyzer/verify/2026-08-15-ultraview-seam-hardening/gesture-router-cocoa.md`；未观测到
弹层冲突，不触发 `grabMouse()` 回退。

**Files:** Create `mf4_analyzer/ui/chart_stack/ultraview/viewport_router.py`、
`tests/ui/test_ultraview_viewport_router.py`；Modify `page.py`（持有/安装/卸载）、`widgets.py`
（删五处 move 转发 + 四个模块级 helper 的平移/滚轮/捏合/空格分支）；`STRUCT` U3 白名单 11 → 4。

- [ ] **Step 1（先写事件序列用例，红着提交）：** offscreen 下用 `QTest` 从五种起点
  （`UltraViewCard` / `BoardGrid` 空白 / `FreeGridCard` / `FreeGridBoard` 空白 /
  `BoardScrollArea` 视口）分别：中键按下 → 移动跨越到另一种 widget 上 → 释放；
  空格按住 + 左键同样一遍；断言 `page.is_board_panning()` 全程 True、释放后 False、
  滚动偏移量等于位移；左键在卡片上按下不进入平移（卡片拖拽不受影响）；
  Ctrl+滚轮在任一起点都缩放且锚点在光标；文本框有焦点时空格不吞。
  这些用例**先在现状下跑绿**（作为行为锚），再进 Step 2。
- [ ] **Step 2：** `ViewportGestureRouter(QObject)`：构造注入 page 的 `_canvas_host`、
  `_viewport`（`BoardViewport`）与回调（`begin_board_pan` / `update_board_pan` /
  `end_board_pan_for_event` / `handle_zoom_wheel` / `handle_pinch` / `note_space`）；
  `eventFilter` 只处理 `watched` 是 `_canvas_host` 后代的事件；按 spec D4 的事件表分支；
  文本输入焦点判定沿用 `09262e15` V8 的实现。page 在 `showEvent` 安装到
  `QApplication.instance()`、`hideEvent` / `WindowDeactivate` 卸载（与 `_cancel_board_gestures`
  同一处）。
- [ ] **Step 3：** 删 `widgets.py` 五处 `mouseMoveEvent` 里的 `is_board_panning/update_board_pan`
  分支、`_handle_pan_press` / `_handle_pan_release` / `_handle_space_key` /
  `_forward_zoom_wheel` / `_forward_native_zoom` 及其调用；`_page_of` 只剩 4 个卡片语义调用。
  U3 白名单 11 → 4。Step 1 用例仍绿。
- [ ] **Step 4（真机，Cocoa）：** 按 spec D4-4 清单走一遍：五种起点连续平移不断（尤其光标经过
  rail / 岛 / 已打开弹层）、中键与空格两种起手、Ctrl+滚轮与捏合缩放锚点不跳、弹层打开时
  平移不吞弹层点击、Esc/失焦取消。截图 + 简短读数归档到
  `docs/analyzer/verify/2026-08-15-ultraview-seam-hardening/gesture-router-cocoa.md`。
  **发现 app 级过滤器与 Qt 弹层/菜单冲突且 1 个工作日收不住 → 执行 spec D4-4 的回退方案**
  （`grabMouse` 最小版），并把原因写进 inventory；U3 目标相应改为 ≤6（press 起手仍在 widget）。
- [ ] **Step 5：** `PYTEST STRUCT UV -q`。

Run: `PYTEST tests/ui/test_ultraview_viewport_router.py STRUCT -q && PYTEST UV -q`

## Task 8 · 收尾

- [x] **Step 1：** 按新的 `AGENTS.md` 聚焦门禁规则，未重跑全量；Task 0 的三条失配
  （后经 B7 更正为 1 独立 + 1 污染 + 1 已修）已由用户接受为接缝范围外基线，
  且不属于本批代码改动。
- [x] **Step 2：** spec 已改为实施状态，指标、Task 完成表和唯一未验证的 Cocoa 门禁均已记录。
- [x] **Step 3：** D4 lesson 与索引已补；D1–D3 不额外拆 lesson。
- [x] **Step 4：** 已核对 `ui/hints.py` / `ui/quickref.py` 为零改动；用户可见的快捷键和起手
  方式没有变化。
- [x] **Step 5：** 后续 annotation 计划若开工，仍以本批 D0 护栏为前置并另立 page 拆分 spec。

Run: owner + 适用边界聚焦组合（不跑全量 / 全 `UV` 通配集）
