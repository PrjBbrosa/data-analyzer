# Axis Settings + COT Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the legacy frequency-domain order-tracking algorithm (inspector + batch both move to COT-only), and replace `combo_dynamic` + `combo_amp_mode` with a unified "坐标轴设置" group (Y axis range + Z dB-scale floor/ceiling + amplitude unit dropdown) in OrderContextual and FFTTimeContextual.

**Architecture:** Two coordinated migrations sharing a final canvases-API change.
1. **Algorithm consolidation**: drop the `'frequency'` branch in `MainWindow.do_order_time` and the `OrderAnalyzer.compute_time_order_result` call in `BatchRunner._compute_order_time_dataframe`; both now route through `COTOrderAnalyzer.compute`. The user-visible `combo_algorithm` picker disappears; `OrderAnalyzer.compute_time_order_result` becomes dead code in production paths (kept as internal API for one release, deprecation comment).
2. **Axis controls**: Inspector grows a `QGroupBox("坐标轴设置")` with inline rows `[label][chk_auto][spin_min][→][spin_max][unit]`. The Z-row's `unit` is a `QComboBox(["dB","Linear"])` that replaces the old `combo_amp_mode`. `combo_dynamic` is deleted. Canvases (`_color_limits`, `plot_or_update_heatmap`) take `(z_auto, z_floor, z_ceiling, amplitude_mode)` instead of `dynamic: str`.

**Tech Stack:** PyQt5 5.15.11, qtawesome 1.4.2, numpy, pandas, pytest + pytest-qt, COT pipeline already in `mf4_analyzer/signal/order_cot.py`.

**Plan revision history:**
- **2026-04-28 v1**: initial draft after playground selection.
- **2026-04-28 v2**: applied audit fixes from `superpowers:code-reviewer` agent run on v1. Critical fixes C1-C8 + W1, W3, W6, S9. Search "Audit fix" callouts.
- **2026-04-28 v3 (this version)**: addressed v2 re-review findings — three lingering `FFTContextual` references at Goal/File-Structure/Wave-4-prose corrected to `FFTTimeContextual`; Step 5.5 caller #2 (line 1793) gets full before/after code (NEW-3); Step 5.3 `plot_result` signature spelled out concretely with `freq_range` precedence note (NEW-4); Wave 2.4 "delete the `else:` branch" reworded to "delete the post-return fallthrough block at lines 1351-1361" (NEW-2); Wave 4 step 4.3 notes `_BUILTIN_PRESETS` and `_builtin_preset_full_params` legacy keys are read-migrated by Wave 6 (NEW-1); Rollback Strategy gains inter-wave coupling caveats (W5); Wave 4 helper-extraction reconciled with Wave 3.3 inline construction (S7).

---

## Background / Context

### Selected designs (from prior playgrounds)

- **Spinbox/combo arrows** — already implemented as scheme B (`qtawesome → QPixmap → QSS image`) using `mdi6.menu-up/down`. See `docs/plans/2026-04-28-spinbox-arrow-options.html`. New axis-settings rows reuse the existing 22px gutter + compact triangle styling; **no new icon work**.
- **Axis settings layout** — selected scheme B' (Inline 紧凑, 一行一轴) from `docs/plans/2026-04-28-axis-settings-options.html`. Refined in chat:
  - **Order view**: 3 rows = `时间(X) [s]`, `阶次(Y) [no unit]`, `色阶 [dB ▼]`
  - **FFT-vs-Time**: 3 rows = `时间(X) [s]`, `频率(Y) [Hz]`, `色阶 [dB ▼]`
  - **FFT 1D**: 2 rows = `频率(X) [Hz]`, `幅值(Y) [dB ▼]` (unit dropdown moves to Y because there is no Z)
- **dB↔Linear toggle**: when the user switches the Z-row (or Y-row in FFT 1D) unit dropdown, `z_auto` (or `y_auto`) is **forced to True**. The user must explicitly uncheck auto and re-enter floor/ceiling for the new unit. Avoids ambiguous unit-conversion semantics.
- **Old presets compatibility**: `_apply_preset()` accepts legacy `dynamic="30 dB"` etc. and translates to `z_auto=False, z_floor=-30, z_ceiling=0`. `dynamic="Auto"` → `z_auto=True`. Legacy `algorithm="frequency"` is **silently ignored** at preset load.

### Applicable lessons

- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md` — strict-subset invariant between `SUPPORTED_*` gates and live dispatchers. **Applies here**: removing the `'frequency'` algorithm branch in `MainWindow.do_order_time` must coincide with deleting the `algorithm` key from `OrderContextual.current_params()` output (no ghost values left in `order_params`).
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md` — return-type/contract changes must bundle call-site updates. **Applies here**: `_color_limits` and `plot_or_update_heatmap` change kwargs from `dynamic: str` to `(z_auto, z_floor, z_ceiling, amplitude_mode)`. Every call site in `main_window.py` must be updated in lock-step (the brief enumerates each line).
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md` — when a checkbox toggles paired field visibility/enable, seed the initial state once at `__init__` end. **Applies here**: `chk_y_auto` toggles `spin_y_min/max` enabled state; must call `_sync_axis_enabled()` once at the end of widget construction.
- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md` — QSS padding can override Python `setContentsMargins`. **Applies here**: the new inline axis row uses a tight `QHBoxLayout`; verify in offscreen render that the row total width does not exceed the inspector's `_LONG_FIELD_MAX_WIDTH`.

---

## Architecture / Data Flow

### Current state (before this plan)

```
┌─────────────────────────────┐
│ OrderContextual             │
│  combo_algorithm: 频域映射|COT─────┐
│  combo_amp_mode: dB|Linear  │      │
│  combo_dynamic: 30|50|80|Auto      │
│  spin_mo: max_order (calc)  │      │
└────────────┬────────────────┘      │
             ↓ get_params/current_params
        params dict:                  │
        { algorithm, amplitude_mode,  │
          dynamic, max_order, ... }   │
             │                        │
             ↓                        │
┌─────────────────────────────┐       │
│ MainWindow.do_order_time    │       │
│  if algorithm=='cot': COT   │←──────┤
│  else: OrderAnalyzer.       │       │
│        compute_time_order_…│←──────┘
└────────────┬────────────────┘
             ↓ result + dynamic str
┌─────────────────────────────┐
│ canvases.plot_or_update_    │
│ heatmap(dynamic='30 dB',    │
│         amplitude_mode=…)   │
│   if dynamic=='30 dB':      │
│     clip(-30, 0)            │
│   elif '50 dB': clip(-50,0) │
│   …                         │
└─────────────────────────────┘
                    ▲
┌───────────────────┴─────────┐
│ BatchRunner.                │
│ _compute_order_time_         │
│ dataframe()                 │
│   OrderAnalyzer.compute_     │← duplicate frequency-domain path
│   time_order_result(...)    │
└─────────────────────────────┘
```

### Target state (after this plan)

```
┌─────────────────────────────┐
│ OrderContextual             │
│  spin_mo: max_order (calc)  │  ← unchanged
│  spin_samples_per_rev (COT) │  ← always enabled now
│  ┌─ 坐标轴设置 ─────────┐   │
│  │ 时间(X): chk + 2 spin │   │
│  │ 阶次(Y): chk + 2 spin │   │  ← spin_y_max ≤ spin_mo
│  │ 色阶: chk + 2 spin + │   │
│  │       [dB|Linear]▼   │   │  ← replaces combo_amp_mode
│  └──────────────────────┘   │
└────────────┬────────────────┘
             ↓ current_params
        params dict:
        { x_auto, x_min, x_max,
          y_auto, y_min, y_max,
          z_auto, z_floor, z_ceiling,
          amplitude_mode,
          max_order, samples_per_rev, ... }
        # NO algorithm, NO dynamic
             │
             ↓
┌─────────────────────────────┐
│ MainWindow.do_order_time    │
│  COTOrderAnalyzer.compute   │  ← always
│  (no branching)             │
└────────────┬────────────────┘
             ↓ result + axis dict
┌─────────────────────────────┐
│ canvases.plot_or_update_    │
│ heatmap(z_auto, z_floor,    │
│         z_ceiling, amp_mode)│
│   if z_auto:                │
│     vmin,vmax = nanmin/max  │
│   else: vmin,vmax = floor/  │
│                    ceiling  │
│   if not y_auto:            │
│     ax.set_ylim(y_min,y_max)│
│   if not x_auto:            │
│     ax.set_xlim(x_min,x_max)│
└─────────────────────────────┘
                    ▲
┌───────────────────┴─────────┐
│ BatchRunner.                │
│ _compute_order_time_        │
│ dataframe()                 │
│   COTOrderAnalyzer.compute  │  ← changed
│   (samples_per_rev default  │
│    256 if missing)          │
└─────────────────────────────┘

┌─────────────────────────────┐
│ batch_preset_io.            │
│ load_preset_from_json:      │
│  - drop algorithm key silently
│  - 'dynamic'='30 dB' →      │
│    z_floor=-30, z_ceiling=0,│
│    z_auto=False             │
│  - 'dynamic'='Auto' →       │
│    z_auto=True              │
│  - 'amplitude_mode' kept    │
└─────────────────────────────┘
```

### Field migration matrix

| Old field (in params dict) | New field(s) | Notes |
|---|---|---|
| `algorithm` | (removed) | Always COT now |
| `dynamic: str` ("30 dB" \| "Auto" \| ...) | `z_auto: bool, z_floor: float, z_ceiling: float` | Compat: legacy values translated at preset load |
| `amplitude_mode: str` ("Amplitude dB" \| "Amplitude") | unchanged but UI source moves | combo dropped, value comes from new `combo_amp_unit` (Z row or Y row depending on view) |
| (none) | `x_auto, x_min, x_max, y_auto, y_min, y_max` | New axis range controls |
| `max_order` | unchanged (`spin_mo`) | Calc parameter, not display |
| `samples_per_rev` | unchanged (`spin_samples_per_rev`) | Always enabled now |

---

## File Structure

