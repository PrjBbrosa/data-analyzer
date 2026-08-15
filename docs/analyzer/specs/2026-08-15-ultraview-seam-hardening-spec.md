# UltraView 接缝加固（结构护栏 + 五处接缝）· spec

- 日期：2026-08-15 · 状态：**PROPOSED（待授权）**
- 配套 plan：`docs/analyzer/plans/2026-08-15-ultraview-seam-hardening-plan.md`
- 基线：`claude/ultraview-library-geometry-material` @ `c2502de1` + 写本文时（08-15 23:30
  前后）工作区里那批**未提交**的 View 库几何/材质改动。**本文行号取自该工作区快照，不是
  `c2502de1` 本身**——写作期间那批还在被并行会话继续改（同一函数前后两次读到的行号已差
  约 40 行），所以行号只当定位提示，**plan 的 Task 0 必须在那批提交后重新锚定**。
  引用的函数名 / 信号名 / 常量名是稳定的，以名字为准。
- 来源：2026-08-15 UltraView 架构评估（是否需要重新梳理整合）。评估结论与证据收在本文
  §1，不另立 review 文档。
- 前置：无硬前置。与 `2026-08-15-ultraview-annotation-notes-arrows-plan.md`（0/35 待授权）
  的关系见 §4 D7。

## 0. 结论

**不重新梳理整合。** UltraView 的骨架是对的：单一状态 owner、单一变更漏斗、单向数据流、
单一全量刷新根、Qt-free 的模型层、零 `except Exception`、零 lambda 信号连接、
coordinator 3030 行没有一个方法超 60 行。缺陷史里生命周期/崩溃一类在 08-14 就收口了，
剩下的复发都指向**几个具体接缝**，不是耦合结构。

本批只做两类事，都在现有接缝**内部**：

1. **把五条目前只靠约定成立的结构不变量钉成 AST 护栏**（D0）——它们是当前真正在维持
   稳定的东西，而现在没有任何机械看守。
2. **修五处已被缺陷史点名的接缝**（D1–D5）+ 一处静默退化补日志（D6）。

衡量指标（都由常驻测试机械看守，详见 §5）：
- 结构护栏文件存在且 6 条不变量全绿；各白名单**只许缩小**。
- 切 Board 时全量投影次数 **N+1 → 1**（N = 进入 Board 的卡片数）。
- 视图层对模型对象的直接属性写 **1 → 0**；coordinator 对 page 私有方法调用 **1 → 0**。
- `_page_of` 触达面 **11 → ≤4**（若 D4 落地）。
- rail / 岛几何字面量在 `floating_layout.py` 之外的出现次数 **→ 0**。

## 1. 评估依据

### 1.1 结构事实（实测于 `c2502de1` 工作区）

| 维度 | 实测 | 判定 |
| --- | --- | --- |
| 状态所有权 | 唯一 owner `UltraViewCoordinator._workspace`（`ultraview_coordinator.py:448`）。26 个 `ultraview_state` mutator 的调用点：coordinator **27** 处；`page.py` / `widgets.py` / `chrome.py` **0** 处 | ✅ 单一写者 |
| 变更漏斗 | `_after_board_mutation()`（`:1345`）27 个调用点：`mark_workspace_mutated` → `refresh_page`；free-grid 再经 `_commit_grid_change`（`:1584`）→ `_record_grid_transition`（`:1571`）推 undo | ✅ 单漏斗（后置钩子形态，靠约定） |
| 数据流 | widgets —signal→ page —38 个 `*_requested`（`_connect_page` `:899-943`）→ coordinator —13 个公开方法→ page。page 对 coordinator/window **零**引用（`tests/ui/test_ultraview_page.py:432` 钉了 import 边界） | ✅ 单向环 |
| 刷新入口 | 唯一全量根 `page._refresh_projection`（`page.py:2262`），其下是树；coordinator 侧唯一全量路径 `refresh_page`（`:1200`） | ✅ 无并行 rebuild 路径 |
| 模型层 | `ui/ultraview_state.py` / `layouts` / `free_grid` / `viewport` / `floating_layout` / `gesture` 全部 Qt-free（已有 AST 测试钉住） | ✅ |
| 代码卫生 | `except Exception` 0；`connect(lambda` 0；`QTimer.singleShot` 仅 6 处；重入守卫只有 `_restoring_viewport` + `_drag_kind` 家族 + `_sync_nav_busy` | ✅ |
| 生命周期 | 三个 hook 注册表显式断开（`:2015-2045`）；每个延迟回调 weakref + `_inactive()`（47 处）；`shutdown()` 幂等；`test_ultraview_lifecycle_subprocess.py` 4 条子进程用例 | ✅ |
| 类形态 | `UltraViewPage` 186 方法 / 60 实例属性；coordinator 181 方法 / 30 属性；`FreeGridBoard` 57 方法。**宽而不深**：只有 `__init__` 类方法超 100 行 | ⚠️ 大但可导航 |
| 测试 | 18 个文件 13.7k 行，`c2502de1` 工作区 850 passed / 1 failed（那 1 条是在途未提交批删了 `_focus_btn` 没同步 `test_ultraview_viewport.py:880`，非提交态问题）；测试对私有属性的引用 253 处 / 89 个名字 | ⚠️ 重构会大量翻测试 |

