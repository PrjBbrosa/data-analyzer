# UltraView 细分布局晶格、等比预览收口与透明磨砂卡片 — 实施计划

**状态：** Implemented — 代码已落地；前台 macOS / Windows frozen 验收仍待单独执行
**日期：** 2026-08-19
**范围：** 自由网格（Free Grid）中的卡片比例匹配、历史项目迁移、卡片材质与导出一致性。
**原型：** `docs/analyzer/ui-prototypes/2026-08-19-ultraview-frosted-dense-grid-prototype.html`（只验证材质方向，不证明 Qt 实现或比例收口）

## 1. 用户问题与根因

用户标出的不是 UltraView 画布背景的粗线，而是 **View 卡片内部的等比留白**：预览截图完整显示时，图像槽与截图宽高比不一致，于是在顶部/底部或左/右产生大片白带。

当前实现链路已经证实这一点：

1. `UltraViewCard._fit_card_image()` 调用 `preview_reading_box()`，以 `KeepAspectRatio` 完整包含截图；它不会裁掉截图，也不会拉伸。
2. `preview_reading_box()` 优先保留真实抓图比例；这是正确的阅读合同，不能为了填满卡片而扭曲数据图。
3. “按原图比例”按钮经 coordinator 调用 `fit_rect_for_aspect()`；后者只在当前整数 `GridRect` 的粗粒度行列跨度中搜索，并且短边最多再长 2 格。
4. 当前受控网格是 12 列、48 基准行，屏幕指标有固定 `GRID_ROW_HEIGHT=88` 与 `SLOT_GUTTER=12`。当预览图比例介于两个可用 span 比例之间时，算法只能选择最近项，因而留下图中红框的等比留白。

**结论：** 仅把 CanvasHost 背景的 22 px 点阵 / 110 px 粗线加密，不能改变卡片比例，也不能消除红框留白。需要细化持久化的布局晶格，并保持预览 `KeepAspectRatio` 不变。

## 2. 目标、决策与非目标

### 2.1 目标

| 编号 | 用户可见结果 |
|---|---|
| G1 | 点击“按原图比例”后，典型时域双图预览的上下/左右 unused area 显著低于当前 12 列晶格；不裁图、不拉伸。 |
| G2 | 新加入且已有预览的卡片初始 span 更贴近抓图比例；无预览卡保持标准语义。 |
| G3 | 旧 `.tlproj` 的自由网格打开后，卡片顺序、相对位置、占用关系与外部可见几何不跳变；重存后写入新 schema。 |
| G4 | 卡片空白区从纯白改为低不透明度磨砂材质，仍保持标题、图例、操作按钮与图表的对比度。 |
| G5 | 屏幕、复制整板图、导出 PNG 的材质语义一致；导出是确定性的平面合成，不依赖桌面/窗口背景。 |

### 2.2 拟定设计决策

1. 将自由网格升级为 **2×细分晶格**：12 列 / 48 基准行语义变为 24 列 / 96 基准行；历史 `GridRect(column, row, column_span, row_span)` 的四个值按 2 倍迁移。这样现有卡的物理位置保持稳定，而每次移动和调整尺寸可以落在原来一半的步长上。
2. 不能直接把 `GRID_COLUMNS` 改成 16 或简单把最小 cell 尺寸减半。那会改变全板物理宽度、卡间隙和已保存卡片的可见位置。实现必须由纯几何映射定义微网格 edge/pitch，使“历史 span ×2”在 1× 下的外框与旧版保持在 **±1 logical px** 内。
3. `fit_rect_for_aspect()` 保留“完整 contain、优先横向边余量而非底部白带”的阅读策略，但在微网格候选中比较 **实际图像槽像素** 与实际 letterbox 面积；`FIT_SHORT_SIDE_GROW_MAX` 改为以等价物理距离推导，不能因为单位减半而无意允许卡片扩张两倍。
4. “磨砂”定义为 **半透明、带浅色 wash 与细亮边的卡片壳**，不是在每张卡上增加 `QGraphicsBlurEffect`。Qt QSS 没有网页 `backdrop-filter` 的等价实现，而且对子卡做 blur 既昂贵也不能正确模糊其兄弟背景。画布已经由 CanvasHost 统一绘制，半透明壳会自然透出其钛蓝琥珀材质。
5. 捕获的图表 `QImage` 继续保持原始不透明像素、完整比例和清晰度。磨砂覆盖的是外壳、红框中的未使用区域、header/footer/action bar；**不**对数据图的白底做阈值抠图或 alpha 化，以免抹掉网格、轴线和浅色曲线。

