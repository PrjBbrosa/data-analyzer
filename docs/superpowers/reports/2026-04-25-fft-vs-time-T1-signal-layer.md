# FFT vs Time 2D — Tasks 1 & 2 (Signal Layer) Report

**Date:** 2026-04-25
**Specialist:** signal-processing-expert
**Scope:** plan tasks 1 (`scipy` + shared FFT helpers) and 2
(`SpectrogramAnalyzer` with TDD). Strict signal-layer only — no UI
edits, no `OrderAnalyzer` refactor, no `channel_math` touches.

## Summary

Added `scipy>=1.10` as a load-bearing dependency, rewrote
`mf4_analyzer/signal/fft.py` so window construction and one-sided
amplitude normalization live in two module-level helpers
(`get_analysis_window`, `one_sided_amplitude`) shared by `FFTAnalyzer`
and the new `SpectrogramAnalyzer`. Created
`mf4_analyzer/signal/spectrogram.py` with `SpectrogramParams`,
`SpectrogramResult`, and `SpectrogramAnalyzer` (compute + amplitude_to_db).
TDD: wrote the nine-test suite first, watched it fail with
`ModuleNotFoundError`, then implemented to green.

The DC/Nyquist amplitude correction (interior-only doubling) is in
place; the audit recorded below confirms the existing FFT amplitude
test suite does not exercise `amp[0]` / `amp[-1]` and so is unaffected.

## DC / Nyquist audit (Task 1 Step 1)

Command:

```bash
grep -n "compute_fft\|amp\[0\]\|amp\[-1\]\|nyquist" \
    tests/test_fft_amplitude_normalization.py \
    tests/test_signal_no_gui_import.py
```

Result: 7 hits across the two files; all `compute_fft` mentions are
either docstrings or `f, amp = FFTAnalyzer.compute_fft(...)` calls
followed by `np.argmax(amp)`. Bin selection in
`test_fft_amplitude_normalization.py`:

| Test | n | nfft | k | bin freq | DC bin | Nyquist bin |
|---|---|---|---|---|---|---|
| `_assert_peak_matches` | 4096 | 4096 | 200 | ~48.83 Hz | 0 | 2048 |
| `test_dc_offset_is_removed_and_does_not_bias_peak` | 4096 | 4096 | 200 | ~48.83 Hz | 0 | 2048 |
| `test_zero_padding_does_not_change_peak_amplitude` | 2048 | 8192 | 100 | ~48.83 Hz | 0 | 4096 |

Zero matches for `amp[0]`, `amp[-1]`, or `nyquist`. The corrected
single-sided amplitude (DC and Nyquist undoubled, interior bins
doubled) leaves every existing assertion unchanged at the chosen
peak bins. After the rewrite, all six FFT amplitude tests still pass.

## Files changed

- `requirements.txt` — added `scipy>=1.10`.
- `mf4_analyzer/signal/fft.py` — rewrote: added module-level
  `get_analysis_window`, `one_sided_amplitude`; rewrote
  `FFTAnalyzer.get_window` and `FFTAnalyzer.compute_fft` as thin
  delegators; updated `compute_averaged_fft` to call
  `get_analysis_window` instead of building its own window.
- `mf4_analyzer/signal/spectrogram.py` — new file. `SpectrogramParams`
  (frozen dataclass, no display fields), `SpectrogramResult`
  (linear amplitude only, no cached dB), `SpectrogramAnalyzer.compute`
  (uniform-time validation, hop, frame center times, 64 MB float32
  ceiling, throttled progress callback, cancel token) and
  `SpectrogramAnalyzer.amplitude_to_db` (consumed by the canvas-side
  dB cache landing in Task 4 — see lesson
  `signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface`).
- `mf4_analyzer/signal/__init__.py` — exports `SpectrogramAnalyzer`,
  `SpectrogramParams`, `SpectrogramResult` alongside existing names.
- `tests/test_spectrogram.py` — new file, nine tests covering bin-aligned
  amplitude, two-tone resolution, burst time localization, dB
  conversion, frame center times, signal-shorter-than-nfft rejection,
  non-uniform time axis rejection, Hann/FlatTop window preset lock,
  64 MB memory-ceiling rejection.
- `tests/test_signal_no_gui_import.py` — extended the child-process
  guard to also import `mf4_analyzer.signal.spectrogram` and probe
  for `SpectrogramAnalyzer.compute` / `.amplitude_to_db`.

## Files moved

(none — boundary-discipline: no cross-module moves)

## Symbols touched