### 1.2 缺陷史（08-13 → 08-15，27 条 `fix(` 提交按根因分类）

| 根因 | 条数 | 备注 |
| --- | --- | --- |
| 几何/布局数学 | 8 | 弹层尺寸、fit/zoom 锚点、rail 约束、裁切 |
| 状态同步漂移 | 6 | digest 假新鲜、dim 集合泄漏、ghost ≠ 提交结果、内部 flag ≠ 显示态 |
| 容量/LOD/预算 | 4 | |
| 生命周期 | 3 | `60516a72` 之后只剩一条一行的 `WA_DeleteOnClose` |
| 手势/事件路由 | 3 | |
| 视觉 | 2 | |
| 重入/时序 | 1 | |

几何 + 状态同步 = 14/27。**真实复发**（同症状修两次以上）：

- rail 防重叠约束：`3971d5a3` 删掉 → `0c7a8cbb` 加回；zoom 锚点：`3b2d8cde` → `c84cf400`。
  根因：几何常量多处散写，一处修完把另一处的约束顶掉（→ D2）。
- View 库止跳：`ef33592f` → 1.5 小时后 `bfd06625` 又修一次（→ D1 的批量投影减少重建次数）。
- 浮岛按钮激活态残留 / 弹层消隐：`58fee980` → `7a75054e` → `c2502de1`。
- 手势被误取消：`09262e15` → `423b0aef`（→ D4 集中路由）。
- Board 新鲜度五轮（`5e36b27a` → `c84cf400`）——digest / store / page 影子字典三处存新鲜度。
  这条**本批不动**（见 §4 D8），已有三篇 lessons 记录，需要单独立项。

### 1.3 已被识别、目前只靠约定成立的不变量

1. `page.py` / `widgets.py` / `chrome.py` 不调用任何模型 mutator。
2. `page.py` 没有指回 coordinator / window 的引用。
3. `widgets._page_of()`（`widgets.py:144`）只触达 page 的 11 个方法。
4. coordinator 里每个调用 mutator 的方法都以 `_after_board_mutation()` /
   `_commit_grid_change()` 收尾。
5. `_page_of` 用 `objectName() == "ultraViewPage"` 字符串匹配，对应 `page.py:226`
   的 `setObjectName`；改名即静默失效（所有画布手势变 no-op，无异常）。
6. coordinator 只经公开方法驱动 page（当前唯一例外：`:1358` 调 `page._select_ref`）。

`tests/ui/test_main_window_state_ownership.py:118` 明确只扫 `MainWindow` + `*Mixin`，
coordinator 不在棘轮内；`test_no_lambda_signal_connections.py` 覆盖了这些文件但只看 lambda。

## 2. 问题本质

不是「结构不对」，而是「对的结构没有护栏 + 几个接缝各自留了一处复制/越界」。
复制和越界本身都不大，但缺陷史证明它们就是复发点：几何字面量分散导致「修 A 顶掉 B」，
平移转发五处复制导致「新 widget 忘抄一段就断手势」，N+1 全量投影放大了每次 View 库/卡片
重建的可见抖动。

## 3. 设计决策

### D0 · 结构护栏 `tests/ui/test_ultraview_structure.py`（先立法，后施工）

