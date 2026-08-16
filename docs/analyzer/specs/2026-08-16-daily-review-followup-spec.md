# 2026-08-16 当日评审跟进：持久化收口 + 门禁稳定 + UltraView 收尾 · spec

- 日期：2026-08-16 · 状态：**代码已实施（Task 1–15 合入 `claude/daily-review-followup-0816`）。B8 全量绿（HEAD `23d0a1b7`：主体 7402 passed / 0 failed；`tests/acquisition_ui` 359 passed）。C5 Cocoa 真机走查 UNVERIFIED**（见 `docs/analyzer/verify/2026-08-16-daily-followup/cocoa-walkthrough.md`）。
  唯一的产品决策 C2 已由用户于 2026-08-16 裁决为 (a′)，本文无待决项。
- 来源：`docs/analyzer/reviews/2026-08-16-codex-cursor-daily-batch-review.md`（下称「评审」，
  §号引用均指它）
- 配套 plan：`docs/analyzer/plans/2026-08-16-daily-review-followup-plan.md`
- 基线：`8d57ab0e`（分支 `codex/ultraview-seam-hardening`；`main` 在 `f85f2323`）。行号取自
  该提交，实施前若 HEAD 前进按函数名重锚。
- 关系：修订 `2026-08-16-view-markup-and-cursor-persistence-spec.md` 的 D3 / D4 / D5 / D11
  （本文 §A 为准）；不改 `2026-08-15-ultraview-seam-hardening-spec.md` 的 D0–D8 结论，只补
  其护栏判据（§C3）；`2026-08-16-ultraview-elastic-canvas-ux-plan.md` 的相机合同按 §C2
  已裁决的合同回写。

## 0. 一句话

三件事：**(A)** 让时域 View 的标注 / 双游标只有一个真相并在所有重绘后自动回来，pill 不再被
看不见的分析画布清掉；**(B)** 全量门禁的 12 条固定红按根因分治——堵住一个 QSS 污染源、修
三处「生产 QSS 下几何和 Python 常量打架」的产品缺陷、修五处测试时序探针、更新视觉 harness；
**(C)** 把当天 UltraView 三个批次留下的红测试、Retina 背景、日志分级、护栏判据、相机合同
收干净。都在现有接缝内部，不新增模块层级，不拆 page，不改 ink 常量。

## 1. 问题本质

- **A · 三个真相**：标注同时活在 Qt 物品（`AnnotationManager.remarks`）、`ViewState.remarks`、
  和 capture 合并规则的推断里；游标落点活在 `CursorController._ax/_bx`、
  `ViewState.cursor_placement`、和 `cursor_mode` 门禁里。任何一条路径漏了同步（非 View 事务的
  `plot_time` 重建、`off` 后一次 capture、`restore_placement(None)` no-op）就出现「存了但看不
  见 / 看见了但没存 / 看见了别的 View 的」。评审 §1、§4。
- **A · pill 是共享控件却按画布路由**：`ChartStack._pill_for_canvas` 把所有非分屏画布的读数
  都投到主 pill，`_on_cursor_info("")` 不问「发信画布在不在屏上」直接清（`stack.py:1266-1312`）。
  分析画布 `set_result` / `plot_spectra` 都会发空串（`frf_canvas.py:1496`、
  `line_canvas.py:2862`、`heatmap_canvas.py:1732`）。评审 §1.1。
- **B · 测试测的不是产品**：几何契约全部在无 QSS 下标定；生产 QSS 装上后 Qt polish 把
  `min + padding + border` 写回 `setMinimumSize` 覆盖 Python 常量。污染源一装 QSS，测试就
  暴露出这批真实缺陷，被当成「顺序污染」搁置。评审 §5。
- **C · 批次自查不足**：owner 集漏掉 viewport / 视觉 harness（8d57ab0e）、把自己引入的红
  记为既有（d491d41e）、相机合同改了 plan 没改、背景 pixmap 漏 DPR。评审 §3。