| File | Status | Responsibility after plan |
|---|---|---|
| `mf4_analyzer/ui/inspector_sections.py` | **modified** | OrderContextual + FFTTimeContextual contain new "坐标轴设置" group; `combo_algorithm`, `combo_amp_mode`, `combo_dynamic` removed. (FFTContextual, the 1D spectrum class at line 831, is OUT OF SCOPE.) |
| `mf4_analyzer/ui/main_window.py` | **modified** | `do_order_time` always uses COT; `plot_or_update_heatmap` calls use new kwargs |
| `mf4_analyzer/ui/canvases.py` | **modified** | `_color_limits` + `plot_or_update_heatmap` accept `(z_auto, z_floor, z_ceiling, amplitude_mode)`; honor `(x_auto/min/max, y_auto/min/max)` for `set_xlim/set_ylim` |
| `mf4_analyzer/batch.py` | **modified** | `_compute_order_time_dataframe` calls `COTOrderAnalyzer.compute` |
| `mf4_analyzer/batch_preset_io.py` | **modified** | `load_preset_from_json` migrates legacy `algorithm` / `dynamic` keys |
| `mf4_analyzer/signal/order.py` | **untouched core**, comment-only | `OrderAnalyzer.compute_time_order_result` gets `# DEPRECATED` doc note (kept for one release; no removal in this plan) |
| `tests/ui/test_inspector.py` | **modified** | New axis-controls assertions; old `combo_algorithm`/`combo_amp_mode`/`combo_dynamic` tests deleted |
| `tests/test_batch_runner.py` | **modified** | `_compute_order_time_dataframe` test asserts COT path; legacy-preset migration test added |
| `tests/ui/test_canvases.py` | **modified (if exists)** | Updated `_color_limits` / `plot_or_update_heatmap` signature tests |
| `tests/signal/test_order_cot.py` | **referenced**, no change | Existing tests pin COT correctness |
| `docs/superpowers/plans/2026-04-28-axis-settings-and-cot-migration.md` | **this file** | Implementation plan |

---

## Implementation Phases

Six waves, sequenced so each wave's tests pass independently and the working tree never enters a broken state for >1 task. **TDD throughout:** write the failing test first, run it red, implement minimal code, run it green, commit.

### Wave A — Pre-flight

- [ ] **A.1: Verify clean baseline**

  Run:
  ```
  git status
  ```
  Expected: working tree clean (or only untracked files irrelevant to this plan).

  ```
  .venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest-tmp -p no:cacheprovider 2>&1 | tail -3
  ```
  Expected: `403 passed, 1 failed, 1 skipped` (the failing `test_orders_with_subbin_floor_drops_low_orders` is pre-existing float-precision noise, **not** introduced by this plan; record exact count).

- [ ] **A.2: Snapshot baseline metrics**

  Capture in scratch notes:
  - Current pre-existing failures: `tests/signal/test_order.py::test_orders_with_subbin_floor_drops_low_orders` (float precision).
  - Current `tests/` count.
  - Current `grep -c "frequency" mf4_analyzer/ui/main_window.py`.

  These become diff-target baselines for review.

---

### Wave 1 — Batch: switch `_compute_order_time_dataframe` to COT

**Files:**
- Modify: `mf4_analyzer/batch.py:477-491`
- Test: `tests/test_batch_runner.py`

**Why first:** `OrderAnalyzer.compute_time_order_result` will be removed from production paths in Wave 2 (inspector). If batch still calls it, removing the inspector branch breaks batch. Switch batch first so it doesn't depend on the legacy path.

- [ ] **1.1: Write failing test for COT-routed batch order_time**

  Add to `tests/test_batch_runner.py`:

  ```python
  def test_compute_order_time_dataframe_uses_cot(monkeypatch):
      """_compute_order_time_dataframe must route through COTOrderAnalyzer.compute,
      not OrderAnalyzer.compute_time_order_result.

      Spy both call sites; only the COT spy may be invoked.
      """
      from mf4_analyzer import batch as batch_mod
      from mf4_analyzer.signal import order as order_mod
      from mf4_analyzer.signal import order_cot as cot_mod

      cot_calls = []
      legacy_calls = []

      real_cot = cot_mod.COTOrderAnalyzer.compute
      real_legacy = order_mod.OrderAnalyzer.compute_time_order_result

      def spy_cot(sig, rpm, t, params, **kw):
          cot_calls.append(('cot', len(sig)))
          return real_cot(sig, rpm, t, params, **kw)

      def spy_legacy(*a, **kw):
          legacy_calls.append(('legacy',))
          return real_legacy(*a, **kw)

      monkeypatch.setattr(cot_mod.COTOrderAnalyzer, 'compute', staticmethod(spy_cot))
      monkeypatch.setattr(order_mod.OrderAnalyzer, 'compute_time_order_result',
                          staticmethod(spy_legacy))

      # Synthetic 4 s signal at 1 kHz with constant 1200 RPM, second-order tone
      import numpy as np
      fs = 1000.0
      t = np.arange(0.0, 4.0, 1.0 / fs)
      rpm_const = 1200.0
      target_order = 2.0
      f = target_order * rpm_const / 60.0
      sig = np.sin(2 * np.pi * f * t)
      rpm = np.full_like(t, rpm_const)

      params = {
          'fs': fs, 'nfft': 1024, 'window': 'hanning',
          'max_order': 5.0, 'order_res': 0.1, 'time_res': 0.05,
          # samples_per_rev not specified → default 256
      }

      df = batch_mod.BatchRunner._compute_order_time_dataframe(
          sig, rpm, t, fs, params)

      assert cot_calls, 'COT path must be invoked'
      assert not legacy_calls, 'Legacy frequency-domain path must NOT be invoked'
      assert {'time_s', 'order', 'amplitude'} <= set(df.columns)
  ```

- [ ] **1.2: Run test red**

  Run: `.venv/Scripts/python.exe -m pytest tests/test_batch_runner.py::test_compute_order_time_dataframe_uses_cot -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: FAIL — assertion `cot_calls` empty (currently routes through `OrderAnalyzer`).

- [ ] **1.3: Replace batch implementation**

  In `mf4_analyzer/batch.py:477-491`, replace `_compute_order_time_dataframe`:

  ```python
  @classmethod
  def _compute_order_time_dataframe(cls, sig, rpm, time, fs, params):
      """Compute time-order spectrogram via Computed Order Tracking.

      As of 2026-04-28 the legacy frequency-domain path
      (OrderAnalyzer.compute_time_order_result) is no longer invoked here;
      COT handles all RPM regimes (sweep, coast-down, steady-state) without
      smearing. ``samples_per_rev`` defaults to 256 when absent from
      preset params; the COT pipeline requires ``time`` to be strictly
      monotonically increasing.
      """
      import numpy as np
      from .signal.order_cot import COTOrderAnalyzer, COTParams

      # Defensive: COT requires strictly monotonic t. Even microsecond
      # jitter in MF4 timestamps would raise ValueError. If not strict,
      # rebuild a uniform fallback from len + fs.
      time_arr = np.asarray(time, dtype=float)
      if len(time_arr) < 2 or np.any(np.diff(time_arr) <= 0):
          time_arr = np.arange(len(time_arr), dtype=float) / float(fs)

      cot_params = COTParams(
          samples_per_rev=int(params.get('samples_per_rev', 256)),
          nfft=int(params.get('nfft', 1024)),
          window=str(params.get('window', 'hanning')),
          max_order=float(params.get('max_order', params.get('max_ord', 20))),
          order_res=float(params.get('order_res', 0.1)),
          time_res=float(params.get('time_res', 0.05)),
          fs=float(fs),
      )
      result = COTOrderAnalyzer.compute(sig, rpm, time_arr, cot_params)
      return _matrix_to_long_dataframe(
          result.times,
          result.orders,
          result.amplitude,
          x_name='time_s',
          y_name='order',
      )
  ```

  Note: `_order_params` (lines 466-475) was used by the old frequency-domain path. **Verify** it has no remaining callers via `grep -n "_order_params\b" mf4_analyzer/`. If zero hits, delete the method AND the now-unused `from .signal.order import OrderAnalyzer, OrderAnalysisParams` import at `batch.py:23`. (W1 — keeps the diff lint-clean; tests in `tests/test_order_analysis.py` and `tests/ui/test_order_worker.py` still construct `OrderAnalysisParams` directly so the class itself remains importable.)

- [ ] **1.4: Run test green**

  Run: `.venv/Scripts/python.exe -m pytest tests/test_batch_runner.py::test_compute_order_time_dataframe_uses_cot -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: PASS.

- [ ] **1.5: Run full batch test suite to catch regressions**

  Run: `.venv/Scripts/python.exe -m pytest tests/test_batch_runner.py -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: all green. The existing `test_batch_order_time_csv_shape` should still pass with COT (orders/times grid roughly equivalent to the old frequency-domain output). If shape assertions fail with non-trivial differences, investigate whether COT default `samples_per_rev=256` produces a slightly different output grid; if so, update the shape constants in that test.

- [ ] **1.6: Commit**

  ```
  git add tests/test_batch_runner.py mf4_analyzer/batch.py
  git commit -m "feat(batch): route _compute_order_time_dataframe through COTOrderAnalyzer

  Drops the legacy frequency-domain order-tracking path (OrderAnalyzer.
  compute_time_order_result) from batch; COT handles steady, sweep, and
  coast-down regimes uniformly. samples_per_rev defaults to 256 when the
  preset omits it. Strictly-monotonic time vector is enforced with a
  uniform fs-derived fallback for jittered MF4 timestamps."
  ```

---

### Wave 2 — Inspector: remove `combo_algorithm`

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py:1222-1260, 1394-1399, 1430-1447`
- Modify: `mf4_analyzer/ui/main_window.py:1326-1330`
- Test: `tests/ui/test_inspector.py`

- [ ] **2.1: Write failing test asserting algorithm picker is gone**

  Add to `tests/ui/test_inspector.py`:

  ```python
  def test_order_contextual_has_no_algorithm_picker(qtbot):
      """combo_algorithm and on_algo_changed are removed; spin_samples_per_rev
      is always enabled (no longer gated by algorithm choice)."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      assert not hasattr(oc, 'combo_algorithm')
      assert oc.spin_samples_per_rev.isEnabled()

  def test_order_contextual_current_params_omits_algorithm(qtbot):
      """current_params must not emit 'algorithm' key (downstream MainWindow
      no longer branches on it)."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      p = oc.current_params()
      assert 'algorithm' not in p
      assert 'samples_per_rev' in p
  ```

- [ ] **2.2: Run tests red**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_inspector.py::test_order_contextual_has_no_algorithm_picker tests/ui/test_inspector.py::test_order_contextual_current_params_omits_algorithm -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: FAIL on `combo_algorithm` still existing.

