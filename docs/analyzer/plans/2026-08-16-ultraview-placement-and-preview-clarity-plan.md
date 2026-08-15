# UltraView：按意图落位与预览清晰度实施计划

**状态：** Proposed（仅计划，尚未修改产品代码）
**日期：** 2026-08-16
**范围：** UltraView 自由网格的新增/拖入落位；卡片预览在正常使用缩放下的 Retina 清晰度；如确有必要，再处理高缩放预览的受预算清晰度策略。

## 1. 目标与结论

用户需要的是一个“画布”而不是从左上角开始填表格的体验：

1. 点击新增、从库中加入、从未放置区放置而**没有鼠标落点**时，卡片出现在**当前可见画布的中心附近**；连续新增从该中心向周边寻找最近空位。
2. 从 View 库拖到自由画布时，以**鼠标释放点**为最高优先级：卡片中心靠近该点，再吸附到最近的合法网格位置。
3. 拖到已有卡片上只有在明确出现“替换”反馈时才替换；否则仍是“在该位置附近插入”，不再静默吞掉 drop。
4. UltraView 卡片在 macOS Retina 正常缩放（例如 66%/100%）下不应因为自身的 DPR 处理而比原 View 明显软；不通过简单放大位图来伪造清晰度。
5. 仍保持 UltraView 的只读快照、零分析计算、整数网格持久化、单一模型写入口和受控预览内存预算。

这是一个联合批次，但有清楚的两级清晰度策略：

- **第一层（必须实施）：** 修复卡片显示缓冲的 DPR 失配。它不扩大 `PreviewStore` 的内存、也不重算图，预期直接改善普通使用时的软化。
- **第二层（以验收探针为门）：** 300% 或超大卡片仍受 `MAX_PREVIEW_RAW_EDGE=1600` 与 16MP 总预算限制。若第一层后正常缩放已达标，不为高倍率另起大规模离屏重渲染；若未达标，执行本计划的预算优先级任务，而不是只把一个上限常量盲目调大。

## 2. 当前证据与问题定位

### 2.1 落位根因已确认

- `FreeGridBoard.dropEvent()` 读到 `event.pos()`，但空白画布分支只发出 `ref_dropped(section, view_id)`；位置没有跨出 widget 层。
- `UltraViewPage._on_free_grid_ref_dropped()` 和 coordinator 随后只有 ref，没有目标位置。
- `ultraview_state.add_ref()` / `place_free_grid_from_unplaced()` 统一调用 `_first_free_grid_rect()`；该 helper 固定从 `(0, 0)` 按行、列找第一块可用 4×3 矩形。

所以现象不是“网格吸附算错”，而是**drop 坐标被丢弃后回落到了左上优先的默认策略**。

### 2.2 清晰度的静态证据与未验证部分

- `PreviewStore` 把抓图转为 DPR=1 的原始像素 `QImage`，单图最长边封顶 1600，所有受保护预览合计超过 16MP 时会同比缩小。
- `UltraViewCard.preview_display_size()` 已把图像内容区乘 card DPR，用于 residency 和抓图目标；但 `_fit_card_image()` 仍把 DPR=1 的 pixmap 缩放到**未乘 DPR 的逻辑** `contentsRect` 尺寸。Retina 上这会导致 QLabel 把同一缓冲再次铺满到更多物理像素，是普通缩放下软化的明确风险。
- 历史 fit/zoom 规格已记录：300% 下 6 列卡的物理展示需求可超过 1600px；当时 macOS 前台观感未验收。它是高缩放的第二层风险，但不能代替针对当前截图的前台实测。

结论：先用 DPR-aware 缓冲修复可证明的常规问题；随后用尺寸和前台截图判断是否真的需要触及抓图/预算策略。

## 3. 不变量与非目标

### 不变量

- `ui/ultraview_state.py` 继续是板状态、membership、布局持久化的唯一模型 owner；Page/Widget 不直接写 `UltraViewBoardState`。
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
- 不触碰当前工作树中其他人在写的 UltraView/文档/测试改动；实施前必须在干净且明确的提交基线重新锚定行号和测试。

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

### 4.3 高 DPI 预览合同

卡片显示缓冲的三个尺度必须分清：

