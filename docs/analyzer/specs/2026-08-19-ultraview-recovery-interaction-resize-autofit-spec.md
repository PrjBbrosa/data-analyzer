# UltraView 恢复性优化 Spec：可用交互、稳定 Resize 与真实 Autofit

- 日期：2026-08-19
- 状态：**IN PROGRESS**；用户已授权按配套 Plan 施工
- Review：`docs/analyzer/reviews/2026-08-19-ultraview-two-wave-regression-review.md`
- Plan：`docs/analyzer/plans/2026-08-19-ultraview-recovery-interaction-resize-autofit-plan.md`
- 后续体验 Spec：`docs/analyzer/specs/2026-08-20-ultraview-miro-authoring-experience-spec.md`
- 后续完整 Plan：`docs/analyzer/plans/2026-08-20-ultraview-miro-authoring-completion-plan.md`

## 0. 产品结论

UltraView 下一阶段不再继续横向增加工具、样式或对象类型。先恢复四个基本承诺：

1. 用户看到的每个 enabled 控件都完成端到端行为；没有“只会高亮/emit”的按钮。
2. Move/resize 在 Retina、多卡和真实预览下持续跟手，无空白帧、双影或透明闪烁。
3. “适应内容”“按原图比例”“优化布局”是三个名字、三个 owner、三种可预测结果。
4. 创作能力按完整纵向切片交付：先 Select + Sticky，再 Text，再 Shape/Connector，最后 Draw。

任何一项没有用户手势、undo/redo、dirty、save/reopen、offscreen 和 Cocoa 证据时，都不称为 Implemented。

## 1. 范围

### 1.1 本 Spec 包含

- 暂停/隐藏当前未闭环的 creation controls。
- 统一 card/author selection 和 tool/draft gesture owner。
- Sticky 的第一个完整纵向切片。
- 现有 FreeGrid card move/resize 的帧合并、ghost、dirty region 和 settle 策略。
- 单卡 Fit、Board camera Fit、全板布局优化的语义拆分与求解合同。
- 真实图表卡片的 shell、preview paper、hover/selection/drag 视觉合同。
- 测试、Cocoa、Windows frozen 和性能验收门。

### 1.2 非目标

- 本轮不同时完成 Text/Shape/Connector/Draw 全套工具。
- 不把 FreeGrid 改成任意像素坐标或 QGraphicsView。
- 不重新计算分析结果，不改变 View identity，不猜测 sampling rate/unit/time axis。
- 不对预览 QImage 做白色阈值抠图、裁掉轴/标签或非等比拉伸。
- 不以“再细化网格”替代 Autofit objective，也不把反复单卡 Fit 当作全板优化。
- 不把相机状态、hover、active tool 或 draft 存入项目。

## 2. 发布与可见性合同

### R1. Dead affordance 禁止

- 没有完整行为的 control 必须不创建或不可见；仅 disabled 且写“即将推出”也不进入正式界面。
- “完整行为”至少包含：pointer/shortcut 入口、draft feedback、commit/cancel、undo/redo、dirty、
  save/reopen、错误反馈、help/quickref。
- 当前 Sticky/Text/Shapes/Draw 在对应纵切通过前不出现在 release UI；Select 可保留为现有卡片选择语义。

### R2. 完成状态

文档状态固定使用以下枚举：

- `PROPOSED`：合同待授权。
- `IN PROGRESS`：允许施工但门未闭合。
- `CODE COMPLETE / FOREGROUND UNVERIFIED`：自动化通过，Cocoa 未过。
- `ACCEPTED ON macOS / WINDOWS UNVERIFIED`：macOS 通过，Windows frozen 未过。
- `ACCEPTED`：适用平台门全部通过。

不得在完成定义未满足时写 `Implemented`。

## 3. 单一交互 Owner

### I1. `BoardInteractionController`

FreeGrid Board 只有一个 transient interaction owner，建议命名
`BoardInteractionController`，放在 `ui/chart_stack/ultraview/author_tools.py`。它拥有：

- `active_tool: ToolId`
- `pinned_tool: ToolId | None`
- `selection: frozenset[BoardItemKey]`
- `draft: DraftGesture | None`
- `hover_target: BoardItemKey | None`
- guide/snap 临时结果
- 本次 transaction 的 before state 和 commit/cancel 生命周期

Page、FreeGridGesture、card widgets、AuthorPaintLayer、ToolRail 都只能消费其投影或发 intent；不得再新增
平行 selection/tool/draft 状态。

### I2. 身份

```text
BoardItemKey = CardKey(UltraViewRef) | AuthorKey(object_id)
```

