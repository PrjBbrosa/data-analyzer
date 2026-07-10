# Decomposition — Cockpit 实时可预览重构（第一性原理布局 + 曲线可读性）

Date: 2026-07-10
Mode: plan
Spec: `docs/analyzer/acquisition/specs/2026-07-10-cockpit-live-preview-first-principles-spec.md`
Plan: `docs/analyzer/acquisition/plans/2026-07-10-cockpit-live-preview-first-principles-implementation.md`

Task IDs are taken **verbatim** from the on-disk plan (A-1..A-6, B-1..B-6). No task
was re-invented. This audit only validates the split, dependency/serialization
boundaries, and expert assignment.

## Key boundary findings

- `live_cards.py` is mutated by **A-2, A-3, A-4, A-5, A-6 and B-5** — all must be
  the **same expert (`pyqt-ui-engineer`) in a strict serial chain**. Any second
  expert on this file fires rework detection AND races the shared git index.
- `live_downsampler.py` is mutated **only by A-6** (new `RollingDisplayBuckets`).
- `health_strip.py` is mutated by **B-1, B-2, B-3** → serial, same expert.
- `window.py` / `_settings_mixin.py` / `_polling_mixin.py` are mutated by
  **B-2, B-3, B-4** → serial, same expert.
- A-1 (`ui_kit/ticks_math.py` + `ui/pg_canvas/ticks_math.py` shim) is **file-disjoint**
  from the `live_cards.py` chain, so it is a clean `refactor-architect` node — but it
  must land FIRST because A-3/A-4 consume it, and it is serialized against the pyqt
  chain by the shared git index (not run in parallel).
- **A-6 routing**: the incremental 10ms bucket mechanism is already nailed down in the
  plan (no open numeric-design), and A-6 inseparably rewires `live_cards.py`
  push/trim/paint. Assigning it to `signal-processing-expert` would put a second expert
  on `live_cards.py` → rework false-positive + index race. Therefore **A-6 is
  implemented by `pyqt-ui-engineer`**, with `signal-processing-expert` as a **read-only
  reviewer** of bucket min/max/last fidelity + the perf gate (reviewers parallelize
  freely, never touch the index).

## Decomposition

| subtask | expert | depends_on | rationale |
| --- | --- | --- | --- |
| A-1 lift `ticks_math` into shared `ui_kit.ticks_math` + re-export shim | refactor-architect | — | Pure move + re-export shim + import update = textbook refactor-architect scope; file-disjoint from `live_cards.py`; must precede A-3/A-4 consumers. |
| A-2 30s time-window trim + raw buffer 4096→32000 | pyqt-ui-engineer | A-1 | Mutates `live_cards.py`; serialized after A-1 (shared git index). Base state for the whole Phase-A chain. |
| A-3 continuous polyline + envelope + time-based x | pyqt-ui-engineer | A-1, A-2 | Same `live_cards.py` (hard-serial after A-2); consumes A-1 `ui_kit.ticks_math`. QPainterPath render surface. |
| A-4 compact y-ticks + honest window label + no-data/stale + min-span | pyqt-ui-engineer | A-1, A-3 | Same `live_cards.py` (hard-serial after A-3); consumes A-1 `_frame_to_nice`/`_fmt_tick`. |
| A-5 honest recording stats label (drop "since rec start") | pyqt-ui-engineer | A-2, A-5→A-4 | Same `live_cards.py` (hard-serial after A-4); label-only, stats already windowed by A-2. |
| A-6 10ms incremental bucket + stats 2Hz + perf bench | pyqt-ui-engineer | A-2, A-5 | New `RollingDisplayBuckets` in `live_downsampler.py` **plus** push/trim/paint rewire in `live_cards.py`; mechanism pre-nailed in plan → keep on the `live_cards.py` owner to avoid a second-expert rework. |
| A-review numeric/perf review (nice-tick/min-span + bucket fidelity + gate) | signal-processing-expert | A-1, A-4, A-6 | **Read-only.** Honors spec 落地分工 (signal 复核 A3/A5 math + A6 bucket/gate); reviewers never mutate → zero index/rework risk. |
| B-1 clickable `HealthChip` + detail popover | pyqt-ui-engineer | A-6 | Creates `health_popover.py`, mutates `health_strip.py`; UI surface + WA_TranslucentBackground paintEvent floater. Phase-B wave serialized after Phase A on the same branch. |
| B-2 preflight pill + aggregate popover | pyqt-ui-engineer | B-1 | Shares `health_strip.py` + `window.py`; reuses B-1 popover; must be serial after B-1. |
| B-3 bottom fact stream + escalation ladder | pyqt-ui-engineer | B-2 | Shares `window.py`/`_settings_mixin.py`/`_polling_mixin.py`/`health_strip.py` with B-2; serial. |
| B-4 remove capture right pane + 2-col body + relocate metrics | pyqt-ui-engineer | B-3 | Layout/body surgery in `window.py`+mixins+`_toolbar_mixin.py` (same files as B-2/B-3) = UI work, not a module move; keep single expert. Keeps `right_panel.py` for Replay. |
| B-5 capture disconnected checklist, Replay opt-out | pyqt-ui-engineer | B-4 | Re-touches `live_cards.py` (checklist API) + `window.py`; same owner as the A chain. |
| B-6 tour asserts + macOS onscreen acceptance | pyqt-ui-engineer | B-5 | Extends `scripts/cockpit_ui_tour.py` + runs focused suite; final Phase-B gate. |

## Serial vs parallel summary

- **Hard-serial same-file chains (one expert each):**
  `A-2 → A-3 → A-4 → A-5 → A-6` on `live_cards.py`;
  `B-1 → B-2 → B-3` on `health_strip.py`; `B-2 → B-3 → B-4` on `window.py`+mixins.
- **File-disjoint but index-serialized:** A-1 (refactor-architect) vs the pyqt chain —
  run A-1 solo first, not in parallel (shared git index; A-3/A-4 also consume it).
- **Free to parallelize:** only the read-only `A-review` node overlaps a subsequent
  implementer (reviewers do not touch the index).
- **Wave order:** Phase A is independently shippable; run it to a clean merge, then
  start Phase B (or isolate Phase B in its own worktree/session).

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
</content>
</invoke>
