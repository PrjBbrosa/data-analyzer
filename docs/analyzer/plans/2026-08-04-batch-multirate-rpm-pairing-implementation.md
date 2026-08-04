# Batch Multi-Rate RPM Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let free-config batch order analysis use an RPM channel from a different logical source and interpolate it onto the selected target signal's time axis.

**Architecture:** The batch runner already supports `AnalysisPreset.rpm_signal=(source_id, channel)` and interpolates via `np.interp`. Keep that implementation unchanged. When the BatchSheet's selected RPM channel is available in exactly one loaded logical source, attach that transient source/channel pair to the free-config preset; its normal per-source target expansion then excludes sources lacking the target signal.

**Tech Stack:** Python, PyQt5, pytest, NumPy.

## Global Constraints

- Preserve same-source RPM behavior: an RPM name available in more than one source remains `rpm_channel` only.
- Do not persist `rpm_signal`: source IDs are runtime-only and preset JSON deliberately excludes them.
- Reuse `BatchRunner._rpm_values()` for strict time-axis validation and interpolation; do not add another resampler.
- Cover the 48 kHz target / 1.5 kHz RPM logical-source pattern with a regression test.

---

### Task 1: Define the free-config source-pairing contract

**Files:**
- Modify: `tests/ui/test_batch_input_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`

**Interfaces:**
- Consumes: `BatchSheet.source_ids()`, `InputPanel.source_channel_sets()`, and `BatchSheet.rpm_channel()`.
- Produces: `BatchSheet._free_config_rpm_signal() -> tuple[object, str] | None`.

- [x] **Step 1: Write the failing UI-to-runner regression test**

```python
def test_free_order_preset_pairs_unique_cross_source_rpm(qtbot, tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import BatchRunner
    from mf4_analyzer.io import FileData

    target = FileData(
        tmp_path / "target.csv",
        pd.DataFrame({"time": [0.0, 0.25, 0.5], "Left": [1.0, 2.0, 3.0]}),
        ["time", "Left"], {},
    )
    rpm = FileData(
        tmp_path / "rpm.csv",
        pd.DataFrame({"time": [0.0, 0.5], "Com_RPS_Speed_DV": [1000.0, 2000.0]}),
        ["time", "Com_RPS_Speed_DV"], {},
    )
    sheet = BatchSheet(None, files={"noise": target, "speed": rpm})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file("noise", str(target.filepath), frozenset({"Left"}))
    sheet._input_panel._file_list.add_loaded_file("speed", str(rpm.filepath), frozenset({"Com_RPS_Speed_DV"}))
    sheet.apply_method("order_time")
    sheet.apply_target_policy("available_per_source")
    sheet.apply_signals(("Left",))
    sheet.apply_rpm_channel("Com_RPS_Speed_DV")

    preset = sheet.get_preset()

    assert preset.rpm_signal == ("speed", "Com_RPS_Speed_DV")
    assert list(BatchRunner({"noise": target, "speed": rpm})._expand_tasks(preset)) == [("noise", "Left")]
    np.testing.assert_allclose(
        BatchRunner({"noise": target, "speed": rpm})._rpm_values(
            target, preset, target_source_id="noise",
        ),
        [1000.0, 1500.0, 2000.0],
    )
```

- [x] **Step 2: Run the test and observe the expected RED failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/ui/test_batch_input_panel.py::test_free_order_preset_pairs_unique_cross_source_rpm -q`

Expected: the preset has `rpm_signal is None` and RPM lookup fails on the
`Left` source before the production change.

- [x] **Step 3: Implement minimal transient pairing**

```python
def _free_config_rpm_signal(self) -> tuple[object, str] | None:
    rpm_channel = self.rpm_channel()
    if not rpm_channel:
        return None
    source_ids = tuple(
        source_id for source_id, channels
        in self._input_panel.source_channel_sets().items()
        if rpm_channel in channels
    )
    return (source_ids[0], rpm_channel) if len(source_ids) == 1 else None
```

Attach its result with `dataclasses.replace(base, rpm_signal=...)` in the free-config return path.

- [x] **Step 4: Run the focused UI regression test**

Run: `.venv\\Scripts\\python.exe -m pytest tests/ui/test_batch_input_panel.py::test_free_order_preset_pairs_unique_cross_source_rpm -q`

Expected: PASS.

### Task 2: Prove interpolation is used and retain existing behavior

**Files:**
- Modify: `docs/analyzer/plans/2026-08-04-batch-multirate-rpm-pairing-implementation.md`

**Interfaces:**
- Consumes: the transient `rpm_signal` from Task 1 and `BatchRunner._rpm_values(fd, preset, target_source_id=...)`.
- Produces: a protected 48 kHz target / 1.5 kHz RPM interpolation contract.

- [x] **Step 1: Run the focused source integration tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_batch_source_integration.py -k "cross_source_rpm or available_per_source" -q`

Expected: PASS, confirming the new UI pair uses the existing interpolation path and target filtering remains correct.

- [x] **Step 2: Mark both completed checklist items and record verification evidence**

Verification on 2026-08-04:

- RED: `D:\\Coding project\\data analyzer\\.venv\\Scripts\\python.exe -m pytest tests\\ui\\test_batch_input_panel.py::test_free_order_preset_binds_unique_cross_source_rpm -q` failed because `preset.rpm_signal` was `None`.
- GREEN: the same command passed (`1 passed`).
- Focused runner coverage: `D:\\Coding project\\data analyzer\\.venv\\Scripts\\python.exe -m pytest tests\\test_batch_source_integration.py -k "cross_source_rpm or available_per_source" -q` passed (`6 passed`).

### Task 3: Final verification

**Files:**
- Verify only: `mf4_analyzer/ui/drawers/batch/sheet.py`, `tests/ui/test_batch_input_panel.py`, `tests/test_batch_source_integration.py`

- [ ] **Step 1: Run the complete affected suites**

Run: `.venv\\Scripts\\python.exe -m pytest tests/ui/test_batch_input_panel.py tests/test_batch_source_integration.py -q`

Expected: PASS with no failures.

Observed on 2026-08-04: `tests/ui/test_batch_input_panel.py tests/test_batch_source_integration.py -q` had 70 passes and 4 pre-existing Windows path-normalization failures in disk-add tests. The changed behavior itself passed in the full run; the complete source integration suite passed (`20 passed`) and the three directly related UI tests passed (`3 passed`).

- [x] **Step 2: Check patch scope and whitespace**

Run: `git diff --check; git diff -- mf4_analyzer/ui/drawers/batch/sheet.py tests/ui/test_batch_input_panel.py tests/test_batch_source_integration.py docs/analyzer/plans/2026-08-04-batch-multirate-rpm-pairing-implementation.md`

Expected: no whitespace errors; only the transient pairing helper, regression tests, and this plan change.
