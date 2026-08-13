# UltraView P2 受控自由网格与单卡检查实施计划

- 日期：2026-08-13
- 状态：`P2-A Core IMPLEMENTED 2026-08-14；P2-B NO-GO（见 capability audit）；前景/Cocoa 与高级手势验收另行记录`
- 对应规格：
  `docs/analyzer/specs/2026-08-13-ultraview-p2-flex-grid-and-inspection-spec.md`
- 上游 P1：
  `docs/analyzer/specs/2026-08-13-ultraview-p1-scalable-board-workspace-spec.md`
- 建议分支：`feat/ultraview-p2-flex-grid-inspection`
- 基线：必须是通过 P1 verification 的 HEAD；不得以当前 P0/P1 草稿快照直接执行

## Claude 评审结论（2026-08-13）

分级判定：**P2-A Layout：GO（按下列修订）**；**P2-B Inspection：条件 GO**——维持
Task 6 section capability audit 为硬闸，line/heatmap/FRF 任一 NO-GO 则 P2-B 范围回
owner 评审，不得用 active canvas 截图伪实现。整数网格 + 碰撞即拒绝 + 一次一张 live
的三条边界判断正确，24 widget 先测量再虚拟化的路线合理。

评审并入的修订（正文各 Task 已同步）：

1. **GridMetrics 合同前置（Task 2）**：`2×2` 最小 span 与 P1 最低可读尺寸
   （约 300×180）在 1280×800 下矛盾——12 列扣除 padding/gutter 后单列约 93px，
   2 列 span 仅约 198px 宽。必须先冻结：最小列宽、水平滚动出现的 viewport 阈值、
   2 span 卡是否豁免 300px 契约（建议豁免并定位为「缩略图」角色，另设不低于
   chrome 可读性的绝对下限），同步回写 spec §4.2/§8.1 后再冻结 property tests。
2. **分页导出硬合同（Task 5）**：page break 只落在行边界之外，单页高度必须
   ≥ 最大 row_span（8 行）对应像素，否则最高卡片放不进任何页；页向垂直堆叠的
   语义在 spec §14 中写明（原文「水平分页/水平分割」指水平切线，措辞需消歧）。
3. **重开项目场景入 capability 矩阵（Task 6）**：零计算恢复下所有分析 cache 为空
   （`_analysis_restore_pending` 满载），P2-B 将大面积禁用直到用户回源渲染；矩阵、
   UX 文案与验收必须覆盖该状态，不得只测 cache 命中的理想路径。
4. **undo stack 与 Board 生命周期（Task 3）**：删除 Board 丢弃其 stack、duplicate
   从空 stack 开始，作为显式契约测试而非实现巧合。

## 0. 目标、执行策略和禁止事项

本计划分两个连续里程碑：

- **P2-A Layout**：schema 3、12列自由网格、24卡、move/resize/undo/minimap/paged export；
- **P2-B Inspection**：InspectionDocument、一次一个live canvas、只读pan/zoom/cursor和guide。

P2-A必须先独立完成并验证，再开始P2-B。Inspection涉及renderer/lifecycle，不与geometry
大改放在同一提交或同一RED/GREEN循环。

禁止：

- 未完成P1就同时开发schema 2和3；
- 把现有source QWidget reparent到UltraView；
- 调用 `_render_analysis_view_from_cache()`、`do_*` 或项目恢复重算；
- 用active canvas代替目标ref；
- 把inspection局部range写回canonical PreviewRecord；
- 在没有Cocoa数据前先做复杂card virtualization；
- 以固定pass count、partial full suite或offscreen截图声称发布完成；
- stage/覆盖并行dirty work。

## 1. 实施依赖