| 名称 | 单位 | owner |
|---|---:|---|
| `contentsRect` | 逻辑 px | `UltraViewCard` / QSS padding |
| card display target | 物理 px（逻辑 px × card DPR） | `preview_display_size()` / residency |
| pixmap buffer | 原始物理 px，带正确 DPR metadata | `_fit_card_image()` |

`_fit_card_image()` 必须按物理 display target 生成缓冲，然后对产物调用 `setDevicePixelRatio(card_dpr)`。这样 Qt 的 device-independent size 恰好回到 label 的逻辑 contentsRect，同时真实栅格仍拥有 Retina 所需的物理像素。缓存 key 必须包含 raw image key、物理目标宽高、有效 DPR 和 transform 质量；QSS padding 仍只通过 `contentsRect()` 处理。

## 5. 实施顺序

### Task 0 — 冻结基线、添加红测与前台质量探针

**Files:** 新增 `scripts/probe_ultraview_preview_quality.py`；修改 `tests/ui/test_ultraview_state.py`、`tests/ui/test_ultraview_page.py`、`tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_capture.py`；证据仅写入 `.state/ultraview-placement-preview-clarity-*/`。

1. 实施前先记录 `git status --short`、HEAD 和已拥有的改动范围；若 `ultraview_state.py`、`page.py`、`widgets.py`、`ultraview_coordinator.py` 正被另一批未提交代码修改，停止实施并在明确基线后重放此计划。
2. 建一个不修改源 View 的 probe：记录 source widget 的 logical size/DPR、抓取 `QPixmap` raw px、`PreviewStore` raw px、card `contentsRect` logical px、card pixmap raw px/DPR、residency tier/target、store total pixels/evictions。
3. 用已加载的 Time、FFT、时频各一张真实 View，在 66% / 100% / 300% 下记录上述数据和 source/card 截图；将 macOS 前台结果与 offscreen 结果分开存放和报告。
4. 先写红测：
   - 空白 board 的无坐标新增不再得到 `(0,0)`；
   - 非左上释放点的 drop 得到该点附近而非 `(0,0)`；
   - 中心碰撞时 resolver 选最近空位且原 placement 集不变；
   - DPR=2 的 card 缓冲 raw px 是逻辑内容区的 2 倍，pixmap 的 device-independent size 仍等于 contentsRect；
   - 一次尺寸/缩放更新只经 debounce 触发一次 capture，不重复 idle capture。

**退出条件：** 计划的数值前/后基线、红测和真实前台样本齐备。对“清晰度”的任何因果结论都标记为 probe 结论，而不是由截图主观推断。

### Task 1 — Qt-free 插入 resolver 与兼容状态 API

**Files:** 修改 `mf4_analyzer/ui/ultraview_state.py`；测试 `tests/ui/test_ultraview_state.py`、`tests/ui/test_ultraview_free_grid.py`。

1. 在状态层定义合法、有限的 `GridAnchor`/等价 request；它是运行时 intent，不进入 `board_to_payload()`。
2. 将当前 `_first_free_grid_rect()` 的“左上 first fit”拆为可复用的：默认 span 解析、anchor 规范化、最近空位搜索。保持旧 helper 作为没有 UI anchor 的兼容 wrapper，避免测试工具或外部调用突然变义。
3. 给 `add_ref()` 与 `place_free_grid_from_unplaced()` 增加 keyword-only `preferred_anchor=None`；自由网格时调用 resolver，模板模式保持原实现。
4. `None` 的兼容 fallback 使用固定启动中心而不是 `(0,0)`；前台入口必须始终传当前可见中心，故 fallback 仅服务老调用、数据恢复边界和纯状态测试。
5. 覆盖：空板中心、已占中心向外、边界 clamp、默认 span、24 卡/tray、重复 ref、确定性 tie-break、没有 mover/neighbor 被改写。

**退出条件：** 新 resolver 对同一输入严格确定；`ultraview_state.py` 仍无 Qt/Canvas/MainWindow import。

### Task 2 — 自由画布坐标映射、拖放预览与 Page 意图

