# Decomposition — dB Reference Defaults, Auto-Resolution & Labeling: Implementation

- **Date:** 2026-07-12
- **Mode:** plan
- **Top-level request:** Execute the already-authored implementation plan
  `docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md`
  (Task 0–11 + Task 10A discoverability) against spec
  `docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md`
  (acceptance matrix A1–A17) and approved visual reference
  `docs/analyzer/reviews/reports/2026-07-12-db-reference-defaults-draft.html`.
  Doc authoring itself is already done by main Claude; this decomposition
  covers only the specialist execution of Tasks 0–11/10A.
- **User constraint relayed by main Claude:** minimize dispatch cost/avoid
  unnecessary heavyweight agent spin-up ("不要安排fable的agent，消耗太大") —
  see Notes below; does not change routing since the roster only contains
  the three specialists below.
- **Writing-plans skill:** already satisfied — the implementation plan file
  itself is the artifact `superpowers:writing-plans` would produce (>3
  dispatches, deep cross-module coupling). No new plan document needed;
  path cited above and in the return `notes`.

## Routing principle applied

This is a near-exact structural repeat of the 2026-06-21 "FFT/Order compute
vs display root-fix" decomposition
(`docs/lessons-learned/orchestrator/decompositions/2026-06-21-fft-order-compute-vs-display-root-fix.md`):
a display-only cross-cutting parameter (`db_reference`/mode/catalog
revision) must stay out of compute cache keys, touches the same file
cluster (`_fft_mixin.py`, `_fft_time_mixin.py`, `_order_mixin.py`,
`line_canvas.py`, `heatmap_canvas.py`, the three `contextual_*.py`
panels), and the plan itself mandates a **strict linear execution order
with stop gates** (Task 0→1→2→…→10→10A→11). Per
`docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
("big integration tasks run solo", "serialize file-mutating subagents by
default"), this decomposition does NOT attempt to parallelize any node —
every subtask depends on the immediately preceding one, matching the
plan's own gate structure.

Surface-vs-computation split:

- **New pure domain module (Task 1), QSettings persistence store (Task 2),
  per-source dB conversion/render-signature/cache-key discipline (Tasks
  5–7), schema migration (Task 8), Batch resolution (Task 9), final
  regression/audit (Task 11)** → `signal-processing-expert`. Task 2 in
  particular looks like a "PyQt keyword" (`QSettings`) at a naive
  roster-keyword-match level, but it is pure JSON-delta persistence with
  zero widget/layout code — routed per the existing lesson
  `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`,
  which explicitly lists "config-store I/O with UTF-8 round-trip and
  schema validation" as signal-processing-expert territory.
- **New widgets/dialog/QSS (Task 3), Inspector row integration (Task 4),
  visual parity/UI tour (Task 10), discoverability hints/quickref/nudge/
  tooltip (Task 10A)** → `pyqt-ui-engineer`.
- No task in this plan is a pure file-move/shim/import-only change, so
  `refactor-architect` is not dispatched this round.

## Cross-expert same-file watch (rework pre-empt)

- `analysis_view_bridge.py` may be touched by both Task 4 (pyqt-ui,
  "only if an explicit migration hook is needed") and Task 8
  (signal-processing, same conditional). Task 8's brief explicitly
  forbids re-editing Task 4's `get_params/current_params/apply_params/
  preset` methods in the three `contextual_*.py` files and instructs
  Task 8 to `flag` pyqt-ui-engineer instead of editing those methods
  itself — same discipline as
  `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
  (cross-expert edits on a shared file are safe only when each brief
  enumerates forbidden methods up front).
- `batch.py`/`_fft_mixin.py`/`_order_mixin.py` each have their own
  `max(reference, 1e-12)` coercion to remove (Task 9 owns the two
  `batch.py` call sites only; Task 6 already removed the FFT one; Task 7
  already removed the Order one) — Task 9's brief names the exact line
  ownership split so no task re-touches another's coercion removal.
