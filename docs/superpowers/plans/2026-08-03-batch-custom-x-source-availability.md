# Batch Custom-X Source Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a time-chart custom X channel when it coexists with a selected target signal in at least one logical source under the `available_per_source` policy, and skip incompatible source/target pairs consistently.

**Architecture:** Keep the existing common-channel behavior for the `common` and exact-pair scopes.  For `available_per_source`, derive custom-X eligibility from each `FileListWidget` logical source row: a row contributes only when it contains both the selected target and the selected X channel.  The UI candidate list, UI dry-run, unit validation, and `BatchRunner` task expansion all use that same row-level rule.

**Tech Stack:** Python, PyQt5, pytest, pytest-qt.

## Global Constraints

- Do not special-case WWT files, sample-rate labels, source IDs, or channel names.
- Preserve the strict common-channel rule outside `available_per_source`.
- Preserve existing missing-X errors for current-single and explicit exact-pair runs.
- Test the real Qt widget state and the real runner task result.

---

### Task 1: Establish source-coexistence regressions

**Files:**
- Modify: `tests/ui/test_batch_smoke.py`
- Modify: `tests/test_batch_runner.py`

**Interfaces:**
- Consumes: `BatchSheet._build_dry_run_preview()`, `DynamicParamForm._w_x_channel`, `BatchRunner.run()`.
- Produces: failing tests proving a partial custom X is selectable and that missing-X source/target pairs are skipped.

- [ ] **Step 1: Write the UI failing test**

```python
assert form._w_x_channel.model().item(speed_index).isEnabled()
assert sheet._build_dry_run_preview() == [
    (first.filename, "target", "time"),
]
```

- [ ] **Step 2: Run the UI test to verify it fails**

Run: `set QT_QPA_PLATFORM=offscreen; .venv\\Scripts\\python.exe -m pytest tests/ui/test_batch_smoke.py -k available_policy_custom_x -q`

Expected: FAIL because a `(1/2)` custom-X candidate is disabled.

- [ ] **Step 3: Write the runner failing test**

```python
assert result.status == "done"
assert [(item.file_id, item.signal) for item in result.items] == [(0, "sig")]
```

- [ ] **Step 4: Run the runner test to verify it fails**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_batch_runner.py -k available_per_source_custom_x -q`

Expected: FAIL because the source without the custom X becomes a failed task.

### Task 2: Unify candidate, preview, validation, and task planning

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Modify: `mf4_analyzer/batch.py`

**Interfaces:**
- Consumes: logical source row `channels`, selected target signals, `target_policy`, and time params `x_source` / `x_channel`.
- Produces: `DynamicParamForm.set_x_channel_candidates(..., partial_selectable=...)`; only compatible `(source, target)` pairs in dry-run and runner plans.

- [ ] **Step 1: Implement partial-candidate enablement**

```python
form.set_x_channel_candidates(common, partial, partial_selectable=compatible)
```

Only compatible partial X candidates remain selectable under `available_per_source`; retaining a now-incompatible X clears the selection with validation feedback.

- [ ] **Step 2: Implement the BatchSheet row-level helper**

```python
compatible_rows = [
    row for row in loaded_rows
    if x_channel in row.channels and selected_targets.intersection(row.channels)
]
```

Use it for candidate eligibility, custom-X unit collection, empty-compatibility preflight validation, and dry-run filtering.

- [ ] **Step 3: Implement runner task filtering**

```python
if needs_custom_x and available is not None and x_channel not in available:
    continue
```

Apply it only in the `available_per_source` branch so strict policies retain their current behavior.

- [ ] **Step 4: Run the new focused tests to verify they pass**

Run: `set QT_QPA_PLATFORM=offscreen; .venv\\Scripts\\python.exe -m pytest tests/ui/test_batch_smoke.py -k available_policy_custom_x -q`

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_batch_runner.py -k available_per_source_custom_x -q`

Expected: PASS; the UI lists the coavailable X channel and both preview and runner include only the compatible logical source.

### Task 3: Verify adjacent contracts

**Files:**
- Verify: `tests/ui/test_batch_smoke.py`
- Verify: `tests/ui/test_batch_method_buttons.py`
- Verify: `tests/test_batch_runner.py`

**Interfaces:**
- Consumes: focused behavior from Tasks 1 and 2.
- Produces: regression evidence that common-policy custom X remains strict and batch planner output remains consistent.

- [ ] **Step 1: Run focused UI and runner suites**

Run: `set QT_QPA_PLATFORM=offscreen; .venv\\Scripts\\python.exe -m pytest tests/ui/test_batch_smoke.py tests/ui/test_batch_method_buttons.py tests/test_batch_runner.py -k "custom_x or x_channel or available_per_source" -q --basetemp D:\\tmp\\tracelab-pytest\\batch-custom-x-source`

Expected: PASS.

- [ ] **Step 2: Run full relevant files**

Run: `set QT_QPA_PLATFORM=offscreen; .venv\\Scripts\\python.exe -m pytest tests/ui/test_batch_smoke.py tests/ui/test_batch_method_buttons.py tests/test_batch_runner.py -q --basetemp D:\\tmp\\tracelab-pytest\\batch-custom-x-source-full`

Expected: PASS.

- [ ] **Step 3: Check whitespace and diff scope**

Run: `git diff --check`

Expected: no whitespace errors.