**Files:** 修改 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`、`mf4_analyzer/ui/chart_stack/ultraview/page.py`；测试 `tests/ui/test_ultraview_page.py`、`tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_free_grid.py`。

1. `FreeGridBoard.dropEvent()` 在空白/未 arm 卡片路径中保留 `event.pos()`；将它转换为 board-local `GridAnchor`，再通过一个新增且语义清楚的 signal 发送。保留旧两参数 signal 直到所有本仓消费者迁移，随后只删无调用的兼容支路。
2. 默认 card span 由 Page 从 board state 注入 FreeGridBoard；drag 预览和最终 mutation 必须调用同一个 Qt-free resolver，不能两套“看起来一样”的碰撞规则。
3. `dragMoveEvent()` 在空白处显示插入 ghost（至少 outline + target rect）；hover 到 card 但未进入现有 replacement arm 时也显示普通插入预览。进入 replacement arm 时保留现有明确替换反馈。
4. Page 新增一个“free-grid insert request”向 coordinator 的单向 intent。它统一处理 library 新 ref、tray ref 和 drop ref；Page 仍只读 board，不写 state。
5. 新增按钮/库行/托盘的无指针入口通过 `viewport.mapToGlobal()` → `FreeGridBoard.mapFromGlobal()` 取当前可见中心；拖入则使用释放点。滚动、zoom、fit parking origin 和 DPR 不得重复/遗漏转换。
6. drop 到非 arm 卡片不再 `accept` 后静默 return；重复 ref 仍 locate，已 arm 才 replace。

**退出条件：** 66%/100%/300%、滚动后的 drop 均落在正确逻辑网格；ghost 与最终 `GridRect` 完全相同；空白 press、marquee、Esc、拖拽生命周期及 QDrag source-lifetime lessons 不回退。

### Task 3 — Coordinator 写入口、项目持久化与反馈

**Files:** 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`；必要时补 `mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py`；测试 `tests/ui/test_ultraview_mode_integration.py`、`tests/ui/test_ultraview_project_session.py`、`tests/ui/test_ultraview_capture.py`。

1. Coordinator 连接唯一的 free-grid insert intent，根据 membership 调用带 `preferred_anchor` 的 `add_ref()` 或 `place_free_grid_from_unplaced()`；这两个分支都只在成功后调用一次 `_after_board_mutation()`。
2. 从 source tab 的“加入 UltraView”也取得 Page 当前可见中心，避免它绕过新策略。无 Page/非自由网格时走状态层兼容 fallback 或模板原逻辑。
3. exact placement 时不打扰用户；resolver 因碰撞移动到附近时给出短 Toast，例如“已放在附近空位”；满板保留现有 tray/警告文案。
4. 项目保存、恢复、sidecar、导出继续只读取持久化 `GridRect`；新增后保存/重开必须保留 resolver 决定的位置。此任务不扩大既有 membership undo 范围；若当前 add/remove 已不进入 per-board grid undo，则记录为独立产品决策，不混入拖放定位修复。

**退出条件：** Page→Coordinator 单向信号没有新增 lambda；每次成功插入只刷新一次；持久化、重复 ref、tray 和 source-tab 流程通过集成测试。

### Task 4 — Retina 正确的卡片 pixmap 缩放（必做、低风险清晰度修复）

