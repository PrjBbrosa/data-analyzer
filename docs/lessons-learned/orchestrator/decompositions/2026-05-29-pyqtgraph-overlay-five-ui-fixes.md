# Decomposition — pyqtgraph TimeDomain overlay/toolbar five UI fixes

**Date:** 2026-05-29
**Branch:** plan/pyqtgraph-timedomain-migration
**Mode:** plan
**Slug:** pyqtgraph-overlay-five-ui-fixes

## Task summary

Five UI bugs in the live pyqtgraph TimeDomain renderer
(`TimeDomainCanvasPG`), rooted in `mf4_analyzer/ui/pg_canvases.py` and
`mf4_analyzer/ui/chart_stack.py`. Main Claude supplied confirmed
file:line root causes; this decomposition refines measures and routing.

| # | Bug (user, zh) | Confirmed root cause (file:line) | Proposed measure |
|---|---|---|---|
| 1 | 叠模式标题/坐标轴太近，干涉 | overlay per-channel Y axes (pg_canvases.py:534-539) via `_compact_axis_label(max_chars=20)` (pg_canvases.py:664); `\n` inserted (canvases.py:233-235) but `setLabel` renders HTML so `\n` ignored → one long rotated label; autoSIPrefix "(x0.001)"; overlay has NO axis width/spacing mgmt (subplot has `_unify_subplot_left_axis_widths` + inside-label flip). | Replace `\n`→`<br>` or drop; ellipsize/compact label or top horizontal chip; disable/relocate autoSIPrefix; add overlay axis width/offset/spacing mgmt. |
| 2 | 分↔叠切换后叠的曲线不消失 | aux ViewBoxes added top-level via `scene().addItem(aux_vb)` (pg_canvases.py:545); `clear()` (pg_canvases.py:804-843) calls `_glw.clear()` (removes layout PlotItems only) then zeroes `_overlay_aux_viewboxes=[]` WITHOUT `scene.removeItem` → aux VBs + their curves + ch3+ appended right axes leak as ghosts. Same leak class already solved for inside-label TextItems by `_teardown_inside_labels` (pg_canvases.py:2294). | Add `_teardown_overlay_aux_viewboxes()` (mirror `_teardown_inside_labels`), call in `clear()` BEFORE zeroing the lists; also `scene.removeItem`/layout-remove ch3+ appended right AxisItems. |
| 3 | toolbar 缩放只能框选第一行，第二三四行无法框选 | (A) `_set_all_mouse_modes` only called from `pan()`/`zoom()` (chart_stack.py:465-491); `plot_channels` builds NEW ViewBoxes (default PanMode), toolbar 'mode' stays 'zoom', nobody re-applies RectMode to new VBs after replot → box-zoom silently dead. (B) overlay: `_view_boxes()` (chart_stack.py:355-365) returns only aux VBs (all `setMouseEnabled(False)`); real capture surface is the x_master ViewBox, NOT in the list, stays PanMode. Test (test_chart_stack.py:213) only proves RectMode at toggle on fresh state. | Re-apply `toolbar.mode` mouse mode to new ViewBoxes after every replot/mode-switch; in overlay apply Rect/Pan to x_master ViewBox (include it in `_view_boxes()` or special-case). Add runtime confirm of the "only first row" subplot symptom. |
| 4 | home 没恢复到全局，只到上一步 | `home()` → `reset_view_to_data_extents()` (chart_stack.py:417 / pg_canvases.py:746-758) does `vb.autoRange()` per VB, but hot-path PlotDataItem holds ONLY the current-viewport envelope (`_refresh_visible_data` setData with xlim-clipped `positions_envelope`, pg_canvases.py:1784-1800) → autoRange Y from clipped data; `_set_xrange_to_data_union` widens X afterward but Y never re-autoscaled → X global, Y stuck. | Compute Y extents from raw full `channel_data` arrays; explicit `set_ylim`; order = set X union → flush refresh → set Y from raw. Do NOT rely on `vb.autoRange()`. Honor flush-after-mutation ordering. |
| 5 | 叠模式选中曲线移动后，点击空白处无法取消选择 | `_select_overlay_channel_from_scene_pos` (pg_canvases.py:1070-1151) axis-hit fallback `_axis_handle_at_scene_pos` uses `vb.sceneBoundingRect().contains()` (pg_canvases.py:1479-1503), but overlay aux VBs all have geometry == primary full plot rect (`_sync_overlay_aux_viewboxes` pg_canvases.py:1513-1532) → ANY in-plot point contained by every aux VB → always returns ch1 → blank never returns None → never deselects (pg_canvases.py:1216-1224). Test passes only because it clicks ABOVE the plot rect. | Drop/fix the ViewBox-rect axis-hit fallback (rect spans whole plot in overlay); rely on nearest-curve 12px hit, OR test against the real `AxisItem.sceneBoundingRect()` gutter only. |

