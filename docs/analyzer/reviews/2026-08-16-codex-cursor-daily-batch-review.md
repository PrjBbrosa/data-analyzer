# 2026-08-16 Codex / Cursor 当日批次评审

- 日期：2026-08-16（评审时 HEAD `8d57ab0e`，分支 `codex/ultraview-seam-hardening`，
  `main` 在 `f85f2323`；范围 `f85f2323..8d57ab0e` 共 25 个提交）
- 方式：四路只读评审并行（接缝加固批 / 弹性画布批 + 8d57ab0e / 标注·游标持久化批 /
  全量门禁固定红），全部按 `git show <sha>` 的提交态看，不看工作区；只跑聚焦用例与
  两文件组合探针，**没有跑全量**；bug #3 用用户自己的工程 `testdoc/1.tlproj` 离屏复现。
- 处置：不在本文里修。修法收在
  `docs/analyzer/specs/2026-08-16-daily-review-followup-spec.md`（决策）与
  `docs/analyzer/plans/2026-08-16-daily-review-followup-plan.md`（分 Task）。两份已定稿
  （唯一产品决策 C2 于 2026-08-16 裁决为 (a′)），实施待授权。
- 归属（按提交 trailer / 会话）：接缝加固批（762b09f8…b3a1ab2c）、96977050、96f7341b、
  64dbab74、963f236e、42827bea、c80f46e0、25e8f8b7、8d57ab0e = Codex；d491d41e、
  d18b0cfa、49fa9a3f = Cursor；61c387e6 / b011eced / b41dec42 = Claude（Opus）。

## 0. 结论一览

| 批次 | 目标达成 | 严重 | 中 | 低/观察 | 一句话 |
|---|---|---|---|---|---|
| 接缝加固 D0–D8（10 提交） | 7 达成 / 2 部分 / Cocoa 未验 | 0 | 3 | 5 | 骨架落地，护栏判据偏弱，日志分级自相矛盾 |
| 弹性画布 / chrome / 缩放（9 提交）+ 8d57ab0e | 多数达成，相机合同被改未回写 | 3 | 3 | 4 | 两批各留了红测试没察觉；Retina 背景糊 |
| 标注 / 双游标持久化 49fa9a3f | D1–D11 里 4 条部分 | 2（+用户 bug 2） | 2 | 3 | 三个「真相」互相打架，测试没覆盖真实工程 |
| 全量门禁固定红 12 条 | — | 3 产品 bug | 6 测试 bug | 1 harness 漂移 | **10 条同一污染源**，1 条已修 |

用户报告的两条（bug #3）都复现并定位到根因（§1）。当日批次**没有**新增可复现的功能回归
（除 §3.2 列的 5 条被本批自己打红的 owner 用例），主要债务是接缝语义与测试判据。

## 1. 用户 bug #3：重开工程后 pill 不弹、标注不复原

### 1.1 pill 不弹（复现成功，`testdoc/1.tlproj`）

时序：`open_project` → `_apply_active_view` → `_render_view_onto_canvas` →
`restore_cursor_placement` → `_emit_dual_cursor_html()`，此刻 pill **已可见、2 行**。随后
`_dispatch_pending_analysis_restore()` 逐 tick 重算工程里的 FRF / FFT 分析 View，FRF worker
完成 → `_frf_mixin._on_frf_render_requested` → `frf_canvas.set_result()`
（`frf_canvas.py:873`）→ `_clear_frequency_cursor_readout()`（`:1488-1497`）
`cursor_info.emit("")` → `ChartStack._on_cursor_info("", frf_canvas)`
（`stack.py:1305-1312`）→ `_pill_for_canvas(frf_canvas)` 返回**共享主 pill**
（`stack.py:1266-1272`）→ `pill.clear()` → 隐藏。终态：A/B 竖线在，
`cursor_pill_visible()==False`。`line_canvas.py:2862` / `heatmap_canvas.py:1732` 也发空串，
FFT / 时频 View 同理。

`test_project_roundtrip_restores_remarks_and_dual_cursor` 绿是因为测试工程**没有分析 View**。
Wave 3 的 D10（重绘收口重算）没修到这条，因为它不是「没人算」，是「算完被别人清了」。

**根因归类：产品 bug，长期接缝**——分析画布的读数清空信号没有按「发信画布是否在屏」门禁，
直接落到共享 pill。

### 1.2 标注不复原（保存侧丢，不是恢复侧）

