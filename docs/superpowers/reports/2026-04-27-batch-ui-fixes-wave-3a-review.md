# Wave 3a review — `batch.py` fft_time backend

**Plan:** `docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md` (rev 2), Phase 5 — Tasks 7 + 8.
**Commits under review:**
- `0a82f85` feat(batch): add fft_time method dispatch + long-format dataframe (#issue-3)
- `c773342` feat(batch): fft_time PNG render in dB + per-item failure isolation for ceiling

**Reviewer:** Senior Code Reviewer (codex rate-limited fallback).

## Verdict

**approved** — squad may advance to Wave 3b.

Implementation tracks the rev-2 plan exactly; no spurious changes; full
suite green at 354/354. No findings rise to "needs revision" or even
"minor revisions".

## Verification

- **Files-touched scope (W3a only):** PASS
  - `git diff 971a7b1..c773342 --stat` reports exactly two files:
    `mf4_analyzer/batch.py (+59/-6)` and
    `tests/test_batch_runner.py (+91/-1)`.
  - No `mf4_analyzer/ui/...` touched. `method_buttons.py`, `sheet.py`,
    `input_panel.py`, `signal_picker.py` all untouched. Wave-3b
    territory is clean.

- **`SUPPORTED_METHODS` extension (Step 7.3):** PASS
  - `mf4_analyzer/batch.py:157` =
    `{'fft', 'order_time', 'order_track', 'fft_time'}` (4 entries).
  - Pinned by `test_supported_methods_excludes_removed_order_rpm` and
    `test_fft_time_method_supported`.

- **`_run_one` dispatch ordering — fft_time skips RPM (Step 7.3):** PASS
  - `mf4_analyzer/batch.py:400-420`: `if method == 'fft':` →
    `elif method == 'fft_time':` → `else: rpm = self._rpm_values(...)`.
  - The new branch reuses `_apply_time_range(... rpm=None)` and never
    calls `_rpm_values`, so a fft_time preset without an RPM channel
    will not raise `"rpm channel is required"`. This matches the UI
    contract that hides the RPM row for fft_time.

- **`_compute_fft_time_dataframe` returns single dataframe (rev-1 fix #3):** PASS
  - `mf4_analyzer/batch.py:497-527`. Single `pd.DataFrame` return via
    `_matrix_to_long_dataframe`; no tuple. Docstring documents the
    transpose rationale.
  - Calls `SpectrogramAnalyzer.compute` with kwargs
    `signal=, time=, params=, channel_name=` — verified against
    `mf4_analyzer/signal/spectrogram.py:171-181` (positional or kwargs
    OK). Result fields used (`result.times`, `result.frequencies`,
    `result.amplitude`) match `SpectrogramResult` (lines 73-100).
  - `result.amplitude` shape `(freq_bins, frames)` (line 270 in
    spectrogram.py) → `.T` yields `(frames, freq_bins)` →
    `(len(times), len(frequencies))`, satisfying
    `_matrix_to_long_dataframe`'s
    `matrix.shape == (len(x_values), len(y_values))` precondition with
    `x=times, y=frequencies`. Math is right.

- **Long-format columns (Step 7.1 acceptance):** PASS
  - Output columns `['time_s', 'frequency_hz', 'amplitude']` — pinned
    by `test_fft_time_exports_long_format_dataframe` which also asserts
    `frequency_hz.nunique() == 256//2 + 1` (one-sided bin count) and
    `time_s.nunique() > 1` (real time axis, not collapsed).

- **dB rendering for fft_time only (Step 8.4):** PASS
  - `mf4_analyzer/batch.py:589-615`. `if kind == 'fft_time':` block
    converts via `20.0 * np.log10(np.maximum(matrix, eps))` with
    `eps = np.finfo(float).tiny`. Cmap `'turbo'`. Colorbar label
    `'Amplitude (dB)'`. Mirrors
    `SpectrogramAnalyzer.amplitude_to_db`'s floor strategy — no
    `log(0)` warnings.
  - `else:` branch keeps `cbar_label = 'Amplitude'` and feeds raw
    linear matrix to `imshow`, exactly as before.

- **`order_time` (linear) branch unchanged:** PASS
  - Diff `0a82f85..c773342` shows `_write_image` only added the
    `if kind == 'fft_time'` conditional inside the existing matrix-pivot
    `else:` branch and reformatted the `pivot(...)` call across 3
    lines. The `imshow(..., aspect='auto', origin='lower', extent=[...],
    interpolation='bilinear', cmap='turbo')` call is identical
    (the only edit is `pivot.to_numpy()` → `matrix`, where `matrix` is
    `pivot.to_numpy()` for non-fft_time). No semantic change for
    `order_time`. The shared `cmap='turbo'` was already there
    pre-W3a, so the order_time visual is bit-identical.

- **CSV/HDF5 export stays linear (rev-1 fix #?):** PASS
  - Long-format dataframe is built before `_write_image`; the dB
    conversion only mutates the local `matrix` variable. The dataframe
    written to disk is the linear one. Docstring of
    `_compute_fft_time_dataframe` calls this out explicitly:
    *"the exported dataframe stays in linear amplitude — the dB
    conversion is a display-only choice in `_write_image`"*. Good.

- **Step 8.2 regression-guard test (no red→green):** PASS
  - `test_fft_time_amplitude_ceiling_emits_failed_item` exists at
    `tests/test_batch_runner.py:503-527` and passes on the strength of
    Step 7.3 alone. Monkeypatches `SpectrogramAnalyzer.compute` to
    raise `ValueError("...64 MB...")`; existing handler at
    `batch.py:227-260` converts to `BatchItemResult(status='blocked')`
    with the original message threaded into `result.blocked`. Status
    asserted to be in `{"partial", "blocked"}` — covers the
    1-task-1-failure case where current code returns `"blocked"`.

- **No new try/except in `BatchRunner.run`:** PASS
  - `git show 971a7b1:mf4_analyzer/batch.py` lines 225-260 (pre-wave)
    are byte-identical to the post-wave handler (verified via
    `git diff 971a7b1..c773342 -- mf4_analyzer/batch.py | grep -E "^(\+|\-).*(try|except|raise)"`
    returning empty). The plan's "do not add a redundant handler"
    instruction (Step 8.3) was honored.

- **Test counts:** PASS
  - `.venv/bin/python -m pytest tests/test_batch_runner.py -v` →
    25/25 passed. Includes the four W3a additions
    (`test_fft_time_method_supported`,
    `test_fft_time_exports_long_format_dataframe`,
    `test_fft_time_exports_image`,
    `test_fft_time_amplitude_ceiling_emits_failed_item`) and the
    amended `test_supported_methods_excludes_removed_order_rpm`.
  - `.venv/bin/python -m pytest tests/ -q` → **354 passed in 10.70s**.
    Engineer's report of full-suite green confirmed.

## Findings

None above the bar. A couple of below-the-bar observations:

1. **`import numpy as np` already at module top.** The plan's Step 8.4
   snippet showed an `import numpy as np` line inside `_write_image`,
   which would have been an inline import. The implementer correctly
   noticed `numpy` is already imported at `batch.py:19` and skipped
   the redundant inline import. Good adherence to project style
   ("no inline imports") even though the plan snippet itself drifted.

2. **`from .signal.spectrogram import ...` inside
   `_compute_fft_time_dataframe`.** This is an inline import inside a
   method body — technically the project convention is module-top
   imports. The pattern matches what `OrderAnalyzer` does in
   `_compute_order_*_dataframe` (also imports at top via
   `from .signal.order import ...`), but here spectrogram is lazy-loaded.
   Could be promoted to a top-level import for consistency, but the
   lazy import is defensible: `SpectrogramAnalyzer.compute` pulls in
   `scipy.signal` transitively, and lazy-loading keeps batch-only
   `fft`/`order_*` imports light. **Not a blocker.**

3. **Numerical safety of `eps = np.finfo(float).tiny`.** `tiny` for
   `float64` is `~2.225e-308`; `20*log10(2.225e-308) ≈ -6155 dB`. In
   practice the SpectrogramAnalyzer amplitude is `float32`, where the
   smallest normal is `~1.175e-38`. Mixing the `float64` `tiny` with a
   `float32` matrix is fine because `np.maximum` upcasts, but for a
   pure-`float32` floor `np.finfo(np.float32).tiny ≈ 1.175e-38` →
   `~-760 dB` would still safely avoid `-inf`. Both choices keep
   `log(0)` from appearing. The plan explicitly specifies
   `np.finfo(float).tiny` and the implementation matches; the dB
   floor's exact value is not load-bearing because the dynamic-range
   slider in the canvas (out-of-scope here) clips the displayed range
   anyway. No change needed.

## Recommendations (non-blocking)

- Consider promoting the `from .signal.spectrogram import
  SpectrogramAnalyzer, SpectrogramParams` import to the top of
  `batch.py` (alongside the existing `from .signal.fft` /
  `from .signal.order` imports) when a future cleanup pass touches
  this module — purely a style alignment, no behavioral effect.
- The Step 8.4 plan snippet still shows `import numpy as np` inside
  `_write_image`. The implementation correctly omitted it, but a tiny
  rev-3 plan touch-up to remove that line would prevent confusion in
  future replays. (Cosmetic only, not blocking W3b.)
- For the W3b dispatch, the engineer should ensure
  `_METHOD_LABELS` in `sheet.py` gains an `fft_time` entry per rev-2
  fix #7, and that `method_buttons.py` adds `overlap` /
  `remove_mean` widgets so the `params` dict the InputPanel emits
  matches the keys `_compute_fft_time_dataframe` reads
  (`'overlap'`, `'remove_mean'`, `'nfft'`, `'window'`,
  `'db_reference'`). Wave 3a's dataframe path already has sensible
  defaults via `params.get(...)`, so missing widgets degrade
  gracefully rather than crashing.

## Files reviewed

- `/Users/donghang/Downloads/data analyzer/mf4_analyzer/batch.py`
- `/Users/donghang/Downloads/data analyzer/tests/test_batch_runner.py`
- `/Users/donghang/Downloads/data analyzer/mf4_analyzer/signal/spectrogram.py` (read-only, contract verification)
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md` (Phase 5, Rev 2 corrections)
