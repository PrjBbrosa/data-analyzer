# UltraView Move/Resize 持续反馈与渲染管线恢复 Plan

- 日期：2026-08-22
- 状态：**PROPOSED / AUTHORIZED FOR HANDOFF**；本文已获授权作为后续 agent 的执行计划，尚未授权把文档本身标记为完成
- 当前代码基线：`2a537b9b fix(ultraview): stabilize Miro picker, shapes, rail, and draw chrome`
- 范围：Free Grid 中 View card 的 move/resize、selection/marquee/insert/replace/author geometry 等瞬态反馈，以及与其共用的 edge-pan、preview scheduling 和 Cocoa 合成路径
- 非范围：布局算法语义、项目 schema、分析计算、PreviewStore residency、Card Fit、画布视觉主题、Miro 工具种类扩展
- 历史输入：
  - `docs/analyzer/specs/2026-08-14-ultraview-p3-canvas-interaction-spec.md`
  - `docs/analyzer/plans/2026-08-16-ultraview-elastic-canvas-ux-plan.md`
  - `docs/analyzer/reviews/2026-08-19-ultraview-two-wave-regression-review.md`
  - `docs/analyzer/specs/2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md`
  - `docs/analyzer/plans/2026-08-19-ultraview-recovery-interaction-resize-autofit-plan.md`
  - `docs/lessons-learned/pyqt-ui/2026-08-20-ultraview-preview-paints-every-plan-rect.md`

## 0. 执行裁决

当前问题不是 `GridRect`、collision planner 或 release commit 算错，而是瞬态反馈的输入、定时器、投影和透明层合成没有单一 owner。后续不再给当前 `GhostOverlay` 叠加 `raise_()`、透明度、局部 timer、`setUpdatesEnabled()` 或额外 `update()` 补丁。

本计划选择以下唯一生产路线：

1. `FreeGridGesture` / `BoardInteractionController` 继续拥有手势和 selection 真相；布局 planner 与一次性 commit/undo 合同不变。
2. Page 的 edge-pan 只处理**最新指针位置和真实 viewport 位移**；指针不在边缘、scroll/origin 未变化时，不重投影、不重规划、不提交反馈帧。
3. FreeGrid 的瞬态反馈从“弹性 Board 全尺寸透明 sibling”迁移为“`QScrollArea.viewport()` 尺寸的唯一反馈 surface”。
4. feedback surface 可以在 Cocoa expose/恢复时全 viewport 重画，但不能因为相同 candidate 或 16 ms timer 永久重画。
5. 迁移完成后删除 FreeGrid 的旧 full-board `GhostOverlay` 路径和死 fingerprint；不长期保留双路径或运行时 feature flag。
6. `BoardGrid` 模板模式的有限尺寸 overlay 不在本批强制迁移；若它继续复用 `GhostOverlay`，必须与 FreeGrid 的新 surface 明确分开，不能为了兼容让 FreeGrid 留在旧路径。

### 0.1 对历史文档的修订关系

历史文档保留为当时证据，不删除、不回写成当前结论。本文从当前基线起优先于以下实施条款：

| 历史条款 | 本计划裁决 |
|---|---|
| 2026-08-19 Recovery Spec P3：full-board overlay 用 dirty union 局部 `update(QRect)` | **FreeGrid 路径废止**。Cocoa 对超大透明 sibling 的 clipped update 不稳定；改为 viewport-sized surface，允许 bounded full update。 |
| 2026-08-20 lesson：相同 candidate 也要 full `update()` 并持续 `raise_()` | **重新解释**为 surface expose/backing-store 恢复规则，不是每个 timer tick 的常规输入规则。相同 generation 不产生新 present。 |
| 2026-08-16 Elastic Task 3：手势期间常驻 16 ms edge timer | timer 只在 pointer 位于 edge band 且存在非零 pan velocity 时运行；离开 band 立即停止。 |
| 2026-08-19 Recovery Plan R1“已完成” | 当前前台回归证明其 Cocoa/完整 Page 出口未满足；R1 的实现状态从本计划视角为 **REGRESSED / SUPERSEDED**。 |
| 2026-08-14 P3 直接操纵合同 | 保留：普通拖动、8 向 resize、蓝/红反馈、span badge、最后 sample 同步 commit、一次 undo。 |

