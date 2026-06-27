# Decomposition — 时域分屏模式共轴组合并

**Date:** 2026-06-27
**Mode:** plan
**Top-level request:** 让同 `axis_group` 的通道在时域「分屏」模式下合并到一行、
共享一根 Y 轴（量程并集、轴色=组色），未分组通道仍各占一行。明确放弃滚动条。
Subagent-Driven 逐任务执行 + 任务间 review。

**Pre-existing artifacts (对齐，不重新发明):**
- spec: `docs/superpowers/specs/2026-06-27-subplot-shared-axis-groups-design.md` (41537d8)
- plan: `docs/superpowers/plans/2026-06-27-subplot-shared-axis-groups.md` (0242e84)

## Routing rationale (关键决策)

主战场 `mf4_analyzer/ui/pg_canvas/canvas.py` 是 PyQt5 + pyqtgraph 渲染层；
关键词全是 surface（canvas/axis/Y 轴/color/label/ViewBox/PlotItem）→ 按
surface-vs-computation 规则全部归 `pyqt-ui-engineer`。

**4 个任务全部触碰同一文件 `canvas.py` + 同一新测试文件
`tests/ui/test_subplot_shared_axis.py`。** 因此：

1. **不拆给 refactor-architect。** Task 1 虽标「纯重构」，但内容是**新建带逻辑体的
   helper 方法** + **新建测试文件**——属 body-creating，refactor-architect 的
   scope 仅 move/shim/import，会按 pre-Write 自检 refuse（见
   `non-dsp-algorithmic-python-routes-to-signal-processing-expert`），白白多一轮
   round-trip。
2. **同文件跨专家会触发 rework 检测**（refactor→ui 同文件，见
   `refactor-then-ui-same-file-boundary-disjoint`）。全部归同一专家
   `pyqt-ui-engineer` 从根上规避：rework 规则要求「files_changed 交集非空 **且专家
   不同**」，同专家串行不触发。
3. **串行执行**（depends_on 链）——文件改动型 subagent 默认串行，避免共享 git
   index 抢占（`parallel-mutators-share-git-index-even-disjoint-files`）；且
   subagent-driven 本就要求逐任务 + 任务间 review。

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| Task 1: 抽出 `_group_visible_into_slots` helper，叠加分支改调它（纯重构，叠加现有用例守回归） | pyqt-ui-engineer | — | body-creating helper + 测试在 pyqtgraph 渲染层；与 Task 2/3 同文件，归同一专家避跨专家 rework |
| Task 2: 分屏按槽构建——同组合一行共享一根 Y 轴（auto-range 并集、轴色=组色），复用 `_bind_channel` 多曲线绑同一 handle | pyqt-ui-engineer | Task 1 | 核心 UI 渲染改动，消费 Task 1 helper；canvas/axis/color surface |
| Task 3: 边界（单可见成员退化/混合单位/分屏↔叠加归槽一致/底轴落末槽）+ 全量 ui 回归 | pyqt-ui-engineer | Task 2 | 守护测试 + 仅在回归暴露问题时定点修同文件；同专家串行 |
| Task 4: 真机渲染验证 + `/update-hints` 复核共轴提示 | pyqt-ui-engineer | Task 3 | 真机渲染验真（项目铁律）+ hint/quickref 维护，纯 UI |

## Lessons consulted (step 4)

- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/pyqt-ui/2026-06-22-companion-curve-shares-source-axis-not-new-row.md`

## Guardrails carried into every brief

- 子 agent **禁止 `run_in_background` 跑全量 pytest**（~/Downloads 触发 macOS TCC
  EPERM）；定向用例前台跑。
- **离屏渲染 ≠ 真机验证**：offscreen `grab()` 是 cached blit，藏掉真实重绘；Task 4
  必须真机截图。
- 嵌入浮层/菜单的自定义 widget 透明背景坑（`WA_TranslucentBackground` 让本体 QSS
  失效 → 内层 QFrame 兜底）——仅当 Task 4 触及 quickref/hint 浮窗时相关。
- 提交用显式 pathspec `git commit -- <paths>`，绝不 `git add -A`（工作树有 codex
  并行改动）。