`1.tlproj` 里 View 1 的 `remarks` 保存时就是 `[]`。离屏用同一 MF4、鼠标路径加点、
`save_project`、同窗 / 新窗重开、切 View、切模式再保存，标注都能存能复原。
但确认一条产品 bug：**overlay 模式下取消勾选 / 隐藏任一通道** → `plot_time` 全量重建 →
`canvas.clear()` 现在会 `clear_remarks()`（`canvas.py:2716`），没有人重投影；下一次 capture
的 `merge_remarks_for_capture` 把「通道可见且 live 里没有」判为**用户删除** → ViewState 也
永久丢。subplot 走对象复用路径不 `clear()`，侥幸不清。用户的 View 4 正是 overlay。
另一可能是真机 app 起自 19:58 提交之前的中间态（remark 尚未写 `source`），需用户确认；
但上面这条不修，重现只是时间问题。

**根因归类：产品 bug**——D4「画布是投影，ViewState 是真相」只做了 View 事务这一条路，
非事务重绘没有重投影，而 D5 的合并规则又依赖「live 里没有 = 用户删了」。

## 2. 接缝加固批（762b09f8 … b3a1ab2c，+96977050 / 96f7341b / 64dbab74）

**中**
1. `ultraview_coordinator.py:766-782`（bda69148）`_on_viewport_payload` 对「板已不在工作区」
   打 WARNING，但这是**预期路径**（删活动板 / 工程恢复 / `close_all` 时旧板已移出
   `_workspace.boards`，`page.set_board` 切板前先落旧板视口）。
   `tests/ui/test_ultraview_project_session.py -k "delete or close_all or restore"` 5 条全带
   该 WARNING（每开一次工程一条），与同批 96977050「按故障 / 预期分级」自相矛盾。
2. `viewport_router.py:56-58` `eventFilter` 是**应用级**过滤器，先 `_is_canvas_descendant`
   （isinstance + 父链遍历）再判事件类型——页面可见期间对全 app 每个 QObject 的每个事件
   （Timer / Paint / LayoutRequest / MetaCall …）都走一遍父链。纯开销。
3. `tests/ui/test_ultraview_structure.py` 假绿空间：`_model_field_writes()` 只匹配 4 个硬编码
   目标串（`self._board.viewport` / `board.name` / `active_board(self._workspace).show_*`），
   换个接收者名就不可见；`_page_private_surface()` 只识别字面 `page._x`；U1 / D2 只扫
   page / widgets / chrome 三文件，同目录当天新增的 `elastic_workspace.py` / `feedback.py` /
   `ghost_overlay.py` 不在护栏内；D2 只看 `setFixed*` / `QSize` / `_hint`，
   `setMinimum*` / `resize` / `QRect` 漏。「白名单 → 0」的含金量低于 spec 描述。

**低**
4. spec §5 称「白名单只缩不扩」，但 U4 `FROZEN_MUTATION_FUNNEL_EXCEPTIONS` 3→4、mutator
   冻结集 26→28——设计合理，措辞不实。
5. D2.3 「`_hint` 回退 == 真实 `sizeHint()`」只对导航岛成立（`DEFAULT_NAVIGATION_ISLAND_SIZE
   =(222,40)` 是 chrome 里 `4+32*5+42+2*6+4` 的第二份事实）；实测 Global 108 vs 回退 116、
   Status 197 vs 200、Board 133 vs 240。契约用例只断言「回退 == 常量」。
6. a56df8bd：`_iter_viewboxes` 对**空时域画布**（`axes_list` 空、无 `_plot*`）也告警
   「no viewbox found」，空 View 是合法状态不是探测落空（有 `throttled` 兜底）。
7. 7912d8a7 路由器吞 Space：canvas_host 后代里任何非文本框焦点按空格都被 `note_space` 吃掉，
   与改前 widget 级行为一致，不算回归；`_text_field_has_focus` 只保护 QLineEdit 类。

**观察（核实无问题）**：96977050 `_digest_leaf` 覆盖 tuple / list / dict / dataclass，
`set` / numpy 标量仍会落到 TypeError → digest None → 不抓图，现有键形态都覆盖；2ddd8abc
spy 是真计数（六卡 `[1]`），`projection_batch` 是 `try/finally` 按深度计数；D3
`viewport_changed(str, dict)` 按 board_id 落板，`_restoring_viewport` 早退防回写；路由器
show / hide + WindowActivate / Deactivate 装卸、`_installed` 防双装、唯一性用例钉住；
64dbab74 色板 261→234 只降不升、活性测试改搜模式。**Task 7 Cocoa 前台走查仍是唯一未闭合
门禁**（`gesture-router-cocoa.md` UNVERIFIED）。

