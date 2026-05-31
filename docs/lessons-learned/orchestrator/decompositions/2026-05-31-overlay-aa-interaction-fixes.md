# Decomposition — Overlay AA / interaction bug fixes (Fix A–D)

**Date:** 2026-05-31
**Mode:** plan
**Branch:** `plan/pyqtgraph-timedomain-migration`
**Authoritative spec:** `docs/superpowers/specs/2026-05-31-overlay-aa-interaction-fixes-design.md`
**Target file (single):** `mf4_analyzer/ui/pg_canvases.py`
**Tests:** `tests/ui/test_pg_timedomain_canvas.py`, `tests/perf/test_timedomain_pan_perf.py`

## Routing decision

All four fixes (A box-zoom press routing, B AA-off on rubber-band drag,
C density-gate redo + resize re-arm, D DeviceCoordinateCache on idle AA)
live entirely in the pyqtgraph **canvas / interaction / render** layer of
`pg_canvases.py`. The spec keyword set is dominated by **surfaces and
interactions** (ViewBox, RectMode/PanMode, mouseDragEvent, rubber band,
DeviceCoordinateCache, resizeEvent, antialias, cursor hover) — not by
numeric computation. Per the surface-vs-computation rule, even though
"density" and "envelope point count" brush the signal-processing keyword
space, the work is *reading* `getData()` lengths to drive a render-quality
gate, not modifying the envelope algorithm (explicitly out of scope in the
spec). → **All four route to `pyqt-ui-engineer`.**

### Single task, not split

Fixes A–D are mutually coupled through shared state and shared chokepoints:
- A and B both gate on the ViewBox mouse mode (RectMode==1 / PanMode==3).
- B, C, D all funnel through `disable_interactive_quality()` /
  `try_enable_idle_quality()` / `schedule_idle_quality()`.
- C and D both read `_collect_curve_items()` grouped by ViewBox.
- All four edit the **same file** and the **same two test files**.

Splitting them across parallel tasks would race `git add` on the shared
file and tests (see `parallel-same-file-drawer-task-collision`), and
splitting sequentially across *different* experts would trip rework
detection on `files_changed` overlap for zero benefit. → **One
`pyqt-ui-engineer` task implementing A→B→C→D in order, TDD-first.**

### No signal-processing-expert subtask

The density metric reads envelope/curve **point counts** (`getData()`
length per ViewBox) but does NOT touch `positions_envelope`,
`_envelope_cutils.py`, the envelope cache, setData, or any FFT/order path.
That boundary is a UI render-gate concern, so it stays with
`pyqt-ui-engineer`. If during implementation the engineer finds it must
change how envelope point counts are *produced* (it should not — it only
reads existing `getData()` output), that is a flag-back to the
orchestrator, not a silent scope grab.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| Implement Fix A–D (overlay AA + interaction bug fixes) in `pg_canvases.py`, TDD-first | pyqt-ui-engineer | (none) | All four fixes are UI/interaction/render-layer edits to one file, sharing ViewBox-mode state and the AA-quality chokepoints; surface-vs-computation rule + single-file shared-edit rule → one bundled UI task. |

## Lessons consulted (step 4 + directly-relevant role lessons)

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
  — why A–D must be one task, not parallel same-file tasks.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
  — enumerate forbidden symbols in the brief; require `symbols_touched`.
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`
  — pg canvas tests must drive Qt-native events / instance state, not mpl dispatcher.
- `docs/lessons-learned/signal-processing/2026-05-28-component-speedup-does-not-imply-end-to-end-target.md`
  — Fix D perf claim must be measured end-to-end (hover/draw_idle frame), not on the cache flip alone.

## Notes for the dispatcher (main Claude)

- **Real-hardware visual verification is YOUR responsibility, not the
  specialist's.** Subagents cannot drive the live app; per repo rule,
  "属性设上了 + 单测过" is NOT acceptable as the only evidence. After the
  specialist returns green tests, you must capture real interaction /
  screenshots for problems 1–4 per the spec's 验收标准 before declaring done.
- Density thresholds `_AA_SEGMENT_ON`/`_AA_SEGMENT_OFF` are real-hardware
  tunables; the specialist seeds spec defaults (ON≈12000 / OFF≈16000),
  you adjust on the live frame rate.
