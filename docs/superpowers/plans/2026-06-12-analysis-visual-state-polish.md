# Analysis Visual And State Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the confirmed Analysis-section polish regressions without changing the current split/card architecture: smoother heatmaps, FFT curve antialiasing, safer focused-pane source capture, clearer analysis View split semantics, and correct locked-level defaults.

**Architecture:** Keep `AnalysisSectionPage` as the current per-section splitter/card container. Make narrow rendering and state-routing changes inside existing canvases, tabbar/action labels, and `MainWindow` capture/apply paths. Add tests that fail on the current implementation and protect the exact user-visible regressions.

**Tech Stack:** PyQt5, pyqtgraph 0.14.0, pytest-qt/offscreen Qt, existing `ViewTabBar`, `AnalysisViewState`, `PgHeatmapCanvas`, and `PgLineCanvas`.

---

## Scope Boundary

This plan deliberately does **not** move Analysis to the TimeDomain shared-toolbar/bottom-dock architecture. Do not detach chart-card toolbars, do not rebuild the `QSplitter` hierarchy, and do not change how cards are constructed. The only UI work allowed here is local wording/default/state polish inside the existing Analysis row.

## Evidence To Preserve

- `PgHeatmapCanvas.plot_or_update_heatmap(... interp='bilinear')` currently accepts `interp` but ignores it.
- `PgLineCanvas.plot_spectra` creates FFT curves without `antialias=True`.
- `AnalysisViewState.compare` defaults `levels_locked=True`, but `MainWindow._on_analysis_view_switched` falls back to `False`, and `AnalysisSectionPage` seeds the button as `False`.
- `MainWindow._on_analysis_focus_changed` cannot capture the previous focused pane because the page has already changed focus.
- Analysis reuses TimeDomain `ViewTabBar` split menu labels even though Analysis split means "add/remove a second pane in the active view".

## Files

- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Modify: `mf4_analyzer/ui/analysis_section_page.py`
- Modify: `mf4_analyzer/ui/view_tabbar.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`
- Test: `tests/ui/test_pg_line_canvas.py`
- Test: `tests/ui/test_analysis_section_page.py`
- Test: `tests/ui/test_analysis_multiview_integration.py`

---

### Task 1: Heatmap `interp` Actually Enables Smooth Painting

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: Write the failing `interp` state test**

Add this test near the existing heatmap rendering tests in `tests/ui/test_pg_heatmap_canvas.py`:

```python
def test_interp_bilinear_enables_smooth_image_paint(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
        interp='bilinear',
    )
    assert canvas._img.smooth_transform_enabled() is True

    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
        interp='nearest',
    )
    assert canvas._img.smooth_transform_enabled() is False
```