## 3. 弹性画布 / chrome / 缩放批（963f236e … b41dec42）+ 8d57ab0e

聚焦实测（HEAD 8d57ab0e）：`ui_kit` QSS 六护栏 29 passed；state / free_grid / elastic /
viewport / card_actions / feedback / history / page / export / mode_integration /
project_session 340 passed / **3 failed**；hints / quickref / help / structure / chrome /
capture / router / visual harness 216 passed / **3 failed**。临时 worktree 逐提交 bisect：

**严重**
1. **8d57ab0e 打红两条 owner 用例未察觉**：`test_ultraview_viewport.py::
   test_title_only_lod_hides_preview_body_and_empty_backing`（49fa9a3f 绿 → 8d57ab0e 红：
   默认改 hover-only 后 TITLE_ONLY 档 action bar 不再常显）与
   `tests/test_verify_ultraview_visuals.py`（42827bea 修绿 → 8d57ab0e 再红：
   `card_context_1280 missing selected-card actions`）。plan 记的 owner 集 316 passed 漏掉了
   viewport 与视觉 harness。
2. **d491d41e 引入 3 条红，被后续 plan 误记为「既有」**：`test_ultraview_page.py::
   test_free_grid_overlap_drop_moves_blocker_without_modal` / `::test_displacement_inside_
   the_viewport_stays_quiet`（42827bea 绿 → d491d41e 红；探针：open-Fit 后 zoom=1.35，被推到
   第 12 列的卡 x=4974 确实在可视区 2714–4295 之外，产品 toast 是对的，是测试前提随「打开
   即 Fit」失效）；`test_ultraview_capture.py::test_place_free_grid_from_unplaced_toasts_
   when_grid_is_full`（文案改成「画布已放置 24 张，已移到未放置区 · 打开」，测试未更新；且
   对「从托盘放置」场景「已移到未放置区」并不准确——它本来就在托盘）。8d57ab0e 的 plan 把
   前两条 deselect 并称「本批之外」。
3. **画布背景 Retina 模糊**（`chrome.py:449-515` `CanvasHost._build_canvas_background`）：
   `QPixmap(width, height)` 按逻辑尺寸栅格化、无 `setDevicePixelRatio`、缓存键只有 size；
   `paintEvent` `drawPixmap(rect, pixmap)` 拉伸——DPR 2 下 23px 点阵、1px 网格、1px 虚线
   「信号地平线」全部放大 2 倍变糊；跨屏 DPR 变化也不重建。offscreen 测不出，需 Cocoa 验。
   同文件 `:160` 的卡片 pixmap 路径是带 DPR 的，只有背景漏了。

**中**
4. **相机合同翻转未回写 plan**：elastic plan §3.4 / Task 2 / UX-01 / UX-08 / UX-11 仍写
   「新板 ≤66%、Fit ≤100%、合法持久化 viewport 精确恢复、加卡 / 切板不改视口」；代码
   （d491d41e / d18b0cfa）已是 `BOARD_FIT_ZOOM_MAX=ZOOM_MAX`（300%）、
   `FIT_CONTENT_MARGIN=0.02`、每次打开 / 切板 `fit_on_open`。只有 lessons 与 quickref
   同步了。结果 `board.viewport` 变成**只写不读**（`_restore_viewport_from_board` 直接
   `del payload`），接缝加固 D3 为它建的 `viewport_changed(board_id)` / `set_board_viewport`
   漏斗现在服务一个永不回放的值；`NEW_BOARD_ZOOM_MAX` / `default_board_zoom` /
   `initial_viewport` 成了无调用方的兼容壳。**已裁决**（2026-08-16 用户选 (a′)）：删持久化与
   漏斗，改为 page 内存里的会话相机 + extent 签名护栏；见 followup spec §C2。
5. **顺序污染新增**：`test_ultraview_viewport_router.py::test_middle_pan_continues_across_
   canvas_children[template_card]` 单跑绿；跟在 `test_ultraview_capture.py` 后必红
   （963f236e 同序绿、42827bea 起红，`is_board_panning()` False）。
6. **schema 3→4 有损迁移**（8d57ab0e）：旧 Board 级 `show_card_actions=True` 一律降为 False
   （plan §2.2 明写有意），schema 3 只活了 5 小时、无用户可见提示——可接受，需在 help /
   发版说明留一句。