照 `tests/ui/test_main_window_state_ownership.py` 的 AST 手法，一个文件六条不变量。
**每条白名单在 Task 0 实测生成、只许缩小**；本批各接缝任务收尾动作就是「白名单删条 +
本测试转绿」。

| # | 不变量 | 机械形式 | 基线 → 目标 |
| --- | --- | --- | --- |
| U1 | 视图层不写模型 | 扫 `page.py` / `widgets.py` / `chrome.py` 的 `Call` 节点，被调名 ∈ `ultraview_state` 的 mutator 集合（Task 0 从该模块导出：所有接受 board/workspace 并返回 `list[str]` 警告的函数 + `create/duplicate/rename/delete/reorder_board` + `set_active_board` + `mark_workspace_mutated` + `set_workspace_preview_sidecar`）；**另**扫对 `self._board.<x> = ` / `self._workspace.<x> = ` 的属性赋值 | 调用 0 → 0；属性写 1（`page.py:1030`）→ 0（D3） |
| U2 | page 无反向引用 | `page.py` / `widgets.py` / `chrome.py` 的 AST `Name`/`Attribute` 中不出现 `coordinator` / `_ultraview` / `MainWindow` / `main_window` | 0 → 0 |
| U3 | `_page_of` 触达面 | `widgets.py` 中 `_page_of(...)` 结果上访问的属性名集合 == 冻结白名单 | 11 → ≤4（D4） |
| U4 | 变更必经漏斗 | coordinator 中「调用了 mutator 但函数体内既无 `_after_board_mutation` 也无 `_commit_grid_change` / `_apply_grid_snapshot`」的方法名集合 == 冻结白名单（合法的是被上层调用者收尾的纯 helper，逐条注释为什么） | Task 0 实测 N → N（不缩，只防增） |
| U5 | 页面 objectName 契约 | 字面量 `"ultraViewPage"` 在 `chart_stack/ultraview/**` 与 `ui/ultraview_state.py` 中只允许出现一次——常量 `ULTRAVIEW_PAGE_OBJECT_NAME`（放 `ultraview_state.py`，与既有 `ULTRAVIEW_REF_MIME` 同址）；`page.setObjectName` 与 `_page_of` 都引用它 | 2 处字面量 → 1 |
| U6 | coordinator 只用 page 公开面 | coordinator 中 `page._<x>` 形式的属性访问集合 == 冻结白名单 | 1（`_select_ref`）→ 0（D3） |

U1 的 mutator 集合**不要手抄**：测试运行时 `import ultraview_state` 按签名/命名规则收集，
再与一份显式冻结清单比对（防止新增 mutator 悄悄不入集）。

### D1 · `refresh_page` 批量投影 + 两处双触发

现状（`ultraview_coordinator.py:1200-1214`）：`page.set_workspace(...)` 触发一次
`_refresh_projection`；随后对**全工作区所有 Board** 的每个 ref 调 `_push_preview`
（`:1284`）→ `page.apply_preview_and_status`（`page.py:1677`）→ 只要 record 或 status
变了就再 `_refresh_projection()`。切 Board 时 `set_board` 里 `_prune_runtime_caches()`
（`page.py:1742` → `:1717`）先把不在新 Board 的影子清掉，进入 Board 的每个 ref 都
`changed=True`——**N 张卡 = N+1 次整板重建**。稳态变更被 `if changed` 抑到 1 次，
所以这是切板延迟/抖动，不是正确性问题；但也是每次改名都遍历 20 个 Board 算 digest。

决定：
1. page 增加投影批处理：`begin_projection_batch()` / `end_projection_batch()`
   （或 `contextmanager projection_batch()`），批内 `apply_preview_and_status` /
   `set_preview` / `set_ref_status` / `set_library_rows` 只标脏不投影，`end` 时投影一次。
   `refresh_page` 整段包在批里。**不改** `apply_preview_and_status` 对外语义（测试直接调它
   仍同步刷新）。
2. `refresh_page` 推送范围收窄为**活动 Board 的 `membership_set`**（含 unplaced）。
   Task 0 先核实没有消费者读非活动 Board 的 `page._previews`（`show_focus` /
   `_refresh_open_focus` / tray 都在活动 Board 内）；若有，保留全量推送但仍走批处理。
   library 行的状态本就直接从 store 算（`_refresh_library`），不依赖 page 影子。