### 0.2 明确禁止的“快速修复”

- 不把 `_edge_pan_timer` interval 从 16 ms 调大来掩盖重复提交。
- 不在 `paintEvent()`、`mouseMoveEvent()`、`resizeEvent()` 再加一次 `raise_()` / `repaint()` / `processEvents()`。
- 不恢复 drag-time `setUpdatesEnabled(False/True)`、`QGraphicsOpacityEffect` 或清空 live card image。
- 不把同一透明 surface 同时设成 `WA_NoSystemBackground` 或用 `CompositionMode_Source` 清整层。
- 不靠 `QTest` 字段断言、一次 `render()` 或提交文本宣布 Cocoa 问题完成。
- 不以回退 `1a53c733` 整个提交作为正式修复；该提交同时包含 displaced preview、single-overlay truth 和白屏恢复，粗粒度回退会重新引入已知错误。
- 不在本批把生产画布改为 `QGraphicsView`。只有完成本文去重和 bounded surface 后，24-card Cocoa 仍不达预算，才另立重宿主 spec。

## 1. 当前已确认事实

### 1.1 状态与绘制已脱节

完整 `UltraViewPage + Cocoa` 诊断中，move 与 resize 在蓝框不可稳定保持的同一阶段仍满足：

- gesture `armed=True`、`active=True`；
- resize handle 和 move session 类型正确；
- overlay `visible=True`、`showing=True`；
- mover/displaced 的 ghosts 与 highlights 均存在；
- resize badge 仍是目标 span；
- release 事务路径未丢失。

因此本计划不授权修改 planner、`GridRect` 或 commit 语义来“碰运气修蓝框”。

### 1.2 当前重复刷新链

现有调用链为：

```text
真实 mouse move
  -> FreeGridBoard._ingest_pointer_sample
  -> FreeGridGesture.update / plan_layout
  -> _present_live_gesture
  -> GhostOverlay.set_move_previews
  -> raise_ + update

first live frame
  -> workspace_gesture_changed(True, first_global_pos)
  -> Page 启动 16 ms _edge_pan_timer
  -> 即使 velocity == 0 仍 refresh_workspace_gesture(first_global_pos)
  -> 再次 ingest / plan / present / raise / update
```

还有两个放大器：

1. `workspace_gesture_changed` 只在 `started` 时 emit，Page 保存的是首次 live pointer，而不是持续更新的最新 pointer；真实拖动时 timer 可能把旧位置与新 mouse event 交替送入预览链。
2. `_paint_fingerprint_seen` 被写入和清空，但从未用于跳过相同 frame；overlay 的 same-signature 分支又绕过 `_present()` 直接 `raise_(); update()`。

### 1.3 当前运行量化

在一个完整 Page、两张有预览的 FreeGrid card 上，只发送一次 move 后保持指针 500 ms：

| 场景 | preview submissions | overlay Paint | 状态 |
|---|---:|---:|---|
| resize | 34 | 42 | ghosts/highlights/badge 始终存在 |
| move | 34 | 42 | ghosts/highlights/badge 始终存在 |
| resize，诊断性停止 edge timer | 2 | 10 | preview submissions 不再持续增长 |

该 Page 的 FreeGrid/overlay 逻辑尺寸约 `6360×8084`，可见 region 仅约 `1180×740`。当前 workaround 因此把“Cocoa backing store 需要可靠重画”放大成了超大透明 QWidget 的持续 composite churn。

### 1.4 测试盲区

- `test_ultraview_gesture_coalesce.py` 多数创建裸 `FreeGridBoard`，没有 Page edge timer。
- `_wrap_present()` 只统计 `_present()`；same-signature 分支直接 `update()`，因此“present once”不等于“paint once”。
- 大量测试读取 `_ghosts/_highlights/_badge` 私有字段，证明模型里有数据，但不证明屏幕连续帧有像素。
- Page 的 edge-pan 测试主要断言 timer active/stop，没有断言中心区域零重复提交、latest pointer、paint budget 或 Cocoa 保持帧。

## 2. 不可回退的产品合同

