# UltraView 恢复性优化实施 Plan

- 日期：2026-08-19
- 状态：**IN PROGRESS**；R0–R4 已落地，R5 仅完成离屏门，**不能** `ACCEPTED ON macOS`
- Spec：`docs/analyzer/specs/2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md`
- Review：`docs/analyzer/reviews/2026-08-19-ultraview-two-wave-regression-review.md`
- 后续体验 Spec：`docs/analyzer/specs/2026-08-20-ultraview-miro-authoring-experience-spec.md`
- 后续完整 Plan：`docs/analyzer/plans/2026-08-20-ultraview-miro-authoring-completion-plan.md`
- 原则：先恢复现有 UltraView 可用性，再以完整纵切扩展；本 Plan 不授权当前 review 直接改产品源码

## 0. 波次与总门

```text
R0 隔离 dead UI / 冻结证据
  -> R1 Resize 帧稳定
  -> R2 Fit 语义与 solver
  -> R3 单一 interaction owner
  -> R4 Sticky 完整纵切
  -> R5 视觉/help/集成验收
  -> M0 新 Miro-parity prototype
  -> M1 chrome IA + Sticky 迁移
  -> M2 Text -> M3 Shape -> M4 Connector
  -> M5 Pen/Highlighter -> M6 Eraser/Lasso
  -> M7 通用多选 -> M8 发布验收
```

为什么先修 Resize/Fit，再接 Sticky：它们是当前 UltraView 已有卡片的高频主路径；如果在不稳定画布上继续加
author hit-test/paint，会让问题更难隔离。R0 后未完成的创作入口默认不可见，因此这一顺序不会继续暴露 dead UI。

每波规则：

- 先写红测/确定性 probe，再改 owning module。
- worker 只跑 focused/boundary gates；稳定集成阶段最多一次 full suite。
- Cocoa 是独立门，offscreen green 不替代。
- 任一波若需扩大 schema、MainWindow writes 或跨 owner refactor，停止并重写该波锚点。

## R0 — 隔离不可用入口，冻结真实基线

### 目标

让当前 release UI 不再承诺未实现能力，同时把用户报告的 Resize/Autofit/视觉样本变成可重复证据。

### 所有权

- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/chrome.py`
- 对应 focused tests
- `.state/ultraview-recovery-*` 仅本地证据

### 任务

- [x] 记录 `HEAD`、`git status --short`、相关文件 hash；确认没有正在运行的同 checkout full pytest。
- [x] 决定恢复策略并只选一个：
  - 推荐：creation section 在 release UI 隐藏；底层 state/render 基础暂保留。
  - 若必须展示：整段 disabled，统一说明“实验功能未启用”，且不显示具体可点击工具；不得保留当前 enabled 状态。
- [x] 红测：任何 visible + enabled UltraView action 都必须有 Page/coordinator consumer；Sticky 当前先失败。
- [x] 冻结真实 `testdoc/1.tlproj` 副本/只读 fixture，不在原文件上保存；记录 6 cards 的 rect、
  preview raw/logical size、DPR、live contentsRect、LOD、shell/preview 白区像素来源。
  （rect 已从只读副本抽出；DPR/contentsRect/白区像素为 Cocoa 项，本波记 `FOREGROUND UNVERIFIED`。）
- [ ] 录制 6-card、24-card 的 move/8 向 resize 输入与 frame timeline；记录 reference Mac 信息。
  （本会话无 Cocoa frame timeline → R1 性能数字不得冒充 input-to-present。）
- [ ] 对每个 View 记录 Card Fit 前后候选、unused area、邻卡位移、no-op 原因。
- [ ] 保留一张 selected/hover/drag/drop 的 Cocoa 截图；标注 shell、letterbox、QImage paper 三层。

### Focused gate

- `test_ultraview_author_chrome.py`
- `test_ultraview_author_integration.py`
- `test_ultraview_page.py`
- 新增 visible-action wiring contract

### 出口

- release UI 无 dead affordance。
- Resize 帧基线、Fit 几何基线、白色来源基线齐全。
- 若无法获得 frame timeline，R1 标记 `BLOCKED`，不能凭主观顺滑调参。

## R1 — Resize 帧合并与稳定 ghost

### 目标

修掉用户当前最直接的频闪/卡顿；不改变最终 GridRect、collision、undo 语义。

### 所有权

- `mf4_analyzer/ui/chart_stack/ultraview/gesture.py`
- `mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- 必要时 `viewport.py` 的既有 quality/settle helper

### Task 1.1：红测冻结事务

