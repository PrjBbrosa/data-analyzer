# Wave 1 Codex Review — batch-blocks-redesign

**Date:** 2026-04-27
**Commit reviewed:** 06d17a8
**Reviewer:** codex (via codex-rescue)
**Verdict:** approved

## Summary
The Wave 1 code diff conforms to the approved plan's `AnalysisPreset` dataclass and factory changes, the new preset dataclass tests pass, and the existing runner suite passes with a project-local pytest temp/cache workaround. The original runner-suite failure was environmental, not a Wave 1 code defect.

## Spec / plan conformance
- ✓ In-scope files only: `git show 06d17a8 --stat` reports changes only in `mf4_analyzer/batch.py` and `tests/test_batch_preset_dataclass.py`.
- ✓ Plan Step 1 test source is verbatim: `tests/test_batch_preset_dataclass.py` lines 1-49 match the plan's Step 1 source, including the four requested tests.
- ✓ Plan Step 3 replacement source is verbatim for `AnalysisPreset` and its factories: `mf4_analyzer/batch.py` lines 32-97 match the plan's Step 3 block.
- ✓ Spec §4.1 config field: `target_signals` is added as a tuple default at `mf4_analyzer/batch.py:44`, populated only through `free_config` at `mf4_analyzer/batch.py:94`, and rejected by `from_current_single` at `mf4_analyzer/batch.py:53-57`.
- ✓ Spec §4.1 run-time fields: `file_ids` and `file_paths` are tuple defaults at `mf4_analyzer/batch.py:46-47`; non-empty values are rejected by `from_current_single` at `mf4_analyzer/batch.py:58-62` and by `free_config` at `mf4_analyzer/batch.py:78-87`; the tested injection path is `dataclasses.replace` at `tests/test_batch_preset_dataclass.py:46`.
- ✓ Serialization boundary for run-time fields is preserved for Wave 1: the reviewed diff does not touch `mf4_analyzer/batch_preset_io.py`, and no serializer code is introduced in the diff.
- ✓ Mutable-default footgun check: new defaults are immutable tuples, not lists or dicts, at `mf4_analyzer/batch.py:44` and `mf4_analyzer/batch.py:46-47`.
- ✓ Factory guard check: invariant guards use truthy checks (`if target_signals:`, `if file_ids or file_paths:`, `if file_ids:`, `if file_paths:`) at `mf4_analyzer/batch.py:53`, `mf4_analyzer/batch.py:58`, `mf4_analyzer/batch.py:78`, and `mf4_analyzer/batch.py:83`.
- ✓ New Wave 1 tests pass: `py -3 -m pytest tests/test_batch_preset_dataclass.py -v` reports `4 passed, 1 warning in 9.27s`.
- ✓ Existing runner tests are green with project-local temp/cache workaround: `py -3 -m pytest tests/test_batch_runner.py -v --basetemp=.pytest-tmp -p no:cacheprovider` reports all 7 passed in 42.42s.

## Boundary check
- `BatchRunner`: absent
- `BatchProgressEvent`: absent
- `BatchRunResult`: absent
- `BatchItemResult`: absent
- `BatchOutput` shape changes: absent
- `mf4_analyzer/ui/**`: absent
- `mf4_analyzer/batch_preset_io.py`: absent
- `tests/test_batch_runner.py`: absent from diff; runner suite passed with project-local basetemp/cache workaround

## Tests run
`py -3 -m pytest tests/test_batch_preset_dataclass.py -v`

```text
============================= test session starts =============================
platform win32 -- Python 3.13.1, pytest-9.0.2, pluggy-1.6.0 -- D:\Python\python.exe
cachedir: .pytest_cache
PySide6 6.10.2 -- Qt runtime 6.10.2 -- Qt compiled 6.10.2
rootdir: D:\Pycharm_file\MF4-data-analyzer\data-analyzer
plugins: anyio-4.12.1, qt-4.5.0
collecting ... collected 4 items

tests/test_batch_preset_dataclass.py::test_free_config_accepts_target_signals PASSED [ 25%]
tests/test_batch_preset_dataclass.py::test_free_config_rejects_runtime_only_fields PASSED [ 50%]
tests/test_batch_preset_dataclass.py::test_from_current_single_rejects_free_config_fields PASSED [ 75%]
tests/test_batch_preset_dataclass.py::test_runtime_selection_via_replace PASSED [100%]

============================== warnings summary ===============================
..\..\..\Python\Lib\site-packages\_pytest\cacheprovider.py:475
  D:\Python\Lib\site-packages\_pytest\cacheprovider.py:475: PytestCacheWarning: could not create cache path D:\Pycharm_file\MF4-data-analyzer\data-analyzer\.pytest_cache\v\cache\nodeids: [WinError 5] 拒绝访问。: 'D:\\Pycharm_file\\MF4-data-analyzer\\data-analyzer\\.pytest_cache\\v\\cache'
    config.cache.set("cache/nodeids", sorted(self.cached_nodeids))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 4 passed, 1 warning in 9.27s =========================
```

`py -3 -m pytest tests/test_batch_runner.py -v --basetemp=.pytest-tmp -p no:cacheprovider`

```text
============================= test session starts =============================
platform win32 -- Python 3.13.1, pytest-9.0.2, pluggy-1.6.0 -- D:\Python\python.exe
PySide6 6.10.2 -- Qt runtime 6.10.2 -- Qt compiled 6.10.2
rootdir: D:\Pycharm_file\MF4-data-analyzer\data-analyzer
plugins: anyio-4.12.1, qt-4.5.0
collected 7 items

tests/test_batch_runner.py::test_current_single_fft_preset_exports_data PASSED [ 14%]
tests/test_batch_runner.py::test_current_single_fft_preset_exports_image PASSED [ 28%]
tests/test_batch_runner.py::test_current_single_fft_preset_handles_auto_nfft PASSED [ 42%]
tests/test_batch_runner.py::test_matrix_to_long_dataframe_vectorize_shape PASSED [ 57%]
tests/test_batch_runner.py::test_analysis_preset_replace_after_frozen_removed PASSED [ 71%]
tests/test_batch_runner.py::test_free_config_order_track_preset_selects_matching_signals PASSED [ 85%]
tests/test_batch_runner.py::test_batch_order_time_csv_shape PASSED       [100%]

============================= 7 passed in 42.42s ==============================
```

## Re-run note
The original failure was an environmental tmp-dir lock at %TEMP%\pytest-of-RD02689 — not a W1 code defect. Resolved by using project-local basetemp (--basetemp=.pytest-tmp -p no:cacheprovider). No code change required.

## Findings
1. nit: env workaround needed for runner suite tmp dirs on this Windows host.

## Verdict reasoning
The reviewed source changes match the Wave 1 plan and §4.1 spec, and the forbidden-boundary grep is clean. The runner suite is green when pytest uses a project-local basetemp and disables the cache provider, so the original temp-directory lock is environmental and does not block Wave 1 approval.

Wave 2 may proceed.