```text
Task 0 P1 gate和baseline
  ↓
Task 1 schema3 + Qt-free GridRect/legalization
  ↓
Task 2 geometry/conversion/collision/commands
  ↓
Task 3 screen free-grid gestures + keyboard + undo
  ↓
Task 4 minimap/overview/residency/24-card performance
  ↓
Task 5 dynamic/paged compositor + project round-trip
  ↓
Milestone P2-A acceptance
  ↓
Task 6 InspectionDocument seam和section capability audit
  ↓
Task 7 single InspectionSession lifecycle
  ↓
Task 8 pan/zoom/cursor + compatible-axis guides
  ↓
Task 9 zero-compute/performance/lifecycle hardening
  ↓
Task 10 help/full-suite/Cocoa/Windows verification
```

## Task 0 — P1 GO gate、当前证据与scope

**读取**

- P1 spec/plan/verification全文；
- current UltraView state/layout/store/sidecar/page/coordinator/tests；
- `git status --short --branch` / `git log` / `git diff`；
- relevant lessons：plan/spec evidence、Qt lifecycle、render screenshots、full UI gate。

**步骤**

1. P1 UV-P1-A01～A20必须有当前映射；Task E状态可以deferred，但inspection所需document来源
   必须在Task 6重新判断。
2. 运行P1 focused baseline、sidecar hostile-input、lifecycle subprocess、zero-compute、12-card
   benchmark smoke；记录真实结果。
3. 创建P2 branch/worktree；登记所有pre-existing dirty paths并保护。
4. 保存P1 accepted 12-card screenshot/geometry/performance JSON，供P2相对回退比较。
5. 若P1 full suite/Cocoa未完成，停止为`BLOCKED BY P1`。

**Exit gate**：P1真实GO；P2有独立branch、baseline和证据目录。

**建议提交**：无。

## Task 1 — Nested schema 3、GridRect 与非法payload恢复

**修改**

- `mf4_analyzer/ui/ultraview_state.py`
- `tests/ui/test_ultraview_workspace_state.py`
- `tests/test_project_io.py`

**可新增**

- `mf4_analyzer/ui/ultraview_grid_state.py`
- `tests/ui/test_ultraview_grid_state.py`

**RED**

1. `GridRect`/`FreeGridPlacement`不可变identity和bounds：12列、48行、span 2..12/2..8。
2. `layout_mode` template/free_grid互斥；writer不同时写active template/free placements。
3. schema2所有Boards迁移schema3 template mode，字段/sidecar/refs不变。
4. schema3 free grid round-trip；不同window size/DPR不改变geometry。
5. property/参数测试：
   - negative/NaN/string/huge values；
   - overlap、duplicate ref、超过24、越界；
   - 冲突ref和超限ref稳定进tray；
   - 任何合法ref不丢；warnings有稳定codes。
6. normalize幂等：`normalize(serialize(normalize(payload)))`稳定。
7. Qt-free subprocess import不加载`mf4_analyzer.ui` heavyweight/Qt widget/MainWindow。

**GREEN**

1. 若`ultraview_state.py`职责过大，将grid DTO/legalization放Qt-free
   `ultraview_grid_state.py`，state只聚合；不要把实现塞进chart-stack facade。
2. 使用整数coercion且拒绝bool/非finite；不要用宽泛`int(value)`静默截断浮点用户数据。
3. overlap legalize按payload顺序首个wins；其余membership进tray并warning。
4. UI add第25张进tray；loader也不创建第25个placed card。

**验证**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_grid_state.py \
  tests/ui/test_ultraview_workspace_state.py \
  tests/ui/test_ultraview_state.py \
  tests/test_project_io.py