## 2. 设计决策

### A · 时域 View 标注 / 双游标：一个真相

**A1 · pill 路由按「发信卡片是否在屏」门禁。**
`ChartStack._on_cursor_info / _on_dual_cursor_info / _on_dual_cursor_rows /
_on_frequency_cursor_rows` 增加同一条前置：`card = self._card_for_canvas(source)`，若
`card` 的 `_chart_mode` 不等于 `self.current_mode()`（分屏 secondary 视为 `'time'`），
**直接返回**——不清 pill、不写 `_active_cursor_card`、不 reposition。分析画布的
`set_result` / `plot_spectra` 不改（它们发空串是自己的读数语义），门禁只在 stack 一处。
`source is None` 的历史调用视为主时域画布。
验收判据（用户可见量）：含 dual 落点 + 带 source 的 FRF/FFT View 的工程，`open_project` 后
drain 分析恢复队列，`cursor_pill_visible()` 为 True 且 pill 行数 == 可见通道数；切到 FRF
再切回时域，pill 仍在。

**A2 · 标注：画布持有 Qt-free 意图列表，Qt 物品只是投影。**
- `AnnotationManager` 新增 `_intent: list[dict]`（D2 形状：`source/x/y/label_dx/label_dy`）。
  `_add_remark` 追加意图 + 投影；`_remove_remark_at/_by_index` 按物品反查意图并删除；
  `clear_remarks()` 保持「全清」语义（意图 + 物品，用户「清除标注」与 View 事务替换都用它）；
  新增 `_drop_remark_projection()` 只删 Qt 物品，**`canvas.clear()` 改调它**
  （`canvas.py:2716`），不再动意图。
- `_project_remarks()`：按当前 `_channel_lines` 复合键把意图重绑（沿用现有
  `_line_binding_for_source` + `_snap_channel_xy`），通道不在图上的意图**保留不画**。调用点
  与 D10 的 `_restore_dual_cursor_items()` 同一个收口（`plot_channels` 尾部，曲线与
  `channel_data` 就绪之后）——非 View 事务的重绘（勾选 / 隐藏通道、`plot_time`、
  overlay⇄subplot、滤波面板）自动回来。
- `snapshot_remarks()` 返回意图列表；返回前对**仍有活投影**的条目回读 `label_dx/dy`
  （用户拖过标签）与 `x/y`。`restore_remarks(payload)` = 规范化后整体替换意图 + 立即投影。
- View 事务：`_render_view_onto_canvas` 把 `restore_remarks(state.remarks)` **挪到**
  `_plot_time_on_canvas` 之前（只写意图，投影由 plot 收口统一做，避免先投影 outgoing View
  再替换的一帧浪费）；settle 之后不再单独 restore。`_applying_view` 守卫不变。
- `view_bridge.capture_controls_into`：`state.remarks = normalize_remarks(snapshot)`，
  `merge_remarks_for_capture` **退役**（意图已经是 View 作用域且含隐藏通道条目，D5 的推断
  没有存在理由；保留函数一版只做 no-op 兼容并标 deprecated，下一批删）。
- `_owned_names` 若新增托管属性，同步 `tests/ui/test_pg_canvas_backref_invariants.py`；
  意图列表是 manager 自己的属性，不写穿宿主。
验收判据：overlay 加点 → 取消勾选另一通道 → capture → 标注仍在画布且在 `state.remarks`；
subplot 同；隐藏该通道再显示 → 标注回来；用户删点 → capture 后 state 里没有；
`test_view_switch_does_not_leak_remarks_across_time_views` 继续绿。