- [ ] **Step 2: Run the focused failing test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_interp_bilinear_enables_smooth_image_paint -q
```

Expected: FAIL because the current `pg.ImageItem` has no `smooth_transform_enabled()` and `interp` is ignored.

- [ ] **Step 3: Add a small smooth ImageItem wrapper**

In `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`, add this class after `_tick_counts_to_density`:

```python
class _SmoothImageItem(pg.ImageItem):
    """ImageItem that honors mpl-style interpolation hints via QPainter."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._smooth_transform = False

    def set_smooth_transform(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._smooth_transform == enabled:
            return
        self._smooth_transform = enabled
        self.update()

    def smooth_transform_enabled(self) -> bool:
        return self._smooth_transform

    def paint(self, painter, *args):
        previous = painter.testRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._smooth_transform)
        try:
            return super().paint(painter, *args)
        finally:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, previous)
```

Replace the image item construction:

```python
self._img = _SmoothImageItem()
```

- [ ] **Step 4: Wire `interp` to the wrapper**

In `plot_or_update_heatmap`, replace the current ignored-`interp` comment with:

```python
smooth = str(interp or '').lower() in {'bilinear', 'bicubic', 'hanning'}
self._img.set_smooth_transform(smooth)
```

Keep `None` and `'nearest'` unsmoothed so callers can still request crisp cells when needed.

- [ ] **Step 5: Run heatmap tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -q
```

Expected: PASS.

- [ ] **Step 6: Save a fresh visual checkpoint**

Run the existing verification path that produced the split heatmap screenshots, then save updated screenshots under `docs/superpowers/verify/` with names containing `2026-06-12-smooth`. Confirm visually that `p4-fft-time-split` and `p4-order-split` no longer show coarse block boundaries at normal zoom.

---

### Task 2: FFT Section Curves Use Antialiasing

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: Write the failing FFT antialias test**

Add this test after `test_plot_spectra_single_entry`:

```python
def test_fft_curves_are_antialiased(canvas):
    canvas.plot_spectra(
        [_entry(), _entry('f2 · vib', '#dc2626')],
        xlim=(0.0, 500.0),
        amp_label='Amplitude',
        psd_label='PSD',
        title='FFT',
        y_auto=True,
        y_min=0.0,
        y_max=0.0,
    )
    curves = canvas._amp_curves + canvas._psd_curves
    assert curves
    assert all(c.opts.get('antialias') is True for c in curves)
```

- [ ] **Step 2: Run the focused failing test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_fft_curves_are_antialiased -q
```

Expected: FAIL because current FFT `PlotDataItem` curves do not set `antialias=True`.

- [ ] **Step 3: Enable antialiasing only for FFT line curves**

In `mf4_analyzer/ui/pg_canvas/line_canvas.py`, change both `plot()` calls inside `plot_spectra`:

```python
self._amp_curves.append(
    self._plot_amp.plot(
        e['freq'], e['amp'], pen=pen, name=e['label'], antialias=True
    )
)
self._psd_curves.append(
    self._plot_psd.plot(
        e['freq'], e['psd'], pen=pen, name=e['label'], antialias=True
    )
)
```

Do not change TimeDomain antialias density gates in `mf4_analyzer/ui/pg_canvas/quality.py`; this task is FFT-section only.

- [ ] **Step 4: Run FFT canvas tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q
```

Expected: PASS.

---

### Task 3: Focus Switching Captures The Previous Pane's Source

**Files:**
- Modify: `mf4_analyzer/ui/analysis_section_page.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_analysis_section_page.py`
- Test: `tests/ui/test_analysis_multiview_integration.py`

- [ ] **Step 1: Add a page-level previous-focus test**

Add this to `tests/ui/test_analysis_section_page.py` after `test_set_focus`:

```python
def test_previous_focused_index_tracks_focus_change(page):
    page.enter_split()
    assert page.focused_index() == 0
    assert page.previous_focused_index() == 0
    page.set_focused_index(1)
    assert page.previous_focused_index() == 0
    assert page.focused_index() == 1
    page.set_focused_index(0)
    assert page.previous_focused_index() == 1
    assert page.focused_index() == 0
```

- [ ] **Step 2: Add an integration test for real source preservation**

Add this test near the FFT-vs-Time split tests in `tests/ui/test_analysis_multiview_integration.py`:

```python
def test_fft_time_focus_switch_preserves_previous_pane_source(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    fids = list(win.files.keys())
    page = win.chart_stack.page_fft_time
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)

    win._on_analysis_split("fft_time", True)
    assert page.focused_index() == 0

    win._echo_combo_signal(win.inspector.fft_time_ctx.combo_sig, (fids[0], "speed"))
    page.set_focused_index(1)

    assert state.panes[0].sources == [(fids[0], "speed")]
```

- [ ] **Step 3: Run the failing tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py::test_previous_focused_index_tracks_focus_change tests/ui/test_analysis_multiview_integration.py::test_fft_time_focus_switch_preserves_previous_pane_source -q
```

Expected: FAIL because the page does not expose previous focus and `MainWindow._on_analysis_focus_changed` only reapplies the new pane source.

- [ ] **Step 4: Track previous focus in the page**

In `AnalysisSectionPage.__init__`, add:

```python
self._previous_focused = 0
```

Add this method:

```python
def previous_focused_index(self) -> int:
    return self._previous_focused
```

Change `set_focused_index` so it records the old pane before changing focus:

```python
def set_focused_index(self, idx: int) -> None:
    if not (0 <= idx < len(self._cards)):
        return
    if idx == self._focused:
        return
    self._previous_focused = self._focused
    self._focused = idx
    self._apply_focus_style()
    self.focus_changed.emit(idx)
```

When `exit_split()` resets focus to pane 0, also reset `_previous_focused = 0`.

- [ ] **Step 5: Allow source capture for a specified pane**

Change `MainWindow._capture_analysis_sources` to accept an optional pane index:

```python
def _capture_analysis_sources(self, section, state, pane_idx=None):
    page = self._analysis_page(section)
    if pane_idx is None:
        pane_idx = page.focused_index()
    idx = min(int(pane_idx), len(state.panes) - 1)
    pane = state.panes[idx]
    if section == 'fft':
        checked = self.navigator.get_checked_channels()
        pane.sources = [(fid, ch) for fid, ch, _color in checked]
    else:
        ctx = self._analysis_ctx(section)
        sig = ctx.current_signal()
        pane.sources = [tuple(sig)] if sig else []
        if section == 'order':
            rpm = ctx.current_rpm()
            pane.rpm_source = tuple(rpm) if rpm else None
```

Keep existing callers valid because `pane_idx` defaults to `None`.

- [ ] **Step 6: Capture old pane before echoing new pane**

Replace `MainWindow._on_analysis_focus_changed` body after `state = ...` with:

```python
page = self._analysis_page(section)
old_idx = min(page.previous_focused_index(), len(state.panes) - 1)
self._capture_analysis_sources(section, state, pane_idx=old_idx)
self._apply_analysis_sources(section, state)
```

- [ ] **Step 7: Run focused integration tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py tests/ui/test_analysis_multiview_integration.py -q
```

Expected: PASS.

---

### Task 4: Locked Color Levels Default Is Consistent

**Files:**
- Modify: `mf4_analyzer/ui/analysis_section_page.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_analysis_section_page.py`
- Test: `tests/ui/test_analysis_multiview_integration.py`

- [ ] **Step 1: Add page default test**

Add this in `tests/ui/test_analysis_section_page.py` near compare-toggle tests:

```python
def test_heatmap_compare_defaults_lock_levels_on(page):
    assert page.btn_lock_levels.isChecked() is True
```

- [ ] **Step 2: Add apply fallback test**

Add this in `tests/ui/test_analysis_multiview_integration.py` near view-switch tests:

```python
def test_analysis_view_switch_missing_compare_defaults_lock_levels_true(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    state.compare = {}

    win._on_analysis_view_switched("fft_time", mgr.active)

    assert win.chart_stack.page_fft_time.btn_lock_levels.isChecked() is True
```

- [ ] **Step 3: Run failing default tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py::test_heatmap_compare_defaults_lock_levels_on tests/ui/test_analysis_multiview_integration.py::test_analysis_view_switch_missing_compare_defaults_lock_levels_true -q
```

Expected: FAIL because `AnalysisSectionPage` seeds `levels_locked=False` and `MainWindow` falls back to `False`.

- [ ] **Step 4: Make defaults consistent with `AnalysisViewState`**

In `AnalysisSectionPage.__init__`, change:

```python
self.sync_compare_buttons(x_linked=True, levels_locked=True)
```

In `MainWindow._on_analysis_view_switched`, change:

```python
levels_locked = bool(state.compare.get('levels_locked', True))
```

Do not force the lock visible in single-pane mode; `_refresh_compare_buttons()` must continue hiding it unless the heatmap section is split.

- [ ] **Step 5: Run Analysis section and state tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py tests/ui/test_analysis_view_state.py tests/ui/test_analysis_multiview_integration.py -q
```

Expected: PASS.

---

### Task 5: Analysis View Split Controls Match Analysis Semantics

**Files:**
- Modify: `mf4_analyzer/ui/view_tabbar.py`
- Modify: `mf4_analyzer/ui/analysis_section_page.py`
- Test: `tests/ui/test_analysis_section_page.py`

- [ ] **Step 1: Add an Analysis split-control semantics test**

Add this to `tests/ui/test_analysis_section_page.py` near the ViewTabBar-related tests:

```python
def test_analysis_tabbar_uses_active_pane_split_controls(page):
    labels = page.tabbar.split_action_labels()
    assert labels['split'] == "添加对比窗格"
    assert labels['replace'] == "添加对比窗格"
    assert labels['clear'] == "关闭对比窗格"
    assert page.tabbar.split_action_mode() == "active_pane"

    assert not page.tabbar._split_clear.isVisible()
    page.enter_split()
    page.tabbar.refresh_split_controls()
    assert page.tabbar._split_clear.isVisible()
    assert page.tabbar._split_clear.text() == "✕ 关闭对比窗格"
    assert page.tabbar._split_clear.toolTip() == "关闭当前 View 的对比窗格"
```

- [ ] **Step 2: Run the failing semantics test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py::test_analysis_tabbar_uses_active_pane_split_controls -q
```

Expected: FAIL because `ViewTabBar` has only TimeDomain merge labels and its clear button only follows `manager.partner_for`, not Analysis pane count.

- [ ] **Step 3: Add optional split mode to `ViewTabBar`**

Change the `ViewTabBar.__init__` signature only, preserving existing callers:

```python
def __init__(
    self,
    manager,
    parent=None,
    *,
    split_action_labels=None,
    split_action_mode='view_pair',
    active_split_provider=None,
):
```

After the existing `self._manager = manager` assignment, add:

```python
self._split_action_labels = {
    'split': "与此 View 并排",
    'replace': "与此 View 并排（替换当前合并）",
    'clear': "取消合并",
}
if split_action_labels:
    self._split_action_labels.update(split_action_labels)
self._split_action_mode = str(split_action_mode)
self._active_split_provider = active_split_provider
```

Add readback/control helpers for tests and for Analysis pane refresh:

```python
def split_action_labels(self) -> dict:
    return dict(self._split_action_labels)

def split_action_mode(self) -> str:
    return self._split_action_mode

def refresh_split_controls(self) -> None:
    self._update_split_chip()
```

Add this helper:

```python
def _active_pane_split_visible(self) -> bool:
    if self._split_action_mode != 'active_pane':
        return False
    provider = self._active_split_provider
    if provider is None:
        return False
    try:
        return int(provider()) > 1
    except Exception:
        return False
```

Change `_update_split_chip` so `active_pane` mode is handled before the existing TimeDomain partner logic:

```python
if self._split_action_mode == 'active_pane':
    visible = self._active_pane_split_visible()
    self._split_chip.setVisible(False)
    self._split_chip.setText("")
    self._split_clear.setVisible(visible)
    self._split_clear.setText("✕ " + self._split_action_labels['clear'])
    self._split_clear.setToolTip("关闭当前 View 的对比窗格")
    self._split_clear.setAccessibleName("关闭当前 View 的对比窗格" if visible else "")
    return
```

Keep the existing TimeDomain branch intact after this block.

Change `_on_context_menu` label creation to support both modes:

```python
if self._split_action_mode == 'active_pane':
    if self._active_pane_split_visible() and idx == self._manager.active:
        split_action = menu.addAction(self._split_action_labels['clear'])
    else:
        split_action = menu.addAction(self._split_action_labels['split'])
    split_action.setEnabled(idx == self._manager.active)
else:
    if partner is not None:
        split_action = menu.addAction(self._split_action_labels['clear'])
    elif will_replace:
        split_action = menu.addAction(self._split_action_labels['replace'])
    else:
        split_action = menu.addAction(self._split_action_labels['split'])
        split_action.setEnabled(idx != self._manager.active)
```

Change the chosen-action branch:

```python
elif chosen is split_action:
    if self._split_action_mode == 'active_pane':
        if self._active_pane_split_visible():
            self.clear_split_requested.emit(idx)
        else:
            self.split_requested.emit(idx)
        return
    if partner is not None:
        self.clear_split_requested.emit(idx)
    else:
        if will_replace:
            ans = QMessageBox.question(
                self,
                "替换合并",
                f"“{self._manager.get(self._manager.active).name}” 当前已与 "
                f"“{self._manager.get(active_partner).name}” 合并；改为与 "
                f"“{self._manager.get(idx).name}” 合并会解除原合并。继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self.split_requested.emit(idx)
```

- [ ] **Step 4: Pass Analysis-specific split mode from `AnalysisSectionPage`**

Change the tabbar construction in `AnalysisSectionPage.__init__`:

```python
self.tabbar = ViewTabBar(
    manager,
    self._compare_row,
    split_action_mode='active_pane',
    active_split_provider=self.pane_count,
    split_action_labels={
        'split': "添加对比窗格",
        'replace': "添加对比窗格",
        'clear': "关闭对比窗格",
    },
)
```

Call `self.tabbar.refresh_split_controls()` at the end of `enter_split()` and `exit_split()` so the clear button follows pane count. TimeDomain labels and clear-chip behavior stay unchanged because TimeDomain still calls `ViewTabBar(manager, parent)` without overrides.

- [ ] **Step 5: Run tabbar and Analysis page tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py tests/ui/test_view_tabbar.py -q
```

Expected: PASS.

---

### Task 6: Final Verification And Visual Evidence

**Files:**
- No source changes.

- [ ] **Step 1: Run the focused regression bundle**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_analysis_section_page.py tests/ui/test_analysis_multiview_integration.py tests/ui/test_analysis_view_state.py -q
```

Expected: PASS.

- [ ] **Step 2: Re-render visual checkpoints**

Re-run the existing screenshot generation flow for:

- FFT section single-pane and split
- FFT-vs-Time split
- Order split
- FFT-vs-Time copy/export combined image

Save fresh artifacts under `docs/superpowers/verify/` and compare against the current blocky screenshots:

- `docs/superpowers/verify/p4-fft-time-split.png`
- `docs/superpowers/verify/p4-order-split.png`
- `docs/superpowers/verify/p4-copy-fft_time-combined.png`

- [ ] **Step 3: Manual live TraceLab check**

Open the app normally and verify:

- FFT curves look visibly less jagged.
- FFT-vs-Time and Order heatmaps no longer show harsh block edges at normal zoom.
- Switching focus between two Analysis panes preserves each pane's selected source.
- Heatmap split starts with locked color levels unless the user turns it off.
- Analysis right-click split wording says "添加对比窗格/关闭对比窗格", not TimeDomain merge wording.
- The Analysis split/card architecture remains unchanged.

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/analysis_section_page.py mf4_analyzer/ui/view_tabbar.py mf4_analyzer/ui/main_window.py tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_analysis_section_page.py tests/ui/test_analysis_multiview_integration.py
git commit -m "fix(analysis): polish pg visuals and pane state"
```

---

## Self-Review

- Spec coverage: Heatmap smoothing, FFT antialiasing, source capture, level-lock defaults, and Analysis-specific split wording are each covered by a failing test and a focused implementation task.
- Scope check: No task detaches Analysis toolbars, moves bottom docks, or changes the splitter/card architecture.
- Placeholder scan: The plan contains no deferred implementation slots; every code-changing task includes concrete snippets and verification commands.