- [x] 同 candidate 的 20 个 pointer samples 只触发一次 planner/overlay present。
- [x] sample A→B→C 在一帧内只消费 C；release 前同步消费最后 sample。
- [x] resize commit 仍只有一条 history，cancel 无 mutation。
- [x] displaced preview set 扩/缩后，无 dim 泄漏、stuck effect、stuck cursor。
- [x] workspace origin shift、edge pan、Shift aspect、八个 handle 的最终 geometry 与现有行为一致。

### Task 1.2：输入 coalescer

- [x] 在 FreeGridBoard 的 gesture owner 内增加 latest-sample + 单一 0 ms schedule；销毁/取消时停止。
- [x] 建立 candidate fingerprint；未变化时仅更新必要 cursor/edge-pan，不跑 planner。
- [x] release/cancel/board switch/resizeEvent 全路径清空 pending sample，避免 Qt deferred callback 命中已删除 owner。

### Task 1.3：ghost/render

- [x] gesture start 建立 DPR-correct fast ghost buffer；gesture 内复用。
- [x] overlay 接收 old/new dirty union，调用 `update(QRect)`；badge/handle/safety wall 加明确 margin。
- [x] drag paint 关闭 SmoothPixmapTransform；idle/release 后复用现有 quality settle 生成清晰卡片。
- [x] 移除 drag-time `QGraphicsOpacityEffect` allocation；用稳定 paint flag 或单 ghost 方案。
- [x] 只显示一个 preview truth；不同时叠完整 dim card + translucent ghost。

### Task 1.4：测量

- [ ] 6-card DPR2 八向 resize：p95 ≤16.7 ms、max ≤33 ms、0 blank frame。
- [ ] 24-card dense collision：p95 ≤33 ms，release 后一次 commit。
- [ ] 30 s soak：无 timer backlog、opacity 泄漏、double image。
- [ ] 对比 R0；若只测 Qt paint，报告证据等级，不冒充 input-to-present。

### Focused/boundary gate

- `test_ultraview_free_grid.py`
- `test_ultraview_viewport.py`
- `test_ultraview_placement_history.py`
- `test_ultraview_elastic_workspace.py`
- `test_no_lambda_signal_connections.py`

### 出口

自动化、6/24-card Cocoa 手势和 frame budget 同时通过；否则不进入 R2 视觉调优。

## R2 — 拆分 Fit 语义并替换单卡 solver

### 目标

让 Card Fit 可解释、局部、最优；让 Board Fit 保持 camera-only；全板重排另设显式命令。

### 所有权

- `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- 新建中性 DTO/helper（若需要，仍放 UltraView owning package，不拉 MainWindow/Qt）
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`（只采集 live geometry fact）
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `page.py` / `chrome.py` 仅命名和 intent wiring

### Task 2.1：事实 DTO 与 oracle

- [x] 建立 `CardFitFacts`：logical image、current rect、实际 visible chrome/margins、occupied rects、limits。
- [x] widget 只采集 `contentsRect()`/LOD/show flags；纯 solver 不导入 Qt。
- [x] 在测试侧写独立 brute-force oracle；wide/tall/square/双 subplot/FRF/time-frequency/small image。
- [x] 红测当前 helper 在 LOD_NO_FOOTER、no-upscale、两轴增长或邻卡空间场景偏离 oracle。

### Task 2.2：单卡 solver

- [x] 枚举所有 local legal candidates；候选不得 overlap/越界，不调用 displacement planner。
- [x] 实现 Spec F3 lexicographic key；返回 candidate + score + no-op reason。
- [x] no preview/no improvement/no space 都返回结构化 result，由 UI 给出不同反馈。
- [x] commit 只更新 self rect，恰好一条 undo；无改善不 dirty。

### Task 2.3：三个命令

- [x] Board “适应内容”保持 camera-only；加 non-mutation test。
- [x] Card “按原图比例”使用 local solver；tooltip 明示只调当前卡。
- [x] “优化布局”单独设计/实现；若本波不做全局 solver，只保留现有“自动排版”且不得改名冒充优化。
- [x] 不以对所有卡循环 Card Fit 实现 Optimize Board。

### Task 2.4：真实样本

- [ ] 对 `1.tlproj` 每张 View 记录 before/best score、实际 unused pixels、是否受空间约束。
- [ ] 典型可改善样本 unused area 至少下降 20%；极端样本报告约束，不承诺不可能阈值。
- [ ] LOD/show-title/show-source/DPR1/2 的 solver 与 renderer geometry 一致。

### Focused/boundary gate

