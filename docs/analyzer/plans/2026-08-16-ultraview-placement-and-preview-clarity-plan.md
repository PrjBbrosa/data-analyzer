# UltraView：按意图落位与预览清晰度实施计划

**状态：** Implemented / focused offscreen verified（macOS foreground UNVERIFIED）
**日期：** 2026-08-16
**范围：** UltraView 自由网格的新增/拖入落位；卡片预览在正常使用缩放下的 Retina 清晰度；高缩放策略仅在新的前台证据表明确需要时另立实施批次。

## 0. 接缝加固后的重基（2026-08-16）

本计划原先假定 Page/Coordinator 之间只有旧的 ref 事件，且 PreviewStore 尚未有明确的 residency 优先级。该假定已不成立；实现必须以当前 `b3a1ab2c`（及其前序接缝加固提交）为基线：

| 已收口的边界 | 本计划的执行约束 |
|---|---|
| `UltraViewBoardState` 是模型写入口，coordinator 统一在 `_after_board_mutation()` 投影/持久化 | 新落位仅给现有 `add_ref()` / `place_free_grid_from_unplaced()` 增加运行时 anchor；不得写第二条 refresh 或 workspace-mutation 路径。 |
| Page 已有 `projection_batch()`，viewport 手势由 `ViewportGestureRouter` 集中路由 | 落位信号只从 `FreeGridBoard → Page → Coordinator` 单向流动；不得新增 widget 到 Page 的反向查找或绕过 router 的事件处理。 |
| `PreviewStore` 已按 Focus、可见活动卡、其他 Board、tray 的顺序管理 residency | 本批只修复 card 本地 pixmap 的 DPR 解释；不重写预算、tier 或全局 raw-edge 上限。 |
| `FreeGridBoard` 现有 replace arm 与 QDrag 生命周期保护 | 未 arm 的卡面 drop 必须转成普通插入；arm、Esc、drag leave 和 deferred rebuild 语义保持。 |

当前工作树的 `tests/ui/test_ultraview_capture.py` 有他人未提交修改。本批不编辑、不暂存或回退该文件；验证可运行它来检查兼容性，但新增覆盖写到其余相关测试文件。

## 1. 目标与结论

用户需要的是一个“画布”而不是从左上角开始填表格的体验：

1. 点击新增、从库中加入、从未放置区放置而**没有鼠标落点**时，卡片出现在**当前可见画布的中心附近**；连续新增从该中心向周边寻找最近空位。
2. 从 View 库拖到自由画布时，以**鼠标释放点**为最高优先级：卡片中心靠近该点，再吸附到最近的合法网格位置。
3. 拖到已有卡片上只有在明确出现“替换”反馈时才替换；否则仍是“在该位置附近插入”，不再静默吞掉 drop。
4. UltraView 卡片在 macOS Retina 正常缩放（例如 66%/100%）下不应因为自身的 DPR 处理而比原 View 明显软；不通过简单放大位图来伪造清晰度。
5. 仍保持 UltraView 的只读快照、零分析计算、整数网格持久化、单一模型写入口和受控预览内存预算。

这是一个联合批次，但有清楚的两级清晰度策略：

- **第一层（必须实施）：** 修复卡片显示缓冲的 DPR 失配。它不扩大 `PreviewStore` 的内存、也不重算图，预期直接改善普通使用时的软化。
- **第二层（以验收探针为门）：** 300% 或超大卡片仍受 `MAX_PREVIEW_RAW_EDGE=1600` 与 16MP 总预算限制。若第一层后正常缩放已达标，不为高倍率另起大规模离屏重渲染；若未达标，先记录证据并另立计划，不能在本批盲调 cap 或重复已有预算优先级。

## 2. 当前证据与问题定位

### 2.1 落位根因已确认

- `FreeGridBoard.dropEvent()` 读到 `event.pos()`，但空白画布分支只发出 `ref_dropped(section, view_id)`；位置没有跨出 widget 层。
- `UltraViewPage._on_free_grid_ref_dropped()` 和 coordinator 随后只有 ref，没有目标位置。
- `ultraview_state.add_ref()` / `place_free_grid_from_unplaced()` 统一调用 `_first_free_grid_rect()`；该 helper 固定从 `(0, 0)` 按行、列找第一块可用 4×3 矩形。

