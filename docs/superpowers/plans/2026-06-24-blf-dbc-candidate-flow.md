# BLF DBC Candidate Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DBC candidate detection, confirmation, recent DBC persistence, and project-level BLF/DBC bindings before opening BLF files, without exposing raw-byte UI opening.

**Architecture:** `DataLoader` gets a pure probe result for BLF/DBC compatibility. `ProjectIOMixin` owns the UI flow: build candidates, ask confirmation, retry manual DBC selection on mismatch, remember successful DBC path lists, persist recent DBC history via `QSettings`, and pass project-saved DBC bindings into BLF reloads. `project_io` stores optional DBC references per file with relative and absolute paths.

**Tech Stack:** Python, PyQt5, python-can, cantools, pytest with Qt offscreen.

---

### File Structure

- Modify `mf4_analyzer/io/loader.py`: add `BlfDbcProbe` and `DataLoader.probe_blf_dbc()`, sharing DBC loading logic with BLF decode.
- Modify `mf4_analyzer/ui/main_window/window.py`: initialize session DBC history.
- Modify `mf4_analyzer/ui/main_window/_project_io_mixin.py`: replace immediate BLF picker with candidate resolution and confirmation helpers.
- Modify `mf4_analyzer/ui/project_io.py`: add optional DBC references to project file refs and resolve them on project open.
- Modify `tests/_helpers/blf_factory.py`: add a partial-match DBC fixture helper.
- Modify `tests/test_blf_loader.py`: cover strong, weak, and no-match probe behavior.
- Modify `tests/ui/test_blf_open.py`: update UI expectations and cover candidate reuse.
- Modify `tests/ui/test_project_session.py`: cover project BLF/DBC binding save/open behavior.

### Task 1: Add BLF/DBC Probe Tests

**Files:**
- Modify: `tests/_helpers/blf_factory.py`
- Modify: `tests/test_blf_loader.py`

- [x] **Step 1: Add a partial-match DBC fixture**

Add `write_engine_only_dbc(path: Path) -> Path` to `tests/_helpers/blf_factory.py`. It should define only the `EngineData` message at frame id `0x123` with `EngineSpeed` and `Throttle` signals, using the same scale and units as `write_two_message_dbc()`.

- [x] **Step 2: Add failing probe tests**

Add three tests to `tests/test_blf_loader.py`:

```python
def test_probe_blf_dbc_reports_strong_match(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is True
    assert probe.strength == "strong"
    assert probe.matched_frame_id_count == 2
    assert probe.total_frame_id_count == 2
    assert probe.decoded_frame_count == 10
    assert set(probe.signal_names) == {"EngineSpeed", "Throttle", "Speed"}


def test_probe_blf_dbc_reports_partial_match_as_weak(tmp_path):
    dbc = write_engine_only_dbc(tmp_path / "engine.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is True
    assert probe.strength == "weak"
    assert probe.matched_frame_id_count == 1
    assert probe.total_frame_id_count == 2
    assert probe.decoded_frame_count == 5


def test_probe_blf_dbc_reports_no_match_without_raising(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_raw_blf(tmp_path / "raw.blf")

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is False
    assert probe.strength == "none"
    assert probe.decoded_frame_count == 0
```

- [x] **Step 3: Run probe tests and verify RED**

Run:

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py -q
```

Expected before implementation: fail with `AttributeError` for missing
`DataLoader.probe_blf_dbc` or import failure for `write_engine_only_dbc`.

### Task 2: Implement Loader Probe

**Files:**
- Modify: `mf4_analyzer/io/loader.py`
- Modify: `tests/test_blf_loader.py`

- [x] **Step 1: Add `BlfDbcProbe`**

Add a frozen dataclass with these fields:

```python
dbc_paths: tuple[str, ...]
total_frame_count: int
total_frame_id_count: int
matched_frame_count: int
matched_frame_id_count: int
decoded_frame_count: int
decoded_signal_count: int
signal_names: tuple[str, ...]
```

Add properties `is_match`, `decoded_frame_ratio`, `matched_frame_id_ratio`,
and `strength`.

- [x] **Step 2: Share DBC loading**

Extract current DBC loading from `_decode_blf_with_dbc()` into
`_load_dbc_database(dbc_paths)`.

- [x] **Step 3: Add probe helper and public method**

Implement `_probe_blf_dbc_frames(frames, dbc_paths)` and
`DataLoader.probe_blf_dbc(fp, dbc_paths)`.

- [x] **Step 4: Run loader tests and verify GREEN**

Run:

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py -q
```

Expected: all BLF loader tests pass.

### Task 3: Add UI Flow Tests

**Files:**
- Modify: `tests/ui/test_blf_open.py`

- [x] **Step 1: Update raw-cancel expectation**

Rename `test_load_one_routes_blf_raw_when_dbc_skipped` to
`test_load_one_cancelled_dbc_selection_leaves_blf_unopened`. Patch the helper
that asks whether to select a DBC to return `True`, patch `_prompt_blf_dbc` to
return `[]`, call `_load_one()`, and assert `len(mw.files) == 0`.