### 2.3 不做的事

- 不把自由网格改为任意像素坐标、无限制布局或 Canvas 内排序。
- 不通过裁掉预览边缘、非等比缩放或重新计算源 View 来“填满”卡片。
- 不改变模板布局的 slot 合同；本计划只作用于 `layout_mode == free_grid`。
- 不改变 PreviewStore 的抓取、residency、像素预算、DPR 或分析计算；这些与本次“比例留白”不是同一根因。
- 不新增一个用户可配置的“透明度/网格密度”持久化偏好。先以单一经过验证的产品默认值交付，避免不同 Board 出现不可重放的几何/材质差异。

## 3. 不变量

- `mf4_analyzer/ui/ultraview_state.py` 仍是 Board、`GridRect`、持久化与 layout-state 的唯一 owner；不可引入 Qt、MainWindow 或 canvas import。
- `FreeGridBoard → UltraViewPage → UltraViewCoordinator` 的单向 intent 与 `_after_board_mutation()` 的单一持久化/刷新路径不变。
- `GridRect` 始终保存逻辑整数，不写像素、缩放、滚动位置、DPR 或 widget 对象。
- 现有 move / resize / group move / collision / overlap avoidance / organize / auto-arrange / undo / redo 必须在同一套微网格坐标上运行，不能只给 auto-fit 单独做一套像素算法。
- `PreviewStore` 仍共享每个 `UltraViewRef` 的 QImage；同一预览进入多个 Board 不复制原图。
- 历史未知未来 schema 在用户未修改 workspace 时维持 opaque payload 保护；迁移只处理已知 schema 1–4。

## 4. 实施波次

### Wave 0 — 冻结红框样本与行为基线

**所有权文件：** 仅新增/修改测试与 `.state/ultraview-fine-grid-*` 证据；不改产品实现。

1. 以用户截图对应的 View 1（双时域 subplot）和一个宽屏/竖屏预览为样本，记录：原始 QImage `(w, h)`、卡片 `GridRect`、卡片外框 px、`QLabel.contentsRect()`、`preview_reading_box()` 结果、unused width/height 与 unused area。
2. 增加可重复的纯几何测试：对固定图像比例，当前 12×48 版本的最佳可行 span 作为基线；新晶格必须严格降低 unused area，且不得选择裁图/拉伸结果。
3. 为典型旧 layout 建立 “迁移前/后 `rect_to_pixels()` 外框” 的 golden mapping 测试。测试比较边、宽、高，不把抽象坐标相等误当成用户可见稳定。
4. 记录 HEAD、`git status --short`；如果 `ultraview_state.py`、`free_grid.py`、`widgets.py`、`page.py`、`ultraview_coordinator.py` 或 `style.qss` 正被其他工作修改，先协调基线，不能覆盖对方脏改。

**退出条件：** 红框现象有可量化的基线；测试先失败，能区分“背景点阵更密”与“实际 preview unused area 变小”。

### Wave 1 — Qt-free 微网格模型与 schema 迁移

**所有权文件：**