- [ ] **2.3: Delete combo_algorithm block**

  In `mf4_analyzer/ui/inspector_sections.py`, delete entirely:
  - **Lines 1222-1260** (the `combo_algorithm` block including `_on_algo_changed` and the `currentTextChanged.connect`). The trailing `_on_algo_changed(self.combo_algorithm.currentText())` line is also gone.
  - **In `current_params()` (lines 1394-1399)**: remove the three lines
    ```python
    algo_txt = self.combo_algorithm.currentText()
    p['algorithm'] = 'cot' if 'COT' in algo_txt else 'frequency'
    p['samples_per_rev'] = int(self.spin_samples_per_rev.value())
    ```
    and replace with just:
    ```python
    p['samples_per_rev'] = int(self.spin_samples_per_rev.value())
    ```
  - **In `apply_params` (lines 1430-1442)**: remove the `if 'algorithm' in d:` block entirely. Keep the `if 'samples_per_rev' in d:` block.

- [ ] **2.4: Update MainWindow dispatch**

  In `mf4_analyzer/ui/main_window.py:1326-1330`, replace:
  ```python
  algorithm = order_params.get('algorithm', 'frequency')
  op = self.inspector.order_ctx.get_params()
  if algorithm == 'cot':
      from ..signal.order_cot import COTOrderAnalyzer, COTParams
      try:
          ...
  ```
  with the unconditional COT branch:
  ```python
  op = self.inspector.order_ctx.get_params()
  from ..signal.order_cot import COTOrderAnalyzer, COTParams
  try:
      ...
  ```
  > **Audit fix (NEW-2)**: the actual code at `main_window.py:1326-1361` does NOT have an `else:` block — the COT branch ends with `return` at line 1349, and lines 1351-1361 are the post-return fallthrough block holding the legacy `OrderAnalyzer.compute_time_order_result` dispatch. Delete the post-return fallthrough block (lines 1351-1361 of the pre-edit file). After deletion, verify `do_order_time` ends after the COT call's `return`, with no further dispatch.

