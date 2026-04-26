# FFT vs Time 2D — Module A (Signal Layer) Review

**Date:** 2026-04-25
**Reviewer:** Claude (Opus 4.7) — replacement for unavailable codex route
**Subject:** T1 signal-processing-expert deliverable
**Specialist report:** `docs/superpowers/reports/2026-04-25-fft-vs-time-T1-signal-layer.md`
**Reference plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`
**Reference design:** `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`

## Verdict

**approve** — proceed to T2 (mode plumbing). All twelve verification points pass; no blockers, no important issues. Three minor nits worth filing as cleanup-when-touched but none of them block downstream work.

## Blockers

(none)

## Important

(none)

## Nits

1. **`one_sided_amplitude` `amp.size == 2` branch is mathematically wrong for odd `nfft == 3`** — `mf4_analyzer/signal/fft.py:131-134`. The branch is a `pass` (no doubling). For even `nfft == 2`, both bins (DC, Nyquist) are non-interior so `pass` is correct. For odd `nfft == 3`, the second bin sits at `fs/3` and IS interior, so it should be doubled. The report acknowledges the branch is "unreachable from the current callers" (`nfft <= 1` is rejected upstream and `compute_fft` callers all use `n >= 2048`), so this is dead-code hygiene, not a real bug. Either drop the branch entirely (the `if amp.size > 2` path would then no-op on size-2 arrays anyway because `amp[1:-1]` is empty for size 2) or document the odd-3 caveat in the comment. **Severity: low** — unreachable.

2. **Cancel-token poll happens after the amplitude matrix is allocated** — `mf4_analyzer/signal/spectrogram.py:259-266`. The `np.empty((freq_bins, total), dtype=np.float32)` allocation at line 259 runs before the first `cancel_token()` poll at line 266. For the maximum 64 MB allocation, this is a one-shot 64 MB malloc that cannot be aborted. Worth one extra poll before allocation if cancel responsiveness becomes a UX concern in T6/T7; not a problem now. **Severity: low** — within the memory ceiling so allocation is bounded.

3. **`progress_step` calculation uses integer division on small `total`** — `mf4_analyzer/signal/spectrogram.py:264`. `progress_step = max(1, total // 50)` means for `total <= 50` the callback fires every frame (verified empirically: 9 calls on a 9-frame run). The intent ("~50 emissions per run, regardless of total") is achieved on large runs but slightly over-emits on small ones. Acceptable since small runs don't saturate the Qt queue, but worth a comment. **Severity: low** — not a correctness concern.

## Spec-compliance scorecard

| # | Verification point | Status | Note |
|---|---|---|---|
| 1 | DC / Nyquist correctness (interior-only doubling) | **PASS** | `fft.py:123-130` correctly doubles `amp[1:-1]` for even nfft and `amp[1:]` for odd nfft. Empirically: DC=5.0 (not 10.0) for a const-5 signal; Nyquist bin not doubled for even nfft=1024; last bin doubled for odd nfft=1023. No direct unit test of `amp[0]`/`amp[-1]` (existing tests pick interior bins) — minor coverage gap acknowledged in the report and the design's §C5 commentary. |
| 2 | Window helper routes through scipy + alias map + kaiser tuple | **PASS** | `fft.py:32-72` uses `scipy.signal.get_window(spec, n, fftbins=False)`. Alias map `{'hann': 'hanning'}` at line 32-34, then `'hanning' -> 'hann'` to scipy at line 67-69 (correct — scipy spells it `hann`). Kaiser `('kaiser', 14)` tuple at line 65-66. `compute_averaged_fft` migrated to call `get_analysis_window` at `fft.py:192`. |
| 3 | Dataclass shape matches design §4.1 | **PASS** | `SpectrogramParams` is `frozen=True` (line 44), has fs/nfft/window/overlap/remove_mean/db_reference, no `amplitude_mode`, no `time_jitter_tolerance`. `SpectrogramResult` has times/frequencies/amplitude/params/channel_name/unit/metadata, no `amplitude_db`. Defaults match design (`window='hanning'`, `overlap=0.5`, `remove_mean=True`, `db_reference=1.0`). |
| 4 | Validation surface in `compute()` | **PASS** | All required raises confirmed empirically: `fs<=0` (`spectrogram.py:223`), `nfft<=1` (line 226), `overlap not in [0,1)` (line 228), 1-D check (line 232), length mismatch (line 235), shorter than nfft (line 237), strictly-increasing (line 143-150), jitter > tol (line 151-156), oversized memory (line 250-257), `hop <= 0` (line 241), zero frames (line 245). One nit: "zero complete frames" path is technically unreachable — the earlier `sig.size < nfft` rejection covers every input that would yield zero frames. Defensive raise is fine to keep. |
| 5 | Memory ceiling 64 MB float32, pre-flight, MB string | **PASS** | `_MAX_AMPLITUDE_BYTES = 64 * 1024 * 1024` at `spectrogram.py:41` (named constant — passes the brief's explicit ask). Check at lines 248-257 happens BEFORE `np.empty` allocation. Error string includes bin count, frame count, MB, and ceiling MB. Empirical: oversize request raised "memory ceiling exceeded: 4097 bins x 61628 frames ~= 963.2 MB (ceiling 64 MB). Reduce nfft, overlap, or selected time range." Test `test_memory_ceiling_blocks_oversized_request` covers it. |
| 6 | Progress + cancel | **PASS** | Throttle at `spectrogram.py:264` produces 51 emissions for a 1561-frame run (verified). Final emission at i+1 == total guaranteed by the OR-clause. Cancel polled at line 266, BEFORE the FFT for that frame at line 269. Raises `RuntimeError('spectrogram computation cancelled')` matching the brief. See nit 2 for the one allocation-vs-poll nit. |
| 7a | Two-tone test validates real tones (not tautological) | **PASS** | `tests/test_spectrogram.py:38-65`. Verified empirically: without the 4-bin guard, the second-largest raw bin is at 63 Hz (0.5007) — sidelobe of the 64 Hz tone, virtually equal to the genuine 192 Hz peak (0.5000). With the 4-bin guard, the second peak correctly resolves to 192 Hz. The deviation from the plan's `np.argsort(amp)[-2:]` is a real bug fix, not a weakening — captured in the report's Key Decisions. |
| 7b | Non-monotonic surfaces under "non-uniform" message family | **PASS** | `_validate_time_axis` raises `non-uniform time axis: time samples must be strictly increasing` (line 147-150) for non-monotonic and `non-uniform time axis: relative_jitter=...` (line 153-156) for jitter. One consistent prefix lets the UI use one prompt. Verified empirically. |
| 8 | No GUI / Qt / matplotlib import in `signal/*` | **PASS** | `tests/test_signal_no_gui_import.py` extended (line 60-68) to also import `mf4_analyzer.signal.spectrogram` and probe for `SpectrogramAnalyzer.compute` / `.amplitude_to_db`. Test passes (1 passed). |
| 9 | No regression in existing FFT amplitude tests | **PASS** | `pytest tests/test_fft_amplitude_normalization.py -v` exit code 0, **6 passed**. Full test suite `pytest tests/ --ignore=tests/ui -q` exit code 0, **16 passed in 0.90s**. |
| 10 | Cache-consumer documentation | **PASS** | Specialist report §"Notes for downstream specialists" (lines 178-185) explicitly directs T4 to grep for `np.log10` / `20 *` in the canvas refresh path and route through `amplitude_to_db`. The analyzer module's docstring at `spectrogram.py:21-27` explicitly states "The dB matrix is NOT cached on the result. The canvas computes it lazily ... Adding caching here would duplicate state." `SpectrogramResult` carries no `amplitude_db` field. |
| 11 | Stylistic / code quality | **PASS** | Type hints on public surfaces (`compute`, `amplitude_to_db`, `_validate_time_axis`). Docstrings on every public symbol with Parameters/Returns/Raises sections. `_MAX_AMPLITUDE_BYTES` is a named module constant (line 41, passes the brief's explicit "should be a named constant" check). Default arguments are defensive (`max_amplitude_bytes` defaults to `_MAX_AMPLITUDE_BYTES`, allowing T6 override per the report's note). No dead code that affects behavior; no unused imports. |
| 12 | Test quality | **PASS** | Each test in `test_spectrogram.py` has a single assertion target. The burst-localization test (lines 67-88) does carry the threshold-rationale comment that the plan called out: "threshold at 25% of peak energy is a robust separator between 'frame fully inside burst', 'frame straddling boundary', and 'frame entirely outside burst'." Two-tone test rationale (lines 39-45) explains why the 4-bin guard exists, including the Hann sidelobe leakage math. Window-preset test rationale (lines 122-124) explains why both Hann and Flat Top are locked. |

## Test execution evidence

```text
$ .venv/bin/python -m pytest tests/test_fft_amplitude_normalization.py -v
6 passed in 0.60s
EXIT: 0

$ .venv/bin/python -m pytest tests/test_signal_no_gui_import.py tests/test_spectrogram.py -v
10 passed in 0.90s
EXIT: 0

$ .venv/bin/python -m pytest tests/ --ignore=tests/ui -q
16 passed in 0.90s
EXIT: 0
```

All three test invocations from the specialist's `tests_run` field reproduce green, matching the report's claim of "0 failing in scope".

## Probe-level evidence (DC/Nyquist correctness)

```text
even nfft=1024, DC bin amp[0]:        5.0    (correct: NOT doubled — was 10.0 under legacy)
even nfft=1024, Nyquist bin amp[-1]:  1.0    (correct: NOT doubled)
odd  nfft=1023, last bin (interior):  3.7518 ≈ 3.7518  (correct: doubled, matches amp[k=511])
```

Confirms `fft.py:123-130` is correctly distinguishing the even-nfft Nyquist case from the odd-nfft last-interior-bin case.

## Recommendation for main Claude

**Approve as-is and proceed to T2.** The signal layer is clean, the public surface matches the revised design §4.1 exactly, and all the rework concerns from plan v1 (DC/Nyquist scaling, dB-cache ownership boundary, time-jitter as a kwarg, named memory constant, per-frame cancel poll, throttled progress) are honored.

The three nits are hygiene-class and can be addressed when those lines are next touched (probably never for nit 1 since the branch is unreachable; possibly during T6 worker integration for nit 2 if cancel responsiveness becomes a UX concern).

Do **not** re-dispatch the signal-processing-expert. The report's two flagged-decisions (two-tone guard band and non-monotonic message family) are correctly handled and improve on the plan-as-written rather than weakening it.

Downstream specialists should:

- **T4 (canvas):** grep the canvas refresh path for `np.log10` / `20 *` and route through `SpectrogramAnalyzer.amplitude_to_db`. Memoize keyed by `(id(result), db_reference)` per the consumer-side discipline lesson.
- **T6 (worker):** bridge `progress_callback` and `cancel_token` to Qt signals in the worker wrapper, NOT inside the analyzer. The analyzer's `RuntimeError('spectrogram computation cancelled')` is the contract the worker should catch and translate to a Qt status update.
- **T6 (worker):** the `max_amplitude_bytes` kwarg lets a "force compute" path raise the ceiling if the user explicitly opts in. Default 64 MB stays the bound for the normal path.

## Files reviewed (absolute paths)

- `/Users/donghang/Downloads/data analyzer/requirements.txt`
- `/Users/donghang/Downloads/data analyzer/mf4_analyzer/signal/fft.py`
- `/Users/donghang/Downloads/data analyzer/mf4_analyzer/signal/spectrogram.py`
- `/Users/donghang/Downloads/data analyzer/mf4_analyzer/signal/__init__.py`
- `/Users/donghang/Downloads/data analyzer/tests/test_spectrogram.py`
- `/Users/donghang/Downloads/data analyzer/tests/test_signal_no_gui_import.py`
- `/Users/donghang/Downloads/data analyzer/tests/test_fft_amplitude_normalization.py` (regression baseline)
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T1-signal-layer.md`
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`
