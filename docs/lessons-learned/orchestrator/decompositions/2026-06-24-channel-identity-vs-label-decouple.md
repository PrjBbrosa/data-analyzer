# Decomposition — channel identity vs display-label decouple (multi-file, same-name collision root fix)

- **Date:** 2026-06-24
- **Mode:** plan
- **Slug:** channel-identity-vs-label-decouple
- **Trigger:** user said "优化" (no squad keyword) — routed under CLAUDE.md "漏触发" because this is a cross-module, multi-specialist identity/label refactor.
- **Top-level request (user verbatim):** "你按照稳健的方式优化吧，长文件中间可以省略号" — robustly fix the bug where, with multiple files containing same-named channels, checking all then un-checking individual ones makes some curves vanish; and change long-filename display labels to middle-ellipsis.

## Confirmed root cause (from dispatcher, code-verified)

1. Filename prefix truncation: `mf4_analyzer/io/file_data.py:22` `short_name = stem[:18]` (with `label_suffix`, `:27` re-truncates to 14). `get_prefixed_channel` (`:152`) builds the curve id `f"[{short_name}] {ch}"`. Files differing only past char 19 collapse to the same prefix.
2. Primary storage keys on the DISPLAY string, not on a file-distinguishing id: `overlay_axes.py:334-337` `channel_data[name]` / `_channel_lines[name]`. Same-named (and truncation-collided) channels overwrite each other; the first-bound becomes an orphan.

Key insight: the correct stable id is ALREADY in code and ALREADY used correctly by a sibling dict — `overlay_axes.py:338` `_channel_view_state_lines[_view_state_channel_key(data_id, name)]` keys on `(data_id, name)`. `data_id == fid`, plumbed from `window.py` `_build_time_plot_data` (row tuple's 7th element) through `plot_channels` (`canvas.py:467-489`, `data_id=row[6]`) into `_bind_channel`. The composite-key helper already exists: `mf4_analyzer/ui/pg_canvas/_shared.py:16` `_view_state_channel_key(data_id, name)` (json-dumps `[str(data_id), str(name)]`).

## Routing rationale

- The composite-key primitive already exists in `_shared.py` and is already used correctly. There is **no new helper module to author** and **no move/shim/import work** — so `refactor-architect` has no body here (its scope is move/shim/import only; see lesson `non-dsp-algorithmic-python-routes-to-signal-processing-expert`). Adding a refactor subtask would only manufacture cross-specialist rework on the shared `overlay_axes.py` / `canvas.py` files (see lessons `move-then-tighten`, `refactor-then-ui-same-file-boundary-disjoint`).
- All name-keyed consumers live in `pg_canvas/*.py` (canvas/renderer/cursor/annotations/overlay_axes) — PyQt canvas internals (storage dicts, viewport-envelope cache, cursor readouts, annotations, statistics). Surface-vs-computation rule: these are UI surfaces, not DSP → `pyqt-ui-engineer`.
- The middle-ellipsis display label (`file_data.py` short_name / get_prefixed_channel) is pure label formatting (appearance), not a numeric algorithm → `pyqt-ui-engineer`.
- `get_statistics` returns `stats[ch]` where the key doubles as the StatisticsPanel header (`canvas.py:1747`) — identity-vs-label coupling. Migrating keys forces a `get_statistics` return-contract change; per `return-type-change-needs-paired-callsite-update`, bundle the StatisticsPanel header consumer INTO the same UI subtask, do not split it.
- Both UI subtasks mutate files on the same branch (shared git index) and S-label edits `file_data.py` which S-identity reads → SERIALIZE (lesson `parallel-mutators-share-git-index-even-disjoint-files`). The signal verification subtask is read-only and may overlap.

## Subtasks

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S1 identity-vs-label decouple: migrate all name-keyed canvas dicts + every name-keyed consumer to the existing `(fid,name)` composite key; add a key→display-label map; change `get_statistics` to return composite-key→{stats, display_label} and adapt the StatisticsPanel header consumer | pyqt-ui-engineer | — | Substantive consumer rewiring across `pg_canvas/*.py` UI internals; the key contract change must bundle ALL name-keyed consumers as one coherent unit (return-type lesson). The composite-key primitive already exists, so this is migration, not authoring. |
| S2 display label only: change `file_data.py` long-name formatting from `[:18]` head-truncation to middle-ellipsis (`长名…尾.mf4`); keep short/non-overlong names as-is; ensure label is appearance-only and never feeds identity | pyqt-ui-engineer | S1 | Pure label-formatting/appearance change. Sequenced AFTER S1 so identity is already decoupled — the new label is provably appearance-only and cannot regress collision. Same-branch index ⇒ serialize. |
| S3 (read-only verify) confirm no numeric/DSP path keys on the display string and that per-(fid,name) curve data arrays remain numerically untouched by the key migration | signal-processing-expert | S1 | DSP/data-array correctness is signal's domain; a read-only audit that the migration is identity-only (no sample/array semantics changed) and the viewport-envelope cache keying stays numerically equivalent. |

## Lessons consulted (step 4 reads)

- docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md
- docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md
- docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md
- docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md
- docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md
- docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md

## Notes

- Single specialist (pyqt-ui-engineer) owns both mutating subtasks → serialize S1 then S2; no parallel mutation. S3 is read-only and can run concurrently with S2.
- Verify-real-render mandate (CLAUDE.md): both UI subtasks must verify actual rendering (screenshot / live curve count), not just "attribute set + unit test passed".
- This task will require 3 specialist dispatches → `superpowers:writing-plans` consideration flagged in return notes (the per-subtask briefs below carry the plan; no separate plan file needed since the decomposition table IS the plan).
