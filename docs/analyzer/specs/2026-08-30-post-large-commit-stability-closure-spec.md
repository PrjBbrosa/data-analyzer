# 五波大提交后的稳定性与可靠性封口 Spec

- 日期：2026-08-30
- 状态：READY FOR IMPLEMENTATION（增量封口，不替代正在进行的 Smart Layout fixed-point 专项）
- 冻结审查基线：`253ba972c207f0c8e70896a9ef0e9c1ab168b9d5`
- 审查范围：`1ea1a84be3040fae2f434abf45e3404eeea63ca3..253ba972`
- 配套计划：
  [`2026-08-30-post-large-commit-stability-closure-plan.md`](../plans/2026-08-30-post-large-commit-stability-closure-plan.md)
- 增量前置规格：
  [`2026-08-30-wwt-record-tree-lifecycle-and-diagnostics-spec.md`](2026-08-30-wwt-record-tree-lifecycle-and-diagnostics-spec.md) ·
  [`2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md`](2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md)
- 并行专项：
  [`2026-08-30-ultraview-smart-layout-fixed-point-and-fit-isolation-followup-plan.md`](../plans/2026-08-30-ultraview-smart-layout-fixed-point-and-fit-isolation-followup-plan.md)

## 0. 结论

2026-08-30 的五个提交完成了 WWT record-only 文件树、native axis/tick restore、
Custom-X 路径统计、批量 WWT 选择、native X viewport 与 UltraView Smart Layout 等
大范围功能。中立模块、状态 owner、边界测试和多数聚焦测试方向正确，但冻结快照仍是
**NEEDS REVISION**，不能作为稳定发布基线。

本规格只封闭审查中已确认的稳定性缺口：

1. record tree 按 focused Time View 投影，eye handler 却固定写
   `view_manager.active`，导致 split secondary 的显示意图无法修改；
2. UltraView card mouse release 在同步提交可能重建 widget 后继续访问旧 Qt wrapper，
   单测可稳定触发 native segmentation fault；
3. Smart Layout 用户文案和 discovery hints 已更新，但可视化 harness、精确 hint
   轮播合同及 `git diff --check` 未同步；
4. `origin/main` 已有四个普通失败与一个 native crash。它们不能归因于本次五个提交，
   但完整稳定性基线不能继续把它们当作隐形背景噪音。

本规格不重新设计 Smart Layout solver、Card Fit、Board Fit 或 WWT native layout。
这些内容由 fixed-point 专项继续负责。本规格只规定 ownership、Qt 生命周期、验证资产
与集成门禁必须如何封口。

## 1. 已验证证据与边界

### 1.1 冻结提交范围

审查固定在以下五个提交，不把审查期间后到的 dirty/untracked 改动算入结论：

| commit | 主题 |
| --- | --- |
| `db92d41c` | record-only 曲线投影到 owner 文件树 |
| `300ac0ea` | View restore 后实现 right-axis columns 与 native ticks |
| `0fe05a94` | partial native View 保留 generic ticks |
| `6471dc57` | WWT open-batch 选择、Custom-X 路径统计、native X viewport |
| `253ba972` | Adaptive Smart Layout 替代 first-fit auto-arrange |

范围共 94 个文件，约 `+15,264/-1,339`。当前 checkout 中并行 Smart Layout
fixed-point、版本、帮助资源和本机文件改动均不是本规格的完成证据。

### 1.2 自动化证据

冻结快照的已完成证据：

- WWT/Custom-X/native-axis 第一批：`479 passed, 7 skipped`；
- UltraView/WWT 第二批在排除已知 native crash 后：
  `1539 passed, 5 skipped, 2 deselected`；
- import/state/backref/QSS/lambda/QSettings 边界：`44 passed, 1 skipped`；
- 带 `.git` 快照的 batch Qt render parity：`1 passed`；
- 独立 `tests/acquisition_ui`：`359 passed`；
- 近全量主套件：`8548 passed, 44 skipped, 7 failed, 4 deselected`。