```

**Exit gate**：UV-P2-A01/A02/A09。

**建议提交**：`feat(ui): add UltraView free-grid project state`

## Task 2 — 纯几何、转换、碰撞与command模型

**新增**

- `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- `tests/ui/test_ultraview_free_grid.py`

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/layouts.py`
- `tests/ui/test_ultraview_layouts.py`

**前置（评审修订 1）**

先冻结 GridMetrics 合同并回写 spec §4.2/§8.1：最小列宽、行高 target、2 span 卡的
可读性豁免边界（1280×800 下 12 列单列约 93px，2 span 约 198px，低于 P1 的 300px
最低阅读宽度）、以及水平滚动出现的 viewport 阈值。合同未冻结前不得写 property tests。

**RED**

1. `GridMetrics`在1280/1600/DPR独立logical坐标下生成stable cell/gutter/board size。
2. 所有legal GridRect映射pixel rect互不越界；hit-test逆映射在边界/gutter确定。
3. 2/4/6/9/12 template→free map无重叠、顺序稳定、相对位置符合spec。
4. free→template `(row,column,ref)`排序、overflow tray、预览结果不mutate原Board。
5. move/resize候选：bounds、min/max、collision；invalid不产生after state。
6. same-size swap只有双方交换后合法才成功。
7. organize只上移空行，保持column/span和relative row order；重复调用幂等。
8. command before/after/merge/undo/redo只含Qt-freegeometry，不持有widget/image。
9. randomized/property sequences：1000次move/resize/undo后无overlap、bounds合法、round-trip回初态。

**GREEN**

1. 将所有mutation实现为pure candidate/command函数，widget只消费结果。
2. 使用spatial occupancy grid（12×48 bool/ref）检查碰撞，不需要复杂scene索引。
3. conversion map作为测试冻结的常量/函数，不从当前pixel geometry反推。
4. command stack可以用`QUndoStack` presentation wrapper，但command payload/behavior必须Qt-free可测；
   不允许QUndoCommand持有Page/coordinator强引用导致teardown cycle。

**Exit gate**：UV-P2-A03/A05/A06/A07中的纯geometry部分。

**建议提交**：`feat(ui): define deterministic UltraView free-grid geometry`

## Task 3 — FreeGridBoard屏幕、拖动/Resize与键盘

**新增**

- `tests/ui/test_ultraview_free_grid_widget.py`

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_ultraview_page.py`

**RED**

1. template/free mode切换UI有确认/取消/undo，Page发typed intent不直接改state。
2. mouse gesture状态：press未过threshold无drag；ghost move/resize；valid release一次commit；invalid
   release/cancel/Esc/Board switch/window close零commit。
3. drag ghost只更新overlay geometry，不触发全部cards smooth image scale；instrumentation断言。
4. resize handle hit regions四边/四角符合platform pointer和最小touch target；cursor正确。
5. keyboard move/resize/preset与mouse产生相同command；shortcut conflict test覆盖现有app actions。
6. focus/accessibility：row-major spatial navigation、announce rect、invalid不只红色。
7. undo/redo每Board隔离；project reset清；toolwindow close可清stack但保持committed state；
   删除 Board 丢弃其 stack，duplicate Board 从空 stack 开始（显式契约测试）。
8. QSS/paint：ghost/handle/invalid/selected在DPR1/2无backing rectangle/裁切；用真实render pixels验证。

**GREEN**

1. 新`FreeGridBoard`可与现`BoardGrid`组合或替换，但Card widget继续复用，不复制card行为。
2. 使用`QApplication.startDragDistance()`；不要写死鼠标像素阈值。
3. gesture controller持有weak widget handles/generation；不把Page存进long-lived command。
4. commit后只重排受影响cards；quiet settle才平滑rescale。
5. page `reset_sheet_session()`取消ghost/gesture/undo transient，保持BoardState。

**视觉矩阵**

- 1280×800 / 1600×900；DPR1/2；1/12/24 cards；
- normal/selected/hover/drag valid/drag invalid/resize；
- 标题/来源on/off、四态、scroll四角、tray；
- 自动contact sheet + geometry JSON，之后Cocoa前景鼠标/trackpad。

**Exit gate**：UV-P2-A04/A05/A06/A07。

**建议提交**：`feat(ui): edit UltraView card position and size on a grid`

## Task 4 — Minimap、Overview、Residency与24卡性能