**A3 · 双游标落点：不看模式，永远持久化；`restore_placement(None)` 清空。**
- 修订 D3：`cursor_placement` 只要 `ax` 有限就写，**不再按 `cursor_mode == "dual"` 门禁**；
  `normalize_cursor_placement` 去掉 `cursor_mode` 参数的过滤作用（保留签名兼容），
  `ViewState.to_dict/from_dict`、`capture_controls_into`、`capture_view` 同步。显示与否由
  `cursor_mode` 决定（D11 不变）。顶层 schema 仍为 2：老文件缺字段 = None；新文件被旧版本
  读到时旧 `normalize` 会按 mode 丢弃，无害。
- `CursorController.snapshot_placement()` 不再判 `_dual`。
- `restore_placement(None)` / 非法 payload → **清 `_ax/_bx`、隐藏 A/B 物品与极值标记、
  `_placing="A"`**；dual 模式下 emit 一次让 pill 回到「Click A」。这是 View 事务里唯一能
  防止 View A 落点漏进 View B 的地方（`clear()` 不重置 `_ax/_bx` 的既有契约不动）。
- `set_dual_cursor_mode(False)` 保持 D11（只隐藏）；`reset_cursor_state()` 仍是显式抹除。
验收判据：View A 放 A/B → 新建 View B（off）→ B 开 dual → 画布无 A/B、pill 「Click A」；
A 放 A/B → 切 off → 保存 → 重开 → 切 dual → A/B 回来且 pill 读数重算；
`test_pg_cursor_placement.py` 现有用例按新语义更新（off 时 snapshot 不为 None）。

**A4 · 护栏判据只认用户可见量**（延续原 spec §5）：pill 可见 + 行数、A/B 物品 `isVisible()`、
`remark_count()` + 落点像素；新增两条真实场景用例：「工程含 FRF/FFT View」「overlay 重建」。

**A5 · 帮助页**「工程里存了什么」一句改为：标注与双游标落点随 View 保存（关闭游标只是不
显示，重新打开仍在）。

### B · 全量门禁稳定

**B1 · 堵污染源：`tests/conftest.py` 目录级 autouse 快照-还原 app 样式。**
新建 `tests/conftest.py`（目录 conftest，不是仓库根 `conftest.py`——那份按 CLAUDE.md 只做
collector 去重、不放 fixture），autouse function 级 fixture：setup 时记录
`QApplication.instance()` 的 `styleSheet()` / `style().objectName()` / `palette()` / `font()`
（无 app 则记为「无 QSS / 默认」），teardown 时若 app 存在且任一项变了就还原。
`tests/ui/conftest.py::_isolate_app_style` **保留**（ui 段再兜一层，重复还原是幂等的、
零成本；它的 docstring 记着三个真实历史 bug，删掉会丢掉那份说明）。`tools/verify_ultraview_visuals._ensure_app` 作为 CLI 工具**保留装
QSS 的行为**（真机视觉需要），由 fixture 负责还原；不在工具里加 test-only 分支。
验收：`pytest tests/test_verify_ultraview_visuals.py tests/ui/test_pill_switch.py
tests/ui/test_ultraview_chrome.py tests/ui/test_ultraview_entry.py tests/ui/test_chart_stack.py
tests/ui/test_batch_output_panel.py -q` 全绿（这就是评审 §5 的复现组合）。

**B2 · QSS ↔ Python 几何：同一尺寸只许一处写，且契约在生产 QSS 下断言。**
- 规则：Python 已 `setFixedSize/setMinimumSize` 的控件，QSS 里**不写** `min-*/max-*`；反之
  QSS 写尺寸的控件 Python 不再写。若 QSS 必须写（依赖伪状态），值 = 常量 − 2×border −
  padding，注释引用 `floating_layout` 常量名。
- 三处产品修：`QToolButton[role="icon"]`（style.qss:4469-4472，36 → 内容 34 或删）；
  `QLabel#ultraViewRailFilterWarningDot`（:4702，8 → 内容 6，半径按最终盒 /2）；
  `QFrame#ultraViewLayoutPopover QToolButton[role="layoutThumb"]`（:4425，删 `min-width:0;
  min-height:0`）。