近全量七个失败分为：

| 类别 | 数量 | 结论 |
| --- | ---: | --- |
| 本次新增验证回归 | 2 | UltraView visual harness 仍检查“自动排版”；hint 精确队列未加入三个新 hint |
| `origin/main` 同样失败 | 4 | 两个 FFT-time fake probe、TimeDomain hotpath fake、QSS palette ratchet |
| archive 环境缺 `.git` | 1 | 带 `.git` 快照复跑已通过，不是产品失败 |

另有 `test_card_drag_near_viewport_edge_starts_page_edge_timer` 在 `origin/main` 与
`253ba972` 均稳定 exit 139。它是继承的 native crash，不是本次新增回归，但任何
未排除的完整 Qt gate 都会因此异常退出，所以不能宣布 full suite green。

### 1.3 独立复现

split View 的最小状态探针：

```text
primary index = view_manager.active = 0
focused/visible record tree = secondary View
eye payload = (secondary view_id, record binding_id, false)
result = secondary.hidden_curve_binding_ids remains []
```

Qt crash 的稳定栈顶：

```text
FreeGridBoard.handle_card_mouse_release
  → _finish_gesture(commit=True, ...)
  → synchronous geometry signal / projection refresh
  → card.mapTo(self, event.pos())
  → native segmentation fault
```

这些是可执行证据，不以截图、旧报告或 focused pass 替代。

## 2. 范围与非目标

### 2.1 本规格要做

1. 让 record tree 的读取、写入和重绘使用同一个 focused View identity。
2. 把迟到 eye event、View 删除/切换、split primary/secondary 切换做成可测试的拒绝或
   精确路由，不再隐式回退到 active primary。
3. 消除 UltraView release transaction 对已失效 card/event wrapper 的后置访问。
4. 确保同步 geometry commit、页面重投影、`deleteLater`、edge-pan timer 与 cursor
   cleanup 的生命周期顺序安全、幂等、可观察。
5. 同步 Smart Layout 可视化 harness、hint rotation、help/quickref 契约与陈旧文案。
6. 恢复 branch diff hygiene，并区分“本次新增回归”和“继承基线失败”。
7. 在稳定 source snapshot 上完成 owner、boundary、full main、acquisition、Cocoa 和
   Windows 分层验收。

### 2.2 明确不做

- 不改 Smart Layout fixed-point、候选生成、score、Card Fit 数学或 Board Fit 语义；
- 不重复正在进行的 fixed-point follow-up 文件所有权；
- 不改 WWT parser、formula evaluator、native axis 数学、Custom-X 数值算法；
- 不引入第二份 record visibility state，不把 record-only 伪装成普通 channel；
- 不用 broad `except Exception`、`try/except: pass` 或 `getattr(..., False)` 掩盖
  生命周期错误；
- 不把 segfault 测试标成 `xfail`、skip、固定顺序或通过 sleep 降低复现概率；
- 不抬高 QSS palette/state-ownership/lambda shrink-only ceiling；
- 不提交本机 `testdoc/` 客户文件作为核心 fixture；
- 不清理、回滚、stage 当前 checkout 的无关 dirty/untracked 文件。

## 3. 状态与身份合同

### SCR-01 — focused Time View 是 record tree 的单一交互 owner

在 split TimeDomain 中必须区分：

| 名称 | 含义 | 是否可作为 record-eye owner |
| --- | --- | --- |
| `view_manager.active` | 主栏/Tab manager 的 active index | 否，split secondary focus 时不是用户目标 |
| `_focused_view_idx` | 当前接收通道/record 操作的主栏或副栏 index | 是 |
| signal `view_id` | 点击发生时树投影携带的稳定 View identity | 是，需与 focused target 二次校验 |

record tree rows 的读取、eye 写入、replot canvas 与同步回投影必须解析成同一个
`(focused_index, view_id)`。任何一步不得重新读取 `view_manager.active` 覆盖目标。

### SCR-02 — record-eye transaction