**新增**

- `mf4_analyzer/ui/chart_stack/ultraview/minimap.py`
- `tests/ui/test_ultraview_minimap.py`
- `tools/benchmark_ultraview_free_grid.py`

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/preview_store.py`
- `tests/ui/test_ultraview_preview_store.py`
- `tests/ui/test_ultraview_probes.py`

**RED**

1. minimap只画bounds/status/viewport，不读/复制QImage；24cards image count不增加。
2. minimap click/drag/keyboard将viewport clamp到Board；不改变geometry/source。
3. overview完整24图点击定位；切回时card visible/focused。
4. residency target：viewport cards中分辨率，focus/export高，screen-off低/可evict；scroll后更新。
5. scroll burst期间屏外cards不smooth scale；settle后新visible cards更新一次。
6. 24 Card widgets baseline instrumentation：widget/image/RSS/scroll/resize p95/max。
7. 只有benchmark超过门禁才启用recycling feature flag并写补充spec/test；默认实现不先虚拟化。

**GREEN**

1. Minimap是小型custom widget，输入immutable rect/status projection；不连接每Card signal。
2. viewport change经过节流/coalescing更新residency和minimap。
3. activeBoard 24 refs在budget内按actual target size降级；inspection future scope预留temporary tier但
   此Task不创建canvas。
4. benchmark运行三轮，保存raw JSON/environment，不挑最好结果。

**Exit gate**：UV-P2-A08/A17 layout half；若未达到性能目标，有明确profile/decision，不隐藏。

**建议提交**：`perf(ui): navigate and budget twenty-four card UltraView boards`

## Task 5 — Schema3项目接线、动态/分页导出与P2-A验收

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/compositor.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `tests/ui/test_ultraview_export.py`
- `tests/ui/test_ultraview_project_session.py`
- `tests/ui/test_ultraview_job_isolation.py`

**RED**

1. schema3 free grid save/open/Save As；sidecar format/ref共享不因geometry复制。
2. 24-card compositor screen同geometry、完整logical height、尾空裁剪、不含handles/minimap/guides。
3. max edge/pixels前置检查；1×/2×超过限制给scale-down或paged choice，不危险allocate。
4. paged PNG按行边界分页（页向垂直堆叠、水平切线）、卡片不被页边切开；必要时调整
   page break到card boundary；单页高度必须 ≥ 最大 row_span（8 行）对应像素高度，
   否则最高卡片放不进任何页；文件名`-01`顺序、失败cleanup/partial reporting正确。
5. clipboard超限提示export，不静默缩小；普通Board clipboard保持。
6. P2-A完整layout操作链零compute/cache write/restore/source mutation。
7. project快速切换/close时gesture/undo/minimap callbacks取消；lifecycle subprocess exit0。

**GREEN**

1. compositor扩展free-grid projection，不从screen widget grab。
2. 分页planner是pure geometry，先返回pages/card mapping再allocate/draw。
3. project codec只保存committed state；gesture/undo/minimap/scroll不进JSON。
4. zero-compute probe扩展而不替换P1三层探针。

**Milestone P2-A gate**

- UV-P2-A01～A09/A15 layout部分/A16 layout链PASS；
- focused tests、lifecycle、P1 regressions、Cocoa24图layout矩阵通过；
- 未达到则不进入Task 6。

**建议提交**：`feat(project): persist and export UltraView free-grid boards`

## Task 6 — Inspection capability audit与InspectionDocument seam

**先写评审产物**

- `docs/analyzer/reviews/2026-08-13-ultraview-inspection-render-seam-review.md`

**可能新增**

- `mf4_analyzer/ui/chart_stack/ultraview/inspection_documents.py`
- `tests/ui/test_ultraview_inspection_documents.py`

**读取/核对**

- time canvas当前render model/build result与数据ownership；
- FFT entries/result/presenter；
- FFT-Time/Order heatmap result与presenter；
- FRF result/display context；
- P1-E是否实施；
- pg_canvas public presenter/backref/import boundaries。

**必须先给section矩阵**

| Section | 精确ref结果来源 | 可复用presenter | 需不需要源data load | 零计算可行 | P2状态 |
|---|---|---|---|---|---|
| time | 实查 | 实查 | 实查 | GO/NO-GO | enabled/disabled |
| fft | 实查 | 实查 | no才可GO | GO/NO-GO | ... |
| fft_time | 实查 | 实查 | no才可GO | GO/NO-GO | ... |
| frf | 实查 | 实查 | no才可GO | GO/NO-GO | ... |
| order | 实查 | 实查 | no才可GO | GO/NO-GO | ... |

不能从”当前有preview”推断”当前有render-ready result”。至少line、heatmap、FRF三类必须GO，
否则P2-B产品范围需回到Claude/owner评审，不能用active canvas截图伪实现。

矩阵必须单列一档「项目重开后（零计算恢复、cache 为空、`_analysis_restore_pending`
满载）」：此时五个 section 的 document 预计全部 unavailable，inspection 大面积禁用
直到用户回源渲染。该状态的 UX 文案、帮助与验收都要覆盖，不得只测 cache 命中的
理想路径。

**RED**

1. `InspectionDocument` immutable/Qt-neutral，stable ref、axis/meta、result/model、display context。
2. 每section adapter只接受精确ref state/pins/cache/binding；active B不污染A。
3. restore pending/cache miss/source reload需要时返回structured unavailable，不调用任何render/compute。
4. document generation/digest绑定；source变化后旧document invalid。
5. import boundary：document DTO不importMainWindow/QWidget；adapter放owner侧lazy import。

**Exit gate**：UV-P2-A10设计证据；section capability矩阵经评审GO。

**建议提交**：`refactor(ui): define read-only UltraView inspection documents`

## Task 7 — Single InspectionSession生命周期与三类canvas

**新增**

- `mf4_analyzer/ui/chart_stack/ultraview/inspection.py`
- `tests/ui/test_ultraview_inspection.py`
- `tests/ui/test_ultraview_inspection_lifecycle_subprocess.py`

**修改（按adapter owner）**

- line/heatmap/FRF presenter/canvas owner files，仅增加明确read-only render seam
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`