- 新护栏：`tests/ui/test_ultraview_chrome.py` 加一组「装载生产 QSS 后」的几何断言（rail 按钮
  == `RAIL_BUTTON_SIZE`、warning dot 8×8、layout thumb `minimumHeight ≥ 104`），fixture 负责
  还原；这组是**用户看到的产品**的契约，与无 QSS 契约并存。
- 顺带核查（不在 B2 里修）：`ui_kit/style.qss` 其余 `min-*/max-*` 与 Python `setFixed*` 重复
  的地方列成清单进 inventory，交后续批。

**B3 · 五处测试时序 / 探针修（评审 §5 表 #1-6, #9）**：`test_pill_switch` 的
`_render_at_dpr` 不画窗口背景（`render(painter, QPoint(), QRegion(), DrawChildren)`）；
`test_batch_output_panel` 开 popover 前 `waitExposed` + settle 并断言 popover 可见；
`test_chart_stack` 的 `before` 在 settle 两拍后读；`test_ultraview_entry` 的
`_measured_full_required` 在 show + polish 后按 fitter 同口径 `_widget_min_width` 测。
**观察项转 Task**：rail fitter 用严格 `<` 而 host 布局最小恰等于 `full_required`，生产里
compact 档是否真能触发，用真实 ChartStack rail 在生产 QSS 下验一次；不能触发就是产品 bug。

**B4 · 视觉 harness 与 8d57ab0e 契约对齐**：`card_context_1280` 场景先
`set_workspace_show_card_actions(True)`（或给选中卡键盘焦点）再抓，`assert_geometry` 的
「selected-card actions」判据改成「hover / 焦点 / 常驻三者之一」；
`test_title_only_lod_hides_preview_body_and_empty_backing` 同理改前提。

**B5 · d491d41e 三条红**：`test_free_grid_overlap_drop_moves_blocker_without_modal` /
`test_displacement_inside_the_viewport_stays_quiet` 的前提改为「打开即 Fit」的合同（先把视口
zoom 设到能容纳目标列，或断言 toast 内容而非静默）；
`test_place_free_grid_from_unplaced_toasts_when_grid_is_full` 更新文案，且产品文案对「从托盘
放置」场景改为「画布已放置 24 张，仍在未放置区 · 打开」（评审 §3-2）。

**B6 · 新增顺序污染**：`test_ultraview_viewport_router.py::test_middle_pan_continues_across_
canvas_children[template_card]` 跟在 `test_ultraview_capture.py` 后红。先用两文件组合复现，
再按 F1 的路由器生命周期（`_is_active` 依赖 `QApplication.activeWindow()` / 隐式抓取）排查
capture 用例是否留下了未关的顶层窗或未释放的 grab；修根因不加 skip。

