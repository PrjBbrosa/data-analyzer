# Generic ASCII Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-based loading for delimited and fixed-width ASCII data.

**Architecture:** A dedicated ASCII probe chooses a delimited or fixed-width
layout. `DataLoader.load_ascii` owns parser dispatch and returns timing metadata;
GUI and batch only register the resulting `FileData`.

**Tech Stack:** Python, pandas, pytest, PyQt5.

## Global Constraints

- No new dependency or repository.
- Accept a fixed-width layout only with an aligned header and eight stable numeric records.
- Never infer a sampling rate from a scalar unless the full metadata signature matches.
- Preserve NaN values during fixed-width import.

---

### Task 1: Add failing probe and loader tests

**Files:**
- Create: `tests/test_ascii_loader.py`
- Create: `mf4_analyzer/io/ascii_format.py`

- [ ] Write tests for a delimited ASC, a metadata-bearing fixed-width ASC,
  and a numeric block without a valid header.
- [ ] Run `pytest tests/test_ascii_loader.py -q` and observe import failure
  before the module exists.
- [ ] Implement the probe and loader-facing layout contracts.
- [ ] Re-run the test file and require all tests to pass.

### Task 2: Route real import paths

**Files:**
- Modify: `mf4_analyzer/io/loader.py`
- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Modify: `tests/test_batch_loader_dispatch.py`

- [ ] Add failing tests proving `.asc` dispatches to `load_ascii`.
- [ ] Implement `.asc` routing while preserving `.csv` and `.fdc` behavior.
- [ ] Pass recognized metadata `fs` and source metadata to `FileData`.
- [ ] Run the focused loader and batch tests.

### Task 3: Verify safety and regressions

**Files:**
- Verify: `tests/test_ascii_loader.py`
- Verify: `tests/test_csv_header_loading.py`
- Verify: `tests/test_batch_loader_dispatch.py`
- Verify: `tests/ui/test_drop_import.py`
- Verify: `tests/ui/test_weighting_ui.py`

- [ ] Run the focused suite.
- [ ] Inspect `git diff --check` and assert a no-time fixed-width input fails
  with a sampling-rate error rather than loading at 1000 Hz.