- `mf4_analyzer/ui/ultraview_state.py`
- `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- `mf4_analyzer/ui/chart_stack/ultraview/layouts.py`（仅常量/几何 contract 若确有需要）
- `tests/ui/test_ultraview_state.py`
- `tests/ui/test_ultraview_free_grid.py`
- `tests/ui/test_ultraview_project_session.py`

1. 引入命名明确的网格 resolution / version 常量；将基准列、行、安全边界、min/max span、默认 preset 与模板转自由网格映射统一提升为微格单位。`MAX_PLACED_CARDS`、membership 上限和 Board 上限不变。
2. 为 `GridMetrics`/`rect_to_pixels()` 设计精确 edge-pitch 映射：历史 card 的 origin、right/bottom edge、外框宽高在迁移为 `×2` 后保持 ±1 px。不得用 `24 * GRID_MIN_COLUMN_WIDTH` 推宽画布后让整块 Board 变宽。
3. 把旧值依赖（例如 12 列 packing、safe bounds、min visible rows、minimap、export crop、gesture pixel-to-cell delta）全部改为 resolution-aware 的纯 helper。特别检查：`screen_grid_metrics()`、`export_grid_metrics()`、`scale_grid_metrics()`、`rect_to_pixels()`、`pixels_to_grid_delta()`、`legal_grid_rect()`、`organized_placements()` 与 auto-arrange / avoidance planner。
4. 将 `ULTRAVIEW_SCHEMA` 从 4 升至 5；`free_grid` payload 明确写新列数/网格版本。读取 schema 1–4 的自由网格时：
   - 将 `column`、`row`、`column_span`、`row_span` 全部乘 2；
   - `free_grid_default_size` 仍保存 preset 名称，其值表在运行时变成微格 span；
   - 再执行合法化/重叠检查；迁移不能把合法旧卡无声丢入 tray；
   - 新 schema 输出只使用 24 列数据；未知未来 schema 继续走既有 opaque/fallback 合同。
5. `BoardPlacementSnapshot`、undo/redo、复制 Board、template ↔ free-grid 转换以及当前 Board 的 runtime transition 都只持有已迁移的统一单位，绝不在各调用方按需 `×2`。

**新增/更新红绿测试：**

- schema 4 自由网格 → schema 5：ref 顺序、tray、非重叠、相对布局与像素外框稳定；重存后只含 schema 5/24 columns；
- 2×单位下的 base frame、安全边界、移动、resize、group move、collision、overlap avoidance、自动排版、organize 与 24 卡板均可重复；
- template 转 free-grid 后的槽位外框与旧模板视觉映射一致；
- screen/export 同用一份 grid metrics，导出不被窗口大小影响。

**退出条件：** 模型无 Qt import；旧项目无迁移警告风暴、无 orphan/tray 回退，且所有已保存布局视觉稳定。

### Wave 2 — 更细的等比求解与所有入口统一

**所有权文件：**

- `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 必要时 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `tests/ui/test_ultraview_free_grid.py`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_mode_integration.py`

1. 将 `fit_rect_for_aspect()` 的 cost 明确为 `preview_reading_box` 后的 **actual unused pixel area / longest unused axis**；保留既有的“侧边余量优先于上下白带”判定，但让它在微网格候选中取最优，而不是重写为 raw card ratio 猜测。
2. 搜索范围仍受 card 当前可用空间、`GRID_MAX_*` 与 safety bounds 限制；短边增长上限用当前物理预算折算为微格，不允许单位升级导致卡片无端扩大或撞开远处邻居。
3. `_on_free_grid_autofit()` 继续通过 `plan_layout(..., LAYOUT_RESIZE)` 和 `set_free_grid_rects()` 一次事务提交。无可用空间时明确 toast，不能静默裁图或改为覆盖邻居。
4. `_fitted_insert_span()`、拖入后的 deferred fit、工具栏 “按原图比例”、card action 与右键入口共用同一纯 helper。具有预览时用其真实 QImage 比例；无预览时使用现有 standard preset，不做猜测。
5. 在 card 上显示 “按原图比例” 后，只收敛**该卡**的 outer rect；Board `适应内容` 仍只改变 viewport camera。两者不合并、不改名。

**验收样本：**

| 样本 | 期望 |
|---|---|
| 用户图中的双时域 View | 点击 fit 后上下白带下降到 Wave 0 基线的目标阈值以下；完整两张图、轴和时间标签可见。 |
| 宽屏截图 | 若仍有余量，优先留左右边余量，不制造更显眼的上下带。 |
| 竖屏/FRF 预览 | 自动增加正确短边，不越过 safety 或破坏其他卡。 |
| 无预览、missing、orphaned | 不执行假 fit，不更改 GridRect。 |
| 撞卡与满板 | 事务拒绝或走既有 displacement policy；无静默缩小、无丢失。 |

**退出条件：** 典型样本的 unused-area regression 通过；红框留白从“粗粒度不可调”变为小到不主导视觉，且没有画面裁切或数据变形。

### Wave 3 — 透明磨砂壳与导出材质一致性

**所有权文件：**

- `mf4_analyzer/ui_kit/style.qss`
- 必要时 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `mf4_analyzer/ui/chart_stack/ultraview/compositor.py`
- `mf4_analyzer/ui_kit/ultraview_style.py`（仅新增已命名的 Titanium token 时）
- `tests/ui/test_ultraview_chrome.py`
- `tests/ui/test_ultraview_free_grid.py`
- `tests/test_verify_ultraview_visuals.py`

1. 将 `QWidget#ultraViewCard` 的最终覆盖规则集中为一处：使用例如 `rgba(255, 255, 254, α)` 的半透明 surface、低对比 1 px 亮边和精细 radius；保留 card 无 per-card shadow 的性能原则。不要把透明规则扩散到普通分析 View。
2. 同步 header/footer/action bar：header/footer 已是 transparent child，action bar 现有的实心 `#fcfdfe` 改为同材质的浅透明表面；hover/selected/replacement/drop/orphaned 状态只能改变边框、wash 或图标颜色，不能恢复一块不透明白底。
3. 保持 `UltraViewCard` 的 `WA_StyledBackground` 与现有透明 Board/ScrollArea 路径。若某平台上子 widget backing 仍变白，仅增加最小的 card-local paint/QSS host 修复；不对 CanvasHost、主窗口或全局 app 设置 `WA_TranslucentBackground`。
4. 不使用 `QGraphicsBlurEffect` 或 widget 截屏来模拟玻璃：前者会把 24 卡渲染成本推高，后者会使手势、DPR 和滚动背景失真。所需磨砂感由 CanvasHost 的 Titanium 背景、半透明 shell 和轻度 inner wash 组成。
5. 更新 compositor：导出 PNG 先绘制确定性的 Titanium paper/canvas base，再以相同 alpha/边框规则合成 card shell；由于 PNG 不能看到桌面背后内容，导出不应生成透明洞或依赖真实窗口 backdrop。预览 QImage 保持原始像素。
6. 用真实截图检查卡片空白区：能读出淡点阵/材质，但曲线、刻度、chip、操作条和 footer 仍满足对比度；不同 section 色点不能被玻璃层冲淡到难以识别。