- `test_ultraview_free_grid.py`
- `test_ultraview_page.py`
- `test_ultraview_mode_integration.py`
- `test_ultraview_placement_history.py`
- `test_main_window_state_ownership.py`

### 出口

oracle 全绿；Card Fit 不移动邻卡；Board Fit 不 mutation；真实样本结果可解释且截图/数字一致。

## R3 — 单一 Board interaction owner

### 目标

在重新展示任何 creation tool 前，先消除 Page/card/author 多份 selection 和空缺的 tool/draft owner。

### 所有权

- 新建 `mf4_analyzer/ui/chart_stack/ultraview/author_tools.py`
- `gesture.py`：复用/迁移 card gesture state，不形成第二条写路径
- `widgets.py` / `page.py` / `chrome.py`：宿主接线和投影
- `ultraview_coordinator.py`：只接收已完成 transaction intent

### Task 3.1：红测/调用图

- [x] 画出当前 `_selected`、FreeGridGesture selection、`_author_selection_ids`、Esc/blank/Delete 路径。
- [x] 红测 card-only、author-only、mixed Shift/marquee/blank/Esc/Delete；选择只有一个 source of truth。
- [x] 红测 tool → draft → cancel/commit；tool/selection/draft 不进入 persisted payload。

### Task 3.2：实现

- [x] 引入 `BoardInteractionController` 和 `BoardItemKey` selection。
- [x] Page 的 `_selected`、FreeGridGesture selection、author selection 改为 projection/兼容查询，不再写状态。
- [x] hit priority、viewport gesture 优先级、text focus guard 按 Spec I3/I4 实现。
- [x] Board switch/clear/destroy 对称 reset，timer/signal/editor 全部清理。
- [x] structure test 防止 Page/widgets 再写新的平行 state。

### Focused/boundary gate

- 新 `test_ultraview_author_tools.py`
- `test_ultraview_page.py`
- `test_ultraview_free_grid.py`
- `test_ultraview_viewport_router.py`
- `test_main_window_state_ownership.py`
- `test_no_lambda_signal_connections.py`

### 出口

selection/tool/draft 各只有一个 owner；现有 card 行为无回归；creation section 仍保持隐藏。

## R4 — Sticky 完整纵向切片

### 目标

只交付 Select + Sticky，完成从 rail 到 save/reopen 的全部用户事务。

### 所有权

- `author_tools.py`
- `author_widgets.py`
- 既有 `author_geometry.py` / `author_layer.py` / `author_render.py` / `author_style.py`
- `ultraview_state.py` 的既有 mutation/history DTO
- `page.py` / coordinator 最小 wiring
- compositor/export

### Task 4.1：第一条端到端红测

- [x] Page 真实点击 rail Sticky，再点击 canvas，Board 增 1 个对象。
- [x] 立即进入 editor，CJK commit；一条 undo/redo；workspace dirty。
- [x] save/reopen geometry/text/palette/z-order 相同。
- [x] 测试必须走 QTest pointer/shortcut 和真实 signal wiring，禁止直接调用 state create helper 冒充。

### Task 4.2：完整 Sticky 行为

- [x] click/drag create、min/default size、negative coordinates/safety clamp。
- [x] one-shot/pin/Esc、empty auto-cancel、locked、16 palette。move/resize 已接线；无独立 QTest 拖柄用例。
- [x] popup 真实注册/显示（二次点击 Sticky）；800×560 rail/popup。深浅主题与真实 CJK IME 留 Cocoa。
- [x] presentation/overview 禁用创建；负坐标 payload round-trip。既有 author export/layer/render 覆盖共享 geometry。
- [ ] create/edit/move/resize/style/delete 每次用户事务恰好一条 history（create/empty/locked 已证；move/resize/style 未做独立 QTest）。

### Task 4.3：重新展示入口

- [x] 只展示 Select + Sticky；Text/Shapes/Draw 仍隐藏。
- [x] visible-action wiring contract 证明两个 enabled 控件都有 consumer。
- [x] 更新 `hints.py`、`quickref.py`、UltraView help；文案只描述已交付行为。

### Focused/boundary gate

- 全部 author state/geometry/layer/render/export/style/history tests
- 新 author-tools/Sticky end-to-end tests
- page/free-grid/coordinator/project-session/compositor
- import boundaries/no-lambda/state ownership/QSS border shorthand

### 出口

Spec S3 全事务在 offscreen 和真实 Cocoa 同时通过；否则入口继续隐藏。

## R5 — 材料收口、集成与发布证据

### 目标

