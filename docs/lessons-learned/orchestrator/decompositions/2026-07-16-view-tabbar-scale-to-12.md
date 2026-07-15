# Decomposition — 时域 View 标签栏扩容至 12（紧凑密度 + 溢出菜单）

- **Date:** 2026-07-16
- **Mode:** plan
- **Spec:** `docs/superpowers/specs/2026-07-16-view-tabbar-scale-to-12.md`（已批准）
- **Top-level request:** 「就按推荐来，写好 spec 和 plan，然后安排 agent 执行」
- **Dispatches:** 2（串行）
- **Rework-detection forecast:** 不会触发（同一专家；规则要求「专家不同」）

## 结论摘要

Spec 的 T1–T4 是**四个可独立验收的变更**，但**不是四个可独立派发的边界**。
按文件重切成 2 个 item：

| item | = spec 任务 | 写入文件 |
| --- | --- | --- |
| S1 | T1 + T2 | `view_state.py` · `main_window/window.py` · `view_tabbar.py`(仅 2 处) · `style.qss`(仅 1 处注释) |
| S2 | T3 + T4 | `view_tabbar.py`(除 `_update_plus_state`) · `style.qss`(`::tab` 密度规则) |

## Decomposition

| subtask | expert | depends_on | rationale |
| --- | --- | --- | --- |
| S1 — View 上限解耦为构造参数 + 调色板扩到 12（含全部配套调用点） | `pyqt-ui-engineer` | — | T1/T2 改的是 `view_state.py` 同一个模块头 + `_make`/`new_view`/`duplicate` 同一簇方法，拆开等于两次派发重写同 5 行 → 依 `move-then-tighten` 折叠。`_update_plus_state` 与 `window.py:229` 是该契约变更的**配对调用点**，依 `return-type-change-needs-paired-callsite-update` 一并绑入。非 refactor-architect：无文件搬迁，是 `__init__` 签名 + 方法体改动（该 agent 会按 roster 拒收，见 `non-dsp-algorithmic-...` 记载的实例）。 |
| S2 — 拆 `setFixedWidth` 宽度钉子 + 紧凑密度 + `»` 溢出菜单 + 真机渲染证据 | `pyqt-ui-engineer` | S1 | T3 算出的可用宽度预算**就是** T4 密度降档/溢出判定的输入，且两者同改 `_sync_tabbar_width`；拆开 = S_i 建预算、S_j 立刻重构预算（move-then-tighten 反模式）。依赖 S1 是硬依赖而非排序偏好：`tests/ui/test_view_tabbar.py::_manager_with_views` 用真实 `new_view()` 造 View，上限 6 时**根本造不出** 14/20 个 View 来验收 T3/T4。 |

### 为什么不并行

两个 item 都写 `view_tabbar.py` 与 `style.qss`。同专家 → rework 检测不会响（规则要求专家不同）；
但依 `parallel-mutators-share-git-index-even-disjoint-files` 与 `parallel-same-file-drawer-task-collision`，
并行 mutator 仍会抢 git index / `git add` 扫入对方半成品。**串行**，并按
`refactor-then-ui-same-file-boundary-disjoint` 的手法在每份 brief 里**显式列禁止触碰的方法**。

## 对 spec 的三处修正（不迁就）

### 1. T1 点错了文件 — `stack.py` 不需要改，真正的目标是 `window.py`

Spec T1 写：「`chart_stack/stack.py` — 时域 manager 传 `max_views=12`」。**时域 manager 不在
那个文件里。** 实测：

- `mf4_analyzer/ui/main_window/window.py:229` → `self.view_manager = ViewManager(self)` ← **时域，唯一要改的构造点**
- `mf4_analyzer/ui/chart_stack/stack.py:128-130` → 只有 `fft` / `fft_time` / `order` 三个 `AnalysisViewState` manager，**保持默认 6 = 不传参 = 零改动**

即 `stack.py` 在本次改动中**完全不需要出现**。若按 spec 原文派发，`window.py` 不在授权文件表内，
专家只能 FLAG 换一轮 —— 正是 `plan-mapped-decomposition-misses-live-call-sites` 记录的失败形状
（计划的文件表是「新代码写哪」，不是「现有行为从哪可达」）。规划期直接改掉，省一次往返。

### 2. T3/T4 与 T1/T2 是两组假缝

见上表 rationale。四步「独立可测」成立，「独立可派」不成立。

### 3. §5 漏了最大的风险 — 溢出菜单会打断 tab-index ↔ view-index 恒等

`view_tabbar.py` 有 6 处依赖「QTabBar 第 i 个 tab == `manager.views[i]`」：