**RED**

1. document unavailable时“交互检查”禁用且reason可见；QImage focus仍可用。
2. 打开A创建一session；打开B严格close A（stop timer/disconnect/remove/delete/drain）后create B；
   live canvas count始终≤1。
3. Board切换、tool close、project reset/open、source delete/digest invalid、MainWindow shutdown关闭session。
4. queued callback带session generation；旧session late signal不触及new canvas/page。
5. line、heatmap、FRF真实result fixture首帧有ink/axis/title，且不需要source load/compute。
6. 反复100次三类open/switch/close子进程exit0；sip deleted wrapper不复用。
7. InspectionController/Page之间signal receiver count稳定，reset后不重复连接。

**GREEN**

1. Controller拥有session/canvas/overlay host；Page只发open/close intent。
2. Canvas在GUI thread创建paint，关闭顺序：stop interactions/timers→disconnect→remove host→deleteLater；
   tests显式drain deferred delete。
3. 不缓存五张隐藏canvas；若复用同类型单canvas，复用前`sip.isdeleted`+完整reset，并用测试证明
   无旧result/cursor/range泄漏；简单安全优先于微优化。
4. Presenter seam不得duplicate numerical algorithm，unexpected exceptions传播到observable error。

**Exit gate**：UV-P2-A10/A11/A13和lifecycle基础。

**建议提交**：`feat(ui): add single-card UltraView inspection sessions`

## Task 8 — Pan/Zoom/Cursor与兼容轴guide

**新增/修改**