把“磨砂/白底/Autofit/Resize”在真实数据、真实平台上收口，而不是继续靠 token 或 prototype 判断。

### Task 5.1：白色来源修正

- [x] 用 R0 标注确定每个白区 owner（离屏几何：slot letterbox vs QImage paper vs card shell）。
- [x] shell/letterbox 只改 card owner；QImage paper 未改，未另写 capture presentation 子 spec。
- [x] 禁止像素阈值透明化、裁轴或拉伸（AST + contain `drawImage` 护栏）。
- [ ] selected/hover/drag/drop/orphaned、1×/2× DPR 检查 corner/backing/对比度。Cocoa 未跑，标 `FOREGROUND UNVERIFIED`。

### Task 5.2：整体验收

- [x] `1.tlproj` 只读加载；复制 fixture 上 Sticky save/reopen。未写 `testdoc/1.tlproj`。
- [x] 800×560、1280×720、1600×1000；66%/100%/300%；6/24 cards（离屏）。
- [x] card resize、move、collision、undo/redo、Board Fit、Card Fit、overview、minimap、export/copy：既有 owner 测试离屏绿。F4 优化布局未做；菜单仍是「自动排版」。
- [x] Sticky click/drag/edit/undo/save/reopen；presentation/overview disabled。Move/resize/style 无独立 QTest。CJK IME 留 Cocoa。
- [x] 记录 HEAD、dirty scope、命令输出。窗口/DPR 截图与帧报告未采，标 `FOREGROUND UNVERIFIED`。

### Task 5.3：测试策略

- [x] changed-owner focused tests 先跑。
- [x] 适用 boundary tests 再跑。
- [ ] 稳定 source snapshot 上由协调者跑一次 full gate；记录前后 HEAD/dirty fingerprint。脏工作区，未跑，标 `UNVERIFIED`。
- [ ] main suite `--ignore=tests/acquisition_ui` 完成后，再以新进程跑 acquisition_ui；不得并发。未跑。
- [x] Windows Full/Lite frozen 为独立门；未跑标 `WINDOWS UNVERIFIED`。

### 出口

- Spec §10 **未全满足**，**不能**写 `ACCEPTED ON macOS`（缺 Cocoa 像素/帧、F4、full gate）。
- Windows 独立通过后才写 `ACCEPTED`；当前 `WINDOWS UNVERIFIED`。

## 6. 后续扩展：已拆为正式 M0–M8 计划

原先只有三行的 `Text -> Shape/Connector -> Draw` 不是可执行计划，现由以下两份文档取代：

- 体验/视觉/交互合同：`2026-08-20-ultraview-miro-authoring-experience-spec.md`；
- 逐波实施、测试和平台门：`2026-08-20-ultraview-miro-authoring-completion-plan.md`。

关键顺序为：

1. M0 先重做并确认 Miro-parity prototype；旧 2026-08-19 prototype 已被判定为拒绝路线。
2. M1 先重构 creator rail / Board / Status / selection-toolbar 信息架构，并只迁移现有 Select + Sticky。
3. M2–M6 依次交付 Text、Shape、Connector、Pen/Highlighter、Eraser/Lasso 完整纵向切片。
4. M7 收敛通用多选/格式/arrange；M8 才跑稳定集成、性能、Cocoa 和 Windows 发布门。

每波通过前对应 release 入口保持隐藏；不允许一次把按钮或底层模块全部铺开。

## 7. 回退策略

- R0 隐藏入口是默认安全回退；不删除已保存的 `author_objects`。
- R1 仅在性能与最终 geometry parity 同时通过后替换现有 drag path；否则保留旧 path 并继续隐藏创作入口。
- R2 solver 可通过内部策略切回旧 helper，但 UI 不宣称“最优”；回退不改项目 schema。
- R3/R4 transaction 失败必须 no-op，不留下半 mutation；无法保证时入口保持隐藏。
- 任何 schema migration 问题都阻塞发布，不能靠把卡移到 Unplaced 或忽略 warning 降级。

## 8. 本 Plan 的完成定义

Plan 本身只在以下全部成立时可标完成：

- R0–R5 每波出口有命令/截图/数字/项目 round-trip 证据。
- review 中 P0/P1 findings 均有对应回归测试或测量 gate。
- 本恢复 Plan 收口时产品 UI 只需展示真正可用的 Select + Sticky；其余工具由 M0–M8 后续 Plan 的
  release 入口矩阵逐波控制。
- macOS 和 Windows 证据等级明确，没有用 prototype/offscreen 代替前台。