3. 顺手收两处双触发（都在 page）：
   - `_refresh_minimap` 连了 5 个滚动条/视口信号（`page.py:435-439`）又在
     `_refresh_free_grid_projection` 里直接调（`:2426`）；`set_free_grid` → `_sync_metrics`
     改尺寸 → `rangeChanged` 已经触发一次。去掉直接调用，或改为批内合并。
   - `_select_ref`（`:2187`）先 `_refresh_projection()`（其中 `_sync_transient_chrome`
     已经调 `_refresh_card_context`）再显式 `_refresh_card_context()`；去掉第二次。

验收：spy 测试——N 张卡的 Board 切入时 `_refresh_projection` 恰好 1 次；改名一次 ≤1 次；
`apply_preview_and_status` 单独调用仍同步刷新（既有语义）。

### D2 · 浮层几何常量单一事实源

现状（HEAD）：`floating_layout.py` 定义 `RAIL_WIDTH=48` / `RAIL_CONTENT_HEIGHT=196` /
`ISLAND_HEIGHT=40` / 四个岛宽；`chrome.py:48` 另有 `RAIL_MIN_HEIGHT = 196`（同值另写）、
`:460 setFixedWidth(48)`、`:618 QSize(48, …)`、四个岛各自 `setFixedHeight(40)`；
`page.py:723-727` `_hint` 回退写死 `(240,40)/(116,40)/(200,40)/(232,40)/(48, RAIL_CONTENT_HEIGHT)`
（232 与 `NAVIGATION_ISLAND_WIDTH=268` 已经对不上）。写本文时的在途工作区快照里 chrome
已改成 `from .floating_layout import RAIL_CONTENT_HEIGHT, RAIL_WIDTH` 且
`test_ultraview_chrome.py` 新增了 `rail.sizeHint().width() == RAIL_WIDTH` 一类断言——
方向正确；Task 0 在那批落地后核实还剩哪些字面量，本条只做收尾与钉死。

决定：
1. rail / 岛 / 弹层的尺寸常量**只在 `floating_layout.py` 定义**（它已是 Qt-free 的纯几何
   模块，被 `test_ultraview_floating_layout.py:48` 钉住）；`chrome.py` / `page.py` /
   `widgets.py` 一律 import，不再出现 40 / 48 / 56 / 196 / 233 / 268 / 240 / 116 / 200 这些
   与浮层几何相关的裸字面量（AST 测试：在这三个文件里，`setFixedHeight/Width/Size`、
   `QSize(...)`、`_hint(...)` 回退元组的实参不得是这几个整数字面量；白名单空）。
2. `page._hint` 回退元组由常量组装；`chrome.RAIL_MIN_HEIGHT` 删除，直接用
   `RAIL_CONTENT_HEIGHT`。
3. 纯函数层的防重叠已有覆盖（`test_ultraview_floating_layout.py::
   test_rail_never_overlaps_board_or_status_island_on_short_stages` 参数化到 160px 矮舞台）；
   缺的是 **widget 实际尺寸 ↔ 常量** 的契约——纯布局算对了、widget 自己另写一个数照样错位。
   在 `test_ultraview_chrome.py` 加一组：`ToolRail` / 四个岛 / `BoardPopover` 的
   `sizeHint()` 或固定尺寸与 `floating_layout` 常量一致；`page._hint` 回退值与真实 widget
   `sizeHint()` 一致（回退只该在 widget 未布局时用到，二者不一致就是漂移信号）。

### D3 · 收两处越界写 + 三处 owner 内直写