- `mf4_analyzer/ui/chart_stack/ultraview/inspection.py`
- 可新增 `mf4_analyzer/ui/chart_stack/ultraview/guides.py`
- preview meta/sidecar manifest版本化字段
- `tests/ui/test_ultraview_inspection.py`
- `tests/ui/test_ultraview_guides.py`
- `tests/ui/test_ultraview_preview_sidecar.py`

**RED**

1. inspection允许pan/zoom/Home/single cursor；禁用参数/markup/pane/filter/source controls。
2. interaction前后source ViewState/PaneState/ranges/active/markup/cache/canonical preview完全相等。
3. close inspection不publish canonical PreviewRecord；可复制临时检查图且文案/metadata区分。
4. PreviewMeta plot content rect/linear transform来自renderer事实，round-trip sidecar；缺失安全禁guide。
5. axis compatibility矩阵：kind/unit/finite range/transform全满足才guide；Hz/rpm/time/order/unknown不误连。
6. cursor X→target normalized pixel映射正确，超range提示；heatmap只X，不Y/color。
7. static card guide overlay不修改QImage、不创建canvas、不拦截drag/drop/card click。
8. cursor high-rate更新节流；20 compatible cards不产生signal/log storm。
9. source digest变化立即close/invalidate session与guide。

**GREEN**

1. Guides输入immutable facts+cursor/range，使用lightweight overlay painter；不连接每Card到source canvas。
2. canonical unit compare使用既有规范字段；不自己写字符串模糊换算。
3. plot rect由canvas renderer暴露的read-onlygeometry snapshot提供；无法证明则disabled。
4. temporary inspection copy直接grab/render inspection canvas，但不调用PreviewStore.publish/sidecar。

**Exit gate**：UV-P2-A12/A14。

**建议提交**：`feat(ui): guide compatible UltraView previews from one inspection`

## Task 9 — P2完整零计算、性能与生命周期加固

**修改**

- `tests/ui/test_ultraview_job_isolation.py`
- `tests/ui/test_ultraview_lifecycle_subprocess.py`
- `tests/ui/test_ultraview_probes.py`
- benchmarks/evidence scripts

**步骤**

1. 实现spec §12完整P2链，断言三层compute/cache write=0，restore/source/canonical preview不变。
2. 三轮Cocoa：24 cards scroll/resize/commit/undo/minimap/overview/export；line/heatmap/FRF
   inspection open/first paint/pan/zoom/cursor/close。
3. 记录callback/paint分离p50/p95/max/raw、RSS、image/widget/live canvas count、stall。
4. 与P1 accepted baseline同机器/DPR/尺寸比较；>20%回退或>500ms stall FAIL并profile。
5. 反复Board/tool/project/source lifecycle，晚到callback/Qt wrapper/receiver count探针。
6. 只有证据表明24 widgets导致门禁失败，才暂停、写virtualization补充spec并实施；不得悄悄
   在本Task大重构。
7. run import boundaries、pg backref invariants、main window state ownership，不能放宽白名单。

**Exit gate**：UV-P2-A16/A17/A19；所有process有exit code，partial output不是PASS。

**建议提交**：`test(ui): harden UltraView free-grid and inspection performance`

## Task 10 — 帮助、全套回归与平台验收

**修改**

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- UltraView help guide/screenshots/tests
- 新verification：
  `docs/analyzer/verify/2026-08-13-ultraview-p2-verification.md`

**步骤**

1. 帮助准确写12列/48行/24卡、无重叠、移动/resize/undo、minimap、一次一张inspection、
   zero-compute、不可用reason、guide兼容、inspection不回写源。
2. shortcut在macOS/Windows keymap与现有action冲突测试后再定稿。
3. 视觉矩阵自动化 + Cocoa：
   - template/free conversion；
   - 12/24 cards、各种size preset、invalid ghost、handles；
   - minimap/overview/paged PNG；
   - line/heatmap/FRF inspection/cursor/guides/unavailable；
   - Board switch/tool close/MainWindow分析交互同时存在。