所以现象不是“网格吸附算错”，而是**drop 坐标被丢弃后回落到了左上优先的默认策略**。

### 2.2 清晰度的静态证据与未验证部分

- `PreviewStore` 把抓图转为 DPR=1 的原始像素 `QImage`，单图最长边封顶 1600；其现有 residency 已优先保护 Focus 和可见活动卡。本批不重写这套策略。
- `UltraViewCard.preview_display_size()` 已把图像内容区乘 card DPR，用于 residency 和抓图目标；但 `_fit_card_image()` 仍把 DPR=1 的 pixmap 缩放到**未乘 DPR 的逻辑** `contentsRect` 尺寸。Retina 上这会导致 QLabel 把同一缓冲再次铺满到更多物理像素，是普通缩放下软化的明确风险。
- 历史 fit/zoom 规格已记录：300% 下 6 列卡的物理展示需求可超过 1600px；当时 macOS 前台观感未验收。它是高缩放的第二层风险，但不能代替针对当前截图的前台实测。

结论：先用 DPR-aware 缓冲修复可证明的常规问题；随后用尺寸和前台截图判断是否真的需要触及抓图/预算策略。

## 3. 不变量与非目标

### 不变量

- `ui/ultraview_state.py` 继续是板状态、membership、布局持久化的唯一模型 owner；Page/Widget 不直接写 `UltraViewBoardState`，widget 到 coordinator 的请求必须经 Page signal 漏斗。
- 写入仍经 `UltraViewCoordinator._after_board_mutation()`；新流程不能创建第二条 `mark_workspace_mutated()` / refresh 路径。
- 持久化的是 `GridRect(column, row, column_span, row_span)`，绝不把窗口像素、滚动条值、DPR 或 Qt 对象写入项目。
- `PreviewStore` 仍只保存共享 `QImage`，不向 board/card 复制原始图；sidecar 格式、digest、状态语义和零计算边界不变。
- 原 View 的计算、缓存恢复、通道选择、View 设置均不因 UltraView 清晰度请求而改变。
- 常规移动/缩放、插入都不得隐式挤压、缩小或重排已有用户卡片；只有现有直接操控布局策略允许的显式 collision plan 才能移动卡片。

### 非目标

- 不把自由网格换成像素坐标或无边界无限画布。
- 不改变模板布局的 slot 填充/替换语义。
- 不做卡片内实时图表、重新计算、原始 View widget reparent 或新注释系统。
- 不把“更高 scale 的 `QPixmap.scaled()`”冒充为真实高分辨率渲染；若某 section 的 source grab 本身只是位图放大，计划必须明确记录，不能把它算作清晰度提升。
- 不触碰当前工作树中其他人在写的 `tests/ui/test_ultraview_capture.py` 改动；仅基于明确 HEAD 和本批拥有的文件实施。

## 4. 交互与质量合同

### 4.1 插入意图优先级

| 入口 | 首选锚点 | 冲突规则 | 结果 |
|---|---|---|---|
| 库 → 空白自由画布拖放 | 释放点 | 找离释放点最近的合法空位 | 新卡中心尽可能在鼠标下 |
| 未放置区 → 空白自由画布拖放 | 释放点 | 同上 | 从 tray 回到画布附近 |
| 新增按钮/库行“加入”/tray“放置” | 当前 scroll viewport 的可见中心 | 从中心向外找最近合法空位 | 连续卡围绕当前工作区展开 |
| 拖到已有卡片 | 已显示替换 arm 时是目标卡 | 未 arm 则按普通插入处理 | 替换必须可见、可预期 |
| 重复 ref | 不生成新 intent | 定位现有卡 | 保持现有去重语义 |

“当前可见中心”必须是 board scroll viewport 的中心映射到 `FreeGridBoard` 后的坐标，不能使用窗口中心、整张逻辑画布的固定中心，亦不能受左侧 rail 或悬浮 chrome 的局部坐标污染。

### 4.2 统一的网格插入解析

新增 Qt-free、未持久化的 `GridAnchor`（或等价的两个有限浮点/整数 cell 坐标）和一个**纯函数** resolver。它接收：现有 placements、默认 span、preferred center，并输出一个合法的 `GridRect | None`。