成功点击的顺序固定为：

```text
receive (view_id, binding_id, visible)
→ resolve focused Time View once
→ require resolved view_id == payload view_id
→ require binding still exists and y_ref.kind == "wwt_record"
→ update only that View.hidden_curve_binding_ids
→ resolve that index's canvas
→ replot that index with preserve_xlim=True
→ re-project record tree from the same View
```

拒绝场景：

- focused View 已切换；
- payload View 已删除或替换；
- binding 已在 file close/detach 中被过滤；
- binding 不再是 record-only Y；
- 当前 Section 不允许 Time projection。

拒绝必须是 zero mutation；如果树可能陈旧，只允许同步当前 focused View，不写另一个
View。普通 `checked`、channel colors、record store、其他 View hidden ids 均不变。

### SCR-03 — split primary/secondary 验收矩阵

| 场景 | 期望写入 | 期望重绘 |
| --- | --- | --- |
| 单栏 active View | 单栏 View hidden ids | 单栏 canvas |
| split 聚焦 primary | primary View hidden ids | primary canvas |
| split 聚焦 secondary | secondary View hidden ids | secondary canvas |
| tree 显示 secondary 后 focus 切回 primary，旧 click 才到 | zero mutation | 当前 tree resync，零错误 canvas replot |
| 两栏引用相同 record/binding source | 仍按各自 `view_id + binding_id` 独立 | 只重绘目标栏 |
| duplicate/save/reopen | 深拷贝/持久化各自意图 | restore 后聚焦谁投影谁 |

### SCR-04 — Qt release 前冻结所有易失输入

`handle_card_mouse_release(card, event)` 在任何可能同步 emit/refresh/delete 的调用之前，
必须冻结后续所需的纯值：

- stable `UltraViewRef`；
- board-local release position；
- global position；
- mouse button/modifiers；
- 当前 resize/gesture intent。

调用 `_finish_gesture()` 后：

- 不再访问传入的 `card`；
- 不再调用 `event.pos()`、`event.globalPos()` 或其他 Qt wrapper getter；
- cursor 恢复使用事先冻结的 board-local `QPoint` 或当前 board/ref 的重新解析结果；
- 若 host 自身已销毁，安全结束，不为恢复 cursor 复活 widget；
- 不把 `sip.isdeleted()` 当作继续使用旧 wrapper 的许可。首选设计是根本不保留旧
  wrapper；`sip.isdeleted()` 只可作为缓存/teardown 的防线。

### SCR-05 — release cleanup 精确一次

无论 move、resize、group move、非法 drop、move-to-unplaced、edge-pan 或 signal slot
是否同步重建页面：

- gesture take/release 精确一次；
- coalesce/edge-pan timer 停止；
- mouse grab 释放；
- ghost/dim/selection chrome 清理；
- `drag_finished` 最多一次；
- geometry/group geometry intent 最多一次；
- cursor 恢复不触发新的 geometry mutation；
- parentless/test widgets 在 teardown 前停止 timer/signal 并 drain deferred delete。

### SCR-06 — native crash 是失败，不是允许排除的常态

目标测试必须在独立 fresh process 中返回 exit code 0。出现 exit 139、abort、timeout、
无 summary 或测试期间相关 source 变化，一律 `UNVERIFIED/FAIL`。

不得以以下方式关闭问题：

- 永久 `--deselect` 该测试；
- `xfail`/skip；
- 改为只断言 timer active 而不执行 release；
- 增加 sleep 或改变 test order；
- 捕获 Python exception 假装能覆盖 native use-after-delete。

## 4. 验证资产与文案合同

### SCR-07 — 用户动作名称单点一致

产品已把 Board 动作从“自动排版”收敛为：

- `智能排版`：允许改变 size + position，成功后一次 Board Fit；
- `紧凑排列`：只改变 position；
- `按原图比例`：只处理目标 card；
- `适应内容`：只改变 camera。

