# Decomposition — 重做图表底部 hint 提示条（加权 + 变停留滚动 + 退役常驻区 + section tips + 谱图锚点修正）

**Date:** 2026-06-15
**Mode:** plan
**Top-level request (verbatim):** "可以，你写好plan，然后安排agent直接开始吧。注意提示位置。"
（设计意图由 main Claude 在 prompt 中补全；6 点设计 + "注意提示位置" UI 验收。）

## Why a single consolidated subtask, not 3 split ones

The whole change is single-file-dominant and UI-owned:

- `chart_stack.py` — rotation engine (`_hint_rotation_timer` :1122, `_advance_context_hint` :1619), footer layout (:1264-1286), pause hook (`set_hint_rotation_paused` :1630), weight wiring.
- `hints.py` — `Hint` dataclass (:14), `persistent_hints()` (:189), `context_hints()` (:197), new `dwell_ms`/`weight` fields, new section tips, retirement-by-usage.
- `heatmap_canvas.py` — wheel-dispatch fix (`_handle_wheel_dispatch` :812) + slice/colorbar/divider tip triggers.
- read-only touchpoints: `line_canvas.py:1542` (时域预览选源), `inspector_sections.py:2027` (预设右键).

Every one of the six design points re-touches **both** `chart_stack.py` and `hints.py`. Splitting by layer (model / engine / content) would make all three subtasks edit the same two files → the rework-detection rule fires on every pair (`refactor-then-ui-same-file-boundary-disjoint` shows this misfire is expected even when scopes are disjoint), and the shared git index makes parallel mutation unsafe (`parallel-mutators-share-git-index-even-disjoint-files`: "Big integration tasks touching chart_stack.py MUST run solo"). The least-rework decomposition is therefore ONE pyqt-ui-engineer subtask with an internally-phased brief, per `move-then-tighten-causes-cross-specialist-rework` (don't split work that re-touches the same file across dispatches).

## Why no signal-processing-expert dispatch

The only DSP-adjacent question is the *semantics* of the heatmap wheel (what Ctrl/Shift SHOULD do). That is already settled in the verified context: line canvas implements Ctrl→X / Shift→Y (`line_canvas.py:505`); heatmap returns False (`heatmap_canvas.py:812-813`) so pyqtgraph default = both-axes zoom, no lock. No new DSP/transform code is needed — only re-pointing the wheel handler at the existing lock semantics and correcting footer copy. The confirmed semantics are folded into the brief; a separate signal-processing dispatch would add a round-trip for zero new computation. If during implementation the engineer finds the heatmap's intended axis-lock semantics genuinely ambiguous (e.g. which axis Ctrl locks for an Order/RPM map), flag back for a signal-processing confirmation rather than guessing.

## Why no refactor-architect dispatch

No module move / shim / import-graph change. All edits are in-place behavior + data-model field additions within existing files. refactor-architect's scope (move/shim/import only) does not apply.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| 重做底部 hint 提示条：加权+变停留单行滚动、退役静态常驻区(顺手修谱图锚点字面错误)、补各 section 专属 tip、交互暂停、用够降权/退役；并刻意安排滚动行渲染位置(稳定不跳) | pyqt-ui-engineer | — | 6 点全部落在 chart_stack.py / hints.py / heatmap_canvas.py，全 UI 数据模型+轮播+布局+谱图滚轮语义修正；同文件重复触碰必须单 writer 串行执行(见 parallel-mutators / move-then-tighten 教训)；DSP 语义已确认无需新算法 |

Internally the engineer should phase it: **(P1)** `hints.py` 数据模型 `dwell_ms`/`weight` + 默认值 + 各 section 专属 tip 文案 + 退役/降权逻辑 → **(P2)** `chart_stack.py` 轮播改变停留 + 退役 `_hint_persistent` + 把基础手势按 section 正确化并入滚动池 + footer 位置安排 + 暂停钩子接线 → **(P3)** `heatmap_canvas.py` 滚轮修正 + slice/colorbar/divider tip 触发 + line_canvas/inspector 触点接线。Phases are internal to one specialist — do NOT dispatch them separately.

## Lessons consulted (plan-mode step 4)

- docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md
- docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md
- docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md
- docs/lessons-learned/orchestrator/2026-04-26-interactive-playground-unblocks-ui-alignment.md
- docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md

## Skills

- `superpowers:writing-plans` NOT triggered (single dispatch, not >3).
- `superpowers:brainstorming` NOT triggered (design intent is unambiguous — main Claude already converged the 6 points + "注意提示位置").
- Style memory (Precision Light, footer chrome ≠ data colors) attached to the brief.
