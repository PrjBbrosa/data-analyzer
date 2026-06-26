# Manual Order RPM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a quick manual constant-RPM mode for interactive Order/COT analysis when no RPM channel is available.

**Architecture:** Store RPM source mode and manual RPM on `OrderContextual` params, keep pane-local `rpm_source` unchanged, and resolve the final RPM array inside `_order_rpm_for(...)`. Cache keys include mode/value so channel RPM and manual RPM never reuse each other's results.

**Tech Stack:** PyQt5 widgets, existing `OrderContextual`, `OrderMixin`, pytest/pytest-qt.

---

### Task 1: Order Panel Manual RPM Controls

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_order.py`
- Test: `tests/ui/test_inspector.py`

- [ ] **Step 1: Write failing UI/params tests**

Add tests in `tests/ui/test_inspector.py`:

```python
def test_order_contextual_manual_rpm_defaults_and_round_trip(qapp):
    from mf4_analyzer.ui.inspector_sections.contextual_order import OrderContextual

    ctx = OrderContextual()
    assert ctx.rpm_mode() == "channel"
    assert ctx.manual_rpm() == 1000.0
    assert ctx.combo_rpm.isEnabled()
    assert not ctx.spin_manual_rpm.isEnabled()

    ctx.set_rpm_mode("manual")
    ctx.spin_manual_rpm.setValue(1350.0)

    params = ctx.current_params()
    assert params["rpm_mode"] == "manual"
    assert params["manual_rpm"] == 1350.0
    assert not ctx.combo_rpm.isEnabled()
    assert ctx.spin_manual_rpm.isEnabled()

    restored = OrderContextual()
    restored.apply_params(params)
    assert restored.rpm_mode() == "manual"
    assert restored.manual_rpm() == 1350.0
    assert not restored.combo_rpm.isEnabled()
    assert restored.spin_manual_rpm.isEnabled()
```

- [ ] **Step 2: Run red test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. /Users/donghang/Downloads/data\ analyzer/.venv/bin/python -m pytest tests/ui/test_inspector.py::test_order_contextual_manual_rpm_defaults_and_round_trip -q
```

Expected: fail because `rpm_mode`, `manual_rpm`, `set_rpm_mode`, and `spin_manual_rpm` do not exist.

- [ ] **Step 3: Implement controls and params**

In `OrderContextual.__init__`, add:

```python
self.combo_rpm_mode = QComboBox()
self.combo_rpm_mode.addItem("转速通道", "channel")
self.combo_rpm_mode.addItem("手动 RPM", "manual")
fl.addRow("转速来源:", _fit_field(self.combo_rpm_mode, max_width=_SHORT_FIELD_MAX_WIDTH))

self.spin_manual_rpm = _no_buttons(CompactDoubleSpinBox())
self.spin_manual_rpm.setRange(1.0, 100000.0)
self.spin_manual_rpm.setDecimals(1)
self.spin_manual_rpm.setValue(1000.0)
self.spin_manual_rpm.setSuffix(" rpm")
fl.addRow("手动RPM:", _fit_field(self.spin_manual_rpm, max_width=_SHORT_FIELD_MAX_WIDTH))
```

Add helpers:

```python
def rpm_mode(self):
    return self.combo_rpm_mode.currentData() or "channel"

def set_rpm_mode(self, mode):
    target = "manual" if str(mode) == "manual" else "channel"
    idx = self.combo_rpm_mode.findData(target)
    if idx >= 0:
        self.combo_rpm_mode.setCurrentIndex(idx)
    self._sync_rpm_mode()

def manual_rpm(self):
    return float(self.spin_manual_rpm.value())

def _sync_rpm_mode(self):
    manual = self.rpm_mode() == "manual"
    self.combo_rpm.setEnabled(not manual)
    self.spin_rf.setEnabled(not manual)
    self.spin_manual_rpm.setEnabled(manual)
```

