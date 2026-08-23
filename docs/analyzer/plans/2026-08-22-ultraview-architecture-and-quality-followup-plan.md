# UltraView 架构与质量后续优化 Plan

- 初始日期：2026-08-22
- Review 更新：2026-08-23
- 状态：**ARCHITECTURE FOLLOW-UP IMPLEMENTED / AUTOMATED GATES GREEN / OWNER STATE SEAM CLOSED / METHOD FACADE PARTIAL / AUTHOR-CHROME BACKLOG OPEN / COCOA UNVERIFIED / NOT PUBLISHED**
- 本地合并基线：`2feddfa17e2494d2551b6dd755aa5240e64c36da`
- 分支状态：本 Plan 所在提交为当前本地候选；`codex/ultraview-post-hardening-architecture` 保留在合并基线 `2feddfa1`。本地 `main` 尚未 push，ahead 数以实时 `git status` 为准
- 提交范围：本 Plan、两个新增 protocol/lifecycle tests 与对应产品源码；验证结束后另出现的并发 author-chrome 产品 Plan、`ssh-keygen`、`ssh-keygen.pub` 均排除
- 上游 Hardening Plan：`docs/analyzer/plans/2026-08-22-ultraview-stability-and-quality-hardening-plan.md`
- 上游架构 Spec：`docs/analyzer/specs/2026-08-22-ultraview-post-hardening-architecture-optimization-spec.md`
- 上游架构 Plan：`docs/analyzer/plans/2026-08-22-ultraview-post-hardening-architecture-optimization-plan.md`
- 独立产品缺陷 Plan：`docs/analyzer/plans/2026-08-23-ultraview-author-chrome-product-fixes-plan.md`（并发产物，`RECORDED / NOT STARTED`）
- 本文件定位：合并后代码、Review 与验证结果的后续执行 source of truth；历史 Plan/Spec 保留历史状态，不倒写为当前验收结论

## 0. 最终 Review 裁决

### 0.1 结论

本轮架构优化已经在本地 `main` 合并，核心拆分不再处于 WIP：Capture owner、Workspace owner、Qt-free core、state/widgets façade、Page/FreeGrid controllers 与 `free_grid ↔ card_fit` 解环均已落地。

2026-08-23 的第二次 review 找出的残留问题也已直接修复：SearchField guard、mixed transaction 原子性、visual verifier 假绿、resize 后 popup 锚定与内容可达性、Page private access、Capture private facts probe、Coordinator 对 owner 私有容器的读取，以及生命周期/规模计数门均已闭环。

仍不能把 UltraView 写成“全面完成”，剩余边界分为四类：

1. `UltraViewCoordinator` 仍有 60 个 Capture、73 个 Workspace 私有方法调用点；它们是 compatibility method seam，不再泄漏 owner 私有可写容器，但还不是最终窄 façade；
2. 当前候选尚缺真实 macOS Cocoa 前台手势/像素/IME/z-order 证据，以及稳定候选上的 p50/p95/RSS 观测；
3. 并发生成的 author-chrome 产品 Plan 新记录了色板/菜单、死入口、作者 resize 光标、Laser 外观与布局裁切等缺陷，状态明确为 `NOT STARTED`；它不是本轮架构修复的完成证据；
4. 本地工作未 push，Windows Full/Lite frozen 仍未验证；这两项与已经全绿的本地自动化 gate 不能混为一谈。

因此当前裁决是：**本轮架构 follow-up 与自动化闭环已完成，owner 状态边界已稳定；method façade、author-chrome 产品 backlog、真实平台和发布状态保持 PARTIAL / OPEN / UNVERIFIED。**

### 0.2 合并后成果矩阵