1. 将 preferred center 减去卡片半 span，得到候选左上格；使用已有合法化逻辑 clamp 到 12 列/48 行范围。
2. 若该 rect 空闲，直接选用。
3. 否则枚举所有同 span 的合法 rect，按“候选 rect 中心到锚点中心的平方距离”排序；距离相同用固定的顺时针/行列 tie-break，保证重放、测试和保存恢复确定。
4. 选第一个无 overlap 的 rect；不调用 `plan_layout()` 来挤走 blocker，不缩小邻居。
5. 无合法位置或已达 placed 上限时保留现有 tray/`grid_full` 语义。

默认 span 必须从 `board.free_grid_default_size` 解析，不能继续在一个新 helper 中另写 `(4, 3)`；当前 `standard` 仍得到 4×3。

`preferred_anchor=None` 是兼容调用：保持原有左上 first-fit，不把未知的旧调用悄悄改成“画布中心”。所有真实自由网格 UI 入口都必须显式传入 Page 计算出的可见中心或 drop 锚点。

### 4.3 高 DPI 预览合同

卡片显示缓冲的三个尺度必须分清：

| 名称 | 单位 | owner |
|---|---:|---|
| `contentsRect` | 逻辑 px | `UltraViewCard` / QSS padding |
| card display target | 物理 px（逻辑 px × card DPR） | `preview_display_size()` / residency |
| pixmap buffer | 原始物理 px，带正确 DPR metadata | `_fit_card_image()` |

`_fit_card_image()` 必须按物理 display target 生成缓冲，然后对产物调用 `setDevicePixelRatio(card_dpr)`。这样 Qt 的 device-independent size 回到**保持宽高比后的 logical fit size**（落在 `contentsRect` 内，而非强行等于整个 contentsRect），同时真实栅格仍拥有 Retina 所需的物理像素。缓存 key 必须包含 raw image key、物理目标宽高、有效 DPR 和 transform 质量；QSS padding 仍只通过 `contentsRect()` 处理。

## 5. 实施顺序

### Task 0 — 冻结基线、添加红测与前台质量记录

**Files:** 修改 `tests/ui/test_ultraview_state.py`、`tests/ui/test_ultraview_free_grid.py`、`tests/ui/test_ultraview_page.py`、`tests/ui/test_ultraview_viewport.py`；证据仅写入 `.state/ultraview-placement-preview-clarity-*/`。

1. 实施前先记录 `git status --short`、HEAD 和已拥有的改动范围；若 `ultraview_state.py`、`page.py`、`widgets.py`、`ultraview_coordinator.py` 正被另一批未提交代码修改，停止实施并在明确基线后重放此计划。
2. 前台可用时记录 source/card 的 logical size、DPR、抓图 raw px、`PreviewStore` raw px、card pixmap raw px/DPR；将 macOS 前台和 offscreen 证据分开保存。前台不可用不阻塞第一层修复，但最终状态必须标为前台未验收。
3. 先写红测：
   - 真实无坐标 UI 新增显式传入可见中心；兼容状态 API 的无 anchor 调用仍保持 `(0,0)` first-fit；
   - 非左上释放点的 drop 得到该点附近而非 `(0,0)`；
   - 中心碰撞时 resolver 选最近空位且原 placement 集不变；
   - DPR=2 的 card 缓冲 raw px 是 logical fit size 的 2 倍，pixmap 的 device-independent size 与该 fit size 相符；
   - 未 arm 卡面 drop 发出普通插入 intent，replace arm 仍是唯一替换分支。

**退出条件：** 红测先于实现，前台可用时有数值/截图样本；任何缺失前台结论明确标记为 UNVERIFIED。

### Task 1 — Qt-free 插入 resolver 与兼容状态 API

**Files:** 修改 `mf4_analyzer/ui/ultraview_state.py`；测试 `tests/ui/test_ultraview_state.py`、`tests/ui/test_ultraview_free_grid.py`。