### 2.1 Move

1. 左键超过 `startDragDistance` 的第一帧同步出现 snapped target feedback，不等待 timer。
2. 合法目标：mover 蓝色 outline/wash；若 planner 让位邻卡，mover 保持蓝色，所有 displaced cards 显示各自目标图像和红色 warning edge。
3. pointer 位于同一 snapped candidate 内时，蓝框持续可见但不重新 plan/present。
4. pointer 进入新 candidate 后，下一 event-loop frame 只呈现最新 candidate。
5. release 同步 flush 最新 sample，再以画面最后显示的 plan 一次提交；不得提交旧 pointer 或只提交倒数第二帧。

### 2.2 Resize

1. 8 向 handle、cursor、Shift 保持比例和 min/max span 合同不变。
2. 首次越过阈值即出现蓝色目标框和尺寸徽标；两者持续到 release/cancel。
3. badge 内容必须来自 candidate span，不从 widget 当前 geometry 反推。
4. collision reject 为红色；safety bounds 为铜色墙，二者不可互换。
5. resize 期间真实 card 不反复 clear/hide/recreate image；只由反馈 surface 呈现目标状态。

### 2.3 生命周期

- `Esc`、release、window deactivate、Board switch、layout switch、project clear、widget destroy 都清除当前 gesture 的反馈和 timer。
- 旧 gesture 的 deferred callback 不能清除新 gesture 的 frame；clear 必须带 `gesture_id/generation` 校验。
- click-only selection 不产生 move/resize ghost，也不得白化 chart；selection chrome 仍可见。
- drag/resize 只改变 release 后的 Board model；hover、frame、timer、surface state 不 dirty、不持久化。

### 2.4 Edge pan

- pointer 位置每个真实 mouse move 都更新到 Page 的 lightweight pointer state，但该更新本身不触发 planner 或 paint。
- pointer 不在 72px edge band：edge timer inactive。
- pointer 在 band：timer active，使用最新 global pointer 计算 velocity。
- 一个 tick 只有在 scrollbar、workspace extent 或 workspace origin 实际变化后，才允许调用一次 `reproject_after_viewport_change()`。
- viewport 没变化：零 reproject、零 planner、零 preview present。
- edge tick 的 scroll/extent change、candidate reproject 和 surface update 是一个逻辑事务；不得先暴露旧 frame 再补新 frame。

## 3. 目标架构

### 3.1 Owner 划分

| Owner | 负责 | 不负责 |
|---|---|---|
| `FreeGridGesture` / `BoardInteractionController` | press/active/candidate/plan/selection、Qt-free transaction state | QTimer、QWidget、viewport scroll、QPainter |
| `FreeGridBoard` gesture adapter | latest pointer coalescing、frame model 构建、DPR ghost source cache、向 Page 发布 lightweight pointer/frame intent | edge timer、scrollbar、Board state commit |
| Page edge-pan controller | gesture lifetime、latest global pointer、edge band、scroll/extent/origin transaction | 普通 mouse move 重规划、ghost 图片、selection 真相 |
| viewport feedback surface | 当前 immutable frame + viewport transform、paint、expose/resize 恢复 | planner、mutation、pointer hit routing、author object model |
| Coordinator | release 后唯一 geometry/history/dirty mutation | transient frame、timer、paint |

### 3.2 分离 lifetime、pointer 和 frame

删除当前同时承载 lifetime 与首次 pointer 的 `workspace_gesture_changed(bool, object)` 模糊合同，替换为等价的明确接口：

```text
workspace_gesture_active_changed(active, gesture_id)
workspace_pointer_changed(gesture_id, global_pos)       # Page 只覆盖 latest pos
feedback_frame_changed(GestureFeedbackFrame | None)     # presentation port
```

允许实现为 typed signal、明确 callback port 或小型 controller，但必须满足：

- lifetime 只在 transition emit；
- pointer 每个真实事件更新，但 Page slot 只赋值；
- frame 只在 candidate/layout/role/badge/transform-relevant state 变化时生成；
- 三者不能再次合并为 `object` payload 后靠 `getattr` 猜语义。

### 3.3 Immutable feedback frame

建议新增 UI-local typed DTO（命名可按当前风格调整）：

