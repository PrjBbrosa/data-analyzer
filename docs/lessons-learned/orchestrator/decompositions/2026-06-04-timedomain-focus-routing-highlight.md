# Decomposition — 时域 View 标签切换 P2 收尾(游标/工具栏聚焦路由 + 高亮可见性)

**Date:** 2026-06-04
**Mode:** plan
**Top-level request:** 完成「时域 View 标签切换」P2 两条收尾:(1) 并排时把游标/工具栏(分屏·叠加·游标模式)路由到聚焦栏;(2) 把聚焦高亮做得更醒目(当前仅 2px 边框,整窗尺度不明显)。基线 commit ee046794(B 已实现 focus routing 先做部分)。

## Shared-file collision analysis

两条收尾都属于 surface/交互改动(非计算),均路由 `pyqt-ui-engineer`。关键事实:
- (1) 游标/工具栏路由 改 `main_window.py::_on_cursor_mode_changed`(609-611,写死 `canvas_time`)+ `chart_stack.py`(重新启用副栏控件 `_set_secondary_time_controls_enabled` 语义反转、把副 card 的 plot_mode_changed/cursor_mode_changed 接到副画布、relay/`_on_time_cursor_mode_changed` 1424-1425/1640-1643)。
- (2) 高亮 是纯 QSS / setProperty,改 `chart_stack.py` 的 `[focused="true"]` 边框规则(2026-06-04 lesson 已确立 WA_StyledBackground + padding 前置条件)。

两个 subtask 都改 `chart_stack.py` → 硬 shared-file 碰撞。按 `parallel-same-file-drawer-task-collision` 指南 #2(shared-file 编辑不可避免时 bundle 进一个 specialist brief),且二者同 expert、同 surface,**合并为单个 `pyqt-ui-engineer` 子任务**,内部按 (1)→(2) 顺序执行,一次真窗口截图同时验两件事。这既避免 git-add 碰撞,也避免 (1) 改完边框规则后 (2) 再覆盖造成的隐性 rework。

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| 游标/工具栏聚焦路由 + 聚焦高亮加强(单 brief,内部 1a→1b→1c→2 顺序) | pyqt-ui-engineer | [] | surface/交互改动;两件事同改 chart_stack.py,按 shared-file 碰撞规则合并为一个 brief,内部串行;高亮是 QSS/setProperty 范畴,与路由同属 pyqt-ui |

## Lessons consulted

- docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md
- docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md
- docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md
- docs/lessons-learned/pyqt-ui/2026-06-04-dynamic-property-border-needs-styledbackground-and-padding.md
- docs/lessons-learned/pyqt-ui/2026-05-26-timedomain-state-preservation.md

## Notes

- 单一 subtask,不触发 superpowers:writing-plans 的 >3 dispatch 阈值。
- 任务无歧义(用户已给出 1a/1b/1c/2 范围 + 接线现状),不触发 brainstorming。
- 红线已写入 brief:改 chart_stack.py/main_window.py 前 grep `def 方法名` 去重(project-ui-files-structural-corruption);游标路由+高亮必须真窗口截图验真(verify-ui-visually),复用 scripts/focus_routing_cocoa_smoke.py。