- display title、短标签和 tooltip 不能充当 identity。
- Card key 使用复合 source/channel/View identity 的现有 `UltraViewRef`。
- Author key 只使用持久化、Board 内唯一的 `object_id`。

### I3. 事件优先级

1. active text editor / popup
2. resize/anchor handle
3. author object，逆 z-order hit-test
4. card
5. blank canvas

中键、Space+左键、既有右键 deferred pan 在任何 creation tool 下仍优先进入 viewport gesture；右键短按仍打开
既有 context menu。

### I4. Tool 状态机

```text
Idle/Select
  -> Armed(tool)
  -> Drafting(pointer down/move)
  -> Editing(optional text/format)
  -> Commit -> Select 或 pinned Armed
  -> Cancel(Esc) -> Select 或 pinned Armed
```

- one-shot tool 成功 commit 后回 Select；pin 后继续 Armed。
- Esc 顺序：退出/取消 editor → 取消 draft → 回 Select → 清 selection → 既有 overlay/presentation 栈。
- active tool 切换、hover、draft 都不 dirty；只有成功持久化 mutation dirty。
- 任何错误必须返回可行动反馈，不能只停在无变化状态。

## 4. 第一条纵向切片：Sticky

### S1. 创建

- `N` 或点击 Sticky 进入 Armed；cursor 和 rail 只显示一个 active tool。
- blank click 创建默认便签并立即编辑；blank drag 以起止框创建。
- 最小 2×1.5 canonical micro-cell，默认 4×3；坐标允许负值但受现有 safety bounds 限制。
- 空文本首次退出自动取消创建，不产生 history/dirty。
- 非空 commit 产生恰好一条 `BoardEditEntry`，mark workspace dirty，projection 立即更新。

### S2. 编辑/选择

- 单击选择；Shift toggle；blank click 清；Esc 清理顺序遵循 I4。
- 双击进入文本编辑；支持中文 IME。
- move/resize/颜色/文本各以一次用户事务产生一条 undo；cancel 完全恢复 before state。
- save/close/reopen 后 geometry、text、palette、z-order 一致。

### S3. Sticky 出口门

在 Sticky 通过以下事务前，不开始 Text/Shape/Draw 产品入口：

```text
click tool -> click canvas -> edit CJK -> commit -> undo -> redo -> save -> reopen
```

另需通过 drag-create、cancel、locked、negative coordinate、presentation/overview disabled 和 800×560 rail/popup。

## 5. Card Move/Resize 性能与视觉合同

### P1. 输入与帧调度

- mouseMove 只写入 `latest_pointer_sample`。
- 一个 0 ms single-shot 或统一 frame scheduler 每个 event-loop frame 最多消费一次最新样本。
- 如果 snap 后 `candidate GridRect`、modifier、layout revision 均未改变：不调用 planner、不换 ghost、不 repaint。
- release 必须同步消费最后一个 sample 后再 commit；不能丢最后位置。

### P2. 规划

- planner 保持 Qt-free、确定性、全有全无提交。
- drag 中只为变化的 candidate 求解；相同 candidate 可按
  `(layout_revision, mover, target, operation, incoming)` 缓存。
- 24-card dense board 下，纯 planner p95 ≤ 2 ms，max ≤ 8 ms；超过时记录输入 fingerprint，不能静默掉帧。
- resize 的 collision preview 可以显示 displaced outline，但真实 widgets 只在 release 后一次 relayout。

### P3. Ghost/paint

- gesture start 时建立一次 ghost source；移动中不从 raw QImage 重复创建对象。
- drag/resize 使用 `QUALITY_FAST` 的 DPR-correct pixmap 或低分辨率 mip；idle settle 后使用 Smooth 结果。
- overlay 更新区域 = old ghost ∪ new ghost ∪ old/new highlight ∪ badge/handle margin；禁止无条件全层 update。
- 不用 `QGraphicsOpacityEffect` 做 drag dim。使用预先存在的 card paint flag，或直接隐藏原卡内容并保持稳定 shell。
- 不同时显示 0.4 原卡和 0.45 ghost 的两份完整预览；默认只显示一个清晰 ghost + 稳定 outline。
- 透明 shell 在 selected/drag/drop 状态下 alpha 不跳变；状态只改 border/wash，不改变是否透底。

### P4. 性能验收场景

参考机必须记录型号、macOS、Qt/Python、DPR、窗口大小与项目 fingerprint：

