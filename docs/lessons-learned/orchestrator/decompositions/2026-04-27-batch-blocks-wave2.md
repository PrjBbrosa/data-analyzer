# Decomposition — batch-blocks-redesign Wave 2

**Date:** 2026-04-27
**Top-level request:** Execute Wave 2 of the batch-blocks-redesign plan
(`BatchRunner` extension — events / cancel / loader injection).
**Mode:** plan
**Plan file:** `docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md`
(§Wave 2, lines 296–922)
**Spec file:** `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md`
(§3.2, §4.3, §4.4, §4.5, §7, §8)

## Routing rationale

Wave 2 is a single, self-contained extension of the numerical batch
pipeline in `mf4_analyzer/batch.py`: a new event dataclass, a new
loader-injection seam, a rewritten `_resolve_files` / `_expand_tasks`
pair, and a new `run()` signature with cancel + on_event keyword-only
parameters. All of it sits squarely on the data-loading + numerical
pipeline boundary, with the ONLY new test surface in
`tests/test_batch_runner.py`. Per the specialist roster (`MDF`, `loader`,
`channel-math`, `DataLoader`, `FileData`), this routes to
`signal-processing-expert`. No UI surface is in scope (the plan
explicitly forbids `mf4_analyzer/ui/**`); no package relocation
(forbids `batch_preset_io.py` and W4+ files), so neither
`pyqt-ui-engineer` nor `refactor-architect` is appropriate.

The plan already supplies verbatim source for `BatchProgressEvent`,
`_default_loader`, the rewritten `_resolve_files`, the two-phase
`_expand_tasks`, the new `run()` body, and 13 explicit pytest cases.
Folding everything (dataclass + sentinel + loader seam + resolve +
expand + run + tests) into one specialist envelope avoids the
`move-then-tighten` cross-specialist rework pattern documented in
`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`.
This is the same routing shape we used for W1, which Codex approved.

The brief enumerates a forbidden-symbols list (W3/W4 territory) per
`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`,
and requires the specialist to return `symbols_touched` and a
`forbidden_symbols_check` self-attestation.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W2: Add `BatchProgressEvent` + `_LoadFailure` sentinel; extend `BatchRunner.__init__(files, loader=None)`; rewrite `_resolve_files`, `_expand_tasks` (two-phase), and `run()` (new signature: `progress_callback` positional, `on_event` / `cancel_token` keyword-only); append 13 new tests to `tests/test_batch_runner.py`; keep W1 tests + the original 7 `test_batch_runner.py` tests green | `signal-processing-expert` | (none — W1 already merged + Codex-approved) | Single-file numerical-pipeline change with adjacent test module, on the data-loader/runner boundary owned by `signal-processing-expert`. Folding dataclass + loader seam + resolve/expand + run + tests into one envelope avoids cross-specialist rework on `mf4_analyzer/batch.py`. |

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index.
- `docs/lessons-learned/.state.yml` — cadence (14 / 0; no prune due).
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — supports keeping body + tests in one envelope; no metadata/import split warranted here.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — drives the explicit forbidden-symbols list (`BatchPresetIO`, `BatchBlocksDialog`, anything under `mf4_analyzer/ui/**`, anything in `mf4_analyzer/batch_preset_io.py`) and the `symbols_touched` reporting requirement.
- `docs/lessons-learned/orchestrator/decompositions/2026-04-27-batch-blocks-wave1.md` — confirms W1 routing/envelope shape; W2 mirrors it.

## Notes

- This checkout is on Windows; the plan's `pytest` invocation includes
  the known tmp-dir-lock workaround
  `py -3 -m pytest tests/test_batch_runner.py -v --basetemp=.pytest-tmp -p no:cacheprovider`.
  The brief carries that command verbatim.
- The plan's `git commit` step is rewritten in the brief to "do NOT
  commit yet — main Claude commits after Phase 3 aggregation".
- The plan corrects spec §4.3's `loader.load_file(path)` to
  `DataLoader.load_mf4(path)` + `FileData(path, data, chs, units, idx=-1)`;
  the brief points the specialist at the plan's `_default_loader`
  source, not the spec.
- No `superpowers:brainstorming` invocation — request is unambiguous
  (verbatim source supplied by the plan).
- No `superpowers:writing-plans` invocation — only one specialist
  dispatch, well below the >3 threshold; the plan itself already
  serves that role.