1. `page.py:1030` `self._board.viewport = {...}`：视图直接写模型，且这是视口能被存盘的
   唯一路径（coordinator 直接序列化 `_workspace`）。改为：page 的
   `_persist_viewport_to_board` 只算 payload 并 `viewport_changed.emit(board_id, payload)`
   （信号从 `pyqtSignal()` 改 `pyqtSignal(str, dict)`；现有连接 `_on_viewport_changed` 忽略参数
   继续重启 `_focus_timer`）；coordinator 新增 `_on_viewport_payload(board_id, payload)`：
   **按 `board_id` 查板**（`ultraview_state._board_index` 或同类查找），再调
   `ultraview_state.set_board_viewport(board, payload)`（新 mutator，复用
   `_legalize_viewport`，返回 warnings）。**必须带 `board_id`，不能用 `active_board()`**：
   切板路径是 coordinator 先 `set_active_board(new)` → `refresh_page` → `page.set_board(new)`
   → page 在换板前落**旧板**视口，此刻 coordinator 侧的活动板已经是新板，按活动板写就会把
   旧板视口写到新板上。**保持现有语义：视口变化不 `mark_workspace_mutated`、
   不走 `_after_board_mutation`**（视口是「digest 外」的呈现态，`84e38391` 立的规矩，
   高频且不该触发全量刷新）。U1 白名单随之 1 → 0。
   `set_board` 切板时那次 `_persist_viewport_to_board()` 是同步依赖——切走前必须先落旧板
   视口，再投影新板。信号是同步直连，顺序不变；Task 里加一条「切板后旧板 viewport 已落到
   旧板、新板 viewport 未被覆盖」的用例守住。
2. `ultraview_coordinator.py:1358` `page._select_ref(ref)` → page 提供公开 `select_ref(ref)`
   （`_select_ref` 保留为内部实现）。U6 白名单 1 → 0。
3. owner 内直写：`:1703 board.name = cleaned` → 改用既有 `rename_board`；
   `:1879/:1883 active_board(...).show_titles/show_sources = ` → 新 mutator
   `set_presentation_flags(board, *, show_titles=None, show_sources=None)`。这三处
   本来就在 owner 里，风险低，但让 U1 的「属性写」形式可以推广到 coordinator：
   `test_ultraview_structure.py` 增一条 U1b——`ultraview_state.py` 之外对
   `UltraViewBoardState` / `UltraViewWorkspaceState` 字段的属性赋值集合 == 白名单，
   目标 0。

### D4 · 视口手势路由集中（唯一需要真机验收的一条）

现状：`is_board_panning()` + `update_board_pan()` 这段转发在 `UltraViewCard`
（`widgets.py:2286`）、`BoardGrid`（`:2722`）、`FreeGridCard`（`:2910`）、`FreeGridBoard`
（`:3364`）、`BoardScrollArea`（`:3897`）五个类的 `mouseMoveEvent` 各抄一份；平移起手
`_handle_pan_press` / 释放 `_handle_pan_release` / 空格 `_handle_space_key` / 滚轮缩放
`_forward_zoom_wheel` / 捏合 `_forward_native_zoom` 同样是模块级 helper 被各类调用
（`widgets.py:203-247`）。原因是 Qt 的隐式抓取：按下发生在哪个 widget，后续 move 就
发给谁。任何新加到画布下的 widget 忘了抄，光标经过它平移就断——`423b0aef` /
`09262e15` 那类「手势被误取消」都是这个家族。

决定：
1. 新建 `ui/chart_stack/ultraview/viewport_router.py`：`ViewportGestureRouter(QObject)`，
   由 page 持有，在 page `showEvent` 时 `QApplication.instance().installEventFilter`、
   `hideEvent` / `WindowDeactivate` 时移除。只处理**目标 widget 是 `_canvas_host` 后代**
   的 `MouseButtonPress`（中键 / 空格按住的左键 → 起手平移）、`MouseMove`（平移中）、
   `MouseButtonRelease`（与起手按钮匹配才结束，沿用 `PanSession` 的按钮记忆）、
   `Wheel`（Ctrl/⌘ + 滚轮 → 缩放）、`NativeGesture`（捏合）、`KeyPress/Release`
   （空格；文本框有焦点时不吞，沿用 `09262e15` V8 的规矩）。命中即 `accept` 并返回
   `True`，其余一律放行。
2. 五个类的转发分支与四个模块级 helper 删除；`_page_of` 触达面从 11 缩到 4
   （`clear_card_selection` / `notify_canvas_click` / `handle_card_double_click` /
   `unplaced_tray`）。这四个是卡片语义，不在本批改信号。
3. 手势取消的两条腿（`WindowDeactivate` / `hideEvent` → `_cancel_board_gestures`，
   `page.py:2008-2027`）不变。