| 范围 | 当前事实 | 裁决 |
|---|---|---|
| `chrome.py` / `widgets.py` family 拆分 | `widgets.py` 已为 77 行 re-export façade，`WAVE1_FACADE_ACTIVE=True` | DONE |
| `ui.ultraview_state` façade | 已缩为 221 行 compatibility façade | DONE |
| Qt-free core | `model/board_ops/author_ops/serialization/grid_geometry/presentation` 已落地，import probe 未加载 Qt | DONE |
| `free_grid ↔ card_fit` cycle | 两者共同依赖 `ultraview_core.grid_geometry`，SCC 已消失 | DONE |
| Workspace mutable-state owner | `UltraViewWorkspaceController` 为单一 owner；aggregator 经 public compatibility views 读取 | DONE |
| Capture mutable-state owner | `UltraViewCaptureCoordinator` 单一拥有 Store/queue/timers/runtime；公开 frozen counts 与 pending query | DONE |
| Page controllers | projection、floating chrome、viewport、context、author UI、wiring 已拆出；AST 禁止 private collaborator access | DONE |
| FreeGrid controllers | feedback、pointer、author owner 已拆出 | DONE（Cocoa gesture 仍未验收） |
| PointerRouter seam | literal public allowlist / explicit Page methods，已移除反射式 `setattr` 扩张 | DONE |
| Visual verifier | schema v2、stage containment、trigger anchor、负向离屏/脱锚 tests | DONE（offscreen evidence） |
| Popup resize | open transient 重锚；高度不足时启用垂直滚动，底部控件可达 | DONE（offscreen evidence） |
| Author-chrome 产品缺陷 | 独立 Plan 记录色板/菜单/死入口/resize cursor/Laser/layout clipping | OPEN / NOT STARTED |
| Coordinator owner state seam | 不再读取 `_queued/_store/_runtime/...` 或 Workspace 私有容器 | DONE |
| Coordinator method seam | 60 Capture + 73 Workspace private command calls | PARTIAL |
| 集中 UltraView gate | 1440 passed / 1 skipped / 193 warnings | GREEN（offscreen） |
| 主 full suite | 8143 passed / 14 skipped / 3 deselected / 2544 warnings | GREEN |
| acquisition suite | 359 passed / 4 warnings | GREEN |
| 真实 Cocoa / Windows frozen | 当前合并 HEAD 无正式证据 | UNVERIFIED |
| 远端发布 | 本地候选未 push；ahead 数以实时 `git status` 为准 | NOT PUBLISHED |

### 0.3 当前验证证据

以下最终结果均在 `HEAD=2feddfa17e2494d2551b6dd755aa5240e64c36da` 加当前 working tree 上取得。测试前后 tracked diff fingerprint 均为 `714fa1ef950c45592c78067a1c252e0c86579fed15f0e2a5a948e9e77405f99d`；两个新增测试文件 hash 也保持不变：lifecycle `5814c50a...`、page protocol `95a7d9aa...`。因此这些结果可作为当前候选的自动化验收证据。

#### Capture focused/boundary

覆盖 capture、facts、PreviewStore、sidecar、project session、lifecycle、job isolation、state ownership 与 import boundary。

```text
review-fix owner set: 198 passed, 56 warnings in 25.93s
lifecycle + stationary hold ratchet: 10 passed in 6.15s
```

#### UltraView concentrated gate

覆盖 `tests/ui/test_ultraview_*.py`、UltraView style、visual verifier、import/state ownership、no-lambda、QSS border/selector gates。

```text
1440 passed, 1 skipped, 193 warnings in 180.08s
```

这证明当前稳定快照的 focused/offscreen/boundary 行为，但不证明真实 Cocoa 像素和前台交互。

#### Full non-acquisition suite

```text
8143 passed, 14 skipped, 3 deselected, 2544 warnings in 1271.73s
```

#### Acquisition suite

```text
359 passed, 4 warnings in 9.04s
```

#### 静态结构

```text
ultraview/page.py                         4239 lines
ui/main_window/ultraview_coordinator.py  1507 lines
ui/chart_stack/ultraview/widgets.py        77 lines
ui/ultraview_state.py                     221 lines
```

Qt-free core AST import graph 无 cycle，subprocess import 后 `qt_loaded=[]`。`git diff --check` 对 tracked source 通过。

行数只用于定位审查热点，不作为继续拆分或验收通过的单独理由。