| 场景 | 指标 |
|---|---|
| 6 cards，DPR 2，单卡 8 向 resize 3 s | input-to-present p95 ≤ 16.7 ms；max ≤ 33 ms；0 blank frame |
| 24 cards，DPR 2，resize 撞开 3+ 邻卡 | p95 ≤ 33 ms；无持续 backlog；release 后 1 次 commit |
| 24 cards，连续 move/resize 30 s | 无 opacity 泄漏、双影、stuck cursor、timer/event backlog |
| resize 后 idle | 150 ms 内完成一次 smooth settle；不改变最终 geometry |

若测量工具只能给 Qt paint 时间，报告必须写明它不等于整机 input-to-present。

## 6. 三个 Fit 命令

### F1. Board Fit（适应内容）

- 只改变 camera zoom/scroll，不改变任何 card/author geometry，不 dirty、不进 undo。
- 使用 cards ∪ visible author ink 的最终 bounds；一次 settle。
- 默认 clamp 与 100%/300% 语义沿现有 viewport spec，不与 Card Fit 共享名字。

### F2. Fit Card Preview（按原图比例）

- 只改变选中 card 的 outer `GridRect`；默认**不移动任何邻卡**。
- 若无合法局部候选，保持原位并提示“附近空间不足；可用优化布局重排全板”。
- 不改变 preview QImage、不裁图、不拉伸、不改分析结果。
- 求解输入是纯 DTO，但 DTO 必须来自实际可见几何：

```text
image logical size
current GridRect and grid metrics
actual header/footer/orphan visibility and heights
actual image contents margins/padding
allowed min/max span and safety bounds
occupied rects excluding self
growth budget / policy
```

不能只用固定 `CARD_FIT_CHROME_HEIGHT` 代替 live LOD/show-title/show-source 状态。

### F3. 单卡目标函数

Card Fit 是局部整形，不是全棋盘选「浪费比最小」的外壳。它保住当前已经显示的预览尺度，只改长宽比去贴图像。

搜索域不是全部 min/max span。先算两个 hug 目标，再只搜索其中一个：

```text
保宽：plot′ = (W, W / A)
保高：plot′ = (H × A, H)
preferred = 面积不增大的那侧；若都增大或都缩小，取 |Δarea| 更小者
搜索域 = {当前 span} ∪ 只沿 preferred 的自由轴 ±2
保宽只改 row_span，保高只改 column_span
```

- `A` 是图像宽高比，`(W, H)` 是当前 live plot。
- hug snap 用 live chrome 把 plot′ 映回最近合法 `(column_span, row_span)`。
- 不能同时对保宽和保高开窗口后再按比例误差选赢家，也不能在次轴上 ±2，否则 chrome 占比会再次把卡片推向更大的「更完美」格子。
- 候选仍原点钉死、不碰邻卡、不越界。窗口只服务 chrome 量化，不能再扫 4–24 × 4–16。

评分使用稳定的 lexicographic key，越小越好：

```text
(
  crop_or_stretch_violation,     # 必须为 0，否则候选非法
  grows,                         # 面积变大则为 1，否则 0
  aspect_unused_ratio,           # 虚拟 upscale 的 contain 留白
  abs(area - current_area),
  abs(column_span - current_cols) + abs(row_span - current_rows),
  bottom_unused_ratio,           # 仅作较后级阅读偏好
  row_span,
  column_span,
)
```

- `aspect_unused_ratio` 按 KeepAspectRatio contain **允许虚拟放大**计算，只衡量比例误差。渲染器仍是 contain + no-upscale；不得把「图小于槽、拒绝放大」造成的空白当成要把大卡收成邮票的理由。
- 只要窗口里还有不增大的合法候选，就不为了更完美的比例去放大。只在当前已经偏小、两条 hug 轴都只能变大时才增长。
- “优先侧边而非底部”只做 tie preference。
- solver 返回 best candidate、score、是否达到可感知改善、未满足原因；无改善则 no-op，不制造一次无意义 undo。
- 测试用独立 oracle 对同一 hug 窗口求最小 key；产品 helper 结果必须完全相等。禁止再用全 min/max 网格的 unused 最小当正确性。
- 首次插入把「当前尺寸」换成 Board 默认 preset，走同一套 hug，不得一放就跳到全板黄金尺寸。

### F4. Optimize Board Layout（优化布局）

- 是显式 Board 命令，有预览/确认或可直接一次 undo；可以移动多张卡。
- 目标不是依次调用 F2。全局 key 至少包含：overlap/越界、总 unused area、最差单卡 unused、
  displaced count、总位移、Board bounding area、稳定 identity tie-break。
- 输入顺序固定，结果确定性；相同 Board + preview facts 必须得到相同布局。
- 任何 card 无 preview 时使用现有 preset，不猜测图像比例。

