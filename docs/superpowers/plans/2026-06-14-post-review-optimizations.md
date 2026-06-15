# Post-Review Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the concrete bugs, contract holes, over-claims, and cleanup opportunities surfaced by the 2026-06-14 global review of the day's 41 commits — restoring a green test suite and hardening the FFT / pyqtgraph-canvas / inspector code touched today.

**Architecture:** Four priority tiers. **A (必须)** makes the suite green again (currently 1 failed + 1 error). **B (需要)** closes latent bugs whose function contracts are unsafe but currently shielded by outer guards. **C (应该)** corrects two commits whose messages over-claim what the code does. **D (可以)** is pure health: dedup, dead-code removal, inert-guard cleanup. Every behavioral change is TDD-first; every cleanup is verified by the existing suite staying green.

**Tech Stack:** Python 3.12, PyQt5 5.15 (offscreen Qt for tests), pyqtgraph, numpy/scipy, pytest + pytest-qt.

**Squad ownership (repo convention — CLAUDE.md):**
- `signal-processing-expert` → Tier B1, C1 (numeric, `signal/fft.py`)
- `pyqt-ui-engineer` → A1, A2, B2, B4, C2, D3, D4, D5, D6
- `refactor-architect` → D1, D2 (cross-canvas dedup / shared helper extraction)