生产常量、Board context、visual harness、geometry manifest assertions、hints、quickref、
help 与用户指南必须使用一致的当前名称。可视化 harness 不得硬编码已退休的“自动排版”。
若兼容 signal 仍名为 `auto_arrange_requested`，它只是内部兼容 seam，不得回流到用户
文案。

### SCR-08 — discovery hint 精确队列是产品合同

新增以下 hint 后，精确轮播测试必须按 `priority + registry order` 同步：

```text
file.wwt_batch_choice
time.custom_x_paths
time.wwt_native_home
```

不得通过删掉精确队列测试、放宽为集合包含或提升/降低 priority 来消除失败。若产品确实
要调整顺序，先在 Spec/用户体验层说明，再同步 registry 与测试。

### SCR-09 — diff hygiene

本实施产生的每个 commit 必须同时满足：

```text
git diff --check <base>..<commit>
git diff --cached --check
```

已确认的 `tests/ui/test_view_state.py` EOF 空行在对应 owner commit 中清理。若 branch-wide
diff check 仍命中并行无关文件，报告 scoped/branch-wide 区别，不得顺手修改其他 agent
的内容。

## 5. 继承红基线治理合同

### SCR-10 — 新回归与继承失败分开修

以下四个普通失败在 `origin/main` 与冻结 HEAD 上均存在：

1. `test_fft_time_dispatch_key_equals_lookup_key_for_each_pane`；
2. `test_fft_time_single_path_uses_same_key_builder_as_main_path`；
3. `test_disabled_stats_strip_skips_full_array_statistics`；
4. `test_distinct_hex_literals_may_only_shrink`。

它们进入独立 baseline-debt commit，不与 record-eye 或 crash 产品修复混写：

- fake probe 应绑定真实 owner 新增的窄 seam，不为测试在生产代码增加静默 fallback；
- TimeDomain fake 补 `_active_time_curve_bindings` 的真实空语义；
- QSS palette 必须复用/删除重复色 token，不能把 ceiling 从 211 抬到 212；
- 每项先在基线复现，修复后证明无产品行为变化。

### SCR-11 — full gate 必须基于稳定 fingerprint

full owner 在开始前记录：

```text
HEAD
git status --porcelain fingerprint
running pytest processes and cwd
```

主套件与 `tests/acquisition_ui` 使用两个 fresh process 顺序运行，不并发。运行结束后再次
记录 HEAD/fingerprint；相关文件变化则本轮 full 结果为 `UNVERIFIED`。

任何 focused、boundary、near-full-with-deselect 结果均不能替代最终无排除 full green。

## 6. Ownership 与依赖方向

| 责任 | owner | 禁止做法 |
| --- | --- | --- |
| focused View 解析 | 既有 View focus holder / `_focused_time_view_state()` | 新增 MainWindow bool/index 镜像 |
| record hidden intent | `ViewState.hidden_curve_binding_ids` | widget/record store 持久化显示状态 |
| record tree presentation | ChannelTree/FileNavigator | 用显示名称当 identity |
| card gesture session | FreeGridBoard 既有 gesture/feedback collaborators | page/controller 持有 card wrapper |
| placement mutation | workspace controller / board ops | widget 直接写 Board model |
| Smart Layout fixed-point | 并行专项的 neutral/core owners | 本规格复制 solver/Card Fit 数学 |
| visual/hint contracts | tool + hints/quickref/help 对应 owner | 只改测试期待绕过产品文本 |
| full gate | 唯一 integration owner | 多 agent 并发完整 pytest |

不得扩宽 `tests/ui/test_main_window_state_ownership.py` whitelist；不得破坏
`_CanvasBackref` declarations；不得让 neutral core import UI/Qt。

## 7. 可观察性与错误分类

- stale record-eye event 是可恢复的 UI race：zero mutation + resync，不弹错误框；
- missing/deleted Qt card 是生命周期错误：测试必须暴露，生产日志允许记录一次上下文，
  不静默吞掉；