- `_on_current_changed` → `switch_requested.emit(idx)`
- `_on_tab_moved` → `reorder_requested.emit(from_idx, to_idx)`
- `_refresh_tab_swatches` → `count = min(self._tabs.count(), len(self._manager.views))`
- `_set_current_index(self._manager.active)`
- `_begin_inline_rename` → `self._tabs.tabRect(idx)`
- `_on_context_menu` → `tabAt(pos)` → `idx` 直接当 view 索引发出去

若 T4 用 `removeTab` 把尾部标签收进 `»` 菜单，这 6 处**全部静默错位**（切错 View、重命名错 View、
拖拽排序错位）。实测运行环境 **Qt 5.15.2 / PyQt 5.15.11，`QTabBar.setTabVisible` 存在**（Qt 5.15+），
用它隐藏而非移除即可保持索引恒等。**S2 的 brief 里定为硬约束。**

## 真机渲染证据归属（回答 §5.4 / CLAUDE.md gotcha）

**S2 独家负责**，不拆给第三个 agent —— 证据必须由做改动的人出，否则「绿色巡检」会变成假覆盖
（见 `rendered-evidence-tour-coverage-gap-for-legacy-fallback`：全绿的 9 状态视觉巡检照样漏了一条真实路径）。
S2 需同时交付：

1. **像素**：真实平台插件（非 offscreen）下 N = 6 / 10 / 14 / 20 的截图，存
   `docs/analyzer/evidence/2026-07-16-view-tabbar/`。
2. **几何数值断言**：`_plus` 与 `_split_clear` 的 `geometry()` 落在父 rect 内、`visibleRegion()` 非空；
   可见 tab 数；`»` 计数正确。
3. **§5.3 阈值**：密度档位阈值**从真机实测读出来**，不许抄方案稿的 58px/49px。
4. **§5.1 闪退**：12+ View 下真实驱动拖拽排序（`QTest.mousePress/mouseMove/mouseRelease`），
   确认 `_reordering` guard 原样存活、不复现 use-after-free。

S1 无需渲染证据（验收是单测级：第 13 次 `new_view()` 返回 -1、默认 manager 仍卡 6、12 色两两不同）。

## 已知的中间态

S1 落地后、S2 未落地前，时域上限已是 12 而标签栏仍钉死宽度 —— 即 spec §1.1 描述的破损态
（`+` 与「取消合并」被挤出右缘）。这是链内中间态，两个 item 背靠背执行；**S1 不可单独收工**。

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
- `docs/lessons-learned/orchestrator/2026-07-12-plan-mapped-decomposition-misses-live-call-sites.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`（索引行）
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md`（索引行）
- `docs/lessons-learned/pyqt-ui/2026-07-10-facts-degrade-budget-from-measured-not-literal-px.md`
- `docs/lessons-learned/pyqt-ui/2026-07-10-splitter-column-removal-blast-radius-and-toolbar-minwidth.md`
- `docs/lessons-learned/pyqt-ui/2026-06-15-eliding-label-stable-anchor-and-text-returns-elided.md`
- `docs/lessons-learned/pyqt-dialog-scroll-keeps-actions-visible.md`（原则适用、机制不适用 —— 见下）

### 关于 `pyqt-dialog-scroll-keeps-actions-visible.md`

用户点名要确认。判定：**原则适用，机制不可搬。**

- 适用的是它的 Rule 内核 —— 「动作行不参与可压缩区域」。这正是 spec T3/T4「`+` 与右侧动作区固定、
  永不参与压缩」的**横向同构**。值得在 S2 brief 里作为设计原则引。
- 不可搬的是它的机制 —— `QScrollArea` 包长表单 + `QScreen.availableGeometry()` 钳窗高，是 QDialog
  高度问题的解法。**28px 的标签行里塞 QScrollArea 是错的**（会与 `setUsesScrollButtons` 和 `»` 菜单
  三重叠）。S2 brief 需显式写明「勿照搬 QScrollArea」。

**语料卫生问题（供 main Claude 处置，不由我改）**：该文件落在语料**根目录**，用的是 Codex 的
frontmatter schema（`id` / `owners: [codex]` / `checks`），既不符合 README 的
`<role>/YYYY-MM-DD-<slug>.md` + `role:`/`cause:` 规范，也没有 `LESSONS.md` 索引行。
按 README 的 Reading protocol（先读 LESSONS.md → 按 role heading 过滤），**任何角色的 agent 都不会
检索到它**。它是 Codex 的 lane，我不改写他人 owner 的 lesson；建议 main Claude 决定是否补索引行/迁移。