**低**
7. `_persist_viewport_to_board` 挂在每个 `valueChanged` 上：edge-pan 16 ms tick 与滚轮期间
   每帧发 `viewport_changed` 并重启 `_focus_timer`（去抖正确）；无消费者（见 4）。
8. 高水位 extent 只增不减：25% 缩小后 halo 按半视口计入，再回 300% 时 `FreeGridBoard`
   尺寸可到数万 px，minimap 里卡片被压得极小。plan §3.2.3 明知取舍，建议 Fit / 切板 reset。
9. b011eced 删的 in-flight guard 确为死代码（`_zoom_at` 内无 processEvents），但现在靠隐式
   不变量；建议结构测试钉「zoom 路径不得调 `_refresh_workspace_extent`」。
10. edge-pan 用例只断言 timer 起停（内部态），未断言滚动条位移与 ghost 跟随。

**观察（核实无问题）**：坐标模型三处换算单点（`GridMetrics.exact_*` /
`FreeGridBoard.zoom_anchor_at` / `_refresh_workspace_extent` 两原点相减补偿）；插入 / 拖边 /
删卡 / 切板 / fit 全走 `set_board → _refresh_workspace_extent()`；分母与 0 尺寸有护；卡片
操作 hover 无 QSettings（plan 明示），workspace 级 + `.tlproj`；`_fit_card_image` 缓存键含
DPR，不放大位图；QSS 色板 244→234→212 只缩。8d57ab0e 设计自洽（workspace 偏好、
schema 4、session 态复位）、与批次方向一致，风险只是翻转默认值却没跑全 owner。

## 4. 标注 / 双游标持久化 49fa9a3f

**严重**
1. 跨 View 落点泄漏（已复现）：`clear()` 不重置 `_ax/_bx`（既有契约），
   `restore_placement(None)` 是 no-op（`cursor.py:259-263`）→ View B（off）开 dual 后直接
   显示 View A 的 A/B，capture 后写进 B 的 state。
2. D3 与 D11 矛盾（已复现）：`off` 保留 `_ax/_bx`（D11），但 `snapshot_placement()` 在非
   dual 返回 None，`to_dict` / `capture_controls_into` 按 mode 门禁写 None → 一次 capture /
   保存就丢意图。「同一份数据两个真相」正是 D11 要消灭的。

**中**
3. §1.1 的 pill 路由接缝（分析画布共享主 pill、无 section 门禁）。
4. §1.2 的 `merge_remarks_for_capture` 无法区分「用户删除」与「画布被重建未投影」。

**低 / 观察**：`raw_channel_name` 用 `[…] ` 前缀启发式剥短名，真名以 `[` 开头的通道会被改写；
`_placing` 推导正确；`_emit_dual_cursor_html` 空 `channel_data` 时 primary 非空，pill 不会
被自己藏；用例只在 D10 后断言 pill 可见，缺「分析 View 在场」与「overlay 重建」两个真实场景。

## 5. 全量门禁固定红 12 条

**一句话：12 条里 10 条是同一个污染源。** `tests/test_verify_ultraview_visuals.py`（文件序
在 `tests/ui/` 之前）调用 `tools/verify_ultraview_visuals._ensure_app()`
（`tools/verify_ultraview_visuals.py:60-66`）→ 对 **session 级 QApplication** 执行
`setStyle("Fusion")` + `load_stylesheet(app)`，之后不还原；`tests/ui/conftest.py:166
_isolate_app_style` 只对 `tests/ui/` 生效且是「快照-还原」——它在第一个 ui 用例开始时快照
到的已经是带全局 QSS 的状态，于是整个 ui 段都在**生产 QSS 下**跑，而这 10 条用例的期望值
是在**无 QSS** 下标定的。两文件组合 100% 复现：
`pytest tests/test_verify_ultraview_visuals.py <任一条>` → 数字与全量日志逐一相同。

关键机制（Qt QSS 盒模型）：QSS `min-width/min-height` 是**内容宽**，`QStyleSheetStyle::polish`
把 `min + padding + border` 写进 `widget.setMinimumSize()`，**覆盖 Python 侧
`setFixedSize/setMinimumSize`**（polish 晚于构造）。所以「生产 QSS 下几何 ≠ Python 常量」
有 3 处是**真产品缺陷**——用户看到的就是错的尺寸——不是测试假红。

