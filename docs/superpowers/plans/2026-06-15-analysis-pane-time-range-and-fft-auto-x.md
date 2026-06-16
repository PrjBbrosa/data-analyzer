# Analysis Pane Time Range And FFT Auto X Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow split analysis panes to process the same channel over different time windows, make FFT spectrum auto frequency X range fit useful content without excessive blank space, and highlight the focused analysis pane with the active View color.

**Architecture:** Persist the selected analysis time window on each `AnalysisViewState.panes[*]`, echo that pane-local range when focus changes, and feed that range into FFT / FFT-vs-Time / Order compute and cache keys. Keep FFT display controls view-level, but replace the current coarse 1.3x + 1/2/5 rounding auto-X heuristic with a tighter data-driven limit. Reuse the existing analysis pane focus styling path, but bind its accent color to the active analysis View's `tab_color` instead of a fixed blue.

**Tech Stack:** Python, PyQt5, pyqtgraph, pytest-qt, existing `AnalysisViewState`, `AnalysisResultCache`, `PgLineCanvas`, `PgHeatmapCanvas`.

---

## Evidence From Current Code

- `mf4_analyzer/ui/analysis_view_state.py:26-31` stores pane-local `sources`, `rpm_source`, `xlim`, `ylim`, but no pane-local time range.
- `mf4_analyzer/ui/main_window.py:939-956` captures sources per pane, while `mf4_analyzer/ui/main_window.py:1003-1048` builds cache keys from view-level params only.
- `mf4_analyzer/ui/main_window.py:3136-3148`, `mf4_analyzer/ui/main_window.py:3928-3940`, `mf4_analyzer/ui/main_window.py:4011-4022`, `mf4_analyzer/ui/main_window.py:3337-3362` all read `self.inspector.top.range_enabled()` / `range_values()` directly.
- `mf4_analyzer/ui/main_window.py:1780-1789` only echoes FFT preview range to the focused pane's global Inspector state.
- `mf4_analyzer/ui/main_window.py:2996-3034` computes FFT auto X by finding the highest meaningful frequency, multiplying by `1.3`, then rounding up to coarse `1/2/5 * 10^n`; this can jump from about `10.4 Hz` to `20 Hz`.
- `tests/ui/test_inspector.py:1991-2025` already proves manual FFT X/Y ranges are honored. The broken path is automatic X range.
- `mf4_analyzer/ui/chart_stack.py:1331-1408` implements the TimeDomain split focus cue as a real top accent strip, colored by `ChartStack.set_focus_accent()`.
- `mf4_analyzer/ui/analysis_section_page.py:374-384` already highlights the focused analysis pane, but the accent is fixed `_FOCUS_ACCENT = "#2d7ff9"` instead of the active View color.

## File Map

- Modify `mf4_analyzer/ui/analysis_view_state.py`
  - Add `PaneState.time_range: tuple[float, float] | None`.
  - Persist it in `to_dict()` / `from_dict()`.

- Modify `mf4_analyzer/ui/main_window.py`
  - Add helpers to capture/apply pane-local analysis time ranges.
  - Include effective pane time range in analysis cache keys for FFT, FFT-vs-Time, and Order.
  - Pass effective pane time range into FFT signal fetch, FFT time preview, FFT-vs-Time jobs, and Order signal/RPM fetch.
  - Tighten `_fft_auto_xlim()`.
  - Refresh analysis pane focus styling after analysis View switches so the accent tracks the active View color.

- Modify `mf4_analyzer/ui/analysis_section_page.py`
  - Resolve the focused-pane accent from `manager.get(manager.active).tab_color`.
  - Expose a small `refresh_focus_style()` wrapper for `MainWindow` to call after active View changes.

- Modify `tests/ui/test_analysis_view_state.py`
  - Verify `PaneState.time_range` round-trips and missing old-project data remains valid.

- Modify `tests/ui/test_fft_fetch_signal.py`
  - Verify `_fft_fetch_signal(..., time_range=...)` masks with explicit range and remains backward compatible with Inspector fallback.

- Modify `tests/ui/test_analysis_multiview_integration.py`
  - Verify split panes can use the same `(fid, ch)` with different pane-local time ranges and produce distinct cache entries/results.
  - Verify focus switching echoes the pane-local range back into the Inspector.

