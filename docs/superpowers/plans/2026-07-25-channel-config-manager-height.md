# Channel Configuration Manager Default Height Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Channel Configuration Manager open at a taskbar-safe 1180x680 size while preserving its 940x680 minimum size and visible footer controls.

**Architecture:** Keep the dialog layout unchanged: its existing scroll areas absorb the smaller initial viewport. Extend the existing geometry regression test to assert the unmodified default geometry before it explicitly resizes the dialog to its minimum size.

**Tech Stack:** Python 3.12, PyQt5, pytest-qt, PowerShell.

## Global Constraints

- Keep `ChannelConfigManagerDialog` at 1180px default width.
- Change only its default height from 790px to 680px.
- Keep its existing 940x680 minimum size.
- Do not change sidebar width, scrolling, save/discard behavior, other dialogs, or button layout.
- Run the focused Qt test with `QT_QPA_PLATFORM=offscreen` and the repository venv.

---

### Task 1: Set and protect the taskbar-safe default geometry

**Files:**

- Modify: `tests/ui/test_channel_config_manager.py:204-235`
- Modify: `mf4_analyzer/ui/widgets/channel_config_manager.py:137-138`

**Interfaces:**

- Consumes: `ChannelConfigManagerDialog(configs, *, selected_id, preview, checked_channel_hints, id_factory)`.
- Produces: a dialog whose initial `size()` is 1180x680 and whose `minimumSize()` is 940x680.

- [ ] **Step 1: Add the failing default-geometry assertions**

In `test_manager_geometry_preserves_html_controls_at_minimum_size`, assert the
new initial size and the retained minimum size immediately after `_dialog(...)`
returns, before calling `dialog.resize(940, 680)`:

```python
    assert dialog.size().width() == 1180
    assert dialog.size().height() == 680
    assert dialog.minimumSize().width() == 940
    assert dialog.minimumSize().height() == 680
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
$env:TMP=(Resolve-Path '.pytest-tmp').Path; $env:TEMP=$env:TMP; $env:TMPDIR=$env:TMP; $env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config_manager.py::test_manager_geometry_preserves_html_controls_at_minimum_size -q
```

Expected: FAIL because the initial dialog height is 790.

- [ ] **Step 3: Change only the default height**

In `ChannelConfigManagerDialog.__init__`, replace:

```python
        self.resize(1180, 790)
```

with:

```python
        self.resize(1180, 680)
```

Leave `self.setMinimumSize(940, 680)` unchanged.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command again.

Expected: PASS. The existing footer assertion verifies that the Save button
remains visible at the 940x680 minimum size.

- [ ] **Step 5: Run the dialog test module**

Run:

```powershell
$env:TMP=(Resolve-Path '.pytest-tmp').Path; $env:TEMP=$env:TMP; $env:TMPDIR=$env:TMP; $env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_config_manager.py -q
```

Expected: PASS with no behavior changes outside default geometry.

- [ ] **Step 6: Commit the implementation**

```powershell
git add tests/ui/test_channel_config_manager.py mf4_analyzer/ui/widgets/channel_config_manager.py
git commit -m "fix: reduce channel configuration dialog height"
```