**Baseline for review:** `be5c61a` (parent of today's first commit). All line numbers below are against `HEAD` = `2cb1a91`.

**Run the suite with:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

---

## Tier A — 必须：让套件回绿 (P1)

Current state: `1 failed, 1971 passed, 3 skipped, 1 error`. Both reds are *today's incomplete batch-fixes*, not new product regressions.

### Task A1: Fix stale Alt→Ctrl assertions in `test_hints.py`

The Alt→Ctrl shortcut migration landed 2026-06-10 (`9570b95`); today's `0b61d5a` ("fix stale Alt assertions") fixed `test_chart_stack.py` but missed `test_hints.py`. `hints.py` now maps `pan → Ctrl+G`, `btn_overlay → Ctrl+2` (verified `mf4_analyzer/ui/hints.py:48,54`).

**Files:**
- Modify/Test: `tests/ui/test_hints.py:106-107`

- [ ] **Step 1: Run the failing test to confirm the red**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_hints.py::test_shortcut_tooltip_returns_exact_registered_key -v`
Expected: FAIL — `assert 'Ctrl+G' == 'Alt+G'`

- [ ] **Step 2: Update both assertions to the registered Ctrl keys**

Replace lines 106-107:

```python
    assert hints.shortcut_tooltip("pan") == "Ctrl+G"
    assert hints.shortcut_tooltip("btn_overlay") == "Ctrl+2"
```

(Line 108 `shortcut_tooltip("missing") is None` is unchanged.)

- [ ] **Step 3: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_hints.py -v`
Expected: PASS (all hints tests)

- [ ] **Step 4: Commit**

```bash
git add tests/ui/test_hints.py
git commit -m "test(hints): finish Alt→Ctrl assertion migration missed by 0b61d5a"
```

### Task A2: Hoist the `_own_chartstacks` teardown-cascade fixture to `conftest.py`

The pyqtgraph teardown cascade (`'LabelItem' object has no attribute '_sizeHint'`) errors `test_timedomain_canvas_contract.py::test_chart_stack_copy_card_image_composites_cursor_pill` in the full run (passes in isolation). Today's `89035ec` added an autouse fixture for this — but only locally in `test_chart_stack.py` (lines 14-45). Hoisting it to `tests/ui/conftest.py` fixes this file *and* any future UI test that builds an unowned `ChartStack`.

**Files:**
- Modify: `tests/ui/conftest.py` (add fixture)
- Modify: `tests/ui/test_chart_stack.py:14-45` (remove the now-duplicated local fixture)

- [ ] **Step 1: Confirm the error reproduces only in the full run**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/ -q 2>&1 | tail -5`
Expected: includes `ERROR tests/ui/test_timedomain_canvas_contract.py::test_chart_stack_copy_card_image_composites_cursor_pill`

- [ ] **Step 2: Add the autouse fixture to `tests/ui/conftest.py`**

Append to `tests/ui/conftest.py` (the file already imports `gc`, `os`, `pytest`, `QApplication`; add the `ChartStack` import at top with the other imports):

```python
@pytest.fixture(autouse=True)
def _own_chartstacks(qapp, monkeypatch):
    """Keep every ChartStack built in a test alive until its queued
    ``QTimer.singleShot(0, ...)`` layout callbacks (quality-indicator / heatmap
    layout sync) are drained, then delete it cleanly.

    Unowned ``ChartStack()`` instances leave layout callbacks queued; when the
    local is GC'd at function return pytest-qt's teardown ``processEvents`` fires
    a callback on a half-dead pyqtgraph ``LabelItem`` — an order-dependent
    teardown-error cascade. Holding a ref keeps the widget ALIVE so the drain
    runs on a live object, then we deleteLater + drain again.
    See docs/lessons-learned/pyqt-ui/2026-06-14-chart-stack-unowned-widgets-pyqtgraph-teardown-cascade.md
    """
    from mf4_analyzer.ui.chart_stack import ChartStack

    created = []
    orig_init = ChartStack.__init__

    def _tracking_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(ChartStack, "__init__", _tracking_init)
    yield
    qapp.processEvents()
    for cs in created:
        try:
            cs.deleteLater()
        except Exception:
            pass
    created.clear()
    qapp.processEvents()
```

- [ ] **Step 3: Remove the now-duplicated local fixture from `test_chart_stack.py`**

Delete lines 14-45 (`@pytest.fixture(autouse=True)` through the blank line after `qapp.processEvents()`). Remove the local `ChartStack` import only if it is now unused elsewhere in the file (it is used by tests, so keep it).

- [ ] **Step 4: Run the previously-erroring test plus the whole chart-stack file in the full-suite context**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_timedomain_canvas_contract.py tests/ui/test_chart_stack.py -q`
Expected: PASS, no teardown ERROR

- [ ] **Step 5: Run the entire suite to confirm green**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: `0 failed ... 0 errors`

- [ ] **Step 6: Commit**

```bash
git add tests/ui/conftest.py tests/ui/test_chart_stack.py
git commit -m "test(ui): hoist _own_chartstacks fixture to conftest — fixes teardown cascade in timedomain contract (root-cause vs 89035ec)"
```

---

## Tier B — 需要：潜伏 bug / 契约洞 (P2)

These are real defects in a function's own contract, currently masked by an outer guard. Fix the contract so it is total, not "safe only because of the caller."

### Task B1: Guard `compute_averaged_fft` degenerate segment against NaN spectrum

`signal/fft.py:218` divides by `w_sum ** 2`. For `effective_nfft == 2` a symmetric Hann window is `[0., 0.]` → `w_sum == 0` → all-NaN spectrum (verified). `n == 1` yields `effective_nfft == 1, half == 0`; `n == 0` raises. Only the UI `len(sig) < 10` guard shields this today; the staticmethod itself must be total.

**Files:**
- Modify: `mf4_analyzer/signal/fft.py` (`FFTAnalyzer.compute_averaged_fft`, ~lines 196-224)
- Test: `tests/test_fft_amplitude_normalization.py` (add to `WelchShortSignalTests`, class at line 156)

- [ ] **Step 1: Write the failing test**

Add to `WelchShortSignalTests`:

```python
    def test_tiny_signal_returns_finite_zero_spectrum(self):
        """n in {0,1,2,3} must yield finite (zero) arrays, never NaN.

        Regression: a length-2 Hann window sums to 0, so the psd divide
        produced an all-NaN spectrum. Reaching a defined-zero branch is the
        contract; see 2026-05-19-branch-reached-is-not-behavior-correct.md.
        """
        fs = 100.0
        for n in (0, 1, 2, 3):
            sig = np.ones(n)
            freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
                sig, fs, win="hanning", nfft=1024, overlap=0.5
            )
            self.assertTrue(np.all(np.isfinite(amp)), f"n={n}: non-finite amp")
            self.assertTrue(np.all(np.isfinite(psd)), f"n={n}: non-finite psd")
            self.assertEqual(amp.shape, freq.shape)
            self.assertEqual(psd.shape, freq.shape)
            self.assertTrue(np.all(amp == 0.0), f"n={n}: expected zero amp")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_fft_amplitude_normalization.py::WelchShortSignalTests::test_tiny_signal_returns_finite_zero_spectrum -v`
Expected: FAIL — non-finite amp at `n=2` (and/or shape/raise at `n in {0,1}`)

- [ ] **Step 3: Add the degenerate guard in `compute_averaged_fft`**

At the top of the method body, before `effective_nfft = min(nfft, n)`:

```python
        n = len(sig)
        if n == 0:
            empty = np.array([])
            return empty, empty, empty
```

Then, immediately after `freq = np.fft.fftfreq(effective_nfft, 1 / fs)[:half]` and before the `psd_sum = np.zeros(half)` loop, insert:

```python
        if half == 0 or w_sum <= 0.0:
            # Degenerate segment: effective_nfft < 2, or a window that sums to
            # zero (e.g. a length-2 Hann). Return a defined zero spectrum
            # instead of dividing by w_sum**2 into NaN.
            zeros = np.zeros(half)
            return freq, zeros, zeros
```

(`w_sum` is already computed at the existing `w_sum = np.sum(w)` line; ensure it is a float — change to `w_sum = float(np.sum(w))`.)

- [ ] **Step 4: Run the new test plus the full FFT file**

Run: `.venv/bin/python -m pytest tests/test_fft_amplitude_normalization.py -v`
Expected: PASS (new test + all existing Welch/normalization tests — the `n >= nfft` path is untouched)

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/signal/fft.py tests/test_fft_amplitude_normalization.py
git commit -m "fix(signal): make compute_averaged_fft total — defined zero spectrum for degenerate nfft (w_sum=0 NaN)"
```

### Task B2: Guard the queued quality-indicator flush against a torn-down card

`chart_stack.py:1344-1346` `_flush_quality_indicator_position` calls `_position_quality_indicator`, which does `canvas.geometry()` (line 1330). A `QTimer.singleShot(0, ...)` can fire after the card's C++ canvas is deleted → `RuntimeError`. Today this is only papered over by the test fixture (Task A2); production is still exposed.

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py:1344-1346`
- Test: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_chart_stack.py`:

```python
def test_flush_quality_indicator_swallows_dead_canvas(qapp, monkeypatch):
    """A queued singleShot flush must not raise if the canvas C++ object was
    deleted before it fired (teardown race)."""
    cs = ChartStack()
    card = cs.widget(0)  # a _ChartCard with the quality-indicator machinery
    card._quality_indicator_position_pending = True

    def _boom():
        raise RuntimeError("wrapped C/C++ object of type ... has been deleted")

    monkeypatch.setattr(card, "_position_quality_indicator", _boom)
    # Must not raise:
    card._flush_quality_indicator_position()
    assert card._quality_indicator_position_pending is False
```

(Adjust `cs.widget(0)` to whatever accessor returns a card carrying `_flush_quality_indicator_position`; confirm by reading the `ChartStack`/`_ChartCard` construction.)

- [ ] **Step 2: Run it to confirm it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_chart_stack.py::test_flush_quality_indicator_swallows_dead_canvas -v`
Expected: FAIL — `RuntimeError` propagates

- [ ] **Step 3: Wrap the flush in a RuntimeError guard**

```python
    def _flush_quality_indicator_position(self):
        self._quality_indicator_position_pending = False
        try:
            self._position_quality_indicator()
        except RuntimeError:
            # Card/canvas C++ object was deleted before this queued singleShot
            # fired (teardown race) — nothing left to position.
            pass
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_chart_stack.py
git commit -m "fix(chart): guard queued quality-indicator flush against deleted canvas (teardown race)"
```

### Task B3: Keep the slice right frame line when there is no colorbar reserve

`heatmap_canvas.py:1411-1419` (`_align_slice_to_main`) restores the visible slice right frame only when `reserve > 1.0`; `_set_slice_right_spacer(None)` (line ~1781) hides the right axis. Every current call site renders with a colorbar so the box stays closed — but a colorbar-less path re-opens the slice box on the right (the exact `d776873` regression, reintroduced by geometry). Make the frame line independent of the reserve width.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` (`_align_slice_to_main`, ~lines 1405-1419; `_set_slice_right_spacer`, ~line 1781)
- Test: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: Read the current logic**

Run: `sed -n '1400,1425p;1775,1795p' mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
Identify where the `right` axis frame pen is set vs. where `reserve > 1.0` gates it.

- [ ] **Step 2: Write the failing test**

```python
def test_slice_right_frame_visible_without_colorbar_reserve(qapp, qtbot):
    """The 1px slice right frame must persist even when the colorbar column
    collapses (reserve <= 1.0) — regression guard for d776873 via geometry."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    canvas = cs.canvas_fft_time
    canvas.setParent(None)
    qtbot.addWidget(canvas)
    canvas.show()
    qapp.processEvents()
    # Force the no-reserve path (no colorbar column):
    canvas._align_slice_to_main(reserve=1.0)  # adjust to real signature
    qapp.processEvents()
    right_axis = canvas._slice_plot.getAxis('right')
    pen = right_axis.pen()
    assert pen.color().alpha() > 0  # frame pen still drawn
```

(Adjust the forced-no-reserve call to the real method signature / private hook discovered in Step 1.)

- [ ] **Step 3: Run it to confirm it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_slice_right_frame_visible_without_colorbar_reserve -v`
Expected: FAIL — frame pen transparent / axis hidden when reserve <= 1.0

- [ ] **Step 4: Decouple the frame pen from the reserve branch**

In `_align_slice_to_main`, move the "show right axis with the neutral frame pen, transparent text" calls out of the `if reserve > 1.0:` branch so the frame is always drawn; keep only the *width/spacer* sizing inside the reserve branch.

- [ ] **Step 5: Run the test plus the full heatmap file**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -q`
Expected: PASS (new test + existing `test_slice_right_frame_visible_after_colorbar_reserve`)

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "fix(analysis): draw slice right frame independent of colorbar reserve width"
```

### Task B4: Log (not silently swallow) failed replot callbacks

`line_canvas.py:428-433` `_run_replot_callbacks` does `except Exception: pass`. These callbacks are the toolbar back/forward + mouse-mode rebinding (registered by `chart_stack.py`); a wiring break is invisible. Keep swallowing (teardown-safe) but emit a debug log.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py` (module-level logger + `_run_replot_callbacks`, lines 428-433)
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: Write the failing test**

```python
def test_replot_callback_failure_is_logged_not_swallowed(qapp, qtbot, caplog):
    import logging
    cs = ChartStack()
    qtbot.addWidget(cs)
    canvas = cs.canvas_fft
    canvas.register_replot_callback(lambda: (_ for _ in ()).throw(ValueError("boom")))
    with caplog.at_level(logging.DEBUG, logger="mf4_analyzer.ui.pg_canvas.line_canvas"):
        canvas._run_replot_callbacks()  # must not raise
    assert any("boom" in r.getMessage() or r.exc_info for r in caplog.records)
```

(Adjust `cs.canvas_fft` / `register_replot_callback` to the real accessor names confirmed in `line_canvas.py`.)

- [ ] **Step 2: Run it to confirm it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_replot_callback_failure_is_logged_not_swallowed -v`
Expected: FAIL — no log record

- [ ] **Step 3: Add a module logger and log in the except**

Near the top imports of `line_canvas.py`:

```python
import logging

logger = logging.getLogger(__name__)
```

Then:

```python
    def _run_replot_callbacks(self) -> None:
        for cb in list(self._replot_callbacks):
            try:
                cb()
            except Exception:
                logger.debug("replot callback %r failed", cb, exc_info=True)
```

- [ ] **Step 4: Run the test plus the full line-canvas file**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(fft): log failed replot callbacks instead of silently swallowing"
```

---

## Tier C — 应该：修正夸大叙述 / 死参数 (P2)

### Task C1: Surface the Welch resolution clamp (the "三路径一致" over-claim)

`407b121`'s message claims it unified the three FFT paths' short-signal handling. It did not: for `n=500, nfft=1024` the three return lengths `512 / 250 / 513`. The Welch path silently clamps the user's requested resolution from `fs/nfft` to `fs/n`. **Recommended:** keep the numerically-honest clamp, but (a) warn so the clamp is not silent, and (b) correct the in-repo lesson/docstring so the "consistent" claim is dropped. (Alternative — pad-to-nfft to match the sibling lengths — is interpolated, not true, resolution; do **not** adopt it unless cross-path length equality becomes a hard requirement. Document the divergence as intentional.)

**Files:**
- Modify: `mf4_analyzer/signal/fft.py` (`compute_averaged_fft`, after `effective_nfft = min(nfft, n)`)
- Modify: `docs/lessons-learned/orchestrator/decompositions/2026-06-14-fft-order-vs-time-four-bug-fixes.md` (drop / correct the "三路径一致" wording)
- Test: `tests/test_fft_amplitude_normalization.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_short_signal_warns_about_resolution_clamp(self):
        import warnings
        fs = 1000.0
        sig = np.sin(2 * np.pi * 50 * np.arange(500) / fs)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            FFTAnalyzer.compute_averaged_fft(sig, fs, win="hanning", nfft=1024)
        assert any(issubclass(w.category, UserWarning) for w in caught)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_fft_amplitude_normalization.py::WelchShortSignalTests::test_short_signal_warns_about_resolution_clamp -v`
Expected: FAIL — no warning emitted

- [ ] **Step 3: Emit a UserWarning when clamping**

Add `import warnings` at the top of `fft.py` if absent. After `effective_nfft = min(nfft, n)`:

```python
        if effective_nfft < nfft:
            warnings.warn(
                f"signal length {n} < nfft {nfft}; frequency resolution "
                f"clamped to fs/{effective_nfft} (matches scipy.signal.welch).",
                UserWarning,
                stacklevel=2,
            )
```

- [ ] **Step 4: Correct the lesson wording**

In the decomposition doc, replace any claim that the three FFT paths return identical short-signal output with: the Welch path clamps to true `fs/n` resolution (and warns); single-frame and peak-hold zero-pad to `nfft`. The lengths/freq-spans intentionally differ.

- [ ] **Step 5: Run the FFT file**

Run: `.venv/bin/python -m pytest tests/test_fft_amplitude_normalization.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/signal/fft.py tests/test_fft_amplitude_normalization.py docs/lessons-learned/orchestrator/decompositions/2026-06-14-fft-order-vs-time-four-bug-fixes.md
git commit -m "fix(signal): warn on Welch short-signal resolution clamp; correct '三路径一致' claim"
```

### Task C2: Remove the dead `checked` parameter + misleading comments in `_update_range_rows_visible`

`inspector_sections.py:1718-1719` ignores its `checked` arg and unconditionally shows the row; comments at 1568/1646/1816-1818 describe a "hide 开始/结束 row when disabled" behavior that does not exist. **Recommended (safe, no behavior change):** drop the dead parameter and the false comments; the row is intentionally always visible. (Alternative — actually hide the row when unchecked — is a product decision; do not implement without confirmation.)

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py:1718-1719` and its call site(s) (~1816-1818), plus the misleading comments at 1568, 1646
- Test: existing suite (no-op refactor)

- [ ] **Step 1: Find all call sites**

Run: `grep -rn "_update_range_rows_visible" mf4_analyzer/`
Confirm every caller passes an argument that is currently ignored.

- [ ] **Step 2: Change signature to no-arg and update callers**

```python
    def _update_range_rows_visible(self):
        # The 开始/结束 row is always shown; the chk_range checkbox row stays
        # visible regardless of state. (Hiding the row on uncheck was never
        # implemented — see review 2026-06-14.)
        _set_form_row_visible(self._range_form, self._range_row_host, True)
```

Update each call site `self._update_range_rows_visible(<arg>)` → `self._update_range_rows_visible()`.

- [ ] **Step 3: Delete the three false comments** at lines 1568, 1646, and the 1816-1818 block describing conditional row visibility.

- [ ] **Step 4: Run the inspector tests + full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_inspector.py -q && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: PASS, no behavior change

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py
git commit -m "refactor(inspector): drop dead _update_range_rows_visible param + false visibility comments"
```

---

## Tier D — 可以：去重 / 死代码 / 清理 (P2/P3)

Pure health. Each task is verified by the existing suite staying green; no behavior change intended.

### Task D1: Extract a `_StackedSplitMixin` to dedup the split/collapse handlers

`line_canvas.py:792-861` and `heatmap_canvas.py:1458-1536` carry near-identical drag/collapse/reset/expand handlers (~70 duplicated lines; docstrings copied verbatim). Today's work correctly hoisted the *primitives* (`_SplitDivider`, `_CollapsedRail`, `_apply_plot_collapse`, `_clamp_bottom_split`, `_position_collapse_layout`, `_make_analysis_plot`) but left the *handler wiring* duplicated. (Owner: `refactor-architect`.)

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/_split_mixin.py`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`, `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Test: existing `tests/ui/test_pg_line_canvas.py`, `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: Diff the two handler blocks to confirm they are identical modulo plot attribute names**

Run: `diff <(sed -n '792,861p' mf4_analyzer/ui/pg_canvas/line_canvas.py) <(sed -n '1458,1536p' mf4_analyzer/ui/pg_canvas/heatmap_canvas.py)`
The only differences should be `_plot_amp/_plot_time` (line) vs `_plot/_slice_plot` (heatmap) and the on-expand self-align hook.

- [ ] **Step 2: Define the mixin parameterized on the two plot attrs + an align hook**

```python
# mf4_analyzer/ui/pg_canvas/_split_mixin.py
class _StackedSplitMixin:
    """Drag/collapse/reset/expand handlers for a two-row stacked split.

    Subclasses must define ``_split_top_plot()`` and ``_split_bottom_plot()``
    returning the two PlotItems, and may override ``_on_split_expanded()`` for
    a post-expand self-align hook (default: no-op).
    """
    def _split_top_plot(self): raise NotImplementedError
    def _split_bottom_plot(self): raise NotImplementedError
    def _on_split_expanded(self): pass
    # ... move the shared _set_bottom_collapsed / _on_collapse_changed /
    #     _position_collapse_ctrl / _on_split_drag_started/_delta/_finished /
    #     _on_split_reset / _available_split_height here, replacing direct
    #     self._plot_amp/self._plot_time refs with self._split_top_plot()/
    #     self._split_bottom_plot().
```

- [ ] **Step 3: Make both canvases inherit the mixin and implement the two hooks**; delete the duplicated handler bodies from each canvas.

- [ ] **Step 4: Run both canvas test files**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py -q`
Expected: PASS unchanged

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/_split_mixin.py mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
git commit -m "refactor(pg_canvas): extract _StackedSplitMixin, dedup split/collapse handlers (~70 lines)"
```

### Task D2: Single `show_major_grid_left_bottom_only` helper

The "after `showGrid`, re-`setGrid(False)` on top/right" workaround now exists in 4 places (`heatmap_canvas.py:613-617`, `line_canvas.py:156-157`, `canvas.py` axis loop, and today's `context_menu.py:283-296`). Collapse into one un-bypassable helper. (Owner: `refactor-architect`.)

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/_shared.py` (add helper)
- Modify: the 4 call sites above
- Test: existing grid-policy tests (`test_pg_timedomain_canvas.py::test_grid_submenu_toggle_keeps_top_right_grid_disabled` etc.)

- [ ] **Step 1: Add the helper to `_shared.py`**

```python
def show_major_grid_left_bottom_only(plot, alpha):
    """Enable the major (left+bottom) grid and force top/right OFF.

    pyqtgraph's ``showGrid`` lights all four axes; we only ever want the
    left+bottom graticule. Centralized so no call site can forget the
    top/right suppression. See context_menu/line_canvas/heatmap_canvas history.
    """
    plot.showGrid(x=True, y=True, alpha=alpha)
    for name in ("top", "right"):
        try:
            plot.getAxis(name).setGrid(False)
        except Exception:
            pass
```

- [ ] **Step 2: Replace each of the 4 sites** with `show_major_grid_left_bottom_only(plot, alpha)`.

- [ ] **Step 3: Run the grid tests + full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: PASS unchanged

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/_shared.py mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/context_menu.py
git commit -m "refactor(pg_canvas): single show_major_grid_left_bottom_only helper (was 4 copies)"
```

### Task D3: Remove confirmed dead code

All verified by the review as unreachable / orphaned. No behavior change.

**Files & removals:**
- `line_canvas.py:820-821` — delete the `_position_split_divider` alias (identical to `_position_collapse_ctrl`); replace its callers (`resizeEvent`/`showEvent`/`_on_split_drag_delta`/`_on_split_reset`, ~lines 838-861) with a single `_position_collapse_ctrl()` call each (drop the redundant second call — `_position_collapse_layout` already positions rail + divider together).
- `heatmap_canvas.py:265-269` — delete the `state == 'top'` branch of `_apply_plot_collapse` (no caller passes `'top'`; both consumers pass only `'bottom'`/`'none'`).
- `heatmap_canvas.py:310-311` — drop the dead `collapsed` parameter of `_split_boundary_y` (its only caller hardcodes `collapsed=False`).
- `ui_kit/style.qss:1149-1182` — delete the orphaned `QLabel#slicePanelTitle` rules (widget removed in `0f7338e`) and dedup the doubled `slice-seg`/`slicePanelTitle` blocks.

- [ ] **Step 1:** Apply each removal above, one file at a time.
- [ ] **Step 2: Confirm no remaining references**

Run: `grep -rn "_position_split_divider\|slicePanelTitle\|state == 'top'\|state==\"top\"" mf4_analyzer/`
Expected: no hits (except the now-single definition sites you kept)

- [ ] **Step 3: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: PASS unchanged

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui_kit/style.qss
git commit -m "chore(pg_canvas): remove dead split-divider alias, unreachable collapse branches, orphaned QSS"
```

### Task D4: Remove inert defensive guards

`inspector_sections.py:1548-1557` wraps `setStyleSheet` in `try/except: pass` — Qt silently ignores bad QSS, so this catches nothing. `setMaximumWidth(_SHORT_FIELD_MAX_WIDTH=260)` on the 2-char "最大" button (line 1547) is cargo-culted from the spinbox sizing and is effectively inert.

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py:1547-1557`
- Test: existing inspector tests

- [ ] **Step 1: Unwrap `setStyleSheet`** (remove the `try/except` + `pragma: no cover`), call it directly. **Remove** the `setMaximumWidth(_SHORT_FIELD_MAX_WIDTH)` line (or replace 260 with a width actually sized to the button if a cap is genuinely wanted — confirm visually).
- [ ] **Step 2: Run the inspector tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_inspector.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py
git commit -m "chore(inspector): drop inert setStyleSheet try/except and cargo-culted max-width on 最大 button"
```

### Task D5: Source the Max-button span from the data model, not spinbox limits

`main_window.py:1801-1803` reads the full span from `spin_start.minimum()`/`spin_end.maximum()`, coupling the Max button to the spinbox limits staying current. Read the data extent `[t0, t_end]` directly from the same source `set_range_limits` is fed from, so a future spinbox-limit drift can't make Max fill the wrong span.

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (`_on_time_range_max_requested`, ~lines 1801-1805)
- Test: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Find the data-extent source**

Run: `grep -n "set_range_limits\|_data_extent\|t_end\|full.*span\|extent" mf4_analyzer/ui/main_window.py | head`
Identify the authoritative `[t0, t_end]` the limits are derived from.

- [ ] **Step 2: Write/extend a test** that sets the data extent and a *stale/narrower* spinbox limit, then asserts Max fills the data extent (not the spinbox limit).

- [ ] **Step 3: Run it to confirm it fails**, then rewrite `_on_time_range_max_requested` to read the data extent directly (keep the `not (hi > lo)` no-op guard for empty/degenerate spans).

- [ ] **Step 4: Run the smoke tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_main_window_smoke.py
git commit -m "fix(analysis): Max button reads data extent directly, not spinbox limits"
```

### Task D6: Make the Max-button "end-to-end" test exercise the real slot

`test_inspector.py::test_max_range_button_fills_full_extent_and_enables` re-implements `MainWindow._on_time_range_max_requested` as a local `_apply_max` copy, so handler drift goes uncaught. Point it at the real slot (or delete it as redundant, since `test_main_window_smoke.py` already covers the real path after D5).

**Files:**
- Modify: `tests/ui/test_inspector.py` (the `_apply_max` test)

- [ ] **Step 1:** Replace the local `_apply_max` re-implementation with a call to the real `MainWindow._on_time_range_max_requested` against a real (offscreen) `MainWindow`, OR delete the test if D5's smoke coverage subsumes it. Keep the low-value existence/wiring trivia tests only if they assert something the smoke test doesn't.
- [ ] **Step 2: Run the inspector tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_inspector.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_inspector.py
git commit -m "test(inspector): Max-button test drives the real slot, not a re-implemented copy"
```

---

## Self-Review checklist (run before execution)

- **Coverage vs review:** every review finding maps to a task — A1/A2 (the two reds), B1 (fft NaN), B2 (chart_stack dead-card), B3 (heatmap right frame), B4 (replot swallow), C1 (fft over-claim + silent clamp), C2 (inspector dead param), D1 (mixin dedup), D2 (grid helper), D3 (dead code: split alias / collapse branches / QSS), D4 (inert guards), D5 (Max span source), D6 (re-implemented test). ✅
- **Suggestions intentionally NOT tasked** (out of scope / pre-existing, not today's regressions): broad `except Exception` defensive idiom across pg_canvas (documented C3 teardown pattern — leave as-is except B2/B4 which are concrete), `_split_title_width` write-only state (pre-existing at baseline), `globalPos()` PyQt6-deprecation (no port planned), font point-size drift in `fonts.py` (acceptable per docstring), magic-number co-location for `_SPLIT_COLLAPSE_AT`/`_SPLIT_MIN_BOTTOM` (cosmetic — fold into D3 if touching the file).
- **No placeholders:** every behavioral task has a concrete failing test + exact code; cleanup tasks are verified by the green suite.
- **Sequencing:** A → B → C → D. A first (unblock CI). D1/D2/D3 touch the same canvas files — run them sequentially, not in parallel, to avoid merge churn. D5 precedes D6 (D6 depends on D5's real-path coverage).

---

## Execution Handoff

Three ways to run this:

1. **Squad (repo convention)** — dispatch per-task to `signal-processing-expert` (B1, C1) / `pyqt-ui-engineer` (A, B2, B4, C2, D3–D6) / `refactor-architect` (D1, D2). Use this if you want the `.state.yml`/lessons bookkeeping. Note: B1/C1 both edit `signal/fft.py`, and D1/D3 both edit the canvas files — sequence those to avoid same-file rework.
2. **Subagent-Driven** — fresh subagent per task, review between tasks (superpowers:subagent-driven-development).
3. **Inline** — execute here with checkpoints (superpowers:executing-plans).

Suggested minimum: do **Tier A now** (suite is red); Tiers B/C next; Tier D opportunistically.