- Modify `tests/ui/test_inspector.py`
  - Verify `_fft_auto_xlim()` no longer creates a wide blank region for low-frequency dominant spectra.

- Modify `tests/ui/test_analysis_section_page.py`
  - Verify the focused analysis pane uses the active View's `tab_color`.
  - Verify non-focused panes stay transparent and single-pane mode has no focus accent.

## Design Decisions

- `PaneState.time_range = None` means "do not filter by a selected time window".
- A concrete `(lo, hi)` means "this pane filters analysis compute to `lo <= t <= hi`".
- The shared Inspector remains the edit surface for the currently focused pane. When focus changes, the previous pane captures the Inspector range and the new pane applies its stored range.
- FFT / FFT-vs-Time / Order share this pane-local time range behavior because all three currently read the same global `inspector.top` range and all three can run in split panes.
- Time-domain view range state is not changed; this plan only touches analysis-section panes.
- FFT manual X range remains untouched. Only `x_auto=True` behavior changes.
- Focus highlight is visible only while an analysis section has two panes. It uses the active analysis View's `tab_color`, matching the TimeDomain idea that the focused-pane cue follows the View color.
- Analysis export remains canvas-only: `AnalysisSectionPage.grab_combined_pixmap()` grabs each pane's canvas pixels, so the focus chrome must not appear in exported images.

---

### Task 1: Persist Pane-Local Analysis Time Range

**Files:**
- Modify: `mf4_analyzer/ui/analysis_view_state.py`
- Test: `tests/ui/test_analysis_view_state.py`

- [ ] **Step 1: Write the failing serialization test**

Add this assertion coverage to `test_round_trip_preserves_everything`:

```python
def test_round_trip_preserves_everything():
    v = AnalysisViewState(name="对比", tab_color="#e8590c")
    v.panes = [
        PaneState(
            sources=[("f1", "vib_x"), ("f2", "vib_x")],
            time_range=(1.25, 2.75),
        ),
        PaneState(
            sources=[("f1", "vib_y")],
            rpm_source=("f1", "rpm"),
            time_range=(5.0, 8.0),
        ),
    ]
    v.params = {"nfft": 4096, "window": "hanning"}
    v.compare = {"x_linked": False, "levels_locked": True}

    v2 = AnalysisViewState.from_dict(v.to_dict())

    assert v2.name == "对比"
    assert v2.panes[0].sources == [("f1", "vib_x"), ("f2", "vib_x")]
    assert v2.panes[0].time_range == (1.25, 2.75)
    assert v2.panes[1].rpm_source == ("f1", "rpm")
    assert v2.panes[1].time_range == (5.0, 8.0)
    assert v2.params["nfft"] == 4096
    assert v2.compare["x_linked"] is False
```

Add this backward-compatibility assertion to `test_from_dict_tolerates_missing_fields`:

```python
def test_from_dict_tolerates_missing_fields():
    v = AnalysisViewState.from_dict({"name": "x", "tab_color": "#fff"})
    assert v.panes[0].sources == []
    assert v.panes[0].time_range is None
    assert v.params == {}
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_view_state.py -q
```

Expected before implementation: fails because `PaneState.__init__()` does not accept `time_range`, or the field does not round-trip.

- [ ] **Step 3: Add the minimal model field**

Patch `PaneState` like this:

```python
@dataclass
class PaneState:
    sources: list[ChannelKey] = field(default_factory=list)
    rpm_source: ChannelKey | None = None     # Order only
    time_range: tuple[float, float] | None = None
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [list(k) for k in self.sources],
            "rpm_source": list(self.rpm_source) if self.rpm_source else None,
            "time_range": list(self.time_range) if self.time_range else None,
            "xlim": list(self.xlim) if self.xlim else None,
            "ylim": list(self.ylim) if self.ylim else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaneState":
        def pair(v):
            return (float(v[0]), float(v[1])) if v else None
        return cls(
            sources=[_coerce_key(k) for k in data.get("sources", [])],
            rpm_source=(_coerce_key(data["rpm_source"])
                        if data.get("rpm_source") else None),
            time_range=pair(data.get("time_range")),
            xlim=pair(data.get("xlim")),
            ylim=pair(data.get("ylim")),
        )
```

