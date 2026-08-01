# Task 10 Implementation Report

## Outcome

Task 10 adds a frozen public-renderer probe for `BatchTimeFigureSpec`, a real
two-source/two-channel grouped time-domain acceptance CLI, and a Matplotlib
3.11-compatible frozen font-pruning contract. The final Full and Lite package
commands both exited 0, both executables exist, both frozen render smoke JSON
files report success with 12 artifacts, and the post-build grouped acceptance
CLI reports `status=success`.

Product commits:

- `6382ff3` - `Preserve Matplotlib frozen fallback font`
- `358d371` - `Cover grouped time exports in frozen acceptance`

## TDD Evidence

### Frozen spec smoke

The new test wraps the real public `render_batch_image` function, records the
payload passed by the smoke harness, then opens the real PNG and asserts it is
nonempty and exactly 640 x 360. It does not grep source text.

- RED: `1 failed, 4 passed in 52.75s`; the first time payload was the legacy
  DataFrame rather than `BatchTimeFigureSpec`.
- GREEN after replacing only the smoke time payload: `5 passed in 46.48s`.

The existing 12-output CLI contract remains four kinds x three formats.

### Grouped acceptance CLI

The CLI test launches the module with the exact public arguments
`--output-dir` and `--result-json`.

- RED: `1 failed in 0.23s`; Python reported that
  `mf4_analyzer.batch_time_group_acceptance` did not exist.
- GREEN: `1 passed in 3.09s`.

The harness creates two real CSV files, reads each back into a `FileData`, and
runs `speed` and `accel` through the production `BatchRunner`. It verifies
manifest artifact facts/checksums and exact member task/source linkage.

### Matplotlib 3.11 frozen compatibility

The first exact Full build discovered a real packaging regression: Matplotlib
3.11.1 defaults `font.enable_last_resort=True`, while the frozen pruning
contract deleted `LastResortHE-Regular.ttf`. The first build completed
PyInstaller but the frozen renderer failed before its first output with a
`FileNotFoundError`; build exit was 1. Copying only that font back into the
failed diagnostic dist made the unchanged frozen verifier pass all 12 outputs,
closing the root-cause hypothesis.

With ownership explicitly extended to the pruning contract:

- RED: `1 failed, 3 passed`; the prune test proved LastResort was removed.
- GREEN: `9 passed in 44.15s` for the pruning-contract and frozen-smoke files.
- Final owned-scope gate: `10 passed in 39.71s`.

The contract now keeps exactly four DejaVu faces plus
`LastResortHE-Regular.ttf`; its test also proves unrelated DejaVu Mono and STIX
fonts are still removed.

## Acceptance JSON

The Step 4 CLI and the required post-build rerun both exited 0. The final JSON
reported:

| Mode | Tasks | Data | Images | Groups | Exact linkage |
| --- | ---: | ---: | ---: | ---: | --- |
| none | 4 | 4 | 4 | 0 | true |
| source | 4 | 4 | 2 | 2 | true |
| channel | 4 | 4 | 2 | 2 | true |

Deleted-image recovery reported:

- `csv_bytes_unchanged=true`
- `csv_mtimes_unchanged=true`
- `deleted_image_recreated=true`
- `resumed_task_count=4`
- 26 unique, existing generated paths in the final evidence JSON

## Regression Partitions

All commands used the repository virtual environment, `PYTHONPATH=.`,
`QT_QPA_PLATFORM=offscreen` where applicable, and unique worktree-local
basetemps.

### Focused feature gate

Result: `607 passed, 6 failed in 52.34s`.

The six failures exactly match the Task 8/9 pre-edit baseline: four disk-probe
state/timeout nodes, the narrow method-button node, and the Windows QUrl
slash-comparison node. There were zero new focused failures.

### Non-UI partition

Result: `1416 passed, 18 skipped, 2 deselected, 14 failed, 1 warning in
105.58s`.

All 14 failures were rerun against a detached `3d4604e` worktree with the same
environment and reproduced exactly:

1. `tests/test_acquisition_config_store.py::test_save_a2l_path_preserves_existing_transport`
2. `tests/test_acquisition_config_store.py::test_save_a2l_path_round_trip`
3. `tests/test_batch_source_integration.py::test_disk_multi_group_policy_uses_loaded_logical_channel_sets[available_per_source-expected_pairs1]`
4. `tests/test_batch_source_integration.py::test_disk_multi_group_policy_uses_loaded_logical_channel_sets[common-expected_pairs0]`
5. `tests/test_batch_source_integration.py::test_legacy_file_paths_migrate_to_all_registry_logical_sources`
6. `tests/test_batch_source_integration.py::test_three_disk_sources_stay_lazy_and_compute_file_major`
7. `tests/test_blf_dbc_candidates.py::test_candidate_identity_is_order_independent_and_path_normalized`
8. `tests/test_cli_vector_backend.py::test_make_vector_backend_raises_on_non_windows`
9. `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_binds_executable_sha_to_frozen_smoke`
10. `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_rejects_manifest_source_not_in_requested_set`
11. `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_uses_batch_runner_for_three_mf4_csv_pdf_sets`
12. `tests/test_gen_help_screenshots.py::test_import_screenshot_uses_real_checked_in_samples`
13. `tests/test_gen_help_screenshots.py::test_synthetic_csv_has_eps_channels`
14. `tests/test_vector_xcp_backend.py::test_vector_backend_is_refused_before_native_import_on_non_windows`