- `mf4_analyzer/signal/fft.py::get_analysis_window` (new, module-level)
- `mf4_analyzer/signal/fft.py::one_sided_amplitude` (new, module-level)
- `mf4_analyzer/signal/fft.py::_WINDOW_ALIASES` (new, module-level constant)
- `mf4_analyzer/signal/fft.py::FFTAnalyzer.get_window` (rewritten — delegates)
- `mf4_analyzer/signal/fft.py::FFTAnalyzer.compute_fft` (rewritten — delegates)
- `mf4_analyzer/signal/fft.py::FFTAnalyzer.compute_psd` (unchanged behaviour, kept for compatibility)
- `mf4_analyzer/signal/fft.py::FFTAnalyzer.compute_averaged_fft` (window helper rerouted)
- `mf4_analyzer/signal/spectrogram.py::SpectrogramParams` (new)
- `mf4_analyzer/signal/spectrogram.py::SpectrogramResult` (new)
- `mf4_analyzer/signal/spectrogram.py::SpectrogramAnalyzer.amplitude_to_db` (new)
- `mf4_analyzer/signal/spectrogram.py::SpectrogramAnalyzer._validate_time_axis` (new)
- `mf4_analyzer/signal/spectrogram.py::SpectrogramAnalyzer.compute` (new)
- `mf4_analyzer/signal/spectrogram.py::_MAX_AMPLITUDE_BYTES` (new, module-level constant)
- `mf4_analyzer/signal/__init__.py::__all__` (extended)

## Forbidden-symbol check

verified — `grep -nE "PyQt5|matplotlib|QWidget|QDialog|QMainWindow|FigureCanvas"`
of `mf4_analyzer/signal/fft.py`, `mf4_analyzer/signal/spectrogram.py`,
and `mf4_analyzer/signal/__init__.py` returns 0 hits. No file under
`mf4_analyzer/ui/*` was edited or referenced. `grep -lE
"spectrogram|SpectrogramAnalyzer|SpectrogramParams|SpectrogramResult"`
across `mf4_analyzer/ui/` returns no files (Task 3 work, deferred to
`pyqt-ui-engineer`).

## Tests run

| Invocation | Before | After |
|---|---|---|
| `pytest tests/test_fft_amplitude_normalization.py -v` | 6 passed | 6 passed |
| `pytest tests/test_signal_no_gui_import.py -v` | 1 passed | 1 passed |
| `pytest tests/test_spectrogram.py -v` | collection error (`ModuleNotFoundError: mf4_analyzer.signal.spectrogram`) | 9 passed |
| `pytest tests/ --ignore=tests/ui -q` | n/a | 16 passed |

`tests_before` failing in scope: 9 (all `tests/test_spectrogram.py`
tests, blocked by missing module).
`tests_after` failing in scope: 0.

## Key decisions

- **Kept `FFTAnalyzer.compute_fft`'s historical contract of returning
  `nfft//2` bins** so `tests/test_fft_amplitude_normalization.py` (which
  asserts peak bin index against the old half-spectrum) passes
  unchanged. Internally `compute_fft` now goes through
  `one_sided_amplitude` (which produces `nfft//2 + 1` bins via
  `np.fft.rfft`) and slices to the historical length. The slice drops
  the Nyquist sample for even `nfft`, so the new DC/Nyquist scaling
  is invisible to the existing tests.
- **`time_jitter_tolerance` is a `compute()` kwarg, not a `SpectrogramParams`
  field.** Per design spec §4.1 — keeping it off the cache key means
  UI-only display tweaks never invalidate the cache.
- **Did not cache the dB matrix on `SpectrogramResult`.** Per design
  spec §4.1 and lesson
  `signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface`
  the canvas in Task 4 will own the dB cache keyed on
  `(id(result), db_reference)`. Caching here would duplicate state.
- **Two-tone test rephrased to use guard-band peak selection.** The
  plan's `np.argsort(amp)[-2:]` two-tone test is mathematically
  unsatisfiable with a 1.0 / 0.5 amplitude ratio under a Hann window:
  Hann's first sidelobe at the dominant tone leaks ~0.5 into adjacent
  bins, exactly the second tone's peak amplitude, so the second-largest
  raw bin is the bin next to the dominant tone, not the genuine second
  tone. The fix: pick the dominant peak, mask a +/- 4-bin guard around
  it, then pick the second peak. This preserves the test's intent
  (resolving 64 Hz and 192 Hz) without changing the algorithm. Recorded
  here as a deviation from the plan-as-written; not material to Tasks
  3-9 since the algorithmic property under test (two-tone resolution)
  is identical.
- **Non-monotonic time axis surfaces under "non-uniform time axis".**
  The plan's `test_rejects_nonuniform_time_axis` test mutates `t[1000]`
  to be earlier than `t[999]`, which is non-monotonic rather than
  jittered. The validator's "strictly increasing" branch was therefore
  reworded to start with `non-uniform time axis: ...` so both cases
  surface under one banner — matches the design spec §10 row "Non-uniform
  time axis: Require rebuild/resample before analysis".