```text
GestureFeedbackFrame
  gesture_id
  generation
  layout_revision
  operation                 # move / resize / insert / marquee / author geometry
  candidate_fingerprint
  items[]                   # ref/object id, canonical rect/box, visual role, image key
  selection/handle geometry
  origin masks
  badge
  safety/collision/edge-hint state
```

合同：

- frame 保存 canonical Board/grid geometry，不保存 workspace widget 的巨大 `QRect`。
- frame 不保存 QWidget、QPainter、scrollbar 或项目 state。
- QPixmap/QImage cache 是 GUI-thread presentation cache，以 stable image key/DPR/target tier 查找；不塞进 Qt-free planner。
- `generation` 单调递增；surface 丢弃旧 generation。
- `candidate_fingerprint` 至少包含 gesture id、layout revision、operation、mover/group、candidate、modifier、plan roles 和 badge。仅像素位置变化但 snapped result 不变时不生成新 frame。

### 3.4 Viewport-sized feedback surface

新增或重构一个 mouse-transparent paint-only surface，parent 为 `BoardScrollArea.viewport()`：

- geometry 始终等于 `viewport.rect()`，不等于 `FreeGridBoard.rect()` 或 elastic workspace extent。
- paint 时将 frame 的 canonical geometry 通过一个明确的 `BoardToViewportTransform` 映射一次。
- scroll/zoom/extent rebase 只更新 transform revision；不复制 planner，不改变 frame identity。
- `present(new_frame)` 只在新 generation/transform revision 时 schedule 一次 bounded full `update()`。
- `QEvent::Expose/Show/Resize/ScreenChangeInternal` 可重画缓存 frame，但不得回调 planner。
- `raise_()` 只在 surface show、stack rebuild 或明确层级改变时调用；普通 frame 不反复 raise。
- Page 明确维护层级：board/author content < feedback surface < viewport floating controls/minimap；不得靠每 16 ms `raise_()` 维持顺序。当前 active editor 若继续作为 Board descendant，surface 必须接收 editor exclusion rect 并跳过该区域，不能为了“置顶”擅自 reparent editor 或破坏 IME。
- surface 继续 paint mover/displaced/collision/safety/origin wash/badge/handles/marquee/replace ring/edge hint；FreeGrid 不再保留第二个瞬态 overlay truth。

`AuthorPaintLayer` 暂保留为静态 author object renderer，但以下瞬态 author chrome 迁入同一 viewport feedback surface：selection、move/resize target、guides、draft bounds。这样 card 与 author gesture 不再争夺两个全 Board transparent siblings。

### 3.5 Frame scheduling

保留“first frame synchronous + later latest-sample 0 ms coalesce + release flush”，但 scheduler 只有一个 owner：

```text
press/armed
  -> real pointer event overwrites latest sample
  -> first threshold crossing synchronously consume and publish frame
  -> later pointer events overwrite latest sample
  -> one 0 ms callback consumes only newest sample
  -> unchanged candidate fingerprint: stop before planner/present
  -> changed candidate: planner once, publish generation+1
  -> release: stop timer, synchronously consume latest, commit displayed plan once
```

如果 present 中发生 re-entry，保存 newest sample；当前 present 完成后最多调度一次。不得递归 present，也不得静默丢 newest sample。

### 3.6 Edge-pan transaction

Page edge tick 顺序固定为：

1. 读取该 gesture 的 latest global pointer；gesture id 不匹配则 stop。
2. 计算 edge velocity；为零则 stop timer，不调用 Board。
3. 记录 old scroll/extent/origin transform。
4. 扩展 extent（如需）并写 scrollbar。
5. 若 transform 未变化，结束 tick。
6. 以 latest pointer 调用一次 `reproject_after_viewport_change()`；该入口可更新 candidate，但不能再次启动/emit lifetime。
7. Page 更新 surface transform 并呈现最终 frame；本 tick 最多一次 surface update。

普通 scrollbar/pan/zoom 若发生在非 layout gesture 中，只更新 cached selection/author projection transform，不调用 move/resize planner。

## 4. 明确删除/替换清单

执行 agent 必须在最终 diff 中逐项给出“已删除 / 保留原因”，不能只新增新类后留下旧路径：