1. 在状态层定义合法、有限的 `GridAnchor`/等价 request；它是运行时 intent，不进入 `board_to_payload()`。
2. 将当前 `_first_free_grid_rect()` 的“左上 first fit”拆为可复用的：默认 span 解析、anchor 规范化、最近空位搜索。保持旧 helper 作为没有 UI anchor 的兼容 wrapper，避免测试工具或外部调用突然变义。
3. 给 `add_ref()` 与 `place_free_grid_from_unplaced()` 增加 keyword-only `preferred_anchor=None`；自由网格时调用 resolver，模板模式保持原实现。
4. `None` 的兼容 fallback 保持既有 `(0,0)` first-fit；前台入口必须始终传当前可见中心，故 fallback 仅服务老调用、数据恢复边界和纯状态测试。
5. 覆盖：空板中心、已占中心向外、边界 clamp、默认 span、24 卡/tray、重复 ref、确定性 tie-break、没有 mover/neighbor 被改写。

**退出条件：** 新 resolver 对同一输入严格确定；`ultraview_state.py` 仍无 Qt/Canvas/MainWindow import。

### Task 2 — 自由画布坐标映射、拖放预览与 Page 意图

**Files:** 修改 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`、`mf4_analyzer/ui/chart_stack/ultraview/page.py`；测试 `tests/ui/test_ultraview_page.py`、`tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_free_grid.py`。

1. `FreeGridBoard.dropEvent()` 在空白/未 arm 卡片路径中保留 `event.pos()`；将它转换为 board-local `GridAnchor`，再通过一个新增且语义清楚的 signal 发送。旧的两参数 ref signal 仅在仍有测试/内部消费者时保留兼容转发，Page 的生产连接只消费携带 anchor 的 intent。
2. 默认 card span 由 Page 从 board state 注入 FreeGridBoard；drag 预览和最终 mutation 必须调用同一个 Qt-free resolver，不能两套“看起来一样”的碰撞规则。ghost 在空白和未 arm 卡面都显示 resolver 的结果；replace arm 生效时才切换为已有替换反馈。
3. Page 新增一个“free-grid insert request”向 coordinator 的单向 intent。它统一处理 library 新 ref、tray ref 和 drop ref；Page 仍只读 board，不写 state，也不从 widget 反向查询 Page。
4. 新增按钮/库行/托盘的无指针入口通过 `viewport.mapToGlobal()` → `FreeGridBoard.mapFromGlobal()` 取当前可见中心；拖入则使用释放点。滚动、zoom、fit parking origin 和 DPR 不得重复/遗漏转换。
5. drop 到非 arm 卡片不再 `accept` 后静默 return；重复 ref 仍 locate，已 arm 才 replace；`dragLeaveEvent()`、Esc 和 QDrag 完成后清除插入 ghost，不破坏现有 deferred rebuild 生命周期。

**退出条件：** 66%/100%/300%、滚动后的 drop 均落在正确逻辑网格；ghost 与最终 `GridRect` 完全相同；空白 press、marquee、Esc、拖拽生命周期及 QDrag source-lifetime lessons 不回退。

### Task 3 — Coordinator 写入口、项目持久化与反馈

**Files:** 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`；必要时补 `mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py`；测试 `tests/ui/test_ultraview_mode_integration.py`、`tests/ui/test_ultraview_project_session.py`、`tests/ui/test_ultraview_capture.py`。

1. Coordinator 连接唯一的 free-grid insert intent，根据 membership 调用带 `preferred_anchor` 的 `add_ref()` 或 `place_free_grid_from_unplaced()`；这两个分支都只在成功后调用一次 `_after_board_mutation()`。
2. 从 source tab 的“加入 UltraView”也取得 Page 当前可见中心，避免它绕过新策略。无 Page/非自由网格时走状态层兼容 fallback 或模板原逻辑。
3. exact placement 或 resolver 邻近落位均不增加无关 Toast；满板保留现有 tray/警告文案。
4. 项目保存、恢复、sidecar、导出继续只读取持久化 `GridRect`；新增后保存/重开必须保留 resolver 决定的位置。此任务不扩大既有 membership undo 范围。

**退出条件：** Page→Coordinator 单向信号没有新增 lambda；每次成功插入只刷新一次；持久化、重复 ref、tray 和 source-tab 流程通过集成测试。

### Task 4 — Retina 正确的卡片 pixmap 缩放（必做、低风险清晰度修复）