4. **验收必须真机**（CLAUDE.md Gotchas「验真机渲染」）：Cocoa 上光标依次经过卡片 /
   空白 / 滚动条 / rail / 岛 / 弹层区域的连续平移不断、中键与空格两种起手、Ctrl+滚轮
   与捏合缩放锚点不跳、弹层打开时平移不吞弹层点击。offscreen 只跑 QTest 事件序列。
   如果真机发现 app 级过滤器与 Qt 弹层/菜单冲突且 1 个工作日内收不住 → 回退为「只在
   `begin_board_pan` 时 `_canvas_host.grabMouse()`、结束时 `releaseMouse()`」的最小方案，
   同样能删掉五处 move 转发（press 起手仍留在 widget，helper 只剩 press 一个）。

### D5 · zoom 广播单点

`_viewport.set_zoom / _grid.set_zoom / _free_grid.set_zoom` 三件套在 `page.py:1049-1051 /
1123-1125 / 1199-1202 / 1330-1332` 抄了四遍。收成 `_broadcast_zoom(zoom)` 一处；
AST 测试：`page.py` 中 `_grid.set_zoom` / `_free_grid.set_zoom` 各只允许出现 1 次。

### D6 · 源画布探测静默退化补日志

coordinator 抓源画布靠六个硬编码私有属性名（`_iter_viewboxes` `:183-200`：`_plot` /
`_plot_amp` / `_plot_time` / `_plot_magnitude` / `_plot_phase` / `_plot_coherence`）与
`_iter_transient_overlay_items` `:224`（`host._cursor`、`_HOVER_CURSOR_LISTS`、
`vb.rbScaleBox`），124 个 `getattr` 兜底。别处改名 → 探测落空 → 抓图**静默**退化，无日志。

决定：探测落空（一个 host 上没找到任何 viewbox）时经 `diagnostics.throttled` 打一条
`logger.warning`（按 `(section, type(host).__name__)` 节流），并加一条特征化测试：
伪造一个把 `_plot` 改名的 host，断言 warning 发出且抓图路径返回 None 而不是抛异常。
不引入 Protocol/注册表——那是另一个尺度的改动，本批不做。

## 4. 显式不做

- **D7 · `UltraViewPage` 拆分**：它是唯一真想拆的类（视口/浮层控制 vs. Board 投影/拖放
  意图两簇）。**本批不拆。** 但 `2026-08-15-ultraview-annotation-notes-arrows-plan.md`
  0/35 全部落在 page/widgets 上——**如果那批要开做，先拆 page 再上**，届时另立 spec，
  以本批的 D0 护栏为前置（拆分是在护栏保护下做才安全）。
- **D8 · 新鲜度三处存储**（digest / `PreviewStore` / `page._previews·_statuses·_ref_exists`）
  的合并：P1/P2 review 已列为遗留，五轮修补都没动它。它牵涉 capture 管线语义，
  单独立项，不塞进本批。
- 不合并模块、不拆 coordinator、不把 signal 改直调、不清理测试里 253 处私有属性引用、
  不改任何视觉。
- 不动 `_alive()` / `_inactive()` 那 47 处——它们全部对着**外部**源画布，是这个组件的
  本职防御，不是内部生命周期问题。

## 5. 验收与护栏

- `tests/ui/test_ultraview_structure.py` 六条（U1 含 U1b、U2–U6）+ D2 几何字面量 lint +
  D5 单点 lint 全绿；白名单只许缩小，写进文件头注释。
- D1 spy 用例：切板 1 次投影；D2 矮舞台参数化；D3 切板落库顺序用例；D4 QTest 事件序列
  用例（五种起点 widget 的平移不断）+ 真机清单归档到 `docs/analyzer/verify/
  2026-08-15-ultraview-seam-hardening/`（截图 + 读数，照 `2026-08-15-ultraview-fit-zoom-probes/`
  的做法）；D6 特征化用例。
- `tests/ui/test_ultraview_*.py` 全绿（基线 850 passed，Task 0 重测）；主体全量与
  `tests/acquisition_ui` 分两条命令跑，失败集与 Task 0 基线一致（CLAUDE.md 的规矩）。
- 既有护栏不动：`test_main_window_state_ownership.py`（coordinator 仍在扫描目录内）、
  `test_no_lambda_signal_connections.py`、`test_ultraview_page.py::test_page_modules_do_not_import_main_window`、
  `test_ultraview_state.py` 的 Qt-free 断言、`test_ultraview_floating_layout.py:48`。