| 当前机制 | 处理 |
|---|---|
| `FreeGridBoard._overlay = GhostOverlay(self)` | FreeGrid 迁移完成后删除；模板 `BoardGrid` 若需要可保留有限 overlay。 |
| FreeGrid `_raise_overlay()` 中同步 full-board geometry/raise | 删除；改由 Page 的 viewport overlay stack owner。 |
| `_paint_fingerprint_seen` 及散落 reset | 删除；由唯一 scheduler 的 `last_consumed_candidate_fingerprint`/frame generation 取代。 |
| `workspace_gesture_changed(bool, object)` | 拆分 lifetime 与 latest pointer 合同。 |
| `refresh_workspace_gesture()` 被每 tick 无条件调用 | 删除通用入口；改为仅 viewport transform 真实变化后的 `reproject_after_viewport_change()`。 |
| GhostOverlay same-signature `raise_(); update()` | FreeGrid 路径删除。新 surface 的 expose repaint 与 frame present 分离。 |
| FreeGrid `resizeEvent()` 把 overlay 扩为整个 workspace 并 `_reproject_live_preview()` | 删除；surface 跟 viewport resize，Board resize 不等于 candidate 变化。 |
| tests 对 `_ghosts/_highlights/_badge/_present` 的主要行为断言 | 迁移为 typed frame、surface pixels、submission/paint budget；仅 painter 单元测试可检查内部细节。 |
| drag-time card freeze/clear/opacity-effect 旧代码或死 helper | 若仍存在引用则删除；不得作为 fallback 恢复。 |
| FreeGrid full-board overlay 的 dirty-rect union/cache | 删除；新 surface bounded full repaint。模板 overlay 代码若保留须命名/测试隔离。 |

## 5. 分阶段实施

每阶段必须单独可 review、可回退；不得让多个 agent 同时编辑 `widgets.py/page.py/ghost_overlay.py`。如需多 agent，按阶段串行交接，测试 worker 可并行但不能改 owning files。

### P0 — 冻结失败、建立可测 observation seam

**Owned files**

- 新增 `tests/ui/test_ultraview_feedback_pipeline.py`（建议）
- 必要时只给现有类增加 read-only diagnostic counters/typed observation；不得在 P0 改行为
- `.state/ultraview-feedback-recovery-*` 保存本地 probe，默认不提交

**先写并证明为 RED**

1. `test_full_page_stationary_center_move_does_not_represent`
   - 完整 Page；pointer 在 edge band 外；一次 move 后等待 500 ms。
   - 当前预期失败：preview submission 持续增长。
   - 目标：初始 settle 后 0 次额外 planner/frame present。
2. `test_full_page_stationary_center_resize_does_not_represent`
   - 同上，覆盖 handle/badge。
3. `test_workspace_timer_uses_latest_pointer_not_first_pointer`
   - A 启动手势，B/C 连续移动；edge tick 只能使用 C。
4. `test_zero_edge_velocity_never_reprojects_gesture`
   - velocity 为零时 planner/present 调用数保持不变。
5. `test_feedback_surface_is_bounded_to_viewport`
   - 当前先以 failing contract 表达：FreeGrid feedback QWidget area 不得超过 viewport area。
6. `test_expose_repaints_cached_frame_without_replanning`
   - 人工 expose/show；允许 paint 增加，planner/frame generation 不变。
7. `test_stale_clear_cannot_hide_newer_gesture_frame`
   - gesture A deferred clear 到达时，gesture B frame 仍显示。

**基线记录**

- HEAD、`git status --short`、窗口/DPR、viewport/overlay geometry。
- move/resize 各 500 ms submissions/paint 数。
- 当前完整 Page screenshot 或连续帧采样；明确 offscreen 与 Cocoa 分类。

**出口**

- 上述 RED 的失败原因与 §1 一致；如发现 planner/candidate 自身错误，停止并修订本文，不把未知并入渲染重构。

### P1 — 修正 lifetime/latest pointer/edge-pan 调度

**Owned files**

- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- 必要的 `gesture.py` 小型 fingerprint DTO；保持 Qt-free
- `tests/ui/test_ultraview_feedback_pipeline.py`
- `tests/ui/test_ultraview_viewport.py`
- `tests/ui/test_ultraview_card_actions.py`

**任务**

1. 拆分 gesture lifetime 与 pointer update；每个 gesture 分配稳定 `gesture_id`。
2. Page pointer slot 只覆盖 latest point；不调用 Board、不 repaint。
3. pointer 每次变化后只根据 edge velocity start/stop edge timer；离开 band 立即 stop。
4. edge tick 仅在 transform 真实变化后 reproject。
5. 修复 candidate fingerprint：在 planner 前比较，布局 revision/modifier/operation/roles 进入 key。
6. release/cancel/destroy 停止 pointer coalescer 与 edge timer，flush/clear 按 gesture id 执行。
7. 删除 `_paint_fingerprint_seen` 死路径和相应 reset。

**P1 出口**

- 中心 hold 500 ms 的额外 planner/frame submissions 为 0。
- A→B→C 只消费 C；release commit 与最后显示 frame 一致。
- edge-pan 仍能在四边连续移动，且每个实际 scroll tick 最多一次 reproject。
- P1 尚未宣称 Cocoa ACCEPTED；旧 full-board overlay 仍可能有 expose 风险，P2 必须继续。

### P2 — 引入 viewport feedback frame/surface

**Owned files**

- 新增 `mf4_analyzer/ui/chart_stack/ultraview/viewport_feedback.py`（建议名）
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `mf4_analyzer/ui/chart_stack/ultraview/ghost_overlay.py`（只做兼容拆分/模板保留）
- 新增/更新 surface painter tests

**任务**

1. 定义 immutable frame、item role、generation 和 board-to-viewport transform。
2. surface parent 到 `BoardScrollArea.viewport()`；设置 mouse-transparent、透明背景、明确 focus policy。
3. 将 move/resize mover、displaced、collision、safety、origin wash、badge 和 handles 迁入 surface。
4. gesture start 一次建立 DPR-correct fast pixmap cache；同 ref/raw revision/DPR 复用，GUI thread 创建/销毁。
5. scroll/zoom/rebase 只更新 transform；expose/resize 只重画 cache，不 replan。
6. surface show 时一次性建立 stacking order；minimap/flyout 的相对层级和 active-editor exclusion rect 写入结构测试。
7. surface `present()` 丢弃旧 generation；`clear(gesture_id)` 不清更新 gesture。

**P2 出口**

- surface geometry 始终等于 viewport rect；elastic workspace 增长不改变 surface allocation。
- move/resize 蓝框在 synthetic full Page 的 0/100/500/2000 ms 图像中持续存在。
- expose、window cover/uncover、resize 后 frame 恢复，planner 调用数不增加。
- 旧 full-board overlay 不再承担 FreeGrid move/resize。

### P3 — 迁移全部 FreeGrid 瞬态 chrome，删除旧路径

**Owned files**

- `widgets.py`
- `page.py`
- `ghost_overlay.py`
- `author_layer.py`（只删除瞬态 selection/guide 重复职责；静态对象绘制保留）
- author/card hit-routing 与 toolbar contract tests

**任务**

1. 迁移 card selection handles、marquee、insert preview、replace ring、edge hint。
2. 迁移 author selection、move/resize target、draft bounds/guides；静态 author ink 继续由 `AuthorPaintLayer` 绘制。
3. active editor、Sticky editor 通过 exclusion rect 保持无遮挡和 IME/hit routing；format flyout、minimap 保持正确层级。
4. 删除 FreeGrid `_overlay`、`_raise_overlay()`、overlay geometry sync、same-signature workaround、旧 dirty union 和无引用 helper。
5. 模板 `BoardGrid` 若继续使用旧 class：重命名/注释/测试明确有限范围；禁止 FreeGrid 回接。
6. 把主要行为测试从私有 overlay 字段迁到 frame/surface/public observation。

**P3 出口**

- FreeGrid 瞬态反馈只有一个 frame source 和一个 viewport surface。
- `rg` 不再发现 FreeGrid 写 full-board GhostOverlay、`_paint_fingerprint_seen` 或无条件 `refresh_workspace_gesture`。
- click、selection、move、resize、marquee、insert、replace、author object handle 全部仍走原有 interaction owner/hit priority。