**Files:** 修改 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`；测试 `tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_page.py`。

1. 提取小型纯/近纯 helper，从逻辑 contents size 和有效 DPR 计算 physical buffer size；非法/删除的 widget 回退 DPR=1。
2. `_fit_card_image()` 将 source image 缩放到 physical target，保留 `Qt.SmoothTransformation`，随后为 scaled pixmap 设置同一 DPR。它的 device-independent size 必须等于保持宽高比后的 logical fit size，且完整落在 label `contentsRect()` 内（不是整个 QLabel，也不要求填满 contentsRect）。
3. scale cache key 改为 physical target + DPR；DPR、card resize、LOD 从隐藏恢复、raw image 更换和质量模式切换都必须失效，连续同输入仍复用同一 buffer。
4. 测试 DPR=1/2：断言 raw pixmap size、DPR、device-independent size、内容区 top row 不被 QSS padding 裁掉；并证明 title-only LOD 不做不可见缩放。
5. 在 macOS 前台用同一 source/card 同尺寸截图检查细线、网格线、文字和峰值标记；这是本 Task 的真实验收，不以 offscreen green 代替。

**退出条件：** 66%/100% 下 card 不再因自身 DPR 缓冲二次放大而软化，内存占用和 `PreviewStore` raw image 尺寸不因本 Task 上升。

### Task 5 — 高缩放的后续决策（本批不实施）

**Files:** 本批无产品代码修改；必要时仅在 `.state/` 保存后续决策证据。

**进入门：** Task 4 已通过前台验收，但 100% 正常卡或用户实际 300% 工作流仍因 store cap/budget 而低于目标；probe 明确显示是 1600 edge 或 16MP shrink，而不是 source 原图自身分辨率有限。

1. 仅当 macOS 前台证据显示 Task 4 后仍由 1600 edge、16MP shrink 或 source 抓图分辨率造成用户可见缺陷时，记录每个 section 的 `scale>1` 真实性、卡数/峰值像素和当前 residency tier。
2. 已有 priority 是 **Focus/当前可见卡 > 活动但不可见卡 > 非活动 Board > tray**；不在无证据情况下改动它，也不盲调 1600/16MP。
3. 若真需产品改动，另建 spec/plan，明确是 card 显示、store budget 还是 source renderer 受限；禁止本批临时 resize/reparent 原 View 或重算分析。

**退出条件：** 本批标记为“未进入门”；若未来进入门，须有独立证据和计划。

### Task 6 — 回归门禁、文案与前台验收

**Files:** 视实际交互文案修改 `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`、`mf4_analyzer/help/ultraview-guide.html`；测试相应 help/hints/quickref 测试及本计划所有 UltraView 测试。

1. 只有当帮助文字声称“拖到哪里放到哪里”或公开新增行为时，更新 hints、quickref 和 UltraView guide；不为内部画质策略添加无价值的用户开关或状态噪音。
2. 依序运行：

   ```bash
   TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
     tests/ui/test_ultraview_state.py \
     tests/ui/test_ultraview_free_grid.py \
     tests/ui/test_ultraview_page.py \
     tests/ui/test_ultraview_viewport.py \
     tests/ui/test_ultraview_mode_integration.py \
     tests/ui/test_ultraview_project_session.py -q
   ```

3. 运行相关边界门：`tests/test_signal_no_gui_import.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_main_window_state_ownership.py`，以及 `git diff --check`。`tests/ui/test_ultraview_capture.py` 可作为兼容检查运行，但因有他人未提交改动，不作为本批新增覆盖的编辑目标。
4. 在真实 macOS 前台验证：高 DPR card 清晰度、viewport 中心新增、拖放释放点、中心 collision、replacement arm、滚动/zoom/fit 后的落位、拖入 tray、24 卡预算、保存/重开。Windows frozen package 仍是独立发布门，不由 offscreen/macOS 替代。

## 6. 验收矩阵

| 编号 | 用户可见结果 | 自动化证据 | 前台证据 |
|---|---|---|---|
| P1 | 空板新增位于中心附近，不在左上 | resolver center test | 空 Board 点击新增 |
| P2 | 连续新增围绕中心扩展 | deterministic collision tests | 连续加入 4–6 View |
| P3 | 拖入空白处尊重释放点 | real `QDropEvent` + scroll/zoom mapping | 拖库卡到四个象限 |
| P4 | 非 arm 卡面不再吞 drop | Page signal integration | hover/释放对比 |
| P5 | 保存/重开不漂移 | project-session payload test | 手工保存、重开 |
| Q1 | DPR=2 card 缓冲有正确 raw px/DPR | pixmap target test | source/card 66%、100% 对照 |
| Q2 | QSS padding 不裁掉顶部图线 | existing contentsRect regression | 时域顶部 spine 目检 |
| Q3 | 300% 画质结论诚实可追溯 | probe dimensions + store stats | macOS 300% 截图 |
| Q4 | 清晰度不以无限内存换取 | 本批不改 Store budget；现有 capture 回归 | 后续进入门时再量测 |

## 7. 风险与回退

| 风险 | 处理 / 回退点 |
|---|---|
| 新 anchor 坐标重复经过 scroll/zoom 转换 | 坐标只在 Page/FreeGridBoard 边界转换一次；state 只收 grid anchor；用四象限 + 已滚动测试钉住。 |
| drop 与 replace 语义冲突 | 仅 armed state 可 replace；其余一律插入 preview，避免 silent accept。 |
| 纯 state resolver 与 ghost 不一致 | Widget 和 coordinator 都调用同一 Qt-free resolver；禁止复制邻近搜索。 |
| Retina 修复使 pixmap cache 增大 | 它只增加卡片本地显示缓冲，不增加 Store 原图；复用 key、LOD hidden 不缩放，并量测 widget cache。 |
| 高缩放提 cap 让 24 卡内存暴涨 | 本批不改 raw edge/16MP；后续必须先以前台证据和卡数峰值进入独立计划。 |
| 高 scale 是位图插值 | 识别后不当作质量修复；真离屏 renderer 属后续独立项目。 |
| 并行工作树正在改同一 UltraView 核心文件 | 实施前暂停/协调，基于明确 commit 重跑 Task 0；本计划本身不覆盖任何在途改动。 |

## 8. 完成定义

本计划完成不等于“离屏测试绿”。完成需要：落位和预览的 targeted tests 全绿、相关边界门通过、macOS 真实画布验证 P1–P5/Q1–Q3；若当前机器无法取得前台证据，则代码和离屏门可完成，但前台验收必须明确为 UNVERIFIED。高缩放真实渲染不在本批暗中降级或扩容。

## 9. 执行记录（2026-08-16）

- **已实施：** Task 0–4、Task 6。状态层新增不持久化的 `GridAnchor` 和最近空位 resolver；Page 将可见 scroll viewport 中心或 `FreeGridBoard` release point 作为单向 intent 交给 coordinator；未 arm 卡面 drop 显示插入 ghost 并插入；卡片本地 pixmap 以 physical target 缩放并写入 DPR metadata。
- **未进入门：** Task 5。当前 `PreviewStore` 的 Focus/可见卡 residency 已存在；本批没有改动 1600 edge、16MP budget 或 source renderer。
- **文案：** 已同步 `ui/hints.py`、`ui/quickref.py` 与 UltraView guide：自由网格中只有出现替换环才替换，其他卡面 drop 在释放点附近插入。
- **自动化：** `test_ultraview_state/free_grid/viewport/mode_integration/project_session` 为 **204 passed**；`test_ultraview_page` 为 **175 passed, 1 deselected**；现有外部修改的 `test_ultraview_capture.py` 为 **63 passed**；结构、导入、lambda、state-owner 与帮助门禁为 **46 passed**。
- **当前基线无关失败：** 即使重基到 `64dbab74` 后，`tests/ui/test_ultraview_page.py::test_library_sections_use_distinct_low_saturation_moonstone_materials` 仍得到 hue **174–213**，超出该测试的 `<=38`；本批未编辑 `ui_kit/style.qss` 或其 ratchet 测试，因此不把该色板问题纳入本计划。
- **前台：** 尝试读取运行中的 Python/TraceLab 无障碍树返回 Computer Use timeout `-10005`，未取得可用 Cocoa 画面。P1–P5/Q1–Q3 的 macOS 前台验收保持 **UNVERIFIED**。