## 1. Severity-ranked findings（2026-08-23 复审后）

| Finding | 严重度 | 当前状态 | 关闭证据 / 剩余风险 |
|---|---:|---|---|
| F1 SearchField guard 指向旧 façade | P1 | CLOSED | inventory 已指向 `library_widgets.py`；focused gate 覆盖真实 owner |
| F2 mixed missing/unplaced/stale/locked/unknown target 部分提交 | P1 | CLOSED | pure plan 整体 reject；Board/author/connector/history/dirty 不变 tests |
| F3 visual verifier 对离屏目标假绿 | P1 | CLOSED | stage containment、required chrome、trigger anchor 均 fail closed；负向 tests |
| F4 resize 后 transient 脱锚或底部控件裁切 | P2 | CLOSED | live reanchor；popup 高度不足时滚动开启；closed 不复活 |
| F5 Page/controller private access 与 PointerRouter 反射扩张 | P2 | CLOSED | explicit commands + shrink-only AST protocol gate |
| F6 Coordinator aggregator seam | P2 | PARTIAL | private mutable-state read 已清零；仍有 60/73 个 private method delegates，按 owner family 逐步迁移 |
| F7 Capture facts private widget probe | P2 | CLOSED | frozen facts 含 markup/pill；chart stack 提供 public adapter；guard 扩大 |
| F8 生命周期与规模回归证据过浅 | P2 | AUTOMATED CLOSED / PLATFORM OPEN | 12/24 refs、20×60 residency、500/2000 ms hold、capture reset/shutdown counts 已覆盖；Cocoa p50/p95/RSS 仍待测 |
| F9 文档、local merge、publish 与平台状态混淆 | P2 | CLOSED FOR DOC / PUBLISH OPEN | 本 Plan 为 current truth；历史文档仅 addendum；push 仍需独立授权 |

复审没有发现新的 P0/P1 未关闭项。当前最高风险是 P2 平台证据与长期 compatibility method seam，不应再以大文件行数触发一次横向“大爆炸”重构。

## 2. 后续目标架构与不变量

### 2.1 目标依赖方向

```text
Qt-free UltraView core（已落地）
  model <- grid_geometry <- board_ops / author_ops <- serialization
                         └──────────── presentation
          ↑
WorkspaceController       CaptureCoordinator
          ↑                    ↑
          └──── narrow UltraViewCoordinator façade ────┘
                                ↑
UltraViewPage composition root
  ├─ PageProjectionBuilder
  ├─ FloatingChromeController
  ├─ ViewportController
  ├─ ContextController / AuthorUIController
  └─ FreeGridBoard host
       ├─ FreeGridFeedbackController
       ├─ PointerRouter
       └─ FreeGridAuthorController
```

已完成的 Qt-free core 与 façade 不再重复进行大拆分。下一轮只围绕真实违规调用点、私有协议和可复现 bug，一次收口一个责任。

### 2.2 必须保持的行为不变量

1. `UltraViewRef(section, view_id)` 是 identity；display name 只用于呈现；
2. 一个 mixed intent 只有一个 accept/reject、一条 history 和一次 dirty 决策；
3. Board/history/dirty 只由 WorkspaceController 写；
4. PreviewStore/bindings/digest/queue/timers/runtime ledger 只由 CaptureCoordinator 写；
5. feedback latest pointer/frame/coalescer 只由 FreeGridFeedbackController 写；
6. viewport camera/animation/edge-pan timer 只由 ViewportController 写；
7. Page 与 aggregator 只依赖 collaborator public facts/commands；
8. transient UI/capture facts 不进入 Board/project/preset/sidecar schema；
9. Mouse/Laser 只改变 cursor provider，不改变 selection、drag 或 zoom；
10. programming error 不得降级为 optional/recoverable failure；
11. legacy micro-grid migration 保持屏幕几何，external drag timer 使用最新 event position；
12. digest 输入覆盖所有实际 cache-key shape，集合排序稳定，未知 leaf 显式失败并记录原因。

