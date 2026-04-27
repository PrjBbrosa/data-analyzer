# Wave-3 Review - Batch Blocks Redesign

**Date:** 2026-04-27
**Commit reviewed:** 9b45b1c
**Reference commit:** 63edc21 (squad artifact only)
**Reviewer:** Codex Wave-3 Review
**Verdict:** APPROVED

## Summary
Verdict: APPROVED. The Wave 3 feature diff is limited to the two intended new files, and the implementation matches the Wave 3 plan source blocks verbatim. The serialization whitelist and schema-version behavior conform to spec section 4.2, and the explicit UTF-8 JSON file I/O issue is resolved in `4013be7`.

## Commit Scope Check (forbidden file leak check)
`git show 9b45b1c --stat` reports only the two in-scope new files:

```text
 mf4_analyzer/batch_preset_io.py | 73 +++++++++++++++++++++++++++++++++
 tests/test_batch_preset_io.py   | 90 +++++++++++++++++++++++++++++++++++++++++
 2 files changed, 163 insertions(+)
```

`git show 9b45b1c --name-only --format=` reports:

```text
mf4_analyzer/batch_preset_io.py
tests/test_batch_preset_io.py
```

Forbidden file leak check: PASS. No changes appear in `mf4_analyzer/batch.py`, `mf4_analyzer/ui/**`, `tests/test_batch_runner.py`, or `tests/test_batch_preset_dataclass.py`.

Forbidden symbol grep over `git show 9b45b1c` for `BatchRunner`, `_expand_tasks`, `_resolve_files`, `BatchProgressEvent`, `_LoadFailure`, `_default_loader`, `_run_one`, `batch.py`, and `mf4_analyzer/ui/` returned no matches. Current HEAD also has no diff from `9b45b1c` for `mf4_analyzer/batch_preset_io.py` or `tests/test_batch_preset_io.py`.

## Test Results
```text
py -3 -m pytest tests/test_batch_preset_io.py -v --basetemp=.pytest-tmp -p no:cacheprovider
============================= test session starts =============================
collected 7 items
tests/test_batch_preset_io.py::test_round_trip_preserves_recipe PASSED   [ 14%]
tests/test_batch_preset_io.py::test_serialization_whitelist PASSED       [ 28%]
tests/test_batch_preset_io.py::test_schema_version_written_as_1 PASSED   [ 42%]
tests/test_batch_preset_io.py::test_missing_schema_version_treated_as_v1 PASSED [ 57%]
tests/test_batch_preset_io.py::test_unknown_schema_version_rejected PASSED [ 71%]
tests/test_batch_preset_io.py::test_corrupt_json_raises PASSED           [ 85%]
tests/test_batch_preset_io.py::test_round_trip_preserves_chinese_signal_names PASSED [100%]
============================== 7 passed in 3.19s ==============================
```

Command:

```text
py -3 -m pytest tests/test_batch_preset_dataclass.py tests/test_batch_runner.py -v --basetemp=.pytest-tmp -p no:cacheprovider
```

Result: PENDING due to environment failure. Pytest collected 25 items; the 4 dataclass tests and `test_supported_methods_excludes_removed_order_rpm` passed, and 20 runner tests errored during setup on `.pytest-tmp`:

```text
E           PermissionError: [WinError 5] 拒绝访问。: '\\\\?\\D:\\Pycharm_file\\MF4-data-analyzer\\data-analyzer\\.pytest-tmp'
================== 5 passed, 20 warnings, 20 errors in 6.92s ==================
```

Per the review instructions, the remaining combined-suite result is recorded as environment-pending rather than a code failure.

## Re-run note
Original codex sandbox could not write .pytest-tmp (Windows %TEMP% lock); main shell re-run with the standard --basetemp=.pytest-tmp -p no:cacheprovider workaround returned 7/7 green. UTF-8 encoding fix landed in 4013be7 with a Chinese round-trip pin test.

