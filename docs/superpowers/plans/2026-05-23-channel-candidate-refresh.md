# Channel Candidate Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every channel-dependent selector in sync after files or channel math edits change the loaded channel universe.

**Architecture:** Treat loaded channel metadata as one universe owned by `MainWindow.files`. Add one refresh path for channel-dependent UI, while keeping the existing separate candidate rules: X-axis candidates use `fd.channels` including time columns; FFT/FFT-vs-Time/Order candidates use `fd.get_signal_channels()` excluding time masters. Preserve valid X-axis selection across refreshes and invalidate applied custom-X state when its source channel is removed.

**Tech Stack:** Python, PyQt5, pytest-qt, pandas/numpy test fixtures.

---

## Findings

- `MainWindow._on_xaxis_mode_changed()` populates the X-axis channel combo from `fd.channels`, but it only runs when the source combo switches to `指定通道`.
- `MainWindow._apply_channel_edits()` writes new math channels into `fd.data`, `fd.channels`, and `fd.channel_units`, then refreshes the navigator and analysis combos via `_update_combos()`. It does not refresh the already-visible X-axis combo.
- `MainWindow._load_one()` has the same stale-path when the user is already in X-axis `channel` mode and then loads another file.
- `MainWindow._reset_plot_state()` already refreshes X-axis candidates on file close, so close is safer than load/edit.
- Export and batch dialogs read channel lists when opened or when their own file rows change; they are not long-lived selectors during channel editor application in the current modal flow.

## Files

- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `mf4_analyzer/ui/inspector_sections.py`
- Modify: `tests/ui/test_main_window_smoke.py`
- Optional after implementation: add/update a lesson under `docs/lessons-learned/pyqt-ui/` if review confirms this should become a durable project rule.

---

### Task 1: Regression Tests For Stale X-Axis Candidates

**Files:**
- Modify: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Add local combo helper near existing custom X-axis tests**

```python
def _combo_texts(combo):
    return [combo.itemText(i) for i in range(combo.count())]
```

- [ ] **Step 2: Add failing test for channel-edit refresh**

```python
def test_channel_edit_refreshes_custom_xaxis_candidates(qapp, qtbot, loaded_csv):
    """A channel created by the editor must be immediately selectable as X."""
    import numpy as np
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    w.inspector.top.set_xaxis_mode("channel")
    w._on_xaxis_mode_changed("channel")
    combo = w.inspector.top._combo_xaxis_ch
    before_data = combo.currentData()

    arr = np.arange(len(w.files[fid].data), dtype=float)
    w._apply_channel_edits(fid, {"d_dt_speed": (arr, "unit/s")}, set())
    qapp.processEvents()

    texts = _combo_texts(combo)
    assert any(text.endswith("d_dt_speed") for text in texts)
    assert combo.currentData() == before_data
```

- [ ] **Step 3: Add failing test for load-while-channel-mode refresh**

```python
def test_file_load_refreshes_custom_xaxis_candidates_when_channel_mode(
    qapp, qtbot, loaded_csv, tmp_path
):
    """Loading another file while X source is 指定通道 must add its channels."""
    import numpy as np
    import pandas as pd
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    second = tmp_path / "second.csv"
    pd.DataFrame({
        "time": np.linspace(0, 1, 128),
        "pressure": np.linspace(10, 20, 128),
    }).to_csv(second, index=False)

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()

    w.inspector.top.set_xaxis_mode("channel")
    w._on_xaxis_mode_changed("channel")

    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([str(second)], ""),
    ):
        w.load_files()
    qapp.processEvents()

    texts = _combo_texts(w.inspector.top._combo_xaxis_ch)
    assert any(text.endswith("pressure") for text in texts)
```

- [ ] **Step 4: Add failing test for removed applied custom-X source**

```python
def test_channel_edit_removing_custom_xaxis_source_resets_to_time(
    qapp, qtbot, loaded_csv
):
    """Removing the applied X source must not leave stale custom-X state."""
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    w.inspector.top.set_xaxis_mode("channel")
    w._on_xaxis_mode_changed("channel")
    combo = w.inspector.top._combo_xaxis_ch
    idx = next(i for i in range(combo.count()) if combo.itemData(i) == (fid, "speed"))
    combo.setCurrentIndex(idx)
    w._apply_xaxis()
    assert w._custom_xaxis_ch == "speed"

    w._apply_channel_edits(fid, {}, {"speed"})
    qapp.processEvents()

    assert w._custom_xaxis_fid is None
    assert w._custom_xaxis_ch is None
    assert w.inspector.top.xaxis_mode() == "time"
```

- [ ] **Step 5: Run the three tests and verify they fail before implementation**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='.'
.venv\Scripts\python.exe -m pytest tests\ui\test_main_window_smoke.py -q -k "custom_xaxis_candidates or custom_xaxis_source"
```

Expected: the new tests fail on stale/missing X-axis state.

---

### Task 2: Preserve X-Axis Combo Selection During Repopulation

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`