- [ ] **Step 4: Verify the model test passes**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_view_state.py -q
```

Expected after implementation: all tests in `test_analysis_view_state.py` pass.

---

### Task 2: Capture, Apply, And Key Pane-Local Time Range

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_analysis_multiview_integration.py`

- [ ] **Step 1: Write the failing focus echo and cache-key tests**

Add this import near the existing imports if it is not present:

```python
from mf4_analyzer.ui.analysis_view_state import PaneState
```

Add these tests to `tests/ui/test_analysis_multiview_integration.py`:

```python
def test_fft_split_same_source_different_time_ranges_have_distinct_cache_keys(
    two_file_win, qapp
):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)

    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[0].time_range = (0.0, 0.35)
    state.panes[1].sources = [(fids[0], "speed")]
    state.panes[1].time_range = (0.55, 1.0)

    k0 = win._analysis_cache_key("fft", fids[0], "speed", pane_idx=0)
    k1 = win._analysis_cache_key("fft", fids[0], "speed", pane_idx=1)

    assert k0 != k1

    win.do_fft()
    qapp.processEvents()

    c0 = page.pane_canvas(0)
    c1 = page.pane_canvas(1)
    assert len(c0._amp_curves) == 1
    assert len(c1._amp_curves) == 1
    assert win.analysis_caches["fft"].get(k0) is not None
    assert win.analysis_caches["fft"].get(k1) is not None
```

```python
def test_analysis_focus_switch_echoes_pane_local_time_range(two_file_win, qapp):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)

    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[0].time_range = (0.1, 0.3)
    state.panes[1].sources = [(fids[0], "speed")]
    state.panes[1].time_range = (0.6, 0.9)

    page.set_focused_index(0)
    win._on_analysis_focus_changed("fft", 0)
    assert win.inspector.top.range_enabled() is True
    assert win.inspector.top.range_values() == pytest.approx((0.1, 0.3))

    page.set_focused_index(1)
    win._on_analysis_focus_changed("fft", 1)
    assert win.inspector.top.range_enabled() is True
    assert win.inspector.top.range_values() == pytest.approx((0.6, 0.9))
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py::test_fft_split_same_source_different_time_ranges_have_distinct_cache_keys tests/ui/test_analysis_multiview_integration.py::test_analysis_focus_switch_echoes_pane_local_time_range -q
```

Expected before implementation: cache keys are equal and/or pane focus does not echo stored `PaneState.time_range`.

- [ ] **Step 3: Add pane time-range helpers**

Add these methods near the existing source-routing helpers in `MainWindow`:

```python
    @staticmethod
    def _normalize_analysis_time_range(value):
        if not value:
            return None
        try:
            lo = float(value[0])
            hi = float(value[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return (lo, hi)

    @staticmethod
    def _analysis_section_uses_time_range(section):
        return section in {"fft", "fft_time", "order"}

    def _capture_analysis_time_range(self, section, state, pane_idx=None):
        if not self._analysis_section_uses_time_range(section):
            return
        page = self._analysis_page(section)
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        if self.inspector.top.range_enabled():
            pane.time_range = self._normalize_analysis_time_range(
                self.inspector.top.range_values()
            )
        else:
            pane.time_range = None

    def _set_top_range_enabled_silently(self, enabled):
        top = self.inspector.top
        old = top.chk_range.blockSignals(True)
        try:
            top.chk_range.setChecked(bool(enabled))
        finally:
            top.chk_range.blockSignals(old)
        top._range_checked_by_mode[top._range_mode] = bool(enabled)
        update = getattr(top, "_update_range_rows_visible", None)
        if callable(update):
            update()

    def _apply_analysis_time_range(self, section, state):
        if not self._analysis_section_uses_time_range(section):
            return
        page = self._analysis_page(section)
        idx = min(page.focused_index(), len(state.panes) - 1)
        rng = self._normalize_analysis_time_range(state.panes[idx].time_range)
        top = self.inspector.top
        if rng is None:
            self._set_top_range_enabled_silently(False)
            return
        top.set_range_from_span(*rng)

    def _pane_time_range_for(self, section, pane_idx=None):
        if not self._analysis_section_uses_time_range(section):
            return None
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        if pane_idx is None:
            page = self._analysis_page(section)
            pane_idx = page.focused_index()
        if not (0 <= int(pane_idx) < len(state.panes)):
            return None
        return self._normalize_analysis_time_range(
            state.panes[int(pane_idx)].time_range
        )
```