`baseline.txt` 的「3 条独立红」判定有误：当时的「聚焦复跑」把污染源放在第一位一起跑，
`test_layout_picker…` 因此被误判为独立红（单跑绿，同跑 20 ≥ 104 失败）。

| # | 用例 | 现状 | 根因 | 修法 | 级 |
|---|---|---|---|---|---|
| 1-2 | `test_pill_switch…[2-*]` | 单跑绿 / 同污染源红 | 测试 bug：`QWidget.render()` 默认画窗口背景，全局 QSS `QWidget{background:#fff}`（style.qss:17）把底涂白，dpr=2 时 x=0 列不再被 1px 描边盖住 → 被 `_knob_center_x` 当成旋钮 | `render(painter, QPoint(), QRegion(), DrawChildren)` 或只扫 x∈[2,42] | P2 |
| 3-5 | `test_batch_render_style_sliders_drag…` ×3 | 同上 | 测试 bug（时序）：`panel.show()` 后立刻开 popover，QSS 触发的延迟重排让锚点 Move/Resize → popover 自己的 eventFilter（`render_style_popover.py:170`）按设计关掉自己，拖拽落空 | 开 popover 前 `waitExposed` + `processEvents()`，断言 popover 可见再拖 | P2 |
| 6 | `test_time_toolbar_has_no_loc_label…` | 同上 | 测试 bug（时序）：QSS 字体让 toolbar 在 `waitExposed` 后一拍才重排（1420→1436），`before` 读早了 | 读 `before` 前 settle 两拍 | P2 |
| 7 | `test_tool_rail_emits…active_badge` | 同上 | **产品 bug**：`QLabel#ultraViewRailFilterWarningDot{min/max 8px; border:1px}`（style.qss:4702）→ 生产里 dot 10×10、`border-radius:4px` 不再正圆；`setFixedSize(8,8)`（chrome.py:639）被 polish 覆盖 | QSS 内容尺寸 6px 或去掉 QSS 尺寸 | P1 |
| 8 | `test_tool_rail_empty_board…primary_cta` | 同上 | **产品 bug**：`QToolButton[role=icon]{min/max 36px; border:1px}`（style.qss:4469-4472）→ 生产里 rail 按钮 38×38，违背 `RAIL_BUTTON_SIZE=36` 与接缝加固 D2 | QSS 内容尺寸 34px（或按常量 − border 生成） | P1 |
| 9 | `test_rail_fitter_shrinks…` | 同上 | 测试 bug：`_measured_full_required` 在 show/polish 前用 `sizeHint` 测量；QSS 下 entry 94→89、`narrow` 低于 host 布局最小，`<` 永不成立 → 超时。**顺带观察**：fitter 用严格 `<` 而 host 最小恰等于 full_required，生产里 compact 是否真能触发需真实 rail 验一次 | show+polish 后再测，按 fitter 同口径 `_widget_min_width` | P2（观察 P1） |
| 10 | `test_layout_picker…template_thumbs` | **单跑绿**（不是独立红） | **产品 bug**：`QToolButton[role=layoutThumb]{min-width:0;min-height:0;padding…;border:1}`（style.qss:4425）→ polish 把最小尺寸改成 14×20，覆盖 `setMinimumSize(168,118)`（chrome.py:1926）；生产 QSS 下缩略图被压到 ~75px 高 | 删该规则的 `min-*` 或写成 `168-12 / 118-20` | P1 |
| 11 | `test_verify_ultraview_visuals…contact_sheet` | 单跑红（真独立） | harness 漂移：25e8f8b7 / 8d57ab0e 把卡片操作改 hover / 偏好显示，harness `card_context_1280` 仍只 `_select_ref` 就要求四个操作可见（`verify_ultraview_visuals.py:819-827`） | 场景先 `set_workspace_show_card_actions(True)` 或给焦点；且 `_ensure_app` 不该改已存在 app 的 QSS | P1 |
| 12 | `test_qss_palette_ratchet…` | **已绿**（64dbab74） | 曾是色板漂移 | 无 | 关 |

复现命令与探针脚本在评审会话 scratchpad `f4/`（`pill_probe*.py` / `toolbar_probe.py` /
`slider_probe*.py` / `fitter_probe.py` / `thumb_probe.py`），未入库。

## 6. 目标达成对照