Detached comparison result: `14 failed, 1 warning in 2.03s`; zero difference.

### Acquisition UI partition

Result: `349 passed, 1 skipped, 5 failed in 29.73s`. The detached baseline
reproduced all five in `3.57s`:

1. `tests/acquisition_ui/test_config_path_persistence.py::test_apply_a2l_persists_and_rehydrates`
2. `tests/acquisition_ui/test_output_dir_display.py::test_compact_path_display_rules`
3. `tests/acquisition_ui/test_output_dir_display.py::test_set_output_dir_updates_selector_and_tooltip`
4. `tests/acquisition_ui/test_record_backend_swap.py::test_begin_connection_blocks_fake_when_vector_unavailable`
5. `tests/acquisition_ui/test_review_handoff.py::test_analyzer_load_file_delegates_to_load_one`

### UI per-file partition

All 128 `tests/ui/test_*.py` files ran in independent pytest processes with
independent basetemps and logs. 113 files exited 0. The 15 nonzero files were
rerun independently at detached `3d4604e`; every exit code and pytest summary
matched exactly:

- `test_batch_input_panel.py`: 4 failed, 44 passed
- `test_batch_method_buttons.py`: 1 failed, 33 passed
- `test_batch_smoke.py`: 1 failed, 28 passed
- `test_blf_batch_import.py`: exit `-1073741819` (`0xC0000005`)
- `test_channel_widget_setters.py`: 3 failed, 5 passed
- `test_head_hdf_rail.py`: 3 failed, 8 passed
- `test_hints.py`: 1 failed, 23 passed
- `test_main_window_smoke.py`: 4 failed, 111 passed
- `test_message_box_buttons.py`: exit `-1073741819` (`0xC0000005`)
- `test_pg_dense_raster.py`: 1 failed, 22 passed
- `test_pg_timedomain_canvas.py`: 1 failed, 381 passed, 1 deselected
- `test_split_focus_routing.py`: 18 failed
- `test_split_per_pane_controls.py`: 23 failed
- `test_split_routing.py`: 6 failed, 1 passed
- `test_task4_cache_invalidation.py`: 1 failed, 12 passed

The two access-violation files were isolated and could not hide any other UI
result. Current and baseline summaries are retained under `.state`; zero new UI
failure or crash was introduced.

## Windows Package Gates

The exact required commands were run without `-SkipInstall`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1 -AppName TraceLabBatchV3Full -Console -KeepPrevious
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows_folder_lite.ps1 -AppName TraceLabBatchV3Lite -Console -KeepPrevious
```

Final results:

| Package | Exit | Executable | Bytes | Smoke JSON |
| --- | ---: | --- | ---: | --- |
| TraceLabBatchV3Full | 0 | `dist/TraceLabBatchV3Full/TraceLabBatchV3Full.exe` | 36,808,647 | `ok=true`, frozen runtime, 12 artifacts |
| TraceLabBatchV3Lite | 0 | `dist/TraceLabBatchV3Lite/TraceLabBatchV3Lite.exe` | 27,942,380 | `ok=true`, frozen runtime, 12 artifacts |

Both smoke JSON files also report extractable PDF text, nonempty PDF visuals,
no CJK glyph warnings, and the expected Turbo samples. Both prune JSON files
record the exact five-font kept set.

## Plan Self-Review Checklist

- [x] Every new parameter has one normalization owner, one runtime default owner and a time-only gate.
- [x] Default params, task identity, task stem and manifest schema/shape compatibility have behavior tests; no test compares volatile whole-manifest bytes.
- [x] Renderer probe occurs before every reservation on every image path.
- [x] Default task publication and explicit group publication are separate, non-contradictory contracts.
- [x] Group journal state is persisted during the run, not only at finalization.
- [x] Resume validates every member source stat; retry cannot rewrite healthy data.
- [x] Preview counts the same group plan the runner executes.
- [x] OutputPanel preview and TaskList dry-run summary both consume the group-aware artifact count.
- [x] Memory constraints are byte-based and checked before spool append.
- [x] X alignment covers time mask, finite mask, regularization and downsampling.
- [x] X label reaches the rendered bottom axis and OutputPanel.
- [x] Empty series, mixed X units, third Y unit and dual-Y manual limits have explicit outcomes.
- [x] UI default serialization, preset pass-through, whole-row hiding and 288 px geometry are tested.
- [x] No placeholder, stale revision directive or cross-stem singleton atomicity requirement remains.

The focused 613-node branch feature surface (607 passing plus the six exact
recorded baseline failures), the acceptance runner, the frozen matrix, and the
Task 1-9 reports collectively provide the checklist evidence.

## Lesson Gate and Concerns

`scripts/lessons/check.py --status` reports `lesson_required: False`,
`candidate_exists: False`, and `selected_lessons_state: True`. No duplicate
lesson was added: the checked-in
`matplotlib-pruning-needs-frozen-render-matrix` lesson already owns this rule,
and the precise pruning regression test plus both frozen package matrices are
the new executable protection.

No Task 10 functional concern remains. Generated `dist/`, `.state/`, build
outputs, and build-updated acquisition evidence are intentionally excluded
from the product commits. The detached baseline registration was removed, but
Windows could not delete its long-path evidence directory; the residual is
under the worktree-local `.state/task10-baseline-3d4604e-20260801-a` only and
is not committed.