- [ ] **2.4b: Add monotonic-time fallback to MainWindow.do_order_time**

  > **Audit fix (R6 / C7)**: COTOrderAnalyzer.compute requires strictly monotonic `t`. After Wave 2 collapses the algorithm branching, real MF4 column timestamps (which can carry microsecond jitter) will hit `np.diff(t) <= 0` and raise ValueError on the GUI thread. Add the same fallback the batch added in Step 1.3.

  In `mf4_analyzer/ui/main_window.py:1306-1349` `do_order_time`, locate the line where `t, sig, fs = self._get_sig()` is read (around line 1307). Just before the `COTOrderAnalyzer.compute(sig, rpm, t, p)` call (around line 1342, after Wave 2's collapse), insert:

  ```python
  import numpy as np
  t_arr = np.asarray(t, dtype=float)
  if len(t_arr) < 2 or np.any(np.diff(t_arr) <= 0):
      t_arr = np.arange(len(t_arr), dtype=float) / float(fs)
  ```

  Pass `t_arr` (not `t`) to `COTOrderAnalyzer.compute`. Note: `np` may already be imported; verify and reuse. The same fallback exists in batch.py (Step 1.3) — safe to extract into a helper later, but for now duplicate (DRY violation acceptable; ~3 lines).

- [ ] **2.5: Run tests green**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_inspector.py -v --basetemp=.pytest-tmp -p no:cacheprovider -k "algorithm or order_contextual"`

  Expected: PASS (the two new tests). Other inspector tests should still pass.

- [ ] **2.6: Verify no stale `combo_algorithm` references remain**

  Run: `grep -rn "combo_algorithm\|频域映射\|_on_algo_changed" mf4_analyzer/ tests/`

  Expected: zero hits in `mf4_analyzer/`. Tests may have a few in deleted-test stubs — verify those are also pruned. Docs / lessons / plans may keep historical references — leave those.

- [ ] **2.7: Commit**

  ```
  git add mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/main_window.py tests/ui/test_inspector.py
  git commit -m "feat(inspector): drop frequency-domain algorithm picker; COT-only

  combo_algorithm and the algorithm-branch in MainWindow.do_order_time are
  removed. spin_samples_per_rev is always enabled. current_params no longer
  emits the 'algorithm' key. apply_params no longer accepts it (legacy
  presets containing 'algorithm' are silently ignored — covered by Wave 6
  preset-IO migration test)."
  ```

---

### Wave 3 — Inspector OrderContextual: new "坐标轴设置" group

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py` (OrderContextual class, around lines 1197-1260 + 1380-1450)
- Test: `tests/ui/test_inspector.py`

This wave installs the user-visible group but does NOT yet wire it into the canvas render. Wave 5 covers that. The widget exposes its values via `current_params()`; downstream code can keep reading legacy keys from `current_params()` for now (Wave 5 deletes them).

- [ ] **3.1: Write failing tests for new axis-settings widget**

  Add to `tests/ui/test_inspector.py`:

  ```python
  def test_order_contextual_has_axis_settings_group(qtbot):
      """OrderContextual must contain a QGroupBox titled '坐标轴设置' with
      9 controls: chk_x_auto + spin_x_min + spin_x_max + chk_y_auto +
      spin_y_min + spin_y_max + chk_z_auto + spin_z_floor + spin_z_ceiling
      + combo_amp_unit (the dB/Linear dropdown on the Z row)."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      for name in (
          'chk_x_auto', 'spin_x_min', 'spin_x_max',
          'chk_y_auto', 'spin_y_min', 'spin_y_max',
          'chk_z_auto', 'spin_z_floor', 'spin_z_ceiling',
          'combo_amp_unit',
      ):
          assert hasattr(oc, name), f'missing {name}'

      # Defaults: x/y auto on, z auto off (mirrors old default 30 dB)
      assert oc.chk_x_auto.isChecked()
      assert oc.chk_y_auto.isChecked()
      assert not oc.chk_z_auto.isChecked()
      assert oc.spin_z_floor.value() == -30.0
      assert oc.spin_z_ceiling.value() == 0.0
      assert oc.combo_amp_unit.currentText() == 'dB'

  def test_order_contextual_combo_amp_mode_and_dynamic_removed(qtbot):
      """combo_amp_mode and combo_dynamic widgets are gone (their values
      are now expressed via combo_amp_unit + spin_z_floor/ceiling)."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      assert not hasattr(oc, 'combo_amp_mode')
      assert not hasattr(oc, 'combo_dynamic')

  def test_order_contextual_y_max_clamped_by_max_order(qtbot):
      """When the user changes spin_mo (max_order, calc param), spin_y_max
      upper bound must follow so display range cannot exceed the calc range."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      oc.spin_mo.setValue(15)
      assert oc.spin_y_max.maximum() == 15.0
      # If user had y_max > 15, it should snap down
      oc.spin_y_max.setValue(20)
      assert oc.spin_y_max.value() <= 15.0

  def test_order_contextual_unit_toggle_forces_z_auto(qtbot):
      """Switching combo_amp_unit dB↔Linear forces chk_z_auto on (per
      the 2026-04-28 plan: avoids ambiguous unit-conversion semantics)."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      # Default: z_auto off, dB unit
      oc.chk_z_auto.setChecked(False)
      assert not oc.chk_z_auto.isChecked()
      oc.combo_amp_unit.setCurrentText('Linear')
      assert oc.chk_z_auto.isChecked()

  def test_order_contextual_current_params_emits_axis_keys(qtbot):
      """current_params must emit the new axis keys."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      p = oc.current_params()
      for key in ('x_auto', 'x_min', 'x_max',
                  'y_auto', 'y_min', 'y_max',
                  'z_auto', 'z_floor', 'z_ceiling',
                  'amplitude_mode'):
          assert key in p, f'missing {key} in current_params'
      assert isinstance(p['z_auto'], bool)
      assert p['amplitude_mode'] in ('Amplitude dB', 'Amplitude')

  def test_order_contextual_apply_preset_legacy_dynamic(qtbot):
      """_apply_preset must translate legacy 'dynamic' string to new
      z_auto/z_floor/z_ceiling state."""
      from mf4_analyzer.ui.inspector_sections import OrderContextual
      oc = OrderContextual()
      qtbot.addWidget(oc)

      # Legacy preset shape
      oc._apply_preset({'amplitude_mode': 'Amplitude dB', 'dynamic': '50 dB'})
      assert not oc.chk_z_auto.isChecked()
      assert oc.spin_z_floor.value() == -50.0
      assert oc.spin_z_ceiling.value() == 0.0

      oc._apply_preset({'amplitude_mode': 'Amplitude dB', 'dynamic': 'Auto'})
      assert oc.chk_z_auto.isChecked()
  ```

- [ ] **3.2: Run tests red**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_inspector.py -v --basetemp=.pytest-tmp -p no:cacheprovider -k "axis_settings or amp_mode_and_dynamic or y_max_clamped or unit_toggle or current_params_emits or apply_preset_legacy_dynamic"`

  Expected: FAIL on missing widgets.

- [ ] **3.3: Build the axis-settings group**

  Goal: replace the existing `combo_amp_mode` + `combo_dynamic` rows in the "谱参数" group (lines 1197-1220) with a new `QGroupBox("坐标轴设置")` placed **after** the spectrum-params group, before any preset/preview UI.

  In `mf4_analyzer/ui/inspector_sections.py` OrderContextual, locate the block ending at the `combo_dynamic.setEnabled` line (around line 1220). **Remove** lines 1197-1260 (the entire display block: combo_amp_mode + combo_dynamic + their addRows + the disable-on-linear lambda + combo_algorithm comments).

  After the spectrum-params group (after `fl.addRow("FFT点数:", ...)` and before any subsequent root.addWidget call), insert a helper method and the new group construction. Add to OrderContextual class (suggest placing the helper near other private helpers, e.g. just before `_collect_preset`):

  ```python
  # ---- 2026-04-28: axis settings group helpers ----
  def _build_axis_row(self, label, chk, spin_min, spin_max, unit_widget):
      """Build one inline axis row: [label][chk][spin_min][→][spin_max][unit].

      Returns a wrapper QWidget; caller adds it to the parent layout.
      """
      from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget
      row = QWidget()
      lay = QHBoxLayout(row)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.setSpacing(4)
      lbl = QLabel(label)
      lbl.setMinimumWidth(56)
      lbl.setMaximumWidth(56)
      lay.addWidget(lbl)
      lay.addWidget(chk)
      spin_min.setMaximumWidth(72)
      spin_max.setMaximumWidth(72)
      lay.addWidget(spin_min, 1)
      lay.addWidget(QLabel('→'))
      lay.addWidget(spin_max, 1)
      if unit_widget is not None:
          lay.addWidget(unit_widget)
      return row

  def _sync_axis_enabled(self):
      """Toggle spin enabled state to match each chk_*_auto."""
      for chk, spins in (
          (self.chk_x_auto, (self.spin_x_min, self.spin_x_max)),
          (self.chk_y_auto, (self.spin_y_min, self.spin_y_max)),
          (self.chk_z_auto, (self.spin_z_floor, self.spin_z_ceiling)),
      ):
          enabled = not chk.isChecked()
          for s in spins:
              s.setEnabled(enabled)

  def _on_amp_unit_changed(self, _txt):
      """Switching dB↔Linear forces z_auto on to avoid stale range values
      in the new unit. Per the 2026-04-28 plan."""
      self.chk_z_auto.setChecked(True)
      self._sync_axis_enabled()

  def _on_max_order_changed(self, val):
      """Clamp spin_y_max upper bound to <= spin_mo (max calc order).
      Display range cannot exceed the calc range."""
      self.spin_y_max.setMaximum(float(val))
      if self.spin_y_max.value() > float(val):
          self.spin_y_max.setValue(float(val))
  ```

  Then, in `OrderContextual.__init__`, after the spectrum-params group is added to root (after `root.addWidget(g)` for "谱参数"), insert:

  ```python
  # ---- 坐标轴设置 (Y axis range + Z dB scale floor/ceiling) ----
  from PyQt5.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel
  axis_g = QGroupBox("坐标轴设置")
  axis_lay = QVBoxLayout(axis_g)
  axis_lay.setContentsMargins(8, 8, 8, 8)
  axis_lay.setSpacing(4)

  # Time (X) row
  self.chk_x_auto = QCheckBox("自动")
  self.chk_x_auto.setChecked(True)
  self.spin_x_min = QDoubleSpinBox()
  self.spin_x_min.setRange(0.0, 1e6)
  self.spin_x_min.setDecimals(2)
  self.spin_x_min.setSuffix(' s')
  self.spin_x_max = QDoubleSpinBox()
  self.spin_x_max.setRange(0.0, 1e6)
  self.spin_x_max.setDecimals(2)
  self.spin_x_max.setSuffix(' s')
  axis_lay.addWidget(self._build_axis_row(
      "时间 (X):", self.chk_x_auto,
      self.spin_x_min, self.spin_x_max, None,
  ))

  # Order (Y) row — clamped to <= spin_mo
  self.chk_y_auto = QCheckBox("自动")
  self.chk_y_auto.setChecked(True)
  self.spin_y_min = QDoubleSpinBox()
  self.spin_y_min.setRange(0.0, 100.0)
  self.spin_y_min.setDecimals(2)
  self.spin_y_max = QDoubleSpinBox()
  self.spin_y_max.setRange(0.0, float(self.spin_mo.value()))
  self.spin_y_max.setDecimals(2)
  self.spin_y_max.setValue(float(self.spin_mo.value()))
  axis_lay.addWidget(self._build_axis_row(
      "阶次 (Y):", self.chk_y_auto,
      self.spin_y_min, self.spin_y_max, None,
  ))

  # Color scale (Z) row — has unit dropdown replacing combo_amp_mode
  self.chk_z_auto = QCheckBox("自动")
  self.chk_z_auto.setChecked(False)  # default: -30..0 dB (matches legacy 30 dB behavior)
  self.spin_z_floor = QDoubleSpinBox()
  self.spin_z_floor.setRange(-200.0, 200.0)
  self.spin_z_floor.setDecimals(2)
  self.spin_z_floor.setValue(-30.0)
  self.spin_z_ceiling = QDoubleSpinBox()
  self.spin_z_ceiling.setRange(-200.0, 200.0)
  self.spin_z_ceiling.setDecimals(2)
  self.spin_z_ceiling.setValue(0.0)
  self.combo_amp_unit = QComboBox()
  self.combo_amp_unit.addItems(['dB', 'Linear'])
  axis_lay.addWidget(self._build_axis_row(
      "色阶:", self.chk_z_auto,
      self.spin_z_floor, self.spin_z_ceiling, self.combo_amp_unit,
  ))

  root.addWidget(axis_g)

  # ---- wiring ----
  self.chk_x_auto.toggled.connect(self._sync_axis_enabled)
  self.chk_y_auto.toggled.connect(self._sync_axis_enabled)
  self.chk_z_auto.toggled.connect(self._sync_axis_enabled)
  self.combo_amp_unit.currentTextChanged.connect(self._on_amp_unit_changed)
  self.spin_mo.valueChanged.connect(self._on_max_order_changed)
  # seed initial enabled state once (per init-sync lesson)
  self._sync_axis_enabled()
  ```

- [ ] **3.4: Update `current_params` and `apply_params` for new keys**

  In OrderContextual `current_params()`:
  ```python
  def current_params(self):
      p = self.get_params()
      # legacy field still emitted for now (Wave 5 deletes the 'dynamic' key
      # downstream); the new 'amplitude_mode' value comes from the unit dropdown
      p['amplitude_mode'] = (
          'Amplitude dB' if self.combo_amp_unit.currentText() == 'dB'
          else 'Amplitude'
      )
      p['samples_per_rev'] = int(self.spin_samples_per_rev.value())
      # axis controls
      p['x_auto'] = bool(self.chk_x_auto.isChecked())
      p['x_min'] = float(self.spin_x_min.value())
      p['x_max'] = float(self.spin_x_max.value())
      p['y_auto'] = bool(self.chk_y_auto.isChecked())
      p['y_min'] = float(self.spin_y_min.value())
      p['y_max'] = float(self.spin_y_max.value())
      p['z_auto'] = bool(self.chk_z_auto.isChecked())
      p['z_floor'] = float(self.spin_z_floor.value())
      p['z_ceiling'] = float(self.spin_z_ceiling.value())
      return p
  ```

  In `apply_params(d)`, replace the `for k, combo in (('amplitude_mode', self.combo_amp_mode), ('dynamic', self.combo_dynamic))` block with:

  ```python
  # New axis fields (preferred path)
  for key, attr in (
      ('x_auto', 'chk_x_auto'), ('y_auto', 'chk_y_auto'), ('z_auto', 'chk_z_auto'),
  ):
      if key in d:
          getattr(self, attr).setChecked(bool(d[key]))
  for key, attr in (
      ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
      ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
      ('z_floor', 'spin_z_floor'), ('z_ceiling', 'spin_z_ceiling'),
  ):
      if key in d:
          try:
              getattr(self, attr).setValue(float(d[key]))
          except (TypeError, ValueError):
              pass

  # amplitude_mode → combo_amp_unit
  if 'amplitude_mode' in d:
      val = str(d['amplitude_mode'])
      target = 'dB' if 'dB' in val else 'Linear'
      i = self.combo_amp_unit.findText(target)
      if i >= 0:
          self.combo_amp_unit.blockSignals(True)
          self.combo_amp_unit.setCurrentIndex(i)
          self.combo_amp_unit.blockSignals(False)

  # Legacy 'dynamic' key compat — translate to z_floor/ceiling/auto
  if 'dynamic' in d and 'z_floor' not in d:
      raw = str(d['dynamic'])
      if raw == 'Auto':
          self.chk_z_auto.setChecked(True)
      else:
          # parse "30 dB" → 30
          try:
              n = float(raw.replace('dB', '').strip())
              self.chk_z_auto.setChecked(False)
              self.spin_z_floor.setValue(-abs(n))
              self.spin_z_ceiling.setValue(0.0)
          except ValueError:
              pass

  self._sync_axis_enabled()
  ```

  **Important:** the old `apply_params` block reading `combo_dynamic` and `combo_amp_mode` must be **fully replaced** by the above. Do not leave dangling references to the deleted combos.

  > **Audit fix (R7 / C8)**: OrderContextual has TWO separate methods that both need the dynamic/amplitude_mode migration logic — they live at different line ranges and currently behave differently:
  >
  > - **`apply_params` (lines 1402-1447)** — already accepts `amplitude_mode`/`dynamic`/`algorithm` and writes them to `combo_amp_mode`/`combo_dynamic`/`combo_algorithm`. The block-replacement code shown above goes here.
  > - **`_apply_preset` (lines 1322-1334)** — currently does NOT accept `amplitude_mode` or `dynamic`. Test 3.1's `test_order_contextual_apply_preset_legacy_dynamic` calls `oc._apply_preset({...})` and expects it to translate. The plan must EXTEND `_apply_preset` to add the same legacy-key translation block as `apply_params`. After the existing `nfft` handling at line 1330, append:
  >
  > ```python
  > # Legacy 'dynamic' key compat — translate to z_floor/ceiling/auto
  > if 'dynamic' in d and 'z_floor' not in d:
  >     raw = str(d['dynamic'])
  >     if raw == 'Auto':
  >         self.chk_z_auto.setChecked(True)
  >     else:
  >         try:
  >             n = float(raw.replace('dB', '').strip())
  >             self.chk_z_auto.setChecked(False)
  >             self.spin_z_floor.setValue(-abs(n))
  >             self.spin_z_ceiling.setValue(0.0)
  >         except ValueError:
  >             pass
  > # Legacy 'amplitude_mode' key compat — translate to combo_amp_unit
  > if 'amplitude_mode' in d:
  >     val = str(d['amplitude_mode'])
  >     target = 'dB' if 'dB' in val else 'Linear'
  >     i = self.combo_amp_unit.findText(target)
  >     if i >= 0:
  >         self.combo_amp_unit.blockSignals(True)
  >         self.combo_amp_unit.setCurrentIndex(i)
  >         self.combo_amp_unit.blockSignals(False)
  > # Apply new axis keys directly if present
  > for key, attr in (
  >     ('z_auto', 'chk_z_auto'), ('y_auto', 'chk_y_auto'), ('x_auto', 'chk_x_auto'),
  > ):
  >     if key in d:
  >         getattr(self, attr).setChecked(bool(d[key]))
  > for key, attr in (
  >     ('z_floor', 'spin_z_floor'), ('z_ceiling', 'spin_z_ceiling'),
  >     ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
  >     ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
  > ):
  >     if key in d:
  >         try:
  >             getattr(self, attr).setValue(float(d[key]))
  >         except (TypeError, ValueError):
  >             pass
  > self._sync_axis_enabled()
  > ```

  Update `_collect_preset` (lines 1313-1320, OrderContextual): currently does NOT emit `dynamic`/`amplitude_mode`, so no change needed for OrderContextual. (Wave 4 covers FFTTimeContextual's `_collect_preset` at line 1831-1845, which DOES currently emit those keys.)

- [ ] **3.5: Run new tests green**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_inspector.py -v --basetemp=.pytest-tmp -p no:cacheprovider -k "axis_settings or amp_mode_and_dynamic or y_max_clamped or unit_toggle or current_params_emits or apply_preset_legacy_dynamic"`

  Expected: PASS, all 6 new tests.

- [ ] **3.6: Run full inspector test suite — old tests should also still pass except some that explicitly used combo_amp_mode/combo_dynamic**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_inspector.py -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: most green; failing tests will be those that asserted `combo_amp_mode` / `combo_dynamic` existed. **Delete those tests** — their semantics are now covered by the new axis-settings tests. If a test had additional unrelated assertions, keep those and remove only the combo references.

- [ ] **3.7: Commit**

  ```
  git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
  git commit -m "feat(inspector): OrderContextual gains 坐标轴设置 group; combo_amp_mode + combo_dynamic dropped

  Introduces 9 new controls: chk_x/y/z_auto, spin_x/y/z {min,max,floor,ceiling},
  combo_amp_unit (dB|Linear). Replaces combo_amp_mode + combo_dynamic with the
  Z-row unit dropdown + spin floor/ceiling. spin_y_max upper bound is clamped
  to <= spin_mo (max_order) so display range cannot exceed calc range. Switching
  the dB↔Linear unit forces z_auto=True (per plan A: explicit re-entry rather
  than implicit unit conversion). _apply_preset accepts legacy 'dynamic' / 'amplitude_mode'
  keys and translates to the new field set."
  ```

---

### Wave 4 — Inspector FFTTimeContextual: same group + freq range migration

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py` (FFTTimeContextual class, lines 1453-1900)
- Test: `tests/ui/test_inspector.py`

> **Audit fix (R1)**: This wave targets `FFTTimeContextual` (line 1453+), NOT `FFTContextual` (line 831-1112). Only `FFTTimeContextual` has `combo_amp_mode` (1572), `combo_dynamic` (1608), `chk_freq_auto` (1587), `spin_freq_min/max` (1592-1605). `FFTContextual` (the 1D-spectrum class) uses different Y-axis controls (`combo_amp_y`, `combo_psd_y`) and is **out of scope** for this wave; if axis range controls for 1D FFT are wanted later, schedule a separate sub-wave.

The FFT-time view renders a spectrogram: X = time, Y = freq, Z = amplitude. Layout:
- **3 rows always**: 频率(X) / 幅值(Y, unused for spectrogram but kept for parity) / 色阶(Z)
- **X row**: label is "频率 (X):" — migrated from `chk_freq_auto + spin_freq_min/max` (existing controls become aliases)
- **Y row**: label is "幅值 (Y):" — new (currently unused by spectrogram render; kept consistent with OrderContextual)
- **Z row**: label is "色阶:" with `[dB|Linear]` unit dropdown — replaces `combo_amp_mode` (1572) and `combo_dynamic` (1608)

- [ ] **4.1: Write failing tests for FFTTimeContextual axis controls**

  Add to `tests/ui/test_inspector.py`:

  ```python
  def test_fft_time_contextual_has_axis_settings_group(qtbot):
      """FFTTimeContextual must contain QGroupBox '坐标轴设置' with the same
      9 controls as OrderContextual but X = freq, Y = amplitude."""
      from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
      fc = FFTTimeContextual()
      qtbot.addWidget(fc)

      for name in (
          'chk_x_auto', 'spin_x_min', 'spin_x_max',
          'chk_y_auto', 'spin_y_min', 'spin_y_max',
          'chk_z_auto', 'spin_z_floor', 'spin_z_ceiling',
          'combo_amp_unit',
      ):
          assert hasattr(fc, name), f'missing {name}'

      # Old controls migrated/removed
      assert not hasattr(fc, 'combo_amp_mode')
      assert not hasattr(fc, 'combo_dynamic')
      # chk_freq_auto + spin_freq_min/max moved into the axis group
      # but kept as attribute names for backward-compat with main_window callers
      # — they now alias to chk_x_auto / spin_x_min / spin_x_max.
      assert fc.chk_freq_auto is fc.chk_x_auto
      assert fc.spin_freq_min is fc.spin_x_min
      assert fc.spin_freq_max is fc.spin_x_max

  def test_fft_time_contextual_current_params_emits_axis_keys(qtbot):
      from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
      fc = FFTTimeContextual()
      qtbot.addWidget(fc)

      p = fc.current_params()
      for key in ('x_auto', 'x_min', 'x_max',
                  'y_auto', 'y_min', 'y_max',
                  'z_auto', 'z_floor', 'z_ceiling',
                  'amplitude_mode'):
          assert key in p
      # Legacy keys preserved for now (Wave 5 callers; safe to keep)
      assert 'freq_auto' in p
      assert 'freq_min' in p
      assert 'freq_max' in p

  def test_fft_time_contextual_apply_legacy_dynamic_80db(qtbot):
      from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
      fc = FFTTimeContextual()
      qtbot.addWidget(fc)
      fc._apply_preset({'amplitude_mode': 'Amplitude dB', 'dynamic': '80 dB'})
      assert not fc.chk_z_auto.isChecked()
      assert fc.spin_z_floor.value() == -80.0
      assert fc.spin_z_ceiling.value() == 0.0
  ```

- [ ] **4.2: Run tests red**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_inspector.py -v --basetemp=.pytest-tmp -p no:cacheprovider -k "fft_time_contextual"`

  Expected: FAIL.

- [ ] **4.3: Apply same group to FFTTimeContextual**

  In `mf4_analyzer/ui/inspector_sections.py` FFTTimeContextual (lines 1453-1900):

  - **Delete** `combo_amp_mode` (around line 1572 area), `combo_dynamic` (line 1608), and the `chk_freq_auto + spin_freq_min/max` block (lines 1587-1605). Their replacements live in the new axis group.
  - **Reuse** the helpers (`_build_axis_row`, `_sync_axis_enabled`, `_on_amp_unit_changed`) from OrderContextual. Use option (a): extract them into a module-level function near the existing `_fit_field` helper, named `_make_axis_settings_group(parent, x_label, x_unit, y_label, y_unit, z_default_floor)`. Have both OrderContextual and FFTTimeContextual call it.

  > **Audit fix (S7)**: this supersedes Wave 3.3's instance-method `_build_axis_row` / `_sync_axis_enabled` / `_on_amp_unit_changed` / `_on_max_order_changed`. When implementing Wave 3.3, build them as instance methods first (per 3.3 code blocks). When Wave 4 lands, **also refactor OrderContextual** to call the module-level `_make_axis_settings_group`, removing the now-redundant instance method bodies. The instance methods `_sync_axis_enabled` and `_on_max_order_changed` may stay as instance methods on OrderContextual since they reference `self.spin_mo` (Order-specific). Only the row-builder + amp-unit-change callback move to module level.

    Suggested module-level helper signature:

    ```python
    def _make_axis_settings_group(
        owner,
        x_label: str, x_unit: str, x_default_min: float, x_default_max: float,
        y_label: str, y_unit: str, y_default_min: float, y_default_max: float,
        z_default_floor: float = -30.0, z_default_ceiling: float = 0.0,
        z_default_auto: bool = False,
    ) -> QGroupBox:
        """Build the 3-row inline axis settings group; assign all spin/chk
        widgets as attributes on owner (chk_x_auto, spin_x_min, ...).
        Wires _sync_axis_enabled and _on_amp_unit_changed."""
    ```

  - In FFTTimeContextual `__init__`, after the spectrum-params group and **before any return / show**, insert (the aliases MUST be set inside `__init__` so test 4.1 sees them at construction):

    ```python
    axis_g = _make_axis_settings_group(
        self,
        x_label='频率 (X):', x_unit='Hz',
        x_default_min=0.0, x_default_max=0.0,  # 0 = Nyquist
        y_label='幅值 (Y):', y_unit='',
        y_default_min=0.0, y_default_max=0.0,
        z_default_floor=-80.0, z_default_ceiling=0.0,
        z_default_auto=False,
    )
    body_lay.addWidget(axis_g)
    # Backward-compat aliases for downstream readers (must be set in __init__)
    self.chk_freq_auto = self.chk_x_auto
    self.spin_freq_min = self.spin_x_min
    self.spin_freq_max = self.spin_x_max
    ```

  - **W3 / R8 mitigation — signal storms**: `_make_axis_settings_group` MUST connect `combo_amp_unit.currentTextChanged` → `_on_amp_unit_changed` AFTER setting initial values; OR wrap the initial `combo_amp_unit.setCurrentIndex(0)` (and any spin `setValue` for axis controls) in `widget.blockSignals(True/False)`. Otherwise the helper triggers `_on_amp_unit_changed` during construction, forcing `chk_z_auto=True` regardless of `z_default_auto=False`.

  - Also for FFTTimeContextual: when `apply_params` / `_apply_preset` (line 1847-1896 area) calls `combo_amp_unit.setCurrentIndex` on legacy preset translation, wrap in `blockSignals(True/False)` per Step 3.4 OrderContextual pattern. Same logic; do not skip the wrapper "because OrderContextual already does it".

  - In OrderContextual, similarly call:

    ```python
    axis_g = _make_axis_settings_group(
        self,
        x_label='时间 (X):', x_unit='s',
        x_default_min=0.0, x_default_max=0.0,
        y_label='阶次 (Y):', y_unit='',
        y_default_min=0.0, y_default_max=float(self.spin_mo.value()),
        z_default_floor=-30.0, z_default_ceiling=0.0,
        z_default_auto=False,
    )
    root.addWidget(axis_g)
    ```

  - In FFTTimeContextual `current_params` (or `get_params` — verify which exists; this class uses both), add the new keys and keep legacy `freq_auto/min/max` as aliases:

    ```python
    p['x_auto'] = bool(self.chk_x_auto.isChecked())
    p['x_min'] = float(self.spin_x_min.value())
    p['x_max'] = float(self.spin_x_max.value())
    p['y_auto'] = bool(self.chk_y_auto.isChecked())
    p['y_min'] = float(self.spin_y_min.value())
    p['y_max'] = float(self.spin_y_max.value())
    p['z_auto'] = bool(self.chk_z_auto.isChecked())
    p['z_floor'] = float(self.spin_z_floor.value())
    p['z_ceiling'] = float(self.spin_z_ceiling.value())
    p['amplitude_mode'] = (
        'Amplitude dB' if self.combo_amp_unit.currentText() == 'dB'
        else 'Amplitude'
    )
    # legacy (kept until Wave 5 trims callers)
    p['freq_auto'] = p['x_auto']
    p['freq_min'] = p['x_min']
    p['freq_max'] = p['x_max']
    ```

  - In FFTTimeContextual `_apply_preset` (lines 1847-1896 area) AND `apply_params` (if separate), fold in legacy `dynamic` parsing — same logic as OrderContextual Step 3.4 (R7). Use `blockSignals` around `combo_amp_unit.setCurrentIndex` (R8).
  - Also update FFTTimeContextual `_collect_preset` (lines 1831-1845) to stop emitting `dynamic` and `amplitude_mode` directly from the now-deleted `combo_*`. Replace with `combo_amp_unit.currentText()` mapping (mirroring step 3.4 for OrderContextual). Note: OrderContextual's `_collect_preset` (lines 1313-1320) does NOT currently emit these keys — no change needed there.

  > **Audit fix (NEW-1)**: `FFTTimeContextual._BUILTIN_PRESETS` (lines 1767-1795) and `_builtin_preset_full_params` (lines 1805-1829) hold legacy `dynamic`/`freq_auto/min/max` keys. After Wave 4 deletes the underlying widgets, calls to `apply_builtin_preset` route through `_apply_preset` with these legacy keys. Functional correctness is preserved by Step 4.3's legacy-key migration block in `_apply_preset` (which translates `dynamic` to `z_floor/ceiling/auto`). However, `_builtin_preset_full_params` round-trip output still contains `dynamic` and `amplitude_mode` keys — Wave 6's `_migrate_axis_keys` in `batch_preset_io.py` handles this on read. Decision: leave `_BUILTIN_PRESETS` literals alone (read-side migration is sufficient), but ADD a brief `# DEPRECATED key form; survives via batch_preset_io._migrate_axis_keys on load` comment above `_BUILTIN_PRESETS` so future readers don't try to clean it up prematurely.

- [ ] **4.4: Run tests green**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_inspector.py -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: green except for tests asserting old `combo_amp_mode` / `combo_dynamic` presence — delete those.

- [ ] **4.5: Commit**

  ```
  git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
  git commit -m "feat(inspector): FFTTimeContextual gains 坐标轴设置 group; freq controls migrated

  chk_freq_auto / spin_freq_min/max are now aliases of chk_x_auto / spin_x_min /
  spin_x_max in the new axis group. combo_amp_mode + combo_dynamic dropped from
  FFTTimeContextual. Legacy 'dynamic' presets translate to z_floor/ceiling.
  _make_axis_settings_group module-level helper deduplicates between
  OrderContextual and FFTTimeContextual. FFTContextual (1D spectrum, line 831)
  is OUT OF SCOPE for this wave."
  ```

---

### Wave 5 — Canvases: signature change `dynamic` → `(z_auto, z_floor, z_ceiling)`

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py` (around lines 1235-1326, 1572-1626)
- Modify: `mf4_analyzer/ui/main_window.py` (line 1467-1479 area, plus any other `plot_or_update_heatmap` / `plot_result` call sites)
- Test: `tests/ui/test_canvases_envelope.py` (or test_canvases.py — verify which exists)

- [ ] **5.1: Write failing test for new signature**

  Add to `tests/ui/test_canvases_envelope.py`:

  ```python
  def test_color_limits_z_explicit_floor_ceiling():
      """_color_limits accepts (z_auto=False, z_floor, z_ceiling) and returns them.
      _color_limits accepts z_auto=True and returns (nanmin, nanmax)."""
      import numpy as np
      from mf4_analyzer.ui.canvases import SpectrogramCanvas

      # Pure-function call doesn't need a Qt instance — patch _color_limits as static
      # If it's not static, instantiate the canvas under offscreen.
      sc = SpectrogramCanvas()
      z = np.array([[-50, -10, -5], [-100, -20, 0]], dtype=float)

      vmin, vmax = sc._color_limits(
          z, amplitude_mode='amplitude_db',
          z_auto=False, z_floor=-30.0, z_ceiling=0.0,
      )
      assert (vmin, vmax) == (-30.0, 0.0)

      vmin, vmax = sc._color_limits(
          z, amplitude_mode='amplitude_db', z_auto=True,
          z_floor=999, z_ceiling=999,  # ignored
      )
      assert vmin == -100.0
      assert vmax == 0.0

  def test_plot_or_update_heatmap_axis_args(qtbot):
      """plot_or_update_heatmap accepts new (z_auto, z_floor, z_ceiling, x_auto,
      x_min, x_max, y_auto, y_min, y_max) kwargs without TypeError."""
      import numpy as np
      from mf4_analyzer.ui.canvases import PlotCanvas

      pc = PlotCanvas()
      qtbot.addWidget(pc)
      m = np.random.RandomState(42).rand(8, 8)

      pc.plot_or_update_heatmap(
          matrix=m, x_extent=(0, 4), y_extent=(0, 20),
          x_label='Time (s)', y_label='Order',
          title='test', cmap='turbo', interp='bilinear',
          cbar_label='Amplitude',
          amplitude_mode='amplitude_db',
          z_auto=False, z_floor=-30.0, z_ceiling=0.0,
          x_auto=True, x_min=0.0, x_max=0.0,
          y_auto=False, y_min=2.0, y_max=18.0,
      )
      # If y_auto=False, ax should have set_ylim(2, 18)
      ax = pc.fig.axes[0]
      lo, hi = ax.get_ylim()
      assert abs(lo - 2.0) < 0.01
      assert abs(hi - 18.0) < 0.01
  ```

- [ ] **5.2: Run tests red**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_canvases_envelope.py -v --basetemp=.pytest-tmp -p no:cacheprovider -k "color_limits_z_explicit or plot_or_update_heatmap_axis_args"`

  Expected: FAIL on missing kwargs / signature mismatch.

- [ ] **5.3: Refactor `_color_limits` and `plot_result` signatures**

  In `mf4_analyzer/ui/canvases.py:1311-1326`, replace:

  ```python
  def _color_limits(self, z, amplitude_mode, dynamic):
      zmax = float(np.nanmax(z))
      if amplitude_mode == 'amplitude_db':
          if dynamic == '80 dB':
              return zmax - 80.0, zmax
          if dynamic == '60 dB':
              return zmax - 60.0, zmax
          return float(np.nanmin(z)), zmax
      return float(np.nanmin(z)), zmax
  ```

  with:

  ```python
  def _color_limits(self, z, amplitude_mode, z_auto, z_floor, z_ceiling):
      """Choose (vmin, vmax) for imshow.

      Replaces the old ``dynamic: str`` API as of 2026-04-28. ``amplitude_mode``
      is kept for backward-compat callers but has no effect on the limits when
      explicit floor/ceiling are supplied — those win.
      """
      if z_auto:
          return float(np.nanmin(z)), float(np.nanmax(z))
      return float(z_floor), float(z_ceiling)
  ```

  > **Audit fix (NEW-4 / C6)**: the public `plot_result` signature also changes — spell it out concretely.

  In `mf4_analyzer/ui/canvases.py` (around line 1235), the existing signature is:

  ```python
  def plot_result(self, result, amplitude_mode='amplitude_db', cmap='turbo',
                  dynamic='80 dB', freq_range=None):
  ```

  Replace with:

  ```python
  def plot_result(self, result, amplitude_mode='amplitude_db', cmap='turbo',
                  z_auto=False, z_floor=-80.0, z_ceiling=0.0,
                  freq_range=None,
                  y_auto=True, y_min=0.0, y_max=0.0):
  ```

  Inside the body, replace the line that calls `self._color_limits(z, amplitude_mode, dynamic)` (or stores `self._dynamic = dynamic`) with the new call passing `z_auto, z_floor, z_ceiling`. Remove any `self._dynamic = dynamic` state mutation (no consumer remains after Wave 5).

  `freq_range` continues to control the **frequency axis** (Y axis on a vertical-frequency spectrogram); it is independent of the new `y_min/y_max` kwargs which control matplotlib `set_ylim` for caller-driven manual ranges. If `y_auto=False and y_max > y_min`, `set_ylim(y_min, y_max)` overrides whatever `freq_range` would have set. Document this precedence in the docstring.

- [ ] **5.4: Refactor `plot_or_update_heatmap`**

  > **Audit fix (R4 / C3)**: actual `plot_or_update_heatmap` signature uses keyword-only args (`*,` after `self`), with `vmin/vmax` BEFORE `cbar_label`. Preserve the keyword-only marker.

  In `mf4_analyzer/ui/canvases.py:1567-1677` (verified actual range), change the signature from:

  ```python
  def plot_or_update_heatmap(self, *, matrix, x_extent, y_extent,
                              x_label, y_label, title,
                              cmap='turbo', interp='bilinear',
                              vmin=None, vmax=None,
                              cbar_label='Amplitude',
                              amplitude_mode='amplitude',
                              dynamic='Auto'):
  ```

  to:

  ```python
  def plot_or_update_heatmap(self, *, matrix, x_extent, y_extent,
                              x_label, y_label, title,
                              cmap='turbo', interp='bilinear',
                              vmin=None, vmax=None,
                              cbar_label='Amplitude',
                              amplitude_mode='amplitude',
                              z_auto=True, z_floor=-30.0, z_ceiling=0.0,
                              x_auto=True, x_min=0.0, x_max=0.0,
                              y_auto=True, y_min=0.0, y_max=0.0):
  ```

  Replace the dynamic-string branching (lines 1609-1614 area):

  ```python
  if dynamic == '30 dB':
      m_disp = np.clip(m_disp, -30.0, 0.0)
  elif dynamic == '50 dB':
      m_disp = np.clip(m_disp, -50.0, 0.0)
  elif dynamic == '80 dB':
      m_disp = np.clip(m_disp, -80.0, 0.0)
  ```

  with:

  ```python
  if not z_auto and amplitude_mode == 'amplitude_db':
      m_disp = np.clip(m_disp, float(z_floor), float(z_ceiling))
  ```

  After computing vmin/vmax via the now-removed `Auto` fallback, set:

  ```python
  if vmin is None:
      vmin = float(z_floor) if not z_auto else float(np.nanmin(m))
  if vmax is None:
      vmax = float(z_ceiling) if not z_auto else 0.0  # or nanmax
  ```

  > **Audit fix (R5 / C4)**: `plot_or_update_heatmap` has TWO branches and BOTH must respect `x_auto`/`y_auto`:
  >
  > **Branch 1 — fast-reuse path (around lines 1640-1655)** — when an existing image is reused via `existing_im.set_data(...)`. Currently does:
  >
  > ```python
  > existing_ax.set_xlim(x_extent)
  > existing_ax.set_ylim(y_extent)
  > ```
  >
  > Replace with:
  >
  > ```python
  > if x_auto:
  >     existing_ax.set_xlim(x_extent)
  > elif x_max > x_min:
  >     existing_ax.set_xlim(float(x_min), float(x_max))
  > if y_auto:
  >     existing_ax.set_ylim(y_extent)
  > elif y_max > y_min:
  >     existing_ax.set_ylim(float(y_min), float(y_max))
  > ```
  >
  > **Branch 2 — first-call / rebuild path** — after `imshow`, before `draw_idle`, add the same conditional logic:
  >
  > ```python
  > ax = self.fig.axes[0]
  > if not x_auto and x_max > x_min:
  >     ax.set_xlim(float(x_min), float(x_max))
  > if not y_auto and y_max > y_min:
  >     ax.set_ylim(float(y_min), float(y_max))
  > ```
  >
  > Without updating Branch 1, the second compute click would silently revert user-set ranges to the auto extent — caught by the manual UI regression in step 6.7.

- [ ] **5.5: Update MainWindow call sites**

  > **Audit fix (R2 / C5)**: there are TWO production callers, both must be updated:
  > 1. `mf4_analyzer/ui/main_window.py:1467` — `self.canvas_order.plot_or_update_heatmap(...)` (Order time-order render)
  > 2. `mf4_analyzer/ui/main_window.py:1793` — `self.canvas_fft_time.plot_result(...)` (FFT-vs-Time spectrogram render)
  >
  > Verification grep before edit: `grep -nE "plot_or_update_heatmap|plot_result\(" mf4_analyzer/`. Expected hits: line 1467 and 1793 in `main_window.py` (plus internal calls inside `canvases.py` itself).
  >
  > For caller #1 (line 1467) and caller #2 (line 1793), full before/after code is shown below. Note `FFTTimeContextual` exposes only `get_params()` (no `current_params()`) — use `get_params()`.

  **Caller #1** (`main_window.py:1467`, Order time-order render). Replace:

  ```python
  amp_mode_token = (
      'amplitude_db'
      if order_params.get('amplitude_mode', 'Amplitude dB') == 'Amplitude dB'
      else 'amplitude'
  )
  self.canvas_order.plot_or_update_heatmap(
      ...
      amplitude_mode=amp_mode_token,
      dynamic=order_params.get('dynamic', '30 dB'),
  )
  ```

  with:

  ```python
  amp_mode_token = (
      'amplitude_db'
      if order_params.get('amplitude_mode', 'Amplitude dB') == 'Amplitude dB'
      else 'amplitude'
  )
  self.canvas_order.plot_or_update_heatmap(
      ...
      amplitude_mode=amp_mode_token,
      z_auto=bool(order_params.get('z_auto', False)),
      z_floor=float(order_params.get('z_floor', -30.0)),
      z_ceiling=float(order_params.get('z_ceiling', 0.0)),
      x_auto=bool(order_params.get('x_auto', True)),
      x_min=float(order_params.get('x_min', 0.0)),
      x_max=float(order_params.get('x_max', 0.0)),
      y_auto=bool(order_params.get('y_auto', True)),
      y_min=float(order_params.get('y_min', 0.0)),
      y_max=float(order_params.get('y_max', 0.0)),
  )
  ```

  **Caller #2** (`main_window.py:1793`, FFT-vs-Time spectrogram render). Locate the `self.canvas_fft_time.plot_result(...)` call. Read the source `fft_time_params = self.inspector.fft_time_ctx.get_params()` and pass the new axis kwargs:

  ```python
  fft_time_params = self.inspector.fft_time_ctx.get_params()
  amp_mode_token = (
      'amplitude_db'
      if fft_time_params.get('amplitude_mode', 'Amplitude dB') == 'Amplitude dB'
      else 'amplitude'
  )
  self.canvas_fft_time.plot_result(
      result,
      amplitude_mode=amp_mode_token,
      cmap=fft_time_params.get('cmap', 'turbo'),
      z_auto=bool(fft_time_params.get('z_auto', False)),
      z_floor=float(fft_time_params.get('z_floor', -80.0)),
      z_ceiling=float(fft_time_params.get('z_ceiling', 0.0)),
      freq_range=(
          (float(fft_time_params['freq_min']), float(fft_time_params['freq_max']))
          if not fft_time_params.get('freq_auto', True)
             and fft_time_params.get('freq_max', 0.0) > fft_time_params.get('freq_min', 0.0)
          else None
      ),
      y_auto=bool(fft_time_params.get('y_auto', True)),
      y_min=float(fft_time_params.get('y_min', 0.0)),
      y_max=float(fft_time_params.get('y_max', 0.0)),
  )
  ```

  The exact name `fft_time_ctx` may differ — verify against existing main_window code (search for `canvas_fft_time` to find the surrounding context). Replace `dynamic=...` kwarg with the explicit `z_*` kwargs as shown.

  Verification grep:
  ```
  grep -n "dynamic=" mf4_analyzer/ui/main_window.py
  ```
  Expected: zero hits after edit.

- [ ] **5.5b: Update `tests/ui/test_canvases.py` to new signature**

  > **Audit fix (R3 / C2)**: `tests/ui/test_canvases.py` has 3 calls passing `dynamic='30 dB'` / `'Auto'` / `'50 dB'` (lines ~30, ~45, ~58). After Wave 5 they will raise `TypeError: unexpected keyword argument 'dynamic'`. The plan's earlier final-sweep claim only covers `tests/ui/test_canvases_envelope.py`.

  In `tests/ui/test_canvases.py`, find each call to `plot_or_update_heatmap(... dynamic=...)` and replace `dynamic='30 dB'` → `z_auto=False, z_floor=-30.0, z_ceiling=0.0`; `dynamic='50 dB'` → `z_auto=False, z_floor=-50.0, z_ceiling=0.0`; `dynamic='Auto'` → `z_auto=True`. After the edits, run `grep -n "dynamic=" tests/ui/test_canvases.py` — expected zero hits.

  Then: `.venv/Scripts/python.exe -m pytest tests/ui/test_canvases.py -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: green.

- [ ] **5.6: Run canvases tests green**

  Run: `.venv/Scripts/python.exe -m pytest tests/ui/test_canvases_envelope.py -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: all green; the two new tests pass; existing tests pass.

  Then full sweep:
  ```
  .venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest-tmp -p no:cacheprovider 2>&1 | tail -5
  ```
  Expected: at most the pre-existing `test_orders_with_subbin_floor_drops_low_orders` failure.

- [ ] **5.7: Commit**

  ```
  git add mf4_analyzer/ui/canvases.py mf4_analyzer/ui/main_window.py tests/ui/test_canvases_envelope.py
  git commit -m "refactor(canvases): _color_limits + plot_or_update_heatmap accept axis kwargs

  Replaces the old 'dynamic: str' API ('30 dB' / 'Auto' / ...) with explicit
  (z_auto, z_floor, z_ceiling, amplitude_mode) and adds optional (x/y_auto,
  x/y_min, x/y_max). MainWindow.do_order_time call site updated. The contract
  change follows the 'return-type-change-needs-paired-callsite-update' lesson —
  every grep-able dynamic= caller is updated in this commit."
  ```

---

### Wave 6 — Preset I/O migration + final cleanup

**Files:**
- Modify: `mf4_analyzer/batch_preset_io.py` (`load_preset_from_json`)
- Modify: `mf4_analyzer/signal/order.py` (deprecation comment)
- Test: `tests/test_batch_runner.py` or new `tests/test_batch_preset_io.py` if exists

- [ ] **6.1: Write failing test for legacy preset migration**

  Add to `tests/test_batch_runner.py` (or wherever preset I/O tests live):

  ```python
  def test_legacy_preset_with_algorithm_silently_ignored(tmp_path):
      """A preset emitted before 2026-04-28 may contain {algorithm: 'frequency'}
      and {dynamic: '30 dB'}. load_preset_from_json must accept it without
      raising and translate to the new field set."""
      import json
      from mf4_analyzer.batch_preset_io import load_preset_from_json

      # W6: schema actually uses target_signals / rpm_channel; the old
      # 'signal' / 'rpm_signal' top-level keys are silently ignored by
      # load_preset_from_json. Use the real schema for fixture clarity.
      legacy = {
          "method": "order_time",
          "name": "legacy",
          "target_signals": ["ch1"],
          "rpm_channel": "rpm",
          "params": {
              "fs": 1000.0, "nfft": 1024, "max_order": 20,
              "order_res": 0.1, "time_res": 0.05,
              "algorithm": "frequency",   # ← legacy
              "dynamic": "30 dB",          # ← legacy
              "amplitude_mode": "Amplitude dB",
          },
      }
      p = tmp_path / "legacy.json"
      p.write_text(json.dumps(legacy), encoding='utf-8')

      preset = load_preset_from_json(str(p))
      assert preset is not None  # not silently dropped (method is supported)
      # 'algorithm' migrated away
      assert 'algorithm' not in preset.params
      # 'dynamic' translated
      assert preset.params.get('z_auto') is False
      assert preset.params.get('z_floor') == -30.0
      assert preset.params.get('z_ceiling') == 0.0
  ```

- [ ] **6.2: Run test red**

  Run: `.venv/Scripts/python.exe -m pytest tests/test_batch_runner.py::test_legacy_preset_with_algorithm_silently_ignored -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: FAIL.

- [ ] **6.3: Implement migration in `load_preset_from_json`**

  In `mf4_analyzer/batch_preset_io.py`, find `load_preset_from_json` and add a migration block before constructing the `AnalysisPreset`:

  ```python
  def _migrate_axis_keys(params: dict) -> dict:
      """Translate legacy 'algorithm' / 'dynamic' / 'amplitude_mode' keys to
      the post-2026-04-28 axis-settings field set. Mutates and returns params.
      Idempotent — safe to call on already-migrated presets."""
      # Drop algorithm key (COT-only after 2026-04-28)
      params.pop('algorithm', None)

      # Translate dynamic → z_auto / z_floor / z_ceiling if not already present
      if 'z_floor' not in params and 'dynamic' in params:
          raw = str(params.pop('dynamic'))
          if raw == 'Auto':
              params['z_auto'] = True
          else:
              try:
                  n = float(raw.replace('dB', '').strip())
                  params['z_auto'] = False
                  params['z_floor'] = -abs(n)
                  params['z_ceiling'] = 0.0
              except ValueError:
                  params['z_auto'] = True  # malformed → safe default
      else:
          params.pop('dynamic', None)

      return params
  ```

  Call `_migrate_axis_keys(params_dict)` before the preset is constructed.

- [ ] **6.4: Run test green**

  Run: `.venv/Scripts/python.exe -m pytest tests/test_batch_runner.py::test_legacy_preset_with_algorithm_silently_ignored -v --basetemp=.pytest-tmp -p no:cacheprovider`

  Expected: PASS.

- [ ] **6.5: Mark `OrderAnalyzer.compute_time_order_result` as deprecated**

  In `mf4_analyzer/signal/order.py:230`, prepend the docstring/decorator:

  ```python
  @staticmethod
  def compute_time_order_result(sig, rpm, t, params, progress_callback=None, cancel_token=None):
      """DEPRECATED 2026-04-28: COT is the only production order-tracking path.

      This frequency-domain mapping implementation is retained for one release
      to support back-compat preset replay in tests. New callers must use
      ``mf4_analyzer.signal.order_cot.COTOrderAnalyzer.compute``.
      """
      ...
  ```

  No code change beyond the docstring.

- [ ] **6.6: Final full sweep**

  Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest-tmp -p no:cacheprovider 2>&1 | tail -5`

  Expected: same baseline failure count as Wave A.1 — `test_orders_with_subbin_floor_drops_low_orders` only.

- [ ] **6.7: Offscreen UI verification**

  Run a small offscreen smoke (script or pytest fixture):

  ```python
  # scratch script: exercises 4 axis-settings states
  import os
  os.environ['QT_QPA_PLATFORM'] = 'offscreen'
  from PyQt5.QtWidgets import QApplication
  from mf4_analyzer.ui.inspector_sections import OrderContextual

  app = QApplication([])
  oc = OrderContextual()
  oc.resize(320, 600)
  oc.show()

  for name, setup in (
      ('auto-on', lambda: (
          oc.chk_y_auto.setChecked(True),
          oc.chk_z_auto.setChecked(True),
      )),
      ('auto-off', lambda: (
          oc.chk_y_auto.setChecked(False),
          oc.spin_y_min.setValue(2.5),
          oc.spin_y_max.setValue(15.0),
          oc.chk_z_auto.setChecked(False),
          oc.spin_z_floor.setValue(-50.0),
          oc.spin_z_ceiling.setValue(-10.0),
      )),
      ('focus', lambda: oc.spin_y_max.setFocus()),
      ('disabled', lambda: oc.setEnabled(False)),
  ):
      setup()
      app.processEvents()
      oc.grab().save(f'.pytest-tmp/axis-B-{name}.png', 'PNG')
  ```

  Expected: 4 PNGs saved. Visual check (manual): rows render correctly, spin arrows visible (qtawesome triangles from prior scheme B), units show, dB↔Linear toggle in the Z row.

- [ ] **6.8: Commit**

  ```
  git add mf4_analyzer/batch_preset_io.py mf4_analyzer/signal/order.py tests/test_batch_runner.py
  git commit -m "feat(preset-io): migrate legacy algorithm/dynamic keys; deprecate compute_time_order_result

  load_preset_from_json now silently drops the obsolete 'algorithm' key
  and translates 'dynamic' (e.g. '30 dB' / 'Auto') to z_auto + z_floor +
  z_ceiling. Idempotent; safe on already-migrated presets.
  OrderAnalyzer.compute_time_order_result gains a DEPRECATED docstring;
  removal scheduled for one release after this change."
  ```

---

## Risks / Edge Cases

### R1: COT requires strictly monotonic time (Wave 1)
**Mitigation:** `_compute_order_time_dataframe` checks `np.any(np.diff(time_arr) <= 0)` and falls back to a uniform fs-derived array. For inspector path, `MainWindow.do_order_time` already constructs `t = np.arange(...) / fs` upstream — verify in the dispatcher. If not, add the same fallback there.

### R2: spin_mo ↔ spin_y_max circular update
**Mitigation:** `_on_max_order_changed` uses `setMaximum` and a single `setValue` clamp; this does not retrigger `valueChanged` since the change comes from the same widget. No `blockSignals` needed. Test 3.1 covers the clamp behavior.

### R3: dB↔Linear toggle reset semantics
**Mitigation:** `_on_amp_unit_changed` forces `chk_z_auto=True`, which makes the spin values visually irrelevant until the user re-enters them. Documented in user-facing tooltip on `combo_amp_unit`. Test 3.1 covers the force-auto behavior.

### R4: `apply_params` signal storms on preset load
**Mitigation:** Wrap `combo_amp_unit.setCurrentText` with `blockSignals(True)` / `blockSignals(False)` (already in the Step 3.4 code). Without this, applying a preset with `amplitude_mode='Amplitude'` would trigger `_on_amp_unit_changed` → `chk_z_auto.setChecked(True)`, overwriting the preset's `z_auto=False`.

### R5: Legacy preset with `algorithm='frequency'` in production batch
**Mitigation:** Wave 6 migration silently drops the key. Migration is idempotent. If a batch preset on disk still has both `algorithm` and `dynamic`, the migrator drops `algorithm` first then translates `dynamic` — order matters but the test in 6.1 covers it.

### R6: `_color_limits` callers besides `plot_result`
**Mitigation:** grep before refactor: `grep -n "_color_limits" mf4_analyzer/`. If any caller besides `plot_result` exists, update them in the same Wave 5 commit. Preliminary check during plan-writing showed only one caller.

### R7: HiDPI rendering of new spinboxes
**Mitigation:** spinboxes inherit the existing scheme-B icon cache (mdi6.menu-up/down). No new icon work. Verify in offscreen with `QT_SCALE_FACTOR=1.5` once.

---

## Verification Plan

### Per-wave gate (must pass before next wave)
- Tests in modified files green.
- New tests added in this plan green.
- No new pre-existing failures (tracker: `test_orders_with_subbin_floor_drops_low_orders` only).
- `git diff --stat` for that wave matches the file list above.

### End-of-plan acceptance
1. **All tests green** except pre-existing baseline:
   `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest-tmp -p no:cacheprovider`
2. **Grep invariants** (zero hits in production code):
   ```
   grep -rn "combo_algorithm\|combo_amp_mode\|combo_dynamic\|频域映射" mf4_analyzer/
   grep -rn "dynamic=" mf4_analyzer/ui/main_window.py
   grep -rn "combo_algorithm\|'algorithm'\|on_algo_changed" mf4_analyzer/
   ```
   All three should yield zero hits in production code. (S9 — third pattern is precise: avoids false positives on the English noun "algorithm" in unrelated comments.)
3. **Strict-subset invariant** (per `plan-verbatim-source-must-reconcile-with-recent-removals` lesson): inspector's `current_params()` output keys ⊆ canvases call signature kwargs. Verify by inspection.
4. **Offscreen 4-state screenshots**: `.pytest-tmp/axis-B-{auto-on,auto-off,focus,disabled}.png` saved and visually OK.
5. **HiDPI smoke**: `QT_SCALE_FACTOR=1.5 python -m pytest tests/ui/test_inspector.py -q` passes.
6. **Real-mf4 regression** (manual): load a representative MF4 in the app, switch to Order mode, click 时间-阶次, confirm:
   - Default render shows -30..0 dB color scale (matches old "30 dB" default).
   - Toggle "色阶 → 自动 off" and set floor=-50, ceiling=-10 → render updates.
   - Toggle Z unit dB→Linear → z_auto goes True, color scale switches to nanmin/max.
   - Toggle "阶次 (Y) → 自动 off" and set range 2..15 → y axis clamped.
   - Switch to FFT mode and verify the same group appears with 频率(X) row.

---

## Rollback Strategy

Each wave is one commit. To roll back:
- **Single wave**: `git revert <commit-sha>` of that wave's commit.
- **Whole plan**: `git revert` the chain in reverse order (Wave 6 → 5 → ... → 1) or `git reset --hard <pre-plan-sha>` if no other commits intervened.

Working-tree-only rollback (mid-plan): `git checkout -- mf4_analyzer/ tests/` discards uncommitted edits.

> **Audit fix (W5)**: inter-wave coupling caveats:
> - **Waves 3 + 4 + 5 are coupled.** Wave 3-4 emit `z_auto/z_floor/z_ceiling/y_auto/y_min/y_max` keys via inspector `current_params`/`get_params`; Wave 5 makes canvases consume them. Reverting Wave 5 alone (without 3+4) leaves canvases ignoring the new keys but inspectors still emit them — the canvas falls back to default `dynamic='Auto'` rendering, which means user-selected ranges silently no-op. Reverting Waves 3+4 alone (without 5) leaves canvases expecting kwargs that no longer flow from inspectors — main_window passes `z_auto=False, z_floor=-30` from `get_params()` defaults via the order-render call site, so this direction is also non-crashing but locks the color scale to the hardcoded default. **Safer rollback: revert 3+4+5 as a group** if any one needs to go.
> - Waves 1 (batch COT) and 2 (algorithm picker removal) are independent of 3-5 — safe to revert individually.
> - Wave 6 (preset I/O migration) depends on Waves 3+4 having landed (the migration outputs `z_*` keys that the preset consumer expects). Reverting Wave 6 alone is safe; reverting Waves 3+4 alone may leave Wave 6's preset migrator emitting keys nothing reads (degraded but not crashing).

---

## Self-Review Notes

**Spec coverage**: Every user requirement from the chat-confirmed plan is covered:
- Task 1 (移除频域映射 inspector + batch + main_window): Waves 1, 2, 6.
- Task 2 (3-row inline axis settings, dB↔Linear unit toggle, spin_y_max ≤ spin_mo, force-auto on unit toggle, legacy preset compat): Waves 3, 4, 5, 6.
- Conflict resolutions confirmed in chat (spin_mo retained, freq controls migrated, TimeContextual untouched, spin_db_ref + combo_cmap retained): explicit in Wave 3-4 file-edit instructions.

**Placeholder scan**: No "TBD" / "implement later" / vague "handle edge cases" left. Every step has either exact code or exact grep/test commands. The only soft spot is the helper extraction in 4.3 ((a) module-level vs (b) duplicate) — left as engineer judgment, both options stated. Acceptable per "Smaller, focused files" guidance; specialist will pick (a) per DRY.

**Type consistency**: Field names `(x_auto, x_min, x_max, y_auto, y_min, y_max, z_auto, z_floor, z_ceiling, amplitude_mode)` used identically across Waves 3, 4, 5, 6. `combo_amp_unit` named consistently. Helpers `_make_axis_settings_group`, `_build_axis_row`, `_sync_axis_enabled`, `_on_amp_unit_changed`, `_on_max_order_changed` named consistently.

**Open question (defer to specialist judgment, not blocker)**: In Wave 4, FFT 1D vs FFT-vs-Time view both share `combo_amp_unit`. The plan ships one shared dropdown placed visually on the Z row. If the specialist finds during implementation that 1D-only sessions never invoke the Z code path and the Y-row dropdown placement causes test ergonomic issues, they may move the dropdown to the Y row in FFT view (mirror diff in `_make_axis_settings_group`). Document in commit if changed.