## Routing decision

All five are pyqtgraph canvas/toolbar surface work — axis label/geometry,
GraphicsScene item lifecycle/teardown, ViewBox mouse-mode wiring, Y-extent
computation from view state, scene-pos hit-testing for selection. Per the
surface-vs-computation rule these are plot/canvas/axis/toolbar SURFACES,
not FFT/Welch/filter computations → `pyqt-ui-engineer`. Not a
package/module refactor, so the persistent-UI routing note keeps it with
`pyqt-ui-engineer` rather than `refactor-architect`.

Bug 4's Y-extent recompute touches raw `channel_data` arrays but is a
view-state-restore concern, not a DSP computation — it stays UI. (If the
specialist finds the raw-array reduction needs a shared numeric helper
that doesn't exist, flag for `signal-processing-expert`; not anticipated.)

## Sequencing constraint (decisive)

All five bugs edit the SAME file `mf4_analyzer/ui/pg_canvases.py`; bugs 3
and 4 also edit `mf4_analyzer/ui/chart_stack.py`; all five likely append to
the same `tests/ui/` files (`test_pg_timedomain_canvas.py`,
`test_chart_stack.py`). Per
`2026-04-24-parallel-same-file-drawer-task-collision.md`, parallelising
same-file edits (even one-liners) races `git add` and produces commits
whose titles don't match contents. The prescribed fix is to BUNDLE
shared-file edits into a single specialist's brief. Therefore all five
fixes collapse into ONE `pyqt-ui-engineer` envelope doing five TDD cycles
sequentially with five separate commits (one per bug, bisectable). A
verification subtask depends on that envelope and runs after it. This is
the identical shape to `2026-05-29-pyqtgraph-timedomain-perf-regression-fix`.

## Spec/plan docs

The user requested a spec (`docs/superpowers/specs/`) and a plan
(`docs/superpowers/plans/`) authored BEFORE execution. The orchestrator's
write scope covers `docs/superpowers/`, but per the planner-executor split
the executor (main Claude) owns the live plan/spec authoring tied to the
dispatch loop and TDD step blocks (matching the perf-regression precedent
where the plan lived at `docs/superpowers/plans/...`). Recommendation in
notes: main Claude authors both docs (it has the TDD step-block + commit
boundary view), and the impl envelope's brief points at them. The
`superpowers:writing-plans` skill applies (>3 effective fixes).

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| impl-bugs-1-to-5 (overlay label geometry; overlay ghost-VB teardown; toolbar zoom mouse-mode re-apply incl. x_master; home global Y-from-raw; overlay blank-click deselect), each TDD-driven, five commits | pyqt-ui-engineer | — | All five are pyqtgraph canvas/toolbar surface fixes in the same 1-2 files; bundled into one envelope to avoid same-file `git add` collisions (lesson 2026-04-24). |
| verify-all (full regression sweep + LIVE GUI verification of all five) | pyqt-ui-engineer | impl-bugs-1-to-5 | Verification-only; must run after code lands. Live GUI check mandatory — offscreen tests previously passed on bugs 3 & 5 by clicking outside the plot rect / on fresh state, masking the live failure. |

## Lessons consulted

- `docs/lessons-learned/orchestrator/decompositions/2026-05-29-pyqtgraph-timedomain-three-ui-fixes.md`
- `docs/lessons-learned/orchestrator/decompositions/2026-05-29-pyqtgraph-timedomain-perf-regression-fix.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`
- `docs/lessons-learned/pyqt-ui/2026-05-28-arraytoqpath-not-byte-identical-to-moveto-lineto-loop.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md`

## Missed-keyword note

The user request contained no squad trigger keyword
(agent/squad/团队/分工/重构/refactor/多专家/multi-agent). Main Claude routed
under the missed-triggers rule — correct: this is a multi-bug
pyqtgraph/PyQt UI code-change task on known files, unambiguous routing.
No roster gap: every bug maps cleanly to `pyqt-ui-engineer` via the
surface-vs-computation rule. This is a phrasing-coverage note (a Chinese
multi-bug-fix imperative without an explicit squad keyword), already
covered conceptually; no new routing lesson warranted.