### P4 — Transaction、collision 和生命周期回归

**Owned files**

- 以测试为主；只有失败证明 owning module 缺口时才改产品代码

**必须覆盖**

- 单卡 move/8 向 resize/Shift aspect。
- 多选刚体 move；任一成员非法时全组不提交。
- 合法 avoidance：mover 蓝、每个 displaced 有图像和红边。
- collision reject、safety wall、search cap 三种角色不混色。
- edge pan 中 signed extent 左/上 rebase；frame 与最终 commit 同坐标。
- release flush、Esc cancel、Board/layout switch、window deactivate、destroyed。
- click selection 不白屏；chart 内容、author ink、preview overlay 无互相 punch-through。
- project/history：一次 gesture 恰好一条 undo；hover/frame/timer 不 dirty、不存盘。

**P4 出口**

- 所有用户事务和 state/history parity 通过；没有为了画面修复改变 layout plan 或项目 payload。

### P5 — Cocoa 帧验收与性能预算

**证据目录**

- `.state/ultraview-feedback-recovery-<HEAD>/`
- 若用户要求耐久报告，再写 `docs/analyzer/verify/`；默认不提交截图/运行产物

**环境记录**

- HEAD 与执行前后 dirty fingerprint。
- Mac 型号、macOS、Python、PyQt/Qt、DPR、窗口/viewport 尺寸、项目/Board/card 数。
- 真实 `./.venv/bin/python -m mf4_analyzer.app`，不得只用 offscreen harness。

**前台矩阵**

| ID | 场景 | 通过标准 |
|---|---|---|
| UV-FB-01 | 6 cards，move hold 2 s | 蓝 target frame 在 0/100/500/2000 ms 均存在；无 blank/whiteout/double image |
| UV-FB-02 | 6 cards，8 向 resize 各 2 s | 蓝框与 badge 全程存在；松手前后 geometry 一致 |
| UV-FB-03 | 24 cards，move/resize 撞开 3+ 邻卡 | mover 蓝、displaced 图像+红边连续；无持续 backlog |
| UV-FB-04 | pointer 停在 viewport 中央 2 s | 0 额外 planner/frame generation；surface 无 60 Hz 自激 repaint |
| UV-FB-05 | 四边 edge pan | timer 只在 band 内；target 跟最新 pointer；scroll 每 tick 最多一次 reproject |
| UV-FB-06 | cover/uncover、切应用、窗口 resize | cached frame 恢复；无 planner；无 chart 白屏 |
| UV-FB-07 | click→move→resize→collision→release soak 30 s | 无 cursor/timer/frame/cache 泄漏；无旧 frame 清新 frame |
| UV-FB-08 | author object 与 card 相邻/重叠 | handle hit priority 正确；feedback surface 不阻断鼠标；active editor 区域无遮挡且 IME 正常 |

**预算**

- 6-card DPR2：input-to-present p95 ≤16.7 ms，max ≤33 ms。
- 24-card DPR2 collision：p95 ≤33 ms，无持续 event backlog。
- 中央静止 500 ms：初始 settle 后 preview submissions = 0；不得再出现当前 34 submissions / 42 Paint 的自激模式。
- feedback surface allocation 不超过 viewport logical area；不得随 workspace extent 线性增长。
- Qt paint timing 不是 input-to-present；报告必须区分两类证据。

**P5 出口**

- 只有 UV-FB-01–08 和预算全部通过，状态才可写 `ACCEPTED ON macOS`。
- Windows frozen 若未跑，明确写 `WINDOWS UNVERIFIED`；不阻止 macOS bugfix commit，但阻止跨平台 release acceptance。

## 6. 自动化测试设计

### 6.1 测试层级

1. **Qt-free owner tests**：candidate fingerprint、latest sample、generation、stale clear、release flush。
2. **surface painter tests**：每个 role 的像素、badge、origin wash、selection/marquee、transform。
3. **完整 Page tests**：edge timer、scroll/extent、viewport geometry、stacking、destroy/reset。
4. **foreground Cocoa tests/probe**：持续帧、cover/uncover、DPR、实际 input-to-present。