**B7 · 基线文档更正**：`docs/analyzer/verify/2026-08-15-ultraview-seam-hardening/baseline.txt`
的「3 条独立红」改为「1 条独立（harness）+ 1 条污染（layout picker）+ 1 条已修（palette）」；
`docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6 补一行指向本 spec。

**B8 · 全量只跑一次。** 本 plan 结束前由协调者独占跑一次两条串行全量（CLAUDE.md 门禁）作
验收；期间任何人不得改工作区。目标：主体 **0 failed**（`test_gen_help_screenshots` 环境性红
除外）+ `tests/acquisition_ui` 全绿。达不到 0 的每一条都要在 plan 里有名字。

### C · UltraView 三批次收尾

**C1 · 画布背景 DPR**：`CanvasHost._build_canvas_background(size)` 改为
`QPixmap(size * dpr)` + `setDevicePixelRatio(dpr)`，缓存键 `(size, dpr)`；`paintEvent`
`drawPixmap(rect, pixmap)` 保留（源 rect 与目标 rect 同逻辑尺寸即不拉伸）。跨屏 DPR 变化
（`QEvent.ScreenChangeInternal` / `devicePixelRatioF()` 变）时失效缓存。Cocoa 真机截图对比
点阵 / 网格 / 虚线像素锐度。

**C2 · 相机合同：会话内记住、不进工程（已裁决，2026-08-16 用户选 (a′)）**

现状：`_persist_viewport_to_board`（`page.py:1204`）在每次滚动 / 缩放把 zoom+center 写进
`board.viewport` 并存入 `.tlproj`，而 `_restore_viewport_from_board`（`page.py:1494`）第一行
就是 `del board, payload` 然后 `fit_on_open()`——**只写不读**。「永远适应」不是深思熟虑的
产品决定，是绕开一个坐标 bug 的处置后固化成了合同（该函数 docstring：restoring a stored
centre on the signed elastic halo is what made open and switch land in an unexplained place）。

**合同（本文为准，回写 elastic plan）：**
1. **打开工程 / 首次进入某 Board / 跨会话** → 适应（`fit_on_open`），行为与今天一致。
2. **同一会话内切板往返** → 回到离开该板时的 zoom 与 center，**前提是该板的弹性 extent
   签名没变**；签名一变（加卡 / 删卡 / 拖进负象限导致 rebase）→ 回到适应。
3. **相机不进 `.tlproj`**：`viewport` 字段、`viewport_changed` 信号、`set_board_viewport`
   漏斗与 `NEW_BOARD_ZOOM_MAX` / `default_board_zoom` / `initial_viewport` 兼容壳一并删除；
   顶层 schema 不 bump，旧工程里的 `viewport` 读到即忽略。

**为什么不能简单「把读打开」（这条决定了实现形状，别绕过）**：`_current_center()`
（`page.py:1610`）= (滚动位移 − `_board_content_origin()` + 视口/2) / zoom。该 origin 随
**弹性 extent rebase** 移动（卡片进负象限、加卡长画布 → `extent.column/row` 变），同一个
center 数值改指另一处。本合同用「签名一致才恢复」把跨 rebase 恢复在**结构上**排除掉，
因此**不需要**把 center 改成有符号格坐标；反过来说，**谁要放宽这条签名判据，就必须先把
坐标换成 rebase 不变量**，否则等于重开 d491d41e 修掉的 bug。

**实现要点：**
- `page` 自持 `_session_camera: dict[board_id, (zoom, center, extent_signature)]`——UI 会话态
  而非 Board 内容，不进模型、不碰状态所有权棘轮与 D0 mutator 冻结集（白名单只缩不扩仍成立）。
- 签名取 `(column, row, columns, rows)`（`GridBounds`）。判等即恢复，否则 `fit_on_open()`。
- 生命周期：离开板时写入；`close_all` / 切换工程 / page 重建时清空；不落盘。
- 删除 `_legalize_viewport` 这条 warning 源——旧工程里非法的 viewport 今天会经
  `_project_io_mixin.py:1989` 弹 toast「总览布局有 N 项无法识别，已按合法值恢复」，为一个
  从不使用的值弹提示；删字段后该假提示随之消失。
- 连带收益：`_on_viewport_payload` 一并删除，评审 §2-1 的 unknown-board WARNING 噪声消失
  （C3 里那一条随之作废，只剩 `_iter_viewboxes` 一处要改）。

**已否决的两个备选（记录理由，别再重提）：**
- **(a) 相机存进 `.tlproj`、跨会话恢复**——否决：需先把 center 换成有符号格坐标才安全，
  改造成本与风险高于收益；且换屏幕 / 换窗口尺寸后旧相机常常离谱。若将来确有「关掉软件明天
  打开还停在原位」的明确需求，再另立 spec，并以坐标改造为前置。
- **(b) 只删持久化、不记会话相机**——否决：会丢掉「放大看某张卡 → 去另一块板核对 →
  切回来」的连续性，而 (a′) 用一份内存字典就能拿到，代价只有一个签名判等。

其余不变：elastic plan §3.4 / Task 2 / UX-01 / UX-08 / UX-11 与状态头必须回写成本合同。
高水位 extent（评审 §3-8）在 Fit / 切板时 reset 到内容包围盒 + halo。

**C3 · 接缝加固收尾**：`_on_viewport_payload` unknown-board 降 DEBUG（或 page 切板目标不在
workspace 就不 emit）；`_iter_viewboxes` 区分「host 无 axes 且无 `_plot*`」（空 View，不告警）
与「有 axes 但 view_box 为 None」（告警）；`ViewportGestureRouter.eventFilter` 先按关心的
6 种 `event.type()` 早退再走父链；结构护栏泛化——`_model_field_writes` 按
`UltraViewBoardState` / `UltraViewWorkspaceState` 字段名集合匹配任意接收者的 `X.<field> =`，
`_page_private_surface` 识别 `self._page._x` / 任意名 `._x`，U1 / D2 扫描面改目录通配，D2
补 `setMinimum*` / `resize` / `QRect`；D2.3 契约补「回退 == 真实 `sizeHint()`」（导航岛的
第二份数值改为从 chrome 计算或反向由常量生成）；新增结构用例钉「`_zoom_at` 路径不得调
`_refresh_workspace_extent`」；edge-pan 用例补滚动条位移与 ghost 跟随断言。

**C4 · 文档同步**：schema 3→4 有损迁移在 `ultraview-guide.html` 与发版说明各一句；
`CLAUDE.md` 版本备注 v7.9.9 → v8.0.0（`app_meta` / 帮助页已是 8.0.0）；lessons-learned 三条
（QSS polish 覆盖 `setFixedSize`；分析画布清共享 pill 需 section 门禁；tools 模块在测试进程
装 app 级 QSS 的污染模式）+ INDEX。

**C5 · Cocoa 真机门禁合并成一次走查**：接缝加固 Task 7 手势路由五起点；钛金琥珀 + C1 背景
锐度；edge-pan 手感；8d57ab0e hover 操作条；A1–A3 的手验清单（原持久化 plan Wave 3 两条 +
本文 A 的三条验收判据）。一次走查出一份 `docs/analyzer/verify/2026-08-16-daily-followup/
cocoa-walkthrough.md`。

## 3. 显式不做
- 不拆 `page.py` / coordinator；不合并 pill 为每画布一份（A1 是门禁不是重构）。
- 不动 ink 常量、AA 闸门、离散结算。
- 分析 View 的标注 / 频率双游标持久化（原 spec D9 不做项不变）。
- pill mini/full 与用户拖位持久化。
- 不为 B1 给 `tools/verify_ultraview_visuals` 加 test-only 分支。
- 不重写 `test_ultraview_structure.py`，只泛化判据。
- 不做跨会话（落盘）相机持久化——C2 备选 (a) 已否决；会话相机只活在内存里。

## 4. 验证策略
每 Task 只跑自己的 owner 用例 + 该层机械护栏（plan 里逐条列）。全量只在 B8 跑一次、由协调者
独占。真机项集中在 C5 一次走查。**任何一条把既有测试改红且 30 分钟定位不到 → revert 该 Task
回报**，不改护栏、不放宽阈值。

## 5. 量化目标
- 全量主体固定红 12 → 0（`test_gen_help_screenshots` 环境性除外）。
- 时域 View 标注 / 游标真相 3 → 1（意图列表 / `_ax,_bx` + ViewState，一一映射，无推断）。
- 生产 QSS 下与 Python 常量不一致的 UltraView 几何 3 → 0，且有护栏。
- 当日三批次留下的红 owner 用例 5 → 0。
- `board.viewport` 只写不读 → **删除**；相机改为会话内内存字典，切板往返可恢复
  （C2 已裁决 (a′)）。旧工程因非法 viewport 弹出的「N 项无法识别」假 toast 归零。