- `heatmap_canvas.py`/`line_canvas.py` dB-math edits stay entirely inside
  the signal-processing cluster (Tasks 6–7); pyqt-ui only touches these
  files' surrounding widgets in Task 10 (QSS/tour), never the dB
  conversion lines.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| Task 0+1 — baseline suite + pure `db_reference.py` catalog/resolver/formatter | signal-processing-expert | — | New pure numeric/domain module + baseline test-count capture; body-creating algorithmic work per non-dsp-algorithmic routing lesson |
| Task 2 — versioned QSettings store, catalog revision | signal-processing-expert | Task 0+1 | JSON-delta persistence/validation/atomicity, zero widget code; routed per the same lesson despite the `ui/` path and `QSettings` keyword |
| Task 3 — scientific editor, compound control, manager dialog, scoped QSS | pyqt-ui-engineer | Task 2 | New widgets/dialog/QSS — pure PyQt surface work |
| Task 4 — integrate compound control into all 3 Inspector contexts + param contracts | pyqt-ui-engineer | Task 3 | Inspector row wiring + get/apply/preset signal contracts on Contextual panels — surface + display-only param plumbing |
| Task 5 — MainWindow service, `ChannelReferenceFacts`, Auto propagation | signal-processing-expert | Task 4 | Resolution-service/algorithmic wiring (non-widget), needs Task 4's control objects to inject into; disjoint file set from Task 4 |
| Task 6 — FFT per-source conversion, mixed labels, render signature | signal-processing-expert | Task 5 | dB-conversion math + cache/render-signature contract — computation, bundled with signal cluster per 2026-06-21 precedent even though it touches `line_canvas.py` |
| Task 7 — FFT-time/Order colorbar, slice, readout + manual color-level shift | signal-processing-expert | Task 6 | Same computation cluster; NEW manual-level-shift math is a direct continuation of the 2026-06-21 color-scale-clip red line |
| Task 8 — AnalysisView/Preset/Project schema migration | signal-processing-expert | Task 7 | Schema/JSON migration logic; explicit forbidden-methods note vs Task 4's contextual preset ownership |
| Task 9 — Batch Auto resolution + image label parity | signal-processing-expert | Task 8 | Per-target resolution + label formatting is computation; trivial BatchSheet snapshot pass-through folded in per "fold mechanical metadata edits into body creator's brief" precedent, with an explicit stop-and-flag clause if it turns out non-trivial |
| Task 10 — HTML-to-TraceLab visual parity + UI tour | pyqt-ui-engineer | Task 9 | Visual/QSS/screenshot verification work; requires all prior chart-label and control work merged first |
| Task 10A — discoverability: hints, quickref, nudge, tooltip | pyqt-ui-engineer | Task 10 | Hint-registry/quickref/tooltip copy — pure UI-surface, follows existing `/update-hints` two-face maintenance flow |
| Task 11 — final regression, stale-identifier audit, handoff | signal-processing-expert | Task 10A | Solo integration/audit task per "big integration tasks run solo"; spans both compute and UI hard-code audit but stays read-mostly + doc completion record |

## Lessons consulted (step 4)

- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/decompositions/2026-06-21-fft-order-compute-vs-display-root-fix.md` (precedent
  decomposition, not a lesson file per README's exclusion rule, but the
  direct structural template for this plan)

## Notes

- "不要安排fable的agent，消耗太大": the agent roster available to this
  orchestrator contains exactly three specialists —
  `signal-processing-expert`, `pyqt-ui-engineer`, `refactor-architect` —
  none named "fable". This decomposition only ever dispatches those
  three. Main Claude should clarify with the user what "fable" refers to
  if the concern persists after this run (possibly confusion with the
  `Claude Fable 5` co-author signature used in commit messages, which is
  unrelated to subagent selection).
- Every subtask depends strictly on its predecessor, matching the plan's
  own "Execution Order And Stop Gates" section — no parallel dispatch is
  recommended for this run.