**Files:** 修改 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`；测试 `tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_page.py`。

1. 提取小型纯/近纯 helper，从逻辑 contents size 和有效 DPR 计算 physical buffer size；非法/删除的 widget 回退 DPR=1。
2. `_fit_card_image()` 将 source image 缩放到 physical target，保留 `Qt.SmoothTransformation`，随后为 scaled pixmap 设置同一 DPR。它的 device-independent size 必须等于 label contentsRect，而不是整个 QLabel。
3. scale cache key 改为 physical target + DPR；DPR、card resize、LOD 从隐藏恢复、raw image 更换和质量模式切换都必须失效，连续同输入仍复用同一 buffer。
4. 测试 DPR=1/2：断言 raw pixmap size、DPR、device-independent size、内容区 top row 不被 QSS padding 裁掉；并证明 title-only LOD 不做不可见缩放。
5. 在 macOS 前台用同一 source/card 同尺寸截图检查细线、网格线、文字和峰值标记；这是本 Task 的真实验收，不以 offscreen green 代替。

**退出条件：** 66%/100% 下 card 不再因自身 DPR 缓冲二次放大而软化，内存占用和 `PreviewStore` raw image 尺寸不因本 Task 上升。

### Task 5 — 仅在基线证明需要时：高缩放抓图与预算优先级

**Files:** 可能修改 `mf4_analyzer/ui/chart_stack/ultraview/preview_store.py`、`mf4_analyzer/ui/main_window/ultraview_coordinator.py`、`mf4_analyzer/ui/chart_stack/ultraview/viewport.py`；测试 `tests/ui/test_ultraview_capture.py`、`tests/ui/test_ultraview_viewport.py`、`tests/ui/test_ultraview_mode_integration.py`。

**进入门：** Task 4 已通过前台验收，但 100% 正常卡或用户实际 300% 工作流仍因 store cap/budget 而低于目标；probe 明确显示是 1600 edge 或 16MP shrink，而不是 source 原图自身分辨率有限。

1. 先为每个 section 记录 grab `scale>1` 的真实性：若实现只是 `base.scaled(...)`，它只能改善平滑，不能算真实清晰度来源；不得据此提高 memory cap。
2. 维持 16MP 全局预算作为默认安全线；只允许在实测分配表支持时把单图 raw edge 从 1600 提到一个明确、测试化的焦点上限（候选 2048），并记录 1/4/12/24 张卡峰值内存。
3. 分配优先级必须是 **Focus/当前可见卡 > 活动但不可见卡 > 非活动 Board > tray**。预算不足时先降不在屏幕内的卡或其未来 recapture 需求，不能按当前实现把所有 resident 图片同比缩小并连焦点卡一起变软。
4. 保持 `target_size` 为物理像素；focus recapture 的 debounce/idle coalescing、digest retry、source 可见性和 `MAX_PREVIEW_RAW_EDGE` 到顶后的停止条件全部保留，避免无限 recapture。
5. 如果各 section 没有真实高分辨率抓图路径，停在“DPR 修复 + 预算优先级”并把真离屏重渲染列为后续独立架构项目；不在本批临时 resize/reparent 原 View，不重算分析。

**退出条件：** 目标工作流中 FOCUS/可见卡优先清晰；总 raw pixels 不越过预算；无 capture storm、无 source recompute、无 sidecar 格式改变。若进入门不成立，此 Task 标记“未需要”，并保留诊断证据。

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
     tests/ui/test_ultraview_capture.py \
     tests/ui/test_ultraview_mode_integration.py \
     tests/ui/test_ultraview_project_session.py -q
   ```

3. 运行相关边界门：`tests/ui/test_import_boundaries.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/test_packaging_imports.py`，以及 `git diff --check`。
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
| Q4 | 清晰度不以无限内存换取 | 1/4/12/24 卡预算 tests | Activity Monitor/诊断数据 |

## 7. 风险与回退

| 风险 | 处理 / 回退点 |
|---|---|
| 新 anchor 坐标重复经过 scroll/zoom 转换 | 坐标只在 Page/FreeGridBoard 边界转换一次；state 只收 grid anchor；用四象限 + 已滚动测试钉住。 |
| drop 与 replace 语义冲突 | 仅 armed state 可 replace；其余一律插入 preview，避免 silent accept。 |
| 纯 state resolver 与 ghost 不一致 | Widget 和 coordinator 都调用同一 Qt-free resolver；禁止复制邻近搜索。 |
| Retina 修复使 pixmap cache 增大 | 它只增加卡片本地显示缓冲，不增加 Store 原图；复用 key、LOD hidden 不缩放，并量测 widget cache。 |
| 调大 raw edge 让 24 卡内存暴涨 | Task 5 默认保持 16MP，先给 visible/focus 分配；没有测量通过不改 cap。 |
| 高 scale 是位图插值 | 识别后不当作质量修复；真离屏 renderer 属后续独立项目。 |
| 并行工作树正在改同一 UltraView 核心文件 | 实施前暂停/协调，基于明确 commit 重跑 Task 0；本计划本身不覆盖任何在途改动。 |

## 8. 完成定义

本计划完成不等于“离屏测试绿”。完成需要同时满足：落位和预览的 targeted tests 全绿、边界门通过、macOS 真实画布验证了 P1–P5/Q1–Q3、质量 probe 解释了当前像素链路，且任何未实施的高缩放真实渲染工作都被明确标为后续而非暗中降级。