### 6.1 接缝加固 spec D0–D8
| 决策 | 判定 | 证据 |
|---|---|---|
| D0 结构护栏 | 部分 | 6+2 条测试存在且绿（40 passed），但判据硬编码、扫描面未含新模块（§2-3） |
| D1 批量投影 | 达成 | `projection_batch` + `refresh_page` 收窄到 `membership_set(board)`，spy 六卡 ==1 |
| D2 几何单点 | 部分 | chrome/page 字面量归零；导航岛回退是第二份数值、其余回退≠sizeHint（§2-5） |
| D3 越界写收口 | 达成（含瑕疵） | `viewport_changed(board_id,payload)`→`set_board_viewport`；U1b 4→0、U6 1→0；unknown-board WARNING 噪声（§2-1）；且消费值现已不回放（§3-4） |
| D4 手势路由 | 代码达成 / 真机未验 | `ViewportGestureRouter` 装卸完整，`_page_of` 11→4，29 用例；Cocoa 清单未执行 |
| D5 zoom 单点 | 达成 | `_broadcast_zoom` 唯一站点 |
| D6 探测落空告警 | 达成（含瑕疵） | 空时域画布误报（§2-6） |
| D7 不拆 page / D8 三处存储不动 | 达成 | — |

### 6.2 弹性画布 plan（2026-08-16-ultraview-elastic-canvas-ux-plan）
| Task | 结论 | 证据 |
|---|---|---|
| T0 红测冻结 | 部分 | 新断言已换，plan checkbox 全空、状态头过期 |
| T1 signed grid + elastic_workspace | 达成 | Qt-free；safety ±48/60 |
| T2 scroll host / 初始 66% / Fit≤100% | **合同被改** | 现为 open/switch Fit≤300%（§3-4） |
| T3 边缘自动平移 / 弱提示 | 达成 | page 单 timer、feedback gate；用例弱（§3-10） |
| T4 新卡一次性 auto-aspect | 达成 | `_pending_auto_aspect` 生命周期完整 |
| T5 动作条对齐 / 移除图标 | 达成 | `test_action_buttons_center_in_header_contents_rect` |
| T6 placement undo / 导出 | 达成 | `_free_grid_export_layout` 含负坐标 |
| T7 文案 / help / quickref | 达成 | quickref 已写 300% / 自动适应 |
| T8 钛蓝琥珀 | 部分 | token/QSS 落地；背景 Retina 模糊（§3-3） |
| T9 真机验收 | 未做 | 全部 UNVERIFIED |
| placement-and-preview-clarity T0–4/6 | 达成 | Retina pixmap DPR、anchor resolver 落地；T5 未进门 |
| 8d57ab0e（presentation preference） | 自洽但有风险 | 引入 2 红（§3-1）；owner 集不全 |

### 6.3 持久化 spec D1–D11
| 决策 | 判定 | 证据 |
|---|---|---|
| D1 Qt-free 模块 / 字段 · D2 标注 JSON · D6 复合键 · D8 remap · D10 收口重算 | 达成 | `view_overlay_state.py`、`_add_remark` 写 `source`、`project_io.py:332`、`_restore_dual_cursor_items` |
| D3 双游标 JSON（仅 dual 写） | 达成但与 D11 冲突 | §4-2 |
| D4 画布投影 / `clear()` 先清 | 部分 | 非 View 事务重建不重投影（§1.2） |
| D5 capture 合并 | 部分 | 重建场景误判删除（§1.2） |
| D7 settle 后恢复 | 达成（仅 View 事务） | `_view_mixin.py:548-553` |
| D11 off 只隐藏 | 部分 | 画布保留、state/文件不保留、跨 View 泄漏（§4-1/2） |
| 真机手验 | 未达成 | 有分析 View 的工程 pill 必被清（§1.1） |

## 7. 遗留清单（本批之外仍未闭合）
- Cocoa 真机：接缝加固 Task 7 手势路由；钛金琥珀视觉；弹性画布 T9；8d57ab0e 前台验收；
  持久化 Wave 3 手验（现在必失败，先修 §1）。
- 文档：elastic plan 状态头 / checkbox；`baseline.txt` 「3 条独立红」更正；schema 4 迁移
  说明；`CLAUDE.md` 版本备注仍写 v7.9.9（`app_meta.APP_VERSION` 已是 v8.0.0，帮助页
  meta 也已 v8.0.0）。
- 结构：`board.viewport` 只写不读——**已裁决**（2026-08-16，用户选 (a′)）：删持久化与漏斗，
  改为 page 内存里的会话相机 + extent 签名护栏，跨会话仍 Fit；见 followup spec §C2 / plan Task 12。
  相机合同待随该 Task 回写 elastic plan。