- [ ] **Step 1: Update `PersistentTop.set_xaxis_candidates`**

Replace the current body with:

```python
def set_xaxis_candidates(self, candidates):
    """candidates: list of (display_text, (fid, ch)) tuples."""
    prev = self._combo_xaxis_ch.currentData()
    self._combo_xaxis_ch.blockSignals(True)
    self._combo_xaxis_ch.clear()
    keep_idx = -1
    for i, (text, data) in enumerate(candidates):
        self._combo_xaxis_ch.addItem(text, data)
        if prev is not None and data == prev:
            keep_idx = i
    if keep_idx >= 0:
        self._combo_xaxis_ch.setCurrentIndex(keep_idx)
    self._combo_xaxis_ch.blockSignals(False)
```

- [ ] **Step 2: Run the channel-edit test**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='.'
.venv\Scripts\python.exe -m pytest tests\ui\test_main_window_smoke.py::test_channel_edit_refreshes_custom_xaxis_candidates -q
```

Expected: still fails until `MainWindow` refreshes the candidate list, but the selection-preservation assertion is now supported.

---

### Task 3: Centralize MainWindow Channel Candidate Refresh

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Add X-axis candidate builder and refresh helpers near `_on_xaxis_mode_changed`**

```python
def _build_xaxis_candidates(self):
    cands = []
    for fid, fd in self.files.items():
        px = f"[{fd.short_name}] "
        for ch in fd.channels:
            cands.append((px + ch, (fid, ch)))
    return cands

def _refresh_xaxis_candidates(self):
    self.inspector.top.set_xaxis_candidates(self._build_xaxis_candidates())

def _validate_custom_xaxis_source(self):
    if self._custom_xaxis_fid is None or self._custom_xaxis_ch is None:
        return
    fd = self.files.get(self._custom_xaxis_fid)
    if fd is not None and self._custom_xaxis_ch in fd.data.columns:
        return
    self._custom_xaxis_fid = None
    self._custom_xaxis_ch = None
    self._custom_xlabel = None
    self.inspector.top.set_xaxis_mode("time")

def _refresh_channel_dependent_controls(self):
    self._validate_custom_xaxis_source()
    self._update_combos()
    if self.inspector.top.xaxis_mode() == "channel":
        self._refresh_xaxis_candidates()
```

- [ ] **Step 2: Route `_on_xaxis_mode_changed` through the helper**

Replace the `if mode == 'channel':` block with:

```python
if mode == 'channel':
    self._refresh_xaxis_candidates()
```

- [ ] **Step 3: Replace load/edit refresh sites**

In `_load_one`, replace:

```python
self._update_combos()
```

with:

```python
self._refresh_channel_dependent_controls()
```

In `_apply_channel_edits`, replace:

```python
self._update_combos()
```

with:

```python
self._refresh_channel_dependent_controls()
```

- [ ] **Step 4: Keep close/reset path using the same refresh point**

In `_reset_plot_state`, replace:

```python
if self.inspector.top.xaxis_mode() == 'channel':
    self._on_xaxis_mode_changed('channel')
self._update_combos()
```

with:

```python
self._refresh_channel_dependent_controls()
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='.'
.venv\Scripts\python.exe -m pytest tests\ui\test_main_window_smoke.py -q -k "xaxis or file_load or close_file"
```

Expected: all selected tests pass.

---

### Task 4: Broader Verification And Lesson Gate

**Files:**
- Check: `tests/ui/test_inspector.py`
- Check: `tests/ui/test_file_navigator.py`
- Check: `tests/ui/test_batch_input_panel.py`
- Optional modify: `docs/lessons-learned/pyqt-ui/<date>-channel-universe-refresh.md`
- Optional modify: `docs/lessons-learned/INDEX.md`

- [ ] **Step 1: Run focused channel UI suites**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='.'
.venv\Scripts\python.exe -m pytest tests\ui\test_main_window_smoke.py tests\ui\test_inspector.py tests\ui\test_file_navigator.py tests\ui\test_batch_input_panel.py -q
```

Expected: pass. If unrelated font warnings appear from PyQt, ignore them unless pytest fails.

- [ ] **Step 2: Run lessons gate**

Run:

```powershell
.venv\Scripts\python.exe scripts\lessons\check.py --clear
```

Only do this if no lesson candidate is required. If implementation or review finds the channel-refresh invariant likely to recur, create a short lesson instead of clearing.

- [ ] **Step 3: If a lesson is required, record the invariant**

Lesson trigger: code touches channel mutation, file load/close, or any selector built from `FileData.channels`, `FileData.get_signal_channels()`, or `fd.data.columns`.

Rule: channel universe changes must refresh all live selectors from one `MainWindow` path and must validate persisted custom-X state, not only the visible widget that triggered the change.
