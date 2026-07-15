# TDMS Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open NI TDMS measurement files in TraceLab with correct numeric channels, engineering units, and waveform time axes.

**Architecture:** Add a lazy `nptdms`-backed `DataLoader.load_tdms` that turns numeric TDMS channels into the same `(DataFrame, channels, units)` contract as MF4. A waveform increment from the file supplies `Time`; duplicate channel names are group-qualified. Register the loader in batch and GUI paths, and include the lazy dependency explicitly in the frozen Windows build.

**Tech Stack:** Python, pandas, NumPy, npTDMS 1.11.0, PyInstaller, pytest.

## Global Constraints

- Depend only on the base `nptdms==1.11.0` package; do not add its optional HDF/pandas extras.
- Import `nptdms` lazily and raise a clear import error when it is unavailable.
- Only ingest non-empty numeric channels; no synthetic sample rate is permitted when TDMS timing metadata is missing.
- A `.tdms_index` companion is not itself an importable data file.
- Preserve existing GUI and batch `FileData` contracts.

---

### Task 1: Define TDMS loader behavior with tests

**Files:**
- Create: `tests/test_tdms_loader.py`
- Modify: `tests/test_batch_loader_dispatch.py`

**Interfaces:**
- Produces: `DataLoader.load_tdms(fp) -> tuple[pd.DataFrame, list[str], dict[str, str]]`.
- Produces: batch dispatch of `.tdms` to `DataLoader.load_tdms`.

- [ ] **Step 1: Write failing loader tests**

Create a temporary TDMS file with `TdmsWriter` and two waveform channels that share `wf_increment=0.25`, `wf_start_offset=1.5`, and per-channel `unit_string`. Assert `Time == [1.5, 1.75, 2.0]`, numeric samples, units, and a group-qualified duplicate channel name.

- [ ] **Step 2: Run the loader test to verify it fails**

Run: `python -m pytest tests/test_tdms_loader.py -q -p no:cacheprovider`

Expected: failure because `DataLoader.load_tdms` does not exist.

- [ ] **Step 3: Write a failing batch-dispatch test**

Patch `DataLoader.load_tdms`, load a `.tdms` path through `_default_loader`, and assert the TDMS loader received that path.

- [ ] **Step 4: Run the batch test to verify it fails**

Run: `python -m pytest tests/test_batch_loader_dispatch.py -q -p no:cacheprovider`

Expected: failure because `.tdms` currently falls through to the MF4 loader.

### Task 2: Implement TDMS parsing and product integration

**Files:**
- Modify: `requirements.txt`
- Modify: `mf4_analyzer/io/loader.py`
- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Modify: `tests/ui/test_weighting_ui.py`

**Interfaces:**
- Consumes: `nptdms.TdmsFile.read(fp)` groups and channels.
- Produces: a frame with a verified `Time` column and numeric signal columns.

- [ ] **Step 1: Add the pinned base dependency**

Add `nptdms==1.11.0` to `requirements.txt` with a comment that it is the base NI TDMS reader.

- [ ] **Step 2: Implement `DataLoader.load_tdms`**

Read the file lazily, collect non-empty numeric channels, use duplicate-aware display names, preserve each `unit_string`, and construct a time axis from a channel with finite positive `wf_increment` plus optional `wf_start_offset`. Raise `ValueError` if there are no numeric channels or no usable waveform timing metadata.

- [ ] **Step 3: Register the file type in batch and GUI paths**

Route `.tdms` explicitly to `load_tdms`; add `*.tdms` to GUI open/drop filters. Do not add `*.tdms_index`.

- [ ] **Step 4: Extend the GUI filter assertion**

Assert that each open dialog filter includes `*.tdms` and none includes `*.tdms_index`.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_tdms_loader.py tests/test_batch_loader_dispatch.py tests/ui/test_weighting_ui.py -q -p no:cacheprovider`

Expected: all tests pass.

### Task 3: Ensure frozen-build inclusion and validate the provided file

**Files:**
- Modify: `tools/build_windows_folder.ps1`
- Modify: `tests/test_windows_build_script.py`

**Interfaces:**
- Produces: PyInstaller receives `--hidden-import nptdms` even though the parser is lazily imported.

- [ ] **Step 1: Write a failing packaging assertion**

Assert that the Windows build script contains `nptdms` in `$HiddenImports`.

- [ ] **Step 2: Run it to verify the assertion fails**

Run: `python -m pytest tests/test_windows_build_script.py -q -p no:cacheprovider`

Expected: failure because the lazy import is not presently visible to PyInstaller.

- [ ] **Step 3: Add the hidden import and re-run tests**

Add `"nptdms"` to `$HiddenImports`, then repeat the packaging test and focused loader tests.

- [ ] **Step 4: Validate the supplied TDMS file**

Run `DataLoader.load_tdms` on `D:\Coding project\data analyzer\testdoc\63_BNB_002_Auto_20260715.tdms` and record row count, signal count, time interval, and sample rate. This validates the actual production format rather than only a synthetic writer fixture.

- [ ] **Step 5: Commit**

Run: `git add requirements.txt mf4_analyzer/io/loader.py mf4_analyzer/batch.py mf4_analyzer/ui/main_window/_project_io_mixin.py tools/build_windows_folder.ps1 tests/test_tdms_loader.py tests/test_batch_loader_dispatch.py tests/ui/test_weighting_ui.py tests/test_windows_build_script.py docs/superpowers/plans/2026-07-15-tdms-import.md && git commit -m "feat(import): add TDMS file support"`

## Self-Review

- The loader, batch execution, GUI selection/drop, frozen packaging, and a real-file check all have explicit tasks.
- No optional TDMS extras, guessed rate, or `.tdms_index` import route is included.
- The loader method name and three-item return contract are consistent in every task.
