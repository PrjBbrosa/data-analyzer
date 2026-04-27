# Decomposition — batch-blocks-redesign Wave 4

**Date:** 2026-04-27
**Top-level request:** Execute Wave 4 of the batch-blocks-redesign plan
— relocate `mf4_analyzer/ui/drawers/batch_sheet.py` into a new
`mf4_analyzer/ui/drawers/batch/` package skeleton (placeholder
`BatchSheet` + `PipelineStrip`), update its single import call site in
`main_window.py`, migrate dependent test fixtures, delete the old
single-file module.
**Mode:** plan
**Plan file:** `docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md`
(§Wave 4, lines 1157–1442)
**Spec file:** `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md`
(§3.1 整体布局, §5 模块边界)

## Routing rationale

Wave 4 is a behavior-preserving relocation: a single-file UI module
becomes a small package skeleton whose surface (placeholder dialog
contents) is intentionally minimal because Waves 5/6/7 fill it in.
The dominant axis of work is **package relocation + import-graph
rewiring + test fixture migration + file deletion**, not Qt UI
authoring. Per the specialist roster, that maps cleanly to
`refactor-architect` (`refactor`, `module`, `package`, `import`,
`relocation` keywords).

The placeholder `BatchSheet`/`PipelineStrip` bodies have verbatim
PyQt5 source supplied by the plan (§Wave 4 Step 4 + Step 5). Although
the surface is technically PyQt, this is **boilerplate paste** and
the surface is throwaway (Wave 5 replaces the detail placeholders;
Wave 6 wires task list; Wave 7 wires runner thread + toolbar). There
is no UI design judgment to make in W4 — `pyqt-ui-engineer` would
add no value and would risk drift from the plan-verbatim source.

Folding **module bodies + tests + import call-site rewrite + test
fixture migration + file deletion** into one specialist envelope is
the same shape used in W1/W2/W3 (Codex-approved each time) and is the
mitigation pattern recorded in
`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`:
when metadata edits are mechanically derivable, fold them into the
body-creator's brief. Splitting "create the package" from "rewrite
the import site / migrate tests" across two specialists would create
exactly the rework pattern that lesson warns against — and would also
race the same `tests/ui/test_drawers.py` shared-file concern recorded
in `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`.

`pyqt-ui-engineer` is not appropriate because (a) the placeholder
layout is verbatim from the plan, (b) the dominant work is package
relocation, (c) inviting a UI engineer to "polish" the placeholder
would actively harm the wave (Wave 5 owns those decisions).

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W4: Create `mf4_analyzer/ui/drawers/batch/` package (`__init__.py` re-exporting `BatchSheet`; `sheet.py` placeholder dialog 1080×760 with three disabled toolbar buttons + `PipelineStrip` + three detail placeholders + Cancel/运行 footer; `pipeline_strip.py` with `PipelineCard`+`PipelineStrip(set_stage)`); add `tests/ui/test_batch_smoke.py` (2 tests: import + `set_stage`); rewrite the single import in `mf4_analyzer/ui/main_window.py:953` from `from .drawers.batch_sheet import BatchSheet` to `from .drawers.batch import BatchSheet`; rewrite the monkeypatch target string in `tests/ui/test_order_smoke.py:66`; delete the two pre-redesign tests at `tests/ui/test_drawers.py:36-65` plus their `from mf4_analyzer.ui.drawers.batch_sheet import BatchSheet` imports; delete `mf4_analyzer/ui/drawers/batch_sheet.py`; preserve the `BatchSheet(parent, files, current_preset=None)` constructor signature; `get_preset()` returns the hard-coded `AnalysisPreset.free_config(name="placeholder", method="fft")` placeholder | `refactor-architect` | (none — W3 already merged + Codex-approved) | Single-specialist relocation: package skeleton + import call-site + test migration + module deletion bundled into one envelope to avoid `move-then-tighten` rework and `tests/ui/test_drawers.py` shared-file races. Plan supplies verbatim PyQt5 source for both new module bodies. |

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index (re-read for cadence).
- `docs/lessons-learned/.state.yml` — cadence (16 / 0; no prune due, threshold ≥20).
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — supports bundling body-creation + import-site rewrite into one specialist envelope.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — drives the explicit forbidden files/symbols list and `symbols_touched` reporting requirement embedded in the brief.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — confirms NOT to fan W4 out across multiple parallel specialists touching `tests/ui/test_drawers.py`.
- `docs/lessons-learned/refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md` — only refactor-role lesson on file; not directly applicable (W4 has no cross-layer constant), but reviewed for completeness.
- `docs/lessons-learned/orchestrator/decompositions/2026-04-27-batch-blocks-wave3.md` — confirms the W1/W2/W3 single-envelope shape that W4 mirrors.

## Notes

- Windows pytest invocation carried verbatim into the brief:
  `py -3 -m pytest tests/ui/test_batch_smoke.py tests/ui/test_drawers.py tests/ui/test_order_smoke.py -v --basetemp=.pytest-tmp -p no:cacheprovider`.
- The plan's Step 12 `git commit` block is rewritten in the brief to
  "do NOT commit yet — main Claude commits after Phase 3 aggregation"
  per the planner-executor split.
- The plan's Step 11 manual smoke is rewritten in the brief to
  "main Claude is responsible for any manual GUI smoke; specialist
  does NOT need to launch the app".
- Relative-import depth call-out included in the brief: the new
  `sheet.py` lives at `mf4_analyzer/ui/drawers/batch/sheet.py` (4
  levels below the package root), so `from ....batch import
  AnalysisPreset` requires **4** leading dots (the existing
  `batch_sheet.py` only used 3). Specialist must verify by running
  pytest after the move — a wrong dot-count surfaces immediately as
  `ImportError`.
- Forbidden-file list embedded in the brief per the silent-boundary-leak
  lesson: `mf4_analyzer/batch.py`, `mf4_analyzer/batch_preset_io.py`,
  `tests/test_batch_runner.py`, `tests/test_batch_preset_dataclass.py`,
  `tests/test_batch_preset_io.py`, plus all not-yet-created sibling
  modules under `drawers/batch/` other than `__init__.py`/`sheet.py`/
  `pipeline_strip.py` (those belong to Waves 5/6/7).
- No `superpowers:brainstorming` invocation — request is unambiguous
  (verbatim source supplied by plan, single specialist).
- No `superpowers:writing-plans` invocation — only one specialist
  dispatch, well below the >3 threshold; the plan itself already
  serves that role.