### 2.3 生命周期不变量

每个 controller/service 对适用场景显式实现 `connect/reset/hide/cancel/shutdown`：

- connect/disconnect 幂等；
- timer、animation、queued grab、signals 在 owner 销毁前停止；
- Board switch/project restore/presentation/tool-window reopen 不留下旧 selection、capture binding、cursor 或 feedback surface；
- 一个输入 signal 不重复 emit；
- cached Qt wrapper 在 `destroyed` 后清理，复用前检查存活；
- UltraView 独立工具窗口 show 后 `transientParent() is None`，Return 不触发 QDialog accept。

## 3. 后续执行 Plan

执行顺序：先恢复主 gate 的可信绿，再修可复现产品问题与假绿 verifier，随后收窄 private protocols，最后进行真实平台验收。禁止仅凭大文件行数再发起横向大拆分。

### Wave 0 — 恢复 authoritative green 与文档真值（COMPLETED）

#### 0.1 修复 SearchField 架构合同

- 将 `test_search_field.py` 的 UltraView call-site inventory 指向 `library_widgets.py`；
- 断言真实 owner 继续使用共享 `SearchField` 和中文 placeholder/copy；
- façade 只验证 re-export/compatibility，不再承担 implementation text assertion；
- 将该测试加入后续 UltraView architecture boundary gate。

Focused gate：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui_kit/test_search_field.py \
  tests/ui/test_ultraview_structure.py \
  tests/ui/test_import_boundaries.py -q