- visual/hint stale assertion 是 verification failure，不是产品 runtime warning；
- archive 缺 `.git` 属 evidence-environment failure，需在带 `.git` 快照复跑；
- pre-existing assertion 与 current regression 必须在报告中分别列出；
- Windows/Cocoa 未跑即写 `UNVERIFIED`，不得用 offscreen 代替。

## 8. 验收矩阵

### 8.1 自动化

最低必须覆盖：

- 单栏、split primary、split secondary、stale click、duplicate/save/reopen record eye；
- geometry signal 同步删除 card、edge-pan release、resize/group move、非法 drop；
- current Smart Layout/Compact Arrange/Board Fit/Card Fit action strings；
- visual harness geometry/contact sheet；
- hint exact priority/registry sequence；
- state/import/backref/no-lambda/QSettings/QSS shrink-only gates；
- full main suite 无 deselect 正常结束；
- `tests/acquisition_ui` fresh process 正常结束；
- `git diff --check` 为零。

### 8.2 macOS Cocoa 前台

1. 打开含 record-only curve 的 WWT，建立 split secondary；
2. primary/secondary 各点一次不同 record eye，只改变目标栏；
3. 快速切 focus 后点旧树位置，不修改错误 View；
4. UltraView 中反复执行 edge drag/release、resize、move-to-unplaced、Undo/Redo；
5. 验证无 crash、无 ghost、无 stuck cursor、无持续 edge-pan timer；
6. Board context 显示“智能排版/紧凑排列”，visual artifact 与前台一致；
7. 与 fixed-point 专项组合后再走 WWT open → Smart Layout → Board Fit 序列。

### 8.3 Windows Full/Lite frozen

分别在 Full/Lite fresh executable 验证 split record eye、UltraView edge drag/release、
Smart Layout 当前文案、Undo/Redo、保存重开与 125%/150% DPI。源码检查、macOS 与
offscreen 均不能替代此门禁。

## 9. Definition of Done

- [ ] split secondary record eye 写入并重绘 secondary，primary 不变；
- [ ] stale eye event zero mutation，tree 回投影当前 focused View；
- [ ] edge-pan release 测试独立进程 exit 0，不再排除；
- [ ] release 后无旧 card/event wrapper 访问，timer/ghost/cursor 对称清理；
- [ ] visual harness 使用“智能排版/紧凑排列”当前合同并通过；
- [ ] hint 精确轮播纳入三个新增 id 并通过；
- [ ] EOF 空行与 scoped/branch diff check 清零；
- [ ] 四个继承普通失败在独立 baseline-debt commit 关闭；
- [ ] owner 与 boundary gates 全绿；
- [ ] full main 无 deselect 正常结束；
- [ ] `tests/acquisition_ui` fresh process 正常结束；
- [ ] macOS Cocoa 通过或明确 `UNVERIFIED`；
- [ ] Windows Full/Lite 通过或明确 `UNVERIFIED`；
- [ ] 当前 fixed-point 专项无 owner 冲突，相关结果在稳定 integration snapshot 重验；
- [ ] lessons status、changed-file review、提交范围审计完成。

## 10. 停止条件

出现任一条件立即停止当前 wave 并回报：

1. record-eye 修复需要修改普通 channel identity、record store 或其他 View；
2. focused View 只能通过新增第二个 MainWindow index/bool 维护；
3. Qt crash 只能通过 skip/xfail/sleep/test order 绕开；
4. release 后仍必须持有旧 card wrapper 才能恢复 cursor；
5. 修 verification gate 需要恢复已退休用户文案或放宽精确合同；
6. 修 QSS 只能通过抬高 shrink-only ceiling；
7. 需要修改 Smart Layout core/card-fit/fixed-point 当前并行 owner；
8. target owner 文件出现无法协调的并发修改；
9. 同 checkout 已有 full pytest 运行；
10. full gate 期间 HEAD/dirty fingerprint 变化；
11. 核心测试必须依赖本机 `testdoc/`；
12. offscreen 与 Cocoa/Windows 的生命周期或交互结论冲突。