**退出条件：** 透明感只作用于 UltraView 卡片壳；无矩形背板、圆角漏白、hover radius reset、可读性降低或 24-card 渲染回退。

### Wave 4 — 用户文案、验证与前台验收

**所有权文件：**

- 若用户操作可见改变，修改 `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py` 与 UltraView help；否则不制造新文案。
- `.state/ultraview-fine-grid-*` 仅保存本地测量、截图与迁移验证证据。

1. 先跑 changed-owner tests，再跑边界门：

   ```bash
   TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
     tests/ui/test_ultraview_state.py \
     tests/ui/test_ultraview_free_grid.py \
     tests/ui/test_ultraview_page.py \
     tests/ui/test_ultraview_mode_integration.py \
     tests/ui/test_ultraview_project_session.py \
     tests/ui/test_ultraview_chrome.py \
     tests/test_verify_ultraview_visuals.py -q
   ```

2. 再运行适用边界门：

   ```bash
   TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
     tests/ui/test_import_boundaries.py \
     tests/test_signal_no_gui_import.py \
     tests/ui/test_no_lambda_signal_connections.py \
     tests/ui/test_main_window_state_ownership.py -q
   git diff --check
   ```

3. 真实 macOS 前台必须验证，不以 offscreen green 代替：
   - 打开已有 12 列 schema 4 `.tlproj`，确认自动迁移后四张卡不跳位；保存、关闭、重开确认 schema 5 稳定；
   - 对用户图中的 View 1 点击“按原图比例”，截图并比对 Wave 0 的上下白带；
   - 观察拖动、八向 resize、group move、自动排版、撤销/重做、缩放、适应内容、minimap、导出和复制图；
   - 观察 66%/100%/300%、单卡与 24 卡时的空白区、操作条与卡片性能；
   - 观察透明磨砂在实际 Cocoa 合成下是否出现白色 backing、四角漏底或文字对比不足。
