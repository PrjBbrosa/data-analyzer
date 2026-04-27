# Decomposition — batch-blocks-redesign Wave 1

**Date:** 2026-04-27
**Top-level request:** Execute Wave 1 of the batch-blocks-redesign plan
(`AnalysisPreset` extension + factory invariants).
**Mode:** plan
**Plan file:** `docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md`
(§Wave 1, lines 101–294)
**Spec file:** `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md`
(§4.1)

## Routing rationale

Wave 1 is a single, self-contained dataclass extension on
`mf4_analyzer/batch.py:31-66` plus one new pytest module. The change is
pure data-modeling with numerical-correctness adjacency (preserves the
existing `from_current_single` / `free_config` path used by
`BatchRunner._expand_tasks`). Per the specialist roster, this matches
`signal-processing-expert` (keywords: batch, loader-adjacent, dataclass
backing the numerical pipeline). One specialist, no parallelism, no
cross-domain split — so no rework risk to enumerate.

The plan explicitly forbids touching `BatchRunner`, and the wave brief
already enumerates the negative space (no UI, no IO, no relocation). We
fold the test creation, the dataclass edit, and the regression-pass on
`tests/test_batch_runner.py` into a single specialist envelope to avoid
the "move-then-tighten" cross-specialist pattern documented in
`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W1: Extend `AnalysisPreset` with `target_signals` / `file_ids` / `file_paths`, enforce factory invariants, add 4-test pytest module, keep `tests/test_batch_runner.py` green | `signal-processing-expert` | (none) | Single-file dataclass change on the numerical-pipeline boundary; specialist already owns `mf4_analyzer/batch.py` per the wave routing table. |

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index.
- `docs/lessons-learned/.state.yml` — cadence (13 / 0; no prune due).
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — confirms keeping body + tests + invariant enforcement inside one specialist envelope is correct here (no metadata/import split needed).
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — drives the explicit `forbidden_symbols` list (`BatchRunner`, `_expand_tasks`, `_resolve_files`, `BatchProgressEvent`) and the `symbols_touched` reporting requirement in the brief.

## Notes

- Plan example uses macOS path `/Users/donghang/Downloads/data analyzer`;
  this checkout is on Windows (`D:\Pycharm_file\MF4-data-analyzer\data-analyzer`).
  Brief instructs the specialist to run pytest from the repo root using
  relative module paths (`pytest tests/test_batch_preset_dataclass.py -v`),
  not the macOS absolute path.
- No `superpowers:brainstorming` invocation — request is unambiguous.
- No `superpowers:writing-plans` invocation — only one specialist
  dispatch, well below the >3 threshold.