- **`one_sided_amplitude`'s `n == 2` branch documented but unreachable
  from the current callers.** `nfft <= 1` is rejected upstream in
  `SpectrogramAnalyzer.compute`, and `compute_fft` has no minimum
  guard but the existing tests use `n >= 2048`. Leaving the
  `amp.size == 2` branch as a documented no-op rather than raising
  preserves call-site flexibility.

## Flagged issues

(none — all rework / boundary concerns are downstream of this subtask)

## Lessons added / merged

(none — the consumer-side cache discipline lesson at
`docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`
already covers the canvas-dB-cache pattern; nothing genuinely new came
out of Tasks 1 & 2 worth a fresh lesson)

## Notes for downstream specialists (Tasks 3-9)

- `SpectrogramAnalyzer.amplitude_to_db(linear, reference)` is the
  canvas-side dB conversion entry point. Task 4's
  `SpectrogramCanvas._db_cache` should grep for direct calls to
  `np.log10` or `20 *` in the canvas refresh path and route them
  through this helper instead, matching the consumer-side discipline
  in lesson
  `signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface`.
- `SpectrogramAnalyzer.compute` accepts `progress_callback(i, total)`
  and `cancel_token() -> bool` kwargs. Both are throttled / polled
  per-frame with no Qt dependency. Worker plumbing in Task 7 should
  bridge these to Qt signals; do not add Qt imports inside the
  analyzer.
- The 64 MB ceiling is configurable via the `max_amplitude_bytes`
  kwarg if Task 6 needs a different ceiling for a "force compute"
  path; the constant `_MAX_AMPLITUDE_BYTES` is the default.

## Return JSON (mirrors the contract requested in the brief)

```json
{
  "status": "ok",
  "files_changed": [
    "requirements.txt",
    "mf4_analyzer/signal/fft.py",
    "mf4_analyzer/signal/spectrogram.py",
    "mf4_analyzer/signal/__init__.py",
    "tests/test_spectrogram.py",
    "tests/test_signal_no_gui_import.py"
  ],
  "files_moved": [],
  "symbols_touched": [
    "mf4_analyzer/signal/fft.py::get_analysis_window",
    "mf4_analyzer/signal/fft.py::one_sided_amplitude",
    "mf4_analyzer/signal/fft.py::_WINDOW_ALIASES",
    "mf4_analyzer/signal/fft.py::FFTAnalyzer.get_window",
    "mf4_analyzer/signal/fft.py::FFTAnalyzer.compute_fft",
    "mf4_analyzer/signal/fft.py::FFTAnalyzer.compute_averaged_fft",
    "mf4_analyzer/signal/spectrogram.py::SpectrogramParams",
    "mf4_analyzer/signal/spectrogram.py::SpectrogramResult",
    "mf4_analyzer/signal/spectrogram.py::SpectrogramAnalyzer.amplitude_to_db",
    "mf4_analyzer/signal/spectrogram.py::SpectrogramAnalyzer._validate_time_axis",
    "mf4_analyzer/signal/spectrogram.py::SpectrogramAnalyzer.compute",
    "mf4_analyzer/signal/spectrogram.py::_MAX_AMPLITUDE_BYTES",
    "mf4_analyzer/signal/__init__.py::__all__"
  ],
  "forbidden_symbols_check": "verified — grep of mf4_analyzer/ui/* in diff returns 0 hits; signal-layer files have 0 PyQt5/matplotlib/QWidget/FigureCanvas hits",
  "tests_run": [
    "pytest tests/test_fft_amplitude_normalization.py -v",
    "pytest tests/test_signal_no_gui_import.py -v",
    "pytest tests/test_spectrogram.py -v",
    "pytest tests/ --ignore=tests/ui -q"
  ],
  "tests_before": "9 failing in scope (tests/test_spectrogram.py, ModuleNotFoundError)",
  "tests_after": "0 failing in scope (16 passing across signal-layer tests)",
  "key_decisions": [
    "kept compute_fft historical contract returning nfft//2 bins so existing test_fft_amplitude_normalization.py passes unchanged",
    "time_jitter_tolerance is a compute() kwarg, not a SpectrogramParams field, to keep cache key stable across UI-only display changes",
    "did not cache dB matrix on SpectrogramResult — canvas-side cache (Task 4) will own it per consumer-side discipline lesson",
    "two-tone test uses guard-band peak selection to handle Hann sidelobe leakage at 1.0/0.5 amplitude ratio (intent unchanged)",
    "non-monotonic time axis surfaces under 'non-uniform time axis' message family"
  ],
  "flagged_issues": [],
  "report_path": "docs/superpowers/reports/2026-04-25-fft-vs-time-T1-signal-layer.md"
}
```