- [x] **Step 2: Add session reuse test**

Add a test that opens one BLF via manual DBC selection, then opens a second BLF
with the same DBC remembered. Patch candidate confirmation to return `"use"`
and patch `_prompt_blf_dbc` to fail if called for the second BLF.

- [x] **Step 3: Run UI tests and verify RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_blf_open.py -q
```

Expected before implementation: fail because cancel still opens raw bytes and
candidate reuse helpers do not exist.

### Task 4: Implement BLF DBC UI Resolution

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`

- [x] **Step 1: Initialize DBC history**

Add `self._blf_dbc_history = []` in `MainWindow.__init__`.

- [x] **Step 2: Replace direct BLF prompt**

Change the `.blf` branch in `_load_one()` to call
`_resolve_blf_dbc_paths(p)`. If it returns `None`, show a canceled status and
return without registering a file. If it returns paths, load the BLF with those
paths, register the file with BLF source metadata, remember the paths, and show
the existing success toast.

- [x] **Step 3: Add candidate helpers**

Add helpers to `ProjectIOMixin`:

- `_remember_blf_dbc_paths(dbc_paths)`
- `_candidate_blf_dbc_paths(path)`
- `_probe_blf_dbc_candidates(path)`
- `_resolve_blf_dbc_paths(path)`
- `_choose_blf_dbc_with_retry(path)`

- [x] **Step 4: Add prompt helpers**

Add helpers with small return contracts so tests can patch them:

- `_ask_open_blf_dbc_dialog(path, message, icon=QMessageBox.Information) -> bool`
- `_ask_blf_dbc_candidate_action(path, candidate) -> "use" | "choose" | "cancel"`
- `_ask_multiple_blf_dbc_candidates(path, candidates) -> list[str] | "choose" | None`
- `_ask_blf_dbc_mismatch_action(path, dbc_paths) -> "retry" | "cancel"`

- [x] **Step 5: Run UI tests and verify GREEN**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_blf_open.py -q
```

Expected: all BLF UI dispatch tests pass.

### Task 5: Focused Regression Verification

**Files:**
- No source changes unless tests reveal a defect.

- [x] **Step 1: Run focused BLF checks**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py tests/ui/test_blf_open.py -q
```

Expected: all selected tests pass.

- [x] **Step 2: Run diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files are modified plus the new
spec and plan.

### Task 6: Persist Recent DBC History

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Test: `tests/ui/test_blf_open.py`

- [x] **Step 1: Write failing recent-history test**

Add a test that injects a temporary `QSettings` store, opens one BLF with a
manual DBC choice, constructs a fresh `MainWindow`, and opens a second BLF by
confirming the persisted candidate without opening the picker again.

- [x] **Step 2: Run UI BLF tests and verify RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_blf_open.py -q
```

Expected before implementation: the fresh `MainWindow` does not have the
previous DBC candidate.

- [x] **Step 3: Implement QSettings-backed recent DBC history**

Add helper methods for loading/saving recent DBC path lists. `_remember_blf_dbc_paths`
should update both the in-memory list and QSettings. Missing DBC files should be
pruned when history is loaded or saved.

- [x] **Step 4: Run UI BLF tests and verify GREEN**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_blf_open.py -q
```

Expected: all BLF UI tests pass.

### Task 7: Persist Project BLF/DBC Binding

**Files:**
- Modify: `mf4_analyzer/ui/project_io.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Test: `tests/ui/test_project_session.py`

- [x] **Step 1: Write failing project-binding test**

Add a test that saves a project after opening a BLF with a DBC, verifies the
`.tlproj` stores a DBC reference, then reopens the project with the DBC picker
patched to fail. The reopen should load the BLF using the saved binding.

- [x] **Step 2: Run project session test and verify RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_project_session.py::test_project_roundtrip_restores_blf_dbc_binding_without_picker -q
```

Expected before implementation: no DBC binding is saved or project reopen tries
to invoke the normal DBC picker.

- [x] **Step 3: Implement optional project DBC refs**

Add project IO structures for DBC path refs, write them when saving BLF-backed
`FileData`, resolve them on project open, and pass them into `_load_one()` as a
verified preferred DBC binding.

- [x] **Step 4: Run project binding test and verify GREEN**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_project_session.py::test_project_roundtrip_restores_blf_dbc_binding_without_picker -q
```

Expected: the test passes.

### Task 8: Final Focused Regression Verification

**Files:**
- No source changes unless tests reveal a defect.

- [x] **Step 1: Run BLF and project persistence checks**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py tests/ui/test_blf_open.py tests/ui/test_project_session.py::test_project_roundtrip_restores_blf_dbc_binding_without_picker -q
```

Expected: all selected tests pass.

- [x] **Step 2: Run diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; status includes only intended BLF/DBC files,
spec, plan, and any pre-existing unrelated dirty paths.