Wire `self.combo_rpm_mode.currentIndexChanged.connect(self._sync_rpm_mode)` and call `_sync_rpm_mode()` after construction.

Extend `_collect_preset`, `get_params`, `current_params`, `_apply_preset_values`, and `apply_params` with `rpm_mode` / `manual_rpm`.

- [ ] **Step 4: Run green UI test**

Run the same single test. Expected: pass.

- [ ] **Step 5: Commit task**

```bash
git add mf4_analyzer/ui/inspector_sections/contextual_order.py tests/ui/test_inspector.py
git commit -m "feat(ui): add manual rpm controls for order"
```

### Task 2: Manual RPM Compute Path And Cache Key

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py`
- Test: `tests/ui/test_compute_progress_integration.py`

- [ ] **Step 1: Write failing compute/cache tests**

Add tests in `tests/ui/test_compute_progress_integration.py`:

```python
def test_order_rpm_for_manual_mode_returns_constant_array(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.inspector.order_ctx.set_rpm_mode("manual")
    win.inspector.order_ctx.spin_manual_rpm.setValue(1234.0)

    rpm = win._order_rpm_for(None, 5)

    assert rpm.tolist() == [1234.0] * 5


def test_order_cache_params_include_manual_rpm_mode_and_value(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    p = {
        "nfft": 256,
        "nfft_mode": "fixed",
        "max_order": 20,
        "order_res": 0.1,
        "time_res": 0.05,
        "samples_per_rev": 256,
        "rpm_factor": 1.0,
        "fs": 1000.0,
        "weighting": "None",
        "rpm_mode": "manual",
        "manual_rpm": 1234.0,
    }

    params = win._order_compute_cache_params(p, None, None)

    assert params["rpm_mode"] == "manual"
    assert params["manual_rpm"] == 1234.0
    assert params["rpm_source"] is None
```

- [ ] **Step 2: Run red tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. /Users/donghang/Downloads/data\ analyzer/.venv/bin/python -m pytest tests/ui/test_compute_progress_integration.py::test_order_rpm_for_manual_mode_returns_constant_array tests/ui/test_compute_progress_integration.py::test_order_cache_params_include_manual_rpm_mode_and_value -q
```

Expected: fail because manual mode is not handled in `_order_rpm_for(...)` and cache params omit the new keys.

- [ ] **Step 3: Implement compute fallback**

In `_order_mixin.py`, update `_order_compute_cache_params(...)` to include:

```python
'rpm_mode': p.get('rpm_mode', 'channel'),
'manual_rpm': float(p.get('manual_rpm', 1000.0)),
```

Update `_order_rpm_for(...)` before the `if not rpm_source` branch:

```python
ctx = self.inspector.order_ctx
if getattr(ctx, 'rpm_mode', lambda: 'channel')() == 'manual':
    return np.full(int(n), float(ctx.manual_rpm()), dtype=float)
```

Ensure `_dispatch_order_job(...)` passes `op` from `get_params()` so the cache key receives `rpm_mode` / `manual_rpm`.

- [ ] **Step 4: Run green compute/cache tests**

Run the same tests. Expected: pass.

- [ ] **Step 5: Commit task**

```bash
git add mf4_analyzer/ui/main_window/_order_mixin.py tests/ui/test_compute_progress_integration.py
git commit -m "feat(order): use manual rpm for cot analysis"
```

### Task 3: Focused Verification

**Files:**
- No source edits unless failures require a fix.

- [ ] **Step 1: Run focused suites**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. /Users/donghang/Downloads/data\ analyzer/.venv/bin/python -m pytest \
  tests/ui/test_inspector.py \
  tests/ui/test_compute_progress_integration.py \
  tests/ui/test_analysis_multiview_integration.py \
  -q
```

Expected: pass.

- [ ] **Step 2: Diff hygiene**

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 3: Commit any verification-only fixes**

Only if Step 1 or 2 required fixes:

```bash
git add <fixed files>
git commit -m "fix(order): polish manual rpm behavior"
```