不得用上一层替代下一层。

### 6.2 Focused commands

先跑 changed-owner tests：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_feedback_pipeline.py \
  tests/ui/test_ultraview_gesture_preview.py \
  tests/ui/test_ultraview_gesture_coalesce.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_viewport.py -q
```

再跑交互/author 邻接 gates：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_board_hit_routing.py \
  tests/ui/test_ultraview_selection_toolbar_contract.py \
  tests/ui/test_ultraview_author_tools.py \
  tests/ui/test_ultraview_author_integration.py \
  tests/ui/test_ultraview_placement_history.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_project_session.py -q
```

适用 boundary gates：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui_kit/test_qss_border_shorthand.py -q

git diff --check
```

本文是跨 Page/widgets/overlay/author-layer 的广泛 UI 边界重构，最终稳定集成 milestone 可由一个协调者运行一次 full gate。先检查同 checkout 是否已有 pytest；主 suite 与 `tests/acquisition_ui` 使用两个新鲜、串行进程，绝不并发。运行期间相关 source 改变则结果记 `UNVERIFIED`。

## 7. 执行与提交纪律

建议提交顺序：

1. `test(ultraview): freeze feedback repaint loop`
2. `fix(ultraview): separate edge pan from pointer presentation`
3. `refactor(ultraview): move feedback onto viewport surface`
4. `refactor(ultraview): retire free-grid full-board overlay`
5. `test(ultraview): close feedback lifecycle and Cocoa regressions`

规则：

- 每一提交只包含该阶段 owned files；保留当前无关 untracked/dirty 文件。
- P0 红测提交允许失败，但分支交给下一 agent 时必须明确；不要把 RED commit 合入主分支。
- 不在多个并行 worker 间拆 `page.py/widgets.py/ghost_overlay.py`；共享 worktree 下按阶段串行。
- 测试和 probe agent 可以并行，但只写独立新测试/`.state`，不得修改同一产品文件。
- 不改变 `APP_VERSION`，本计划不是 release bump。
- 若用户可见手势名称没有变化，不必改 hints/quickref；若执行中改变入口/文案，必须同步两者和 UltraView guide。

## 8. 回退与停止条件

- P1/P2 任一阶段失败，回退该阶段提交；不得恢复 full-board overlay 作为长期双路径 fallback。
- frame/surface 架构未完成前，不删除模板 overlay 或公开 import；先证明调用图。
- 若 bounded viewport surface 在 24-card Cocoa 中仍超预算，先用 trace 区分：ghost scale、underlying QWidget repaint、author layer、planner 或 scroll host；没有证据不调 alpha/timer。
- 去除重复 projection 后若主要瓶颈明确来自 24 个 QWidget/pyqtgraph snapshot 合成，停止本计划的局部调优，另立 QGraphicsView/scene rehost spec；不在本分支维护两套生产画布。
- 任意方案若要求持久化 frame/timer/viewport surface、扩大 MainWindow writes、改变 schema 或重新计算 View，立即停止并请求新的范围授权。

## 9. 完成定义

本文只有在以下全部成立时可标 `COMPLETE`：

1. FreeGrid 中 move/resize/selection/marquee/insert/replace/author transient chrome 只有一个 viewport feedback surface。
2. edge-pan 使用最新 pointer，只在 edge band 和真实 transform change 时 reproject。
3. candidate fingerprint 真正阻止相同 snapped candidate 的 planner/frame present；release flush 最后 sample。
4. FreeGrid full-board GhostOverlay、dead fingerprint、无条件 refresh 和 same-signature raise/update 路径已删除。
5. move/resize 蓝框与 badge 在真实 Cocoa 持续到 release；collision/displaced/safety 角色正确。
6. click、chart content、author layer、active editor 无 whiteout、punch-through、hit-routing 或 stacking 回归。
7. focused/boundary tests 通过；一次稳定 full gate 的证据等级清楚。
8. UV-FB-01–08、6/24-card 预算和 30 s soak 通过，证据记录 HEAD/worktree/environment。
9. 未运行的 Windows frozen gate明确标记，未用 offscreen/HTML/字段断言冒充前台完成。