- [ ] **Step 4: Wire capture/apply into existing view flow**

Change `_capture_active_analysis_view`:

```python
    def _capture_active_analysis_view(self, section, *, capture_sources=True):
        from .analysis_view_bridge import capture_params_to_state
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        capture_params_to_state(self._analysis_ctx(section), state)
        self._capture_analysis_time_range(section, state)
        if capture_sources:
            self._capture_analysis_sources(section, state)
```

Change `_on_analysis_view_switched` after `_apply_analysis_sources(section, state)`:

```python
            self._apply_analysis_sources(section, state)
            self._apply_analysis_time_range(section, state)
```

Change `_on_analysis_focus_changed`:

```python
        old_idx = min(page.previous_focused_index(), len(state.panes) - 1)
        self._capture_analysis_sources(section, state, pane_idx=old_idx)
        self._capture_analysis_time_range(section, state, pane_idx=old_idx)
        self._apply_analysis_sources(section, state)
        self._apply_analysis_time_range(section, state)
```

Change `_on_fft_preview_range_changed` so preview dragging writes to the pane state too:

```python
        self.inspector.top.set_range_from_span(lo, hi)
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        state.panes[pane_idx].time_range = (float(lo), float(hi))
        return True
```

- [ ] **Step 5: Include pane time range in analysis cache keys**

Change `_analysis_cache_key` signature and body:

```python
    def _analysis_cache_key(self, section, fid, ch, rpm_source=None, pane_idx=None):
        cache = self.analysis_caches[section]
        params = dict(self._analysis_compute_params(section))
        if section in {'fft', 'fft_time', 'order'}:
            params['time_range'] = self._pane_time_range_for(section, pane_idx)
        if section == 'order':
            params['rpm_source'] = (
                list(rpm_source) if rpm_source else None
            )
        return cache.make_key(fid, ch, params)
```

Then update split callers to pass `pane_idx`:

```python
key = self._analysis_cache_key('fft', fid, ch, pane_idx=pane_idx)
```

```python
analysis_key = self._analysis_cache_key('fft_time', fid, ch, pane_idx=pane_idx)
```

```python
analysis_key = self._analysis_cache_key(
    'order', fid, ch,
    rpm_source=tuple(rpm_source) if rpm_source else None,
    pane_idx=pane_idx,
)
```

Keep legacy single-pane calls valid by leaving `pane_idx=None`.

- [ ] **Step 6: Verify Task 2 tests pass**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_view_state.py tests/ui/test_analysis_multiview_integration.py::test_fft_split_same_source_different_time_ranges_have_distinct_cache_keys tests/ui/test_analysis_multiview_integration.py::test_analysis_focus_switch_echoes_pane_local_time_range -q
```

Expected after implementation: all selected tests pass.

---

### Task 3: Use Pane Range For FFT, FFT-vs-Time, And Order Computation

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `tests/ui/test_fft_fetch_signal.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`

- [ ] **Step 1: Write explicit range-fetch tests**

Add this test to `tests/ui/test_fft_fetch_signal.py`:

```python
def test_explicit_time_range_masks_signal_without_inspector(win_with_source, monkeypatch):
    w, fd = win_with_source
    monkeypatch.setattr(w.inspector.top, 'range_enabled', lambda: False)

    sig, fs = w._fft_fetch_signal(0, 'sig', time_range=(0.25, 0.75))

    np.testing.assert_array_equal(sig, np.array([30.0, 40.0, 50.0, 60.0, 70.0]))
    assert fs == fd.fs