```

#### 0.2 恢复一次稳定 full baseline

focused/boundary 全绿且 source 稳定后，指定一个 coordinator 串行运行：

1. 主 suite：`--ignore=tests/acquisition_ui`；
2. 主 suite 完成后再运行 `tests/acquisition_ui`；
3. 记录 before/after HEAD、dirty tracked scope、命令、exit code 与完整 summary；
4. 若测试期间 relevant source 变化，则结果记为 `UNVERIFIED`，不立即重复跑 full gate，先稳定快照。

#### 0.3 同步文档状态

- 本文件作为后续执行清单提交；
- 在历史架构 Plan/Spec 增 completion addendum 或链接，不改写原始 proposal/blocked 历史；
- 明确 local merge、remote publish、offscreen green、Cocoa acceptance 四种不同状态。

**Wave 0 exit**：SearchField guard 覆盖真实 owner；两进程 full gate 在同一稳定快照全绿；文档不再声明旧 WIP/旧基线。

### Wave 1 — 产品正确性与 verifier 可信度（COMPLETED）

#### 1.1 mixed transaction 原子性

先加 failing tests，覆盖：

- missing card membership；
- unplaced/stale selection；
- locked/unknown author target；
- mixed nudge/delete；
- reject 后 Board、author、connector、history、dirty 全不变。

实现应落在 pure plan/Workspace mutation funnel，不在 Page/compatibility façade 补状态。

#### 1.2 visual harness fail closed

- 给 manifest 增 schema version；
- 对每个场景记录 stage、target、selection bounds、handles、toolbar、picker、minimap 的同一 host 坐标和 visible 状态；
- validator 先做 target visibility/containment，再做 anchor/overlap；
- missing facts、离屏 target、隐藏必要 chrome、坐标空间不一致均失败；
- 增负向测试，主动把对象滚出 stage 并证明 verifier non-zero；
- 重新生成当前基线，旧 vacuous manifest 作废。

#### 1.3 resize transient reanchor

- AuthorUIController 暴露 immutable active-transient facts，不暴露 popup private widget state；
- FloatingChrome apply/resize 通过 public command 重新解析 live trigger 与 safe area；
- 覆盖 Pointer/Sticky/Shape/Connector/Draw/format；
- 覆盖 800×560、1280×800、1440×900 和双向 resize；
- 断言 closed popup 不复活，active tool、selection、Pointer/Mouse/Laser、focus owner 不变。

**Wave 1 exit**：mixed intent 不再部分提交；verifier 对离屏/缺事实确定失败；所有 open author transient 在 resize 后保持 trigger anchor。

### Wave 2 — 收窄 composition 与 owner seam（AUTOMATED CONTRACTS COMPLETE / METHOD FACADE PARTIAL）

#### 2.1 Page/controller public protocol

状态：**COMPLETED**。

- 将 edge-pan/right-gesture/zoom/smooth-preview/context action 变为 controller public facts/commands；
- 删除 Page 对 `_viewport_ctrl._*`、`_pointer_router._*`、`_board_context._*` 的直接访问；
- `PointerRouter.FORWARDED_METHODS` 改成 literal 最小 allowlist，优先让 production call sites 直接使用 router；
- 禁止运行时遍历 callable 并 `setattr` 扩张 Page；
- 增 AST/structure shrink-only gate，新增 private collaborator access 立即失败。

#### 2.2 Coordinator façade 收口

状态：**MUTABLE STATE SEAM COMPLETED / METHOD SEAM PARTIAL**。

已完成：

- 删除 `_store/_runtime/_bindings/_queued/timer` 等 aggregator mirror；
- sync queue 等产品调用改走 `has_pending_capture()`；
- Workspace compatibility state 改走 owner public view；
- `runtime_counts()` 提供 frozen 生命周期 facts；
- AST gate 禁止 Coordinator 再读取 owner private state container。

后续只按调用族迁移当前 60 个 Capture、73 个 Workspace private method delegate：

1. 先迁 production consumer，保留 public product seam；
2. test seam 改用 owner-oriented fixture；
3. 每次只删除一个 method family，保持 public import/monkeypatch compatibility；
4. 不以 1507 行或 133 个调用点本身作为一次性拆分授权。

#### 2.3 Capture facts 闭环

状态：**COMPLETED**。

- `PresentationCaptureFacts` 增 markup revision 与稳定 pill fingerprint；
- chart stack 通过 public adapter 生成 facts；
- CaptureCoordinator 不再读取 `_annotations/_pill/_pill_for_canvas/_detail`；
- 扩大 private-host guard，新增字段进入禁止清单；
- 保留 dataclass cache key、plain mapping 不碰撞、pin-set 顺序稳定、digest failure 含 offending value 等 tests。

#### 2.4 生命周期与性能 ratchet

状态：**AUTOMATED COUNTERS COMPLETED / COCOA BENCHMARK PARTIAL**。

记录并设相对回归门槛：

- projection refresh count；
- signal connection/emit count；
- feedback planner/present/paint/reproject；
- capture queue/digest/grab；
- 12/24 refs、20 Boards/60 refs；
- PreviewStore residency 去重；
- reset/shutdown 后 live timers/hooks/grab/cursor/surface。

自动化现已覆盖 connect 幂等、投影刷新上限、500/2000 ms stationary hold、Capture queue/timer/hook 清理和 20×60 residency 去重。RSS 与 switch p50/p95 不进入易抖动 unit test；应在 Cocoa 候选上重复测量并记录分布。性能 parity 不能替代产品正确性 tests。

**Wave 2 exit**：mutable owner、lifecycle、capture digest、UI facts 与 private-state containment 已满足；compatibility private method seam 保持明确 `PARTIAL`，只能 shrink，不能扩张。

### Wave 3 — 集成与真实平台验收（IN PROGRESS）

#### 3.1 Focused/boundary gate

每个 owner 先跑 focused tests，再按改动范围运行：

- `tests/ui/test_ultraview_structure.py`
- `tests/ui/test_pg_canvas_backref_invariants.py`
- `tests/ui/test_import_boundaries.py`
- `tests/test_signal_no_gui_import.py`
- `tests/test_batch_render_import_boundary.py`
- `tests/test_native_import_boundaries.py`
- `tests/test_packaging_imports.py`
- `tests/ui/test_main_window_state_ownership.py`
- `tests/ui/test_no_lambda_signal_connections.py`
- `tests/ui_kit/test_qss_border_shorthand.py`
- `tests/ui_kit/test_search_field.py`
- `tests/test_verify_ultraview_visuals.py`

然后在 stable fingerprint 下运行一次 UltraView concentrated gate。并行 worker 不得各自运行 full suite。

#### 3.2 真实 macOS Cocoa 前台矩阵

通过真实入口 `./.venv/bin/python -m mf4_analyzer.app`，使用加载后的 `testdoc/222.tlproj` 与新建 Board 分开记录：

- 窗口：800×560、1280×800、1440×900；
- Pointer popup whole-control click、Mouse/Laser、cursor replacement；
- click/move/resize/collision/edge-pan，0/100/500/2000 ms stationary hold；
- 蓝色 move/resize target 持续到 release，无闪烁、无双 frame；
- Sticky/Text/Shape/Connector/Pen、toolbar、format picker、editor/IME；
- minimap/overview/presentation 与 selection/resize chrome 不遮挡；
- chart preview click/drag/resize 不白屏；
- Board switch/project reset/independent tool-window reopen；
- UltraView tool window 不激活/抬升 Analyzer，Return 不关闭窗口。

每项记录 `PASS / FAIL / UNVERIFIED`，并保留截图、录屏或明确人工观察说明。Offscreen 结果不得替代这一矩阵。

#### 3.3 Full/platform acceptance

所有 relevant source 稳定后，只运行一次两进程 full gate。Windows Full/Lite frozen executable、macOS 前台与 source-level packaging checks 分别记录；未运行保持 `UNVERIFIED`。

**Wave 3 exit**：focused、boundary、full、Cocoa 必须分别有同一候选快照的可追溯证据；无 unexplained regression；远端状态准确。

### Wave 4 — Author-chrome 产品缺陷（独立、NOT STARTED）

执行 source of truth：`docs/analyzer/plans/2026-08-23-ultraview-author-chrome-product-fixes-plan.md`。

该 Wave 不得被本轮绿色 full suite 自动关闭。实现前先完成其 §0 inventory；Laser 大红点/光晕需要先确认 2–3 个候选；其余按 swatch/menu/overlay/dead-control/cursor owner 分族实现。Wave 4 改动后应产生新的候选 fingerprint，并重新运行其 focused、visual、Cocoa 与必要 integration gates。

## 4. 后续提交与迁移序列

当前 working tree 已包含 Grok 的 Waves 0–2 与本轮 review fixes，不应伪造已经不存在的逐波 commit 历史。后续建议：

1. 当前产品/test/docs 作为一个可审查候选提交，但明确排除 `ssh-keygen`、`ssh-keygen.pub`；
2. Cocoa evidence 独立记录，不与产品源码机械混装；
3. Coordinator method seam 以后按 `capture sync → capture facts → workspace placement → workspace history → board lifecycle` 分族迁移，每族独立测试和回退；
4. push `origin/main` 是独立授权步骤，不由本地 merge、测试全绿或本次优化自动推出。

## 5. 完成定义

### 已完成并冻结

- [x] Workspace/Capture 各有一个 mutable-state owner
- [x] Capture/owner focused tests 与 lifecycle counts 全绿
- [x] Qt-free core import-safe，当前 AST graph 无 cycle、import probe 不加载 Qt
- [x] `free_grid ↔ card_fit` cycle 消失
- [x] `widgets.py` 与 `ui.ultraview_state` 成为 compatibility façade
- [x] 当前候选的 UltraView concentrated offscreen gate：1440 passed / 1 skipped
- [x] 当前候选的主 suite：8143 passed / 14 skipped / 3 deselected
- [x] 当前候选的 acquisition suite：359 passed

### 尚未完成

- [x] SearchField 静态合同覆盖真实 owner（`library_widgets.py`）；主 full suite 见下方 live gate
- [x] mixed missing/unplaced/stale/locked/unknown target 整体 reject，无部分 history/dirty
- [x] minimap/format/popup visual facts 完整、非 vacuous、fail closed（manifest schema v2）
- [x] open author transient 在 resize 后保持 trigger anchor；内容过高时垂直滚动可达
- [x] PointerRouter 不再反射扩张 Page instance protocol
- [x] Page 不读写 collaborator private state（shrink-only AST gate）
- [x] Coordinator 不镜像或直接读取 owner private mutable container
- [x] Capture facts 含 markup revision 与 pill fingerprint；CaptureCoordinator 不探测 `_annotations/_pill/_detail`
- [x] lifecycle counter ratchet：connect 幂等、12/24 refs 投影上限、500/2000 ms hold、Capture reset/shutdown
- [x] 20 Boards/60 refs 的 PreviewStore residency 去重
- [ ] Coordinator 60/73 个 private method delegate 按调用族继续收缩
- [ ] Cocoa 候选的 switch p50/p95 与 RSS 重复测量无未解释退化
- [ ] 当前候选快照的真实 Cocoa gesture/UI 矩阵通过
- [ ] 独立 author-chrome 产品 Plan 的 inventory 与实现完成
- [x] 主 suite 与 acquisition suite 在 stable snapshot 串行全绿
- [x] Windows frozen 未执行时明确保持 `UNVERIFIED`
- [x] 历史 Plan/Spec completion addendum 与本 follow-up 状态一致
- [x] 本地 merge、远端 publish、自动化 gate、平台验收状态分别准确记录

上述未完成项关闭前，UltraView 架构状态保持 **PARTIAL**。即使本地分支已合并，也不得写为“全面完成”或“已正式发布”。

## 6. 2026-08-23 follow-up 执行记录

工作区在 `HEAD=2feddfa17e2494d2551b6dd755aa5240e64c36da` 上叠加 Waves 0–2 与本轮 review fixes；`ssh-keygen*` 仍未跟踪且不得提交。验证结束后出现的 author-chrome 产品 Plan 为并发产物，本轮未修改、未实现。

### 已落地代码合同

| Wave | 结果 |
|---|---|
| 0.1 SearchField | inventory 指向 `library_widgets.py` |
| 1.1 mixed atomicity | `plan_selection_nudge/delete` 对 missing/unplaced/stale/locked/unknown 整体 reject |
| 1.2 visual harness | `MANIFEST_SCHEMA_VERSION=2`；离屏 target/required chrome/trigger 脱锚/缺字段 fail closed |
| 1.3 resize reanchor | `AuthorUiController.reanchor_open_transient()`；closed 不复活；popup 高度不足时自动启用垂直滚动 |
| 2.1 Page protocol | Viewport/Pointer/Context public commands；删除 `FORWARDED_METHODS` setattr；`tests/ui/test_ultraview_page_controller_protocol.py` |
| 2.2 Coordinator | 删除 private state mirrors；pending query/public Workspace view/frozen lifecycle counts；AST 禁止重新穿透 owner 容器 |
| 2.3 Capture facts | `markup_revision` + `pill_fingerprint`；canvas/ChartStack public adapters |
| 2.4 lifecycle ratchet | 12/24 refs、20×60 residency、capture reset/shutdown、500/2000 ms stationary hold |

### 最终自动化 gates

```text
review-fix owner set: 198 passed, 56 warnings in 25.93s
lifecycle + stationary hold ratchet: 10 passed in 6.15s
UltraView concentrated: 1440 passed, 1 skipped, 193 warnings in 180.08s
main suite: 8143 passed, 14 skipped, 3 deselected, 2544 warnings in 1271.73s
acquisition suite: 359 passed, 4 warnings in 9.04s
visual verifier runtime: exit 0; contact sheet rendered under /tmp/ultraview-final-visuals
```

主 suite 与 acquisition 使用两个新鲜、串行进程；测试期间 source 未变化。`git diff --check` 通过。

### 仍为独立状态

- Remote publish: 未 push
- Cocoa foreground matrix: `UNVERIFIED`
- Windows Full/Lite frozen: `UNVERIFIED`
- Author-chrome product plan: `RECORDED / NOT STARTED`
- Two-process full suite: `GREEN`（当前候选、稳定 source fingerprint）
