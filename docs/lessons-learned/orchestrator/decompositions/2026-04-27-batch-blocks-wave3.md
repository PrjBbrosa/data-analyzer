# Decomposition — batch-blocks-redesign Wave 3

**Date:** 2026-04-27
**Top-level request:** Execute Wave 3 of the batch-blocks-redesign plan
(`batch_preset_io.py` JSON IO — recipe-only serialization with schema versioning).
**Mode:** plan
**Plan file:** `docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md`
(§Wave 3, lines 925–1155)
**Spec file:** `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md`
(§4.1 serialization whitelist + §4.2 IO protocol)

## Routing rationale

Wave 3 is a self-contained, pure-Python JSON IO module that sits on
the numerical-pipeline / preset boundary owned by `signal-processing-expert`.
It creates exactly two new files:

- `mf4_analyzer/batch_preset_io.py` (new module, ~74 lines, verbatim source supplied by the plan)
- `tests/test_batch_preset_io.py` (6 tests, verbatim source supplied by the plan)

There is no UI surface, no relocation/refactor of existing code, no
import-graph reshuffle, and no edit to any module outside the two new
files. Per the specialist roster, this maps to `signal-processing-expert`
on the `loader` / `MDF` / channel-recipe axis (the module is the persistence
half of `AnalysisPreset`, which W1 placed under `signal-processing-expert`
ownership). `pyqt-ui-engineer` and `refactor-architect` are not appropriate:
no widget/QSS work, and no package relocation.

The plan supplies verbatim source for both files. Folding module body +
tests into one specialist envelope is the same shape used in W1 and W2
(Codex-approved both times) and avoids the `move-then-tighten`
cross-specialist rework pattern documented in
`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`.

The brief enumerates a forbidden-files-and-symbols list (W1/W2 territory
and W4+ territory) per
`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`,
and requires the specialist to return `symbols_touched` plus a
`forbidden_symbols_check` self-attestation.

The brief also explicitly names
`signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`
as a cross-check obligation: before pasting the plan-verbatim
`load_preset_from_json` body, verify `AnalysisPreset.free_config` still
accepts the keyword arguments the plan calls (it does — W1 added
`target_signals` to the factory signature; cfb301b's earlier removal of
`order_rpm` does not affect this module because IO does not gate on
method names). This eliminates the ghost-handler failure mode without
adding work.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W3: Create `mf4_analyzer/batch_preset_io.py` (`SCHEMA_VERSION=1`, `UnsupportedPresetVersion`, `save_preset_to_json`, `load_preset_from_json`) and `tests/test_batch_preset_io.py` (6 tests) per the plan-verbatim source; reconstruct presets via `AnalysisPreset.free_config(...)`; whitelist-serialize only `name`/`method`/`target_signals`/`rpm_channel`/`params`/`outputs.{export_data,export_image,data_format}`; never persist `file_ids`/`file_paths`/`signal`/`rpm_signal`/`signal_pattern`/`outputs.directory`; tolerate missing `schema_version` as v1, reject unknown versions with `UnsupportedPresetVersion`, surface bad JSON as `ValueError`; keep all existing tests green | `signal-processing-expert` | (none — W1 + W2 already merged + Codex-approved) | Two-new-file IO module on the preset/numerical-pipeline boundary; same envelope shape as W1/W2 (single specialist, body + tests bundled). No UI surface, no relocation, so no other expert applies. |

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index.
- `docs/lessons-learned/.state.yml` — cadence (15 / 0; no prune due, threshold is ≥20).
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — supports keeping module body + tests in one envelope; no metadata/import split warranted.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — drives the explicit forbidden files/symbols list and the `symbols_touched` reporting requirement.
- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md` — a plan-verbatim-source obligation; cross-check `free_config` kwargs still match the live W1 factory before pasting.
- `docs/lessons-learned/orchestrator/decompositions/2026-04-27-batch-blocks-wave1.md` — confirms W1 envelope shape; W3 mirrors it.
- `docs/lessons-learned/orchestrator/decompositions/2026-04-27-batch-blocks-wave2.md` — confirms W2 envelope shape; W3 mirrors it.

## Notes

- Windows checkout: pytest invocation is the workaround command
  `py -3 -m pytest tests/test_batch_preset_io.py -v --basetemp=.pytest-tmp -p no:cacheprovider`,
  carried verbatim in the brief.
- The plan's Step 5 `git commit` block is rewritten in the brief to
  "do NOT commit yet — main Claude commits after Phase 3 aggregation"
  per the executor split.
- No `superpowers:brainstorming` invocation — request is unambiguous (verbatim source supplied by the plan).
- No `superpowers:writing-plans` invocation — only one specialist dispatch, well below the >3 threshold; the plan itself already serves that role.