### F5. Autofit 验收

- 固定 wide/tall/square/双 subplot/FRF/time-frequency/小原图/no-preview 样本。
- solver 必须等于 hug-window oracle；典型样本的比例误差应下降，卡片面积不得跳到与当前尺度无关的全板黄金尺寸。否则 UI 不宣称有改善。
- 极端比例不设不可能的统一 8% 门；报告 best score 和物理约束。
- LOD_FULL / NO_FOOTER / TITLE_ONLY、show title/source on/off、DPR 1/2 都要覆盖。
- Card Fit 不移动邻卡；Optimize Board 才可移动，并产生恰好一条 undo。

## 7. 视觉与材料合同

### V1. 分清三层白色

1. Canvas/board material
2. Card shell / image slot letterbox
3. Preview QImage 自己的 paper/margin

诊断必须用像素位置和 widget geometry 判断来源。只允许对正确 owner 修改：

- shell/letterbox：UltraView card/QSS/paint owner。
- QImage paper：源 View 的可重放 capture presentation profile；不能事后按颜色抠透明。
- canvas：CanvasHost，不因单卡需求全局改变。

### V2. Frost

- Frost 是轻度半透明 shell，不是 blur；不添加 per-card `QGraphicsBlurEffect`。
- 真实 chart pixels 保持清晰、不受 card alpha 影响。
- 选中、hover、drag、drop、orphaned 状态在 radius、backing、对比度上连续。
- 800×560、1280×720、1600×1000，DPR 1/2，各至少验证一张真实数据卡。

### V3. Rail

- rail 只显示已交付工具；一个时刻只有一个 active tool。
- 36 px target、Tab 可达、tooltip/accessible name 描述真实行为。
- popup 需 `WA_TranslucentBackground` + clamp，不能只靠 QSS radius。
- compact stage 中所有 visible controls 完整可用，不靠裁掉尾部按钮。

## 8. 数据、History 与恢复

- 不改变 `ULTRAVIEW_SCHEMA`，除非独立 migration review 证明必须改变。
- `author_objects` 继续 additive；unknown kinds 保序透传。
- mutation 只能经 state pure helper → coordinator/controller transaction → `_after_board_mutation()`。
- create/delete/move/resize/text/style 各一条精确 patch；redo fork 清理。
- Board switch/project close/clear 必须 cancel draft、stop timer、hide editor、clear hover/selection，不能遗留 Qt wrapper。
- 任何 crash/异常不得留下半应用 placement + author mutation。

## 9. 测试合同

### 9.1 必须先红的端到端测试

至少新增以下 Page/coordinator 级测试；测试名只是建议：

- `test_sticky_tool_click_then_canvas_click_commits_one_object`
- `test_sticky_drag_create_cancel_and_commit_are_atomic`
- `test_sticky_commit_marks_dirty_and_round_trips_project`
- `test_sticky_create_undo_redo_is_one_transaction`
- `test_visible_creation_controls_all_have_page_consumers`
- `test_resize_coalesces_same_grid_candidate_to_one_plan_and_paint`
- `test_card_fit_matches_bruteforce_oracle_for_live_chrome_dto`
- `test_card_fit_never_moves_neighbor_cards`
- `test_optimize_board_is_one_explicit_undoable_transaction`

“ToolRail emits intent”或“预置对象能 render”不能替代这些测试。

### 9.2 Focused gates

- owner：author tools/state/history/layer, free_grid, gesture, ghost overlay, page, coordinator, compositor。
- boundary：import boundaries、no-lambda、main-window state ownership、QSS border shorthand。
- changed UI：help、hints、quickref 同步。
- 不在每个子波跑 full suite；稳定集成里程碑由一个 owner 跑一次，acquisition_ui 分进程。

## 10. 完成定义

只有全部满足才可将恢复批次标为 `ACCEPTED ON macOS`：

1. release UI 没有 dead affordance。
2. Sticky 纵切完成 S3 全事务。
3. card/author/tool/draft 只有一个 interaction owner。
4. 6/24-card Resize 性能达到 P4，无 flicker/blank/double image。
5. F1/F2/F4 三种 Fit 行为名称、mutation、undo 和 solver 结果符合合同。
6. 真实项目的白色来源已分类，frost 在真实 Cocoa 像素上通过。
7. focused/boundary tests 通过，macOS 前台证据记录 HEAD + worktree fingerprint。
8. Windows frozen 未跑时必须明确写 `WINDOWS UNVERIFIED`，不得用 macOS/offscreen 替代。
