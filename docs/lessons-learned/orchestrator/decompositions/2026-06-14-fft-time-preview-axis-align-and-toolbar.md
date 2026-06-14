# Decomposition — FFT 时域预览：右轴对齐网格 + 刻度密度 + 工具栏补齐 (A/B/C)

- date: 2026-06-14
- mode: plan
- top-level request: 实施已批准的 spec+plan，三项一起做（A 右轴 nice 网格对齐+刻度密度联动、B 标注扩展到时域预览、C 返回/前进视图历史）。
- spec: `docs/superpowers/specs/2026-06-14-fft-time-preview-axis-align-and-toolbar-design.md`
- plan: `docs/superpowers/plans/2026-06-14-fft-time-preview-axis-align-and-toolbar.md`
- routing note: 用户原话仅"一起做。"，未命中 CLAUDE.md 关键词触发；按 "Missed triggers" 规则主动路由（这是明确的多步 UI 源码实施任务、spec §7 指定走 squad runbook）。记录于下方 routing 段。

## Routing / missed-keyword note

触发缺口与既有教训 `2026-05-30-ui-redesign-verb-missed-squad-trigger` 同型：实施 verb（"一起做" / spec→实现 / 实施已批准 plan）不在触发关键词集合内。信号应是"是否要求源码改动"，而非字面关键词。本次按 Missed-triggers 路由。无需新增 roster-gap 教训（已被该既有教训覆盖；如累积更多同型再合并 bump）。

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| A — Y 轴 nice 网格框定（右轴对齐 + 密度联动） | pyqt-ui-engineer | — | 纯 pyqtgraph 轴几何/刻度钉死/ViewBox setMouseEnabled，复用纯函数 `_frame_to_nice`/`_fmt_tick`（不改 `ticks_math.py` 数值）→ 无需 signal-processing-expert。是 surface（轴/刻度/网格）非 computation。 |
| B — 标注扩展到时域预览图 | pyqt-ui-engineer | A | 标注/右键菜单/屏幕像素选最近点/TextItem+红点，纯 PyQt/pyqtgraph 交互。与 A 同改 `line_canvas.py`+同测试文件 → 串行于 A，禁并行（共享 git index + 同文件 hunk）。 |
| C — 返回/前进视图历史在 FFT 画布生效 | pyqt-ui-engineer | A, B | 给 `PgLineCanvas` 补 `register_replot_callback`/`_channel_lines` 契约壳，让既有 `PgNavigationToolbar` 历史生效（不改工具栏、不碰 time domain）。同文件 → 串行于 A/B。C 与 A 的 graticule 有耦合（`__time__` 仅还原 X），须在 A 之后。 |

> 三项均落在同一文件 `mf4_analyzer/ui/pg_canvas/line_canvas.py` + 同测试 `tests/ui/test_pg_line_canvas.py`，且同一 expert。依 `parallel-mutators-share-git-index-even-disjoint-files` 与 `parallel-same-file-drawer-task-collision`：**必须严格串行 A→B→C，绝不并行**。拆成三个 subtask 仅为保留 TDD 先红后绿 + 三次独立 commit 的边界，依赖链强制顺序。

## Lessons consulted (step 4)

- `docs/lessons-learned/pyqt-ui/2026-06-14-boundary-grid-suppression-and-stacked-left-axis-unify.md` — 网格/左轴几何、`setGrid(False)` top/right、context_menu 重新点亮 top/right 的跨画布陷阱、generateDrawSpecs 过滤边界刻度的测试方式。
- `docs/lessons-learned/pyqt-ui/2026-06-11-inspector-tick-counts-vs-pg-density-factors.md` — `set_tick_density` 全项目契约是 tick COUNTS（非 pg density 因子），转换内联在 TickDensityController；极值目视验证。
- `docs/lessons-learned/pyqt-ui/2026-06-14-left-drag-region-select-overrides-pan-and-menu-append-after-reorder.md` — `_plot_time` 左键 drag/菜单/dual-emit/grab_pixmap 既有改动；setMouseEnabled(y=False) 与该 region 改动的共存面。
- `docs/lessons-learned/pyqt-ui/2026-05-29-pyqtgraph-axisitem-setwidth-clamp-and-builtin-right-column-spacing.md` — setWidth 是硬 clamp；overlay 多右轴 showGrid 行为。
- `docs/lessons-learned/pyqt-ui/2026-06-11-sigmouseclicked-fires-after-viewbox-menu.md` — 右键删标注须用 `vb.setMenuEnabled(not mode)` 而非 `ev.accept()`（菜单在 item dispatch 之后才 emit）；直接支撑 B 的 `set_remark_enabled` 改动。

## Pre-flight (executor)

- 调度前 `git log --oneline -5` + `git status` 确认 `line_canvas.py` clean、无 codex 在途改动（spec §5 / plan 协调前置；`workflow-parallel-codex-same-worktree`）。
- 每个 subtask 内严格 TDD 先红后绿（`superpowers:test-driven-development`）。
- A、B 改完按 `superpowers:verify-ui-visually` 对照用户截图做截图复核。
- 行号会漂移，以函数/符号名定位。