## Spec / Plan Conformance (§4.1 whitelist, §4.2 IO protocol, plan verbatim-match)
- PASS: Plan Step 1 test source is verbatim. `docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md:949-1040` matches `tests/test_batch_preset_io.py:1-90`.
- PASS: Plan Step 3 module source is verbatim. `docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md:1052-1126` matches `mf4_analyzer/batch_preset_io.py:1-73`.
- PASS: Spec section 4.2 defines the API surface as `save_preset_to_json(...)` and `load_preset_from_json(...)` at `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md:265-268`; the module implements both at `mf4_analyzer/batch_preset_io.py:22` and `mf4_analyzer/batch_preset_io.py:41`.
- PASS: Spec section 4.2 defines JSON schema v1 with `schema_version`, `name`, `method`, `target_signals`, `rpm_channel`, `params`, and `outputs.{export_data, export_image, data_format}` at `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md:270-288`; the serializer builds exactly those keys at `mf4_analyzer/batch_preset_io.py:25-37`.
- PASS: Spec section 4.2 requires explicit whitelist serialization and excludes runtime fields at `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md:291-300`; the implementation does not call `dataclasses.asdict` and only writes the explicit payload at `mf4_analyzer/batch_preset_io.py:25-37`.
- PASS: Spec section 4.2 version handling requires write v1, missing version as v1, and unknown versions as `UnsupportedPresetVersion` at `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md:293-298`; implementation writes `SCHEMA_VERSION = 1` at `mf4_analyzer/batch_preset_io.py:15` and checks versions at `mf4_analyzer/batch_preset_io.py:52-59`.

## Invariant Analysis
- 8a PASS: `save_preset_to_json` emits only `schema_version`, `name`, `method`, `target_signals`, `rpm_channel`, `params`, and `outputs` with `export_data`, `export_image`, `data_format` at `mf4_analyzer/batch_preset_io.py:25-37`. Runtime/sentinel fields (`file_ids`, `file_paths`, `signal`, `rpm_signal`, `signal_pattern`) and identity/timestamp-style fields (`id`, `created_at`, `updated_at`) are absent because the payload is a closed literal whitelist.
- 8b PASS: `UnsupportedPresetVersion` subclasses `ValueError` at `mf4_analyzer/batch_preset_io.py:18`.
- 8c PASS: missing `schema_version` is treated as v1 at `mf4_analyzer/batch_preset_io.py:52-54`.
- 8d PASS: `json.JSONDecodeError` is converted to `ValueError` with exception chaining at `mf4_analyzer/batch_preset_io.py:45-48`.
- 8e PASS: non-dict top-level JSON raises `ValueError` at `mf4_analyzer/batch_preset_io.py:49-50`.
- 8f PASS: `load_preset_from_json` reconstructs through `AnalysisPreset.free_config(...)` without passing `file_ids` or `file_paths` at `mf4_analyzer/batch_preset_io.py:62-73`. The free-config factory rejects those fields at `mf4_analyzer/batch.py:77-89`.
- 8g PASS: missing `outputs` defaults to `BatchOutput(export_data=True, export_image=True, data_format='csv')` via `outputs_raw = raw.get("outputs") or {}` and defaults at `mf4_analyzer/batch_preset_io.py:61-72`; those are also the dataclass defaults at `mf4_analyzer/batch.py:27-31`.
- 8h PASS: target signals serialize as a list at `mf4_analyzer/batch_preset_io.py:29` and load back as a tuple at `mf4_analyzer/batch_preset_io.py:66`.

## Footguns
Resolved in 4013be7: `path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")` and `path.read_text(encoding="utf-8")` now make preset JSON I/O explicit for non-ASCII content on Windows. The new pin test `test_round_trip_preserves_chinese_signal_names` regression-pins the invariant.

## Verdict
APPROVED.

Blockers: None.

Wave 4 may proceed.