4. Windows frozen Full/Lite 仍是独立发布门；本计划的 macOS / offscreen 结果不可替代它。

## 5. 风险与回退

| 风险 | 防护与回退 |
|---|---|
| 微网格迁移让旧 Board 视觉跳位 | 先有 pixel mapping golden test；任何超出 ±1 px 的旧卡外框偏差都阻塞迁移实现。 |
| 简单加 16 列使 Board 变宽/滚动异常 | 采用 2× coordinate migration 和固定物理 pitch，不接受仅改 `GRID_COLUMNS` 的实现。 |
| 自动 fit 因单位翻倍过度扩张 | grow cap 用物理预算转换；旧/新典型卡的最大像素扩张都写测试。 |
| collision / planner 探索量上升 | 持续量测 `PLANNER_SEARCH_CAP`、24 卡和高密板；每个 blocker 的预算、确定性 tie-break 不退化。 |
| schema 4 卡被错误 tray 化 | migration 后再 legalize；专门测试 `GridRect ×2`、重叠、unplaced 与 duplicate board。 |
| 玻璃材质造成白角或不透明 child | 只沿 `UltraViewCard` 与其子 chrome 的真实 widget 路径修正；实际截图检查，不加全局 translucent 属性。 |
| 导出与屏幕看起来不同 | compositor 使用明确的扁平 Titanium base + 同一 card alpha；像素/截图回归覆盖。 |
| 误将预览白底 alpha 化损害数据 | QImage 内容保持不变；透明仅限 card shell 与其原本 unused area。 |

## 6. 实施记录

- Wave 1–3 已实现：Free Grid 升级为 schema 5 的 2× 微网格，旧自由网格坐标在读取时迁移，等比 solver 使用实际 `preview_reading_box()` 的 unused area 评分。
- 已统一新建、拖入、延迟预览与“按原图比例”的预览尺寸入口，并将 Retina 原始 capture 尺寸换算为逻辑像素后参与 card fit。
- 卡片壳、选中/投放状态与操作条使用 Titanium 半透明磨砂 token；预览 `QImage` 仍维持自己的不透明白底与图表像素。
- 导出 compositor 使用确定性的 Titanium 背景和相同的半透明 card shell，不依赖桌面透明合成。
- 已完成 offscreen owner tests；真实 macOS 前台和 Windows frozen 验收仍按 Wave 4 执行。

## 7. 完成定义

本计划完成需要同时满足：

1. 用户截图所示 View 的等比留白由量化指标证明显著下降，且预览完整、未拉伸、未裁图；
2. schema 1–4 的已知自由网格项目安全迁移到 schema 5，位置/排序/占用与导出稳定；
3. 所有 changed-owner 与边界测试通过；
4. macOS 真实前台已检查比例、手势、保存重开与磨砂圆角；
5. Windows frozen 验收如未执行，最终报告必须明确标记为 **UNVERIFIED**。