4. 两个新进程full suites：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/acquisition_ui
```

5. Windows Full/Lite frozen运行free grid、inspection、PNG/clipboard/lifecycle；未执行写UNVERIFIED。
6. `git diff --check`、lesson status、staged scope、verification A01～A20逐项映射。

**Exit gate**：UV-P2-A18/A19/A20；Cocoa前景完成，Windows证据等级诚实。

**建议提交**：`docs(ui): close UltraView P2 acceptance`

## 2. 建议提交序列

### P2-A Layout

1. `feat(ui): add UltraView free-grid project state`
2. `feat(ui): define deterministic UltraView free-grid geometry`
3. `feat(ui): edit UltraView card position and size on a grid`
4. `perf(ui): navigate and budget twenty-four card UltraView boards`
5. `feat(project): persist and export UltraView free-grid boards`

### P2-B Inspection

6. `refactor(ui): define read-only UltraView inspection documents`
7. `feat(ui): add single-card UltraView inspection sessions`
8. `feat(ui): guide compatible UltraView previews from one inspection`
9. `test(ui): harden UltraView free-grid and inspection performance`
10. `docs(ui): close UltraView P2 acceptance`

每个提交前运行owner focused tests和`git diff --cached --check`；P2-A/P2-B之间必须有独立
milestone verification，便于review/revert，不做一个超大提交。

## 3. 最终 Done Checklist

- [ ] P1 verification真实GO；
- [ ] schema2→3 migration和GridRect legalize/property tests PASS；
- [ ] template↔free、collision、move/resize、undo/redo/organize PASS；
- [ ] 24-card screen/minimap/overview/residency/benchmark PASS；
- [ ] dynamic/paged PNG和clipboard limit PASS；
- [ ] P2-A milestone Cocoa和zero-compute PASS；
- [ ] section capability audit完成，line/heatmap/FRF render seam为GO；
- [ ] single InspectionSession lifecycle subprocess PASS；
- [ ] pan/zoom/cursor不写source/canonical preview；
- [ ] compatible-axis guide metadata/mapping/degradation PASS；
- [ ] 完整P2三层zero-compute、restore/source snapshot不变；
- [ ] performance三轮raw JSON、相对回退和stall门禁完成；
- [ ] architecture/state ownership/backref/import gates不放宽；
- [ ] hints/quickref/help/shortcut/accessibility同步；
- [ ] main suite和acquisition_ui两个新进程正常结束；
- [ ] Cocoa前景PASS；Windows Full/Lite未跑则UNVERIFIED；
- [ ] verification映射UV-P2-A01～A20；
- [ ] commits/stage不含任何并行dirty work。

## 4. 验收 ID → 实施任务映射

| 验收 ID | 主要任务 |
|---|---|
| UV-P2-A01 | Task 1、Task 5 |
| UV-P2-A02 | Task 1、Task 2 |
| UV-P2-A03 | Task 2、Task 3 |
| UV-P2-A04 | Task 3 |
| UV-P2-A05 | Task 2、Task 3 |
| UV-P2-A06 | Task 2、Task 3 |
| UV-P2-A07 | Task 2、Task 3、Task 5 |
| UV-P2-A08 | Task 4 |
| UV-P2-A09 | Task 1、Task 5 |
| UV-P2-A10 | Task 6、Task 7 |
| UV-P2-A11 | Task 7、Task 9 |
| UV-P2-A12 | Task 8、Task 9 |
| UV-P2-A13 | Task 7、Task 8 |
| UV-P2-A14 | Task 8 |
| UV-P2-A15 | Task 5 |
| UV-P2-A16 | Task 5、Task 9 |
| UV-P2-A17 | Task 4、Task 9 |
| UV-P2-A18 | Task 3、Task 10 |
| UV-P2-A19 | Task 7、Task 9、Task 10 |
| UV-P2-A20 | Task 10 |