```

Add this test to `tests/ui/test_analysis_multiview_integration.py`:

```python
def test_fft_split_same_source_uses_each_pane_time_range(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[0].time_range = (0.0, 0.25)
    state.panes[1].sources = [(fids[0], "speed")]
    state.panes[1].time_range = (0.75, 1.0)

    seen_lengths = []
    real_compute = win._fft_compute_arrays

    def spy_compute(sig, fs, fft_params):
        seen_lengths.append(len(sig))
        return real_compute(sig, fs, fft_params)

    monkeypatch.setattr(win, "_fft_compute_arrays", spy_compute)

    win.do_fft()

    assert len(seen_lengths) == 2
    assert all(length < len(win.files[fids[0]].data) for length in seen_lengths)
    assert seen_lengths[0] == seen_lengths[1]
```

Use a more discriminating assertion if the fixture's time samples make the two windows have different lengths.

- [ ] **Step 2: Run the failing tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_fft_fetch_signal.py::test_explicit_time_range_masks_signal_without_inspector tests/ui/test_analysis_multiview_integration.py::test_fft_split_same_source_uses_each_pane_time_range -q
```

Expected before implementation: `_fft_fetch_signal()` rejects the new argument or ignores pane ranges.

- [ ] **Step 3: Add a shared range-mask helper**

Add this helper near `_normalize_analysis_time_range`:

```python
    def _mask_time_range(self, t, *arrays, time_range=None):
        rng = self._normalize_analysis_time_range(time_range)
        if rng is None or t is None:
            return (t, *arrays)
        lo, hi = rng
        mask = (t >= lo) & (t <= hi)
        masked = [arr[mask] for arr in arrays]
        return (t[mask], *masked)
```

- [ ] **Step 4: Thread explicit range through FFT helpers**

Change `_fft_trace_for_source`:

```python
    def _fft_trace_for_source(self, fid, ch, time_range=None):
        fd = self.files.get(fid)
        if fd is None or ch not in fd.data.columns:
            return None, None
        t = np.asarray(fd.time_array, dtype=float)
        sig = np.asarray(fd.data[ch].to_numpy(copy=False), dtype=float)
        if time_range is None and self.inspector.top.range_enabled():
            time_range = self.inspector.top.range_values()
        t, sig = self._mask_time_range(t, sig, time_range=time_range)
        return t, sig
```

Change `_fft_time_preview_entries` to accept `time_range` and pass it to `_fft_trace_for_source`:

```python
    def _fft_time_preview_entries(self, checked=None, time_range=None):
        ...
            t, sig = self._fft_trace_for_source(fid, ch, time_range=time_range)
```

Change `_fft_fetch_signal`:

```python
    def _fft_fetch_signal(self, fid, ch, time_range=None):
        fd = self.files.get(fid)
        if fd is None or ch not in fd.data.columns:
            return None, None
        sig = fd.data[ch].values
        t = fd.time_array
        if time_range is None and self.inspector.top.range_enabled():
            time_range = self.inspector.top.range_values()
        if time_range is not None and t is not None:
            _t, sig = self._mask_time_range(t, sig, time_range=time_range)
        return sig, fd.fs
```

Change `do_fft()` split loop:

```python
            time_range = self._pane_time_range_for('fft', pane_idx)
            for fid, ch in sources:
                key = self._analysis_cache_key('fft', fid, ch, pane_idx=pane_idx)
                result = cache.get(key)
                if result is None:
                    sig, fs = self._fft_fetch_signal(fid, ch, time_range=time_range)
                    ...
                    sig, fs = self._fft_fetch_signal(fid, ch, time_range=time_range)
                    ...
                entries.append(self._fft_entry_from_cache(
                    result, fid, ch, colors.get((fid, ch)), time_range=time_range))
```

Change `_fft_entry_from_cache` signature:

```python
    def _fft_entry_from_cache(self, result, fid, ch, color, time_range=None):
        ...
        t, sig = self._fft_trace_for_source(fid, ch, time_range=time_range)
```

- [ ] **Step 5: Thread explicit range through FFT-vs-Time split jobs**

Change `_dispatch_fft_time_job` signature:

```python
    def _dispatch_fft_time_job(self, pane_idx, fid, ch, force=False, time_range=None):
```

In `_start_next_fft_time_job`, look up and pass the pane range:

```python
            time_range = self._pane_time_range_for('fft_time', pane_idx)
            if self._dispatch_fft_time_job(
                pane_idx, fid, ch, time_range=time_range
            ):
                return
```

Inside `_dispatch_fft_time_job`, replace the global Inspector range block with:

```python
        rng = self._normalize_analysis_time_range(time_range)
        if rng is not None:
            lo, hi = rng
            t, sig = self._mask_time_range(t, sig, time_range=rng)
            if len(sig) < 2:
                return False
            effective_time_range = rng
        else:
            effective_time_range = (float(t[0]), float(t[-1]))
        key_params = dict(p, fid=fid, channel=ch, time_range=effective_time_range)
        key = self._fft_time_cache_key(key_params)
        analysis_key = self._analysis_cache_key(
            'fft_time', fid, ch, pane_idx=pane_idx)
```

Leave `_do_fft_time_single()` compatible with the current Inspector fallback, but change its `analysis_key` to pass `pane_idx=pane_idx`.

- [ ] **Step 6: Thread explicit range through Order split jobs**

Change `_order_sig_for`:

```python
    def _order_sig_for(self, source, time_range=None):
        if not source:
            return None, None
        fid, ch = source
        if fid not in self.files:
            return None, None
        fd = self.files[fid]
        if ch not in fd.data.columns:
            return None, None
        t = fd.time_array
        sig = fd.data[ch].values
        if time_range is None and self.inspector.top.range_enabled():
            time_range = self.inspector.top.range_values()
        if time_range is not None and t is not None:
            t, sig = self._mask_time_range(t, sig, time_range=time_range)
        return t, sig
```

Change `_order_rpm_for`:

```python
    def _order_rpm_for(self, rpm_source, n, time_range=None):
        ...
        if time_range is None and self.inspector.top.range_enabled():
            time_range = self.inspector.top.range_values()
        if time_range is not None and fd.time_array is not None:
            _t, rpm = self._mask_time_range(
                fd.time_array, rpm, time_range=time_range)
        if len(rpm) != n:
            return None
        return rpm
```

Change `_dispatch_order_job`:

```python
        time_range = self._pane_time_range_for('order', pane_idx)
        t, sig = self._order_sig_for((fid, ch), time_range=time_range)
        ...
        rpm = self._order_rpm_for(rpm_source, len(sig), time_range=time_range)
        ...
        self._order_analysis_key = self._analysis_cache_key(
            'order', fid, ch,
            rpm_source=tuple(rpm_source) if rpm_source else None,
            pane_idx=pane_idx)
```

- [ ] **Step 7: Verify computation tests pass**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_fft_fetch_signal.py tests/ui/test_analysis_multiview_integration.py -q
```

Expected after implementation: all selected tests pass.

---

### Task 4: Tighten FFT Spectrum Auto Frequency X Range

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_inspector.py`

- [ ] **Step 1: Write the failing auto-X heuristic test**

Add this test near `test_fft_render_honors_manual_xy_axis_ranges`:

```python
def test_fft_auto_xlim_keeps_low_frequency_spectrum_tight(qtbot):
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    freq = np.linspace(0.0, 25.0, 251)
    amp = np.full_like(freq, 0.0001)
    amp[(freq >= 1.0) & (freq <= 8.0)] = 0.02

    x_max = win._fft_auto_xlim(freq, amp)

    assert 8.0 < x_max <= 10.0
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_inspector.py::test_fft_auto_xlim_keeps_low_frequency_spectrum_tight -q
```

Expected before implementation: fails with the current `20` Hz auto limit.

- [ ] **Step 3: Replace coarse 30% + nice rounding with tight margin**

Patch `_fft_auto_xlim`:

```python
    @staticmethod
    def _fft_auto_xlim(freq, amp):
        """自适应计算 FFT 频率范围。

        忽略 DC 分量，找到幅值仍达到非 DC 峰值 1% 以上的最高频率点，
        再只加小幅余量。pyqtgraph 轴刻度已经会自己取整，这里不要再把
        上限粗暴抬到 1/2/5 * 10^n，否则低频主导谱会留下大块空白。
        """
        if len(freq) < 2 or len(amp) < 2:
            return float(freq[-1]) if len(freq) else 100.0

        freq = np.asarray(freq, dtype=float)
        amp = np.asarray(amp, dtype=float)
        body = amp[1:] if len(amp) > 1 else amp
        peak = float(np.nanmax(body)) if len(body) else 0.0
        if peak <= 0 or not np.isfinite(peak):
            return float(freq[-1])

        threshold = peak * 0.01
        meaningful = np.where(body >= threshold)[0]
        if len(meaningful) == 0:
            return float(freq[-1])

        idx = int(meaningful[-1]) + 1
        f_cutoff = float(freq[min(idx, len(freq) - 1)])
        nyquist = float(freq[-1])
        if not np.isfinite(f_cutoff) or f_cutoff <= 0:
            return nyquist

        df = float(np.nanmedian(np.diff(freq))) if len(freq) > 2 else 0.0
        if not np.isfinite(df) or df <= 0:
            df = max(f_cutoff * 0.02, 1e-9)
        margin = max(df * 2.0, f_cutoff * 0.08)
        return min(nyquist, f_cutoff + margin)
```

- [ ] **Step 4: Run auto/manual X tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_inspector.py::test_fft_auto_xlim_keeps_low_frequency_spectrum_tight tests/ui/test_inspector.py::test_fft_render_honors_manual_xy_axis_ranges -q
```

Expected after implementation: both tests pass; manual range remains exact.

---

### Task 5: Highlight Focused Analysis Pane With Active View Color

**Files:**
- Modify: `mf4_analyzer/ui/analysis_section_page.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_analysis_section_page.py`
- Test: `tests/ui/test_analysis_multiview_integration.py`

- [ ] **Step 1: Write the failing AnalysisSectionPage focus-color tests**

Add these tests near `test_set_focus` in `tests/ui/test_analysis_section_page.py`:

```python
def test_split_focus_border_uses_active_view_tab_color(page):
    page.manager.get(page.manager.active).tab_color = "#e8590c"

    page.enter_split()
    page.set_focused_index(1)

    focused_style = page._cards[1].styleSheet()
    other_style = page._cards[0].styleSheet()
    assert "#e8590c" in focused_style
    assert "border: 1px solid #e8590c" in focused_style
    assert "transparent" in other_style
```

```python
def test_single_analysis_pane_does_not_show_focus_border(page):
    page.manager.get(page.manager.active).tab_color = "#e8590c"

    page.refresh_focus_style()

    style = page._cards[0].styleSheet()
    assert "#e8590c" not in style
    assert "transparent" in style
```

```python
def test_focus_border_refreshes_when_active_view_color_changes(page):
    page.enter_split()
    page.set_focused_index(0)
    page.manager.get(page.manager.active).tab_color = "#e8590c"
    page.refresh_focus_style()
    assert "#e8590c" in page._cards[0].styleSheet()

    page.manager.get(page.manager.active).tab_color = "#2ca02c"
    page.refresh_focus_style()
    assert "#2ca02c" in page._cards[0].styleSheet()
    assert "#e8590c" not in page._cards[0].styleSheet()
```

- [ ] **Step 2: Run the failing focus-color tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py::test_split_focus_border_uses_active_view_tab_color tests/ui/test_analysis_section_page.py::test_single_analysis_pane_does_not_show_focus_border tests/ui/test_analysis_section_page.py::test_focus_border_refreshes_when_active_view_color_changes -q
```

Expected before implementation: fails because `refresh_focus_style()` does not exist and `_apply_focus_style()` still uses fixed `_FOCUS_ACCENT`.

- [ ] **Step 3: Resolve focus accent from the active analysis View**

Patch `mf4_analyzer/ui/analysis_section_page.py` near `_apply_focus_style`:

```python
    def _active_view_focus_accent(self) -> str:
        try:
            state = self.manager.get(self.manager.active)
            color = getattr(state, "tab_color", None)
        except Exception:
            color = None
        return color or _FOCUS_ACCENT

    def refresh_focus_style(self) -> None:
        self._apply_focus_style()

    def _apply_focus_style(self) -> None:
        focus_accent = self._active_view_focus_accent()
        for i, card in enumerate(self._cards):
            accent = (
                focus_accent
                if (i == self._focused and len(self._cards) > 1)
                else "transparent"
            )
            # padding insets the layout content rect so the margin-0 canvas
            # child stops overpainting the 1px ring (same lesson as
            # WA_StyledBackground above).
            card.setStyleSheet(
                f"QWidget#chartCard {{ border: 1px solid {accent}; "
                f"padding: {1 if accent != 'transparent' else 0}px; }}"
            )
```

Keep `_FOCUS_ACCENT` as the fallback for malformed state or tests with a minimal fake manager.

- [ ] **Step 4: Refresh the focus cue on analysis View switches**

Patch `_on_analysis_view_switched` in `mf4_analyzer/ui/main_window.py` after applying params, sources, and pane-local time range:

```python
            apply_params_from_state(self._analysis_ctx(section), state)
            self._apply_analysis_sources(section, state)
            self._apply_analysis_time_range(section, state)
            refresh_focus = getattr(page, "refresh_focus_style", None)
            if callable(refresh_focus):
                refresh_focus()
```

- [ ] **Step 5: Write a MainWindow integration assertion**

Add this test to `tests/ui/test_analysis_multiview_integration.py`:

```python
def test_analysis_view_switch_refreshes_focus_border_color(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]

    mgr.get(mgr.active).tab_color = "#e8590c"
    win._on_analysis_split("fft", True)
    page.set_focused_index(0)
    win._on_analysis_view_switched("fft", mgr.active)
    assert "#e8590c" in page._cards[0].styleSheet()

    idx = mgr.new_view()
    mgr.get(idx).tab_color = "#2ca02c"
    mgr.set_active(idx)
    win._on_analysis_view_switched("fft", idx)
    assert "#2ca02c" in page._cards[0].styleSheet()
    assert "#e8590c" not in page._cards[0].styleSheet()
```

- [ ] **Step 6: Run the focused focus-color tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py::test_split_focus_border_uses_active_view_tab_color tests/ui/test_analysis_section_page.py::test_single_analysis_pane_does_not_show_focus_border tests/ui/test_analysis_section_page.py::test_focus_border_refreshes_when_active_view_color_changes tests/ui/test_analysis_multiview_integration.py::test_analysis_view_switch_refreshes_focus_border_color -q
```

Expected after implementation: all four tests pass.

---

### Task 6: Regression Sweep And Lesson Gate

**Files:**
- No new source files.
- Optional: `docs/lessons-learned/*.md` only if implementation uncovers a new durable rule not already covered by existing lessons.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_view_state.py tests/ui/test_fft_fetch_signal.py tests/ui/test_analysis_multiview_integration.py tests/ui/test_inspector.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run analysis-section focus/layout checks**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py tests/ui/test_view_tabbar.py tests/ui/test_view_tabbar_mount.py -q
```

Expected: analysis split focus styling and shared ViewTabBar chrome still pass.

- [ ] **Step 3: Run lesson-specified canvas checks**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py -q
```

Expected: line/heatmap canvas range and tick-density contracts still pass.

- [ ] **Step 4: Run static diff check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Decide whether a new lesson is required**

Run:

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

If implementation adds a durable new rule beyond these existing lessons:

- `codex-analysis-section-state-needs-pane-local-sources`
- `codex-fft-spectrum-time-preview`
- `codex-fft-time-review-shields`
- `analysis-bottom-axis-explicit-ticks-retick-on-range-change`
- `codex-shared-viewtabbar-and-pg-frames`

then create `.state/lesson-candidate.md` from `docs/lessons-learned/_template.md`, promote it with:

```bash
/usr/bin/python3 scripts/lessons/promote.py
```

If no new rule is needed, do not add a lesson.

---

## Acceptance Criteria

- Split FFT panes can use the same `(fid, ch)` with different `PaneState.time_range` values and store two distinct cache entries.
- Split FFT-vs-Time panes can use the same `(fid, ch)` with different `PaneState.time_range` values without sharing a stale analysis-cache result.
- Split Order panes use the pane-local range for both signal and RPM arrays.
- Focusing a pane echoes that pane's time range into the Inspector; dragging the FFT lower preview writes back to the focused pane.
- Manual FFT X range remains exact.
- FFT auto X range no longer jumps to a much larger coarse "nice" max for low-frequency dominant spectra.
- In split analysis sections, the focused pane has a visible highlight using the active View's `tab_color`; the non-focused pane stays neutral and single-pane mode shows no focus accent.
- Switching analysis Views refreshes the focused-pane highlight color immediately.
- Analysis canvas export remains free of the focus highlight because combined export still grabs pane canvases, not card chrome.
- Existing time-domain range checkbox per-mode isolation remains intact.

## Self-Review

- Spec coverage: all three requested issues are covered. The first is implemented as analysis pane-local state and cache-key correctness. The second is limited to FFT spectrum auto X range, matching the screenshot and current code path. The third upgrades the existing analysis focus cue to use the active View color.
- Placeholder scan: no `TBD`, no "implement later", no unspecified error handling.
- Type consistency: the new state field is always `tuple[float, float] | None`; helper names and call signatures are consistent across tasks.
