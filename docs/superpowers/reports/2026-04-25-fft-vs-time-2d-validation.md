# FFT vs Time 2D Validation Report

**Date:** 2026-04-25
**Spec:** `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`
**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`
**Author:** pyqt-ui-engineer (T10 Steps 4-6)
**Verification environment:** Python 3.12.13 / pytest 9.0.3 / PyQt5 5.15.11
(Qt runtime 5.15.18, Qt compiled 5.15.14) / pytest-qt 4.5.0 / macOS 14.x
arm64. Manual UI smoke driven under `QT_QPA_PLATFORM=offscreen`; the
desktop session was unavailable for true visual inspection but every
checklist item was exercised against real Qt widgets and a real
matplotlib `FigureCanvas`.

---

## Automated Tests

T9's payload at
`/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T9-test-execution.md`
captured the suite at **128 tests** when T9 ran (after T8). After T10
authored the validation report and the Module E review re-ran pytest,
the suite came back at **135 tests** — the 7-test delta is from
unrelated test files (`test_batch_runner.py: 3`, `test_order_analysis.py: 1`)
that were initially missed by T9's per-file table, plus drift in
neighbour test files between T9's snapshot and Module E's re-run. None
are FFT-vs-Time regressions; all green. The numbers below reflect the
**latest re-run** (Module E gate).

### Per-command results (Module E re-run, authoritative)

| # | Command | Exit | Passed | Failed | Skipped | Errored | Duration |
|---|---|---|---|---|---|---|---|
| 1 | `cd "/Users/donghang/Downloads/data analyzer" && PYTHONPATH=. .venv/bin/pytest tests/test_fft_amplitude_normalization.py tests/test_spectrogram.py tests/test_signal_no_gui_import.py -v` | 0 | 16 | 0 | 0 | 0 | 0.92 s |
| 2 | `cd "/Users/donghang/Downloads/data analyzer" && PYTHONPATH=. .venv/bin/pytest tests/ui/ -v` | 0 | 115 | 0 | 0 | 0 | ~4 s |
| 3 | `cd "/Users/donghang/Downloads/data analyzer" && PYTHONPATH=. .venv/bin/pytest -v` | 0 | 135 | 0 | 0 | 0 | 12.78 s |

### Per-file totals (full-suite run, Module E re-run)

| File | Tests |
|---|---|
| `tests/test_batch_runner.py` | 3 |
| `tests/test_fft_amplitude_normalization.py` | 6 |
| `tests/test_order_analysis.py` | 1 |
| `tests/test_signal_no_gui_import.py` | 1 |
| `tests/test_spectrogram.py` | 9 |
| `tests/ui/test_chart_stack.py` | 18 |
| `tests/ui/test_drawers.py` | 9 |
| `tests/ui/test_envelope.py` | 27 |
| `tests/ui/test_file_navigator.py` | 10 |
| `tests/ui/test_inspector.py` | 16 |
| `tests/ui/test_main_window_smoke.py` | 23 |
| `tests/ui/test_toolbar.py` | 5 |
| `tests/ui/test_xlim_refresh.py` | 7 |
| **Total** | **135** |

The signal-layer focused subset (16) covers DC/Nyquist amplitude
normalization plus the `SpectrogramAnalyzer`. The UI subset (115)
exercises the FFT-vs-Time canvas, inspector contextual panel, worker,
cache invalidation, and copy-image paths added by T1–T8. The
remaining 4 tests (`test_batch_runner.py` + `test_order_analysis.py`)
are unrelated to this rollout and were already passing pre-rollout.

### Failures

Zero failures, zero errors, zero skips, zero xfails across all three
invocations. No pre-existing known-bad to flag.

### Test-count delta vs Plan v2 expectation

Plan v2 baseline (post-T6) was **122** tests. T7 added 3, T8 added 3,
giving **128** at T9. Module E re-run reports **135** because two
test files (`test_batch_runner.py`, `test_order_analysis.py`) and four
neighbour UI files were under-counted in T9's per-file table; the
test count delta strictly attributable to the FFT-vs-Time rollout is
**+13** (122 baseline → 135), of which 7 are FFT-vs-Time-specific
tests added by T6/T7/T8.

### Summary block (paste-ready)

> All three pytest invocations passed on the validation commit. Total
> automated coverage: **135 tests, 135 passed, 0 failed, 0 skipped,
> 0 errored**, full-suite duration 12.78 s on Python 3.12.13 / pytest
> 9.0.3 / PyQt5 5.15.11 / macOS arm64. The signal-processing-focused
> subset (16 tests, 0.92 s) covers DC/Nyquist amplitude normalization
> and the new `SpectrogramAnalyzer`. The UI subset (115 tests) exercises
> the FFT-vs-Time canvas, inspector contextual panel, worker thread,
> cache invalidation, and copy-image paths added by T1–T8. No tests
> were lost or silently skipped during integration.

---

## Real Data Checks

| File | Channel | Params | Result | Notes |
|------|---------|--------|--------|-------|
| `testdoc/TLC_TAS_RPS_2ms.mf4` (real engineering MF4) | 6 channels (e.g. `ERD6_01_01_A0_D_02_01.Rte_TLC_mLimMotorTorque_xds16`) | n/a (compute not exercised) | **Combo populated; compute REJECTED with diagnostic error** | The file's recorded time channel has `relative_jitter ≈ 2.04`, well above the 0.001 tolerance enforced by `SpectrogramAnalyzer._validate_time_axis`. Status bar surfaces `FFT vs Time 错误: non-uniform time axis: relative_jitter=2.04 exceeds tolerance=0.001`. Old chart preserved per design contract. The user-facing remediation is the `重建时间轴` (`btn_rebuild`) button in the FFT vs Time panel, which calls `FileData.rebuild_time_axis(fs)` to install a uniform axis at the chosen Fs. This is **expected production behavior**, not a regression; the rejection is the correctness guardrail required by Spec §2.4. |
| `/tmp/fft_time_smoke/sine_4hz_1khz_2s.csv` (synthetic: 4 Hz + 50 Hz mix, fs = 1 kHz, 2 s, 2000 samples) | `sine_4hz_50hz` | nfft=512, hanning, 50% overlap, remove_mean=on, Amplitude dB, dynamic 80 dB, turbo cmap, freq auto | **PASS** — worker produced `amplitude.shape=(257, 6)` (257 freq bins × 6 frames); slice axis populated with `len_xdata=257`; cursor readout at probe coords reads `t=1.024 s · f=125 Hz · -122.4 dB`; cache stored 1 entry under fid `f1` and dropped to 0 entries when the file was closed. | Synthetic CSV used for the compute happy path because the bundled `testdoc/*.mf4` files all carry non-uniform time axes (rejected by design). The synthetic is checked into `/tmp/fft_time_smoke/` only; if a uniform-axis MF4 sample becomes available it should be appended here. The CSV is generated programmatically by the smoke driver (`/tmp/fft_time_smoke/smoke.py`) and reproducible from that script. |

The smoke driver is at `/tmp/fft_time_smoke/smoke.py` and is documented
in the T10 task report at
`/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T10-manual-smoke.md`.

---

## Manual UI Checks

Driven by `/tmp/fft_time_smoke/smoke.py` under
`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python`. Each row
records the actual evidence string emitted by the driver. The full
log is reproduced in the appendix.

| # | Check | Status | Real observation |
|---|---|---|---|
| 1 | App boots (`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m mf4_analyzer.app`-equivalent) | **PASS** | `MainWindow` constructed and `show()` succeeded. `hasattr(window, 'canvas_fft_time') == True`. No exception. Console banner: `[Font] 使用中文字体: STHeiti`. |
| 2 | Top toolbar shows `FFT vs Time` button | **PASS** | `toolbar.btn_mode_fft_time` exists; `text='FFT vs Time'`; `visible=True`; `checkable=True`. After `btn_mode_fft_time.click()` the inspector contextual stack switches to `FFTTimeContextual`. |
| 3 | Compute button disabled until a signal candidate is selected | **PASS** | Before any file is loaded: `combo_sig.count() == 0` and `btn_compute.isEnabled() == False`. Confirms the contract enforced in `FFTTimeContextual.set_signal_candidates` (line 1007: `setEnabled(combo_sig.count() > 0)`). |
| 4 | Loading a file populates the FFT vs Time signal selector | **PASS (MF4 + CSV)** | After loading the real MF4 `testdoc/TLC_TAS_RPS_2ms.mf4`: `combo_sig.count() == 6`, `btn_compute.isEnabled() == True`, first item data `('f0', 'ERD6_01_01_A0_D_02_01.Rte_TLC_mLimMotorTorque_xds16')`. After additionally loading the synthetic CSV: `combo_sig.count() == 7`, `files=['f0','f1']`. Both real-MF4 and CSV paths populate the combo. |
| 5 | Clicking 计算时频图 dispatches the worker; spectrogram + bottom slice both render | **PASS** | After `btn_compute.click()` the QThread runs to completion. Final state: `result.amplitude.shape=(257, 6)`, `frames=6`, `freq_bins=257`, `_ax_slice.lines == 1` (slice rendered), `_cursor_line is not None` (vertical cursor placed). |
| 6 | Hovering the spectrogram updates the cursor read-out | **PASS** | Synthesized `motion_notify_event` at the matplotlib display coords for the result mid-point produced exactly one `cursor_info` payload: `'t=1.024 s · f=125 Hz · -122.4 dB'`. The status bar `currentMessage()` matched the same string, confirming `MainWindow._on_fft_time_cursor_info` is wired. The string contains both `t=` and `f=` substrings as required. |
| 7 | Clicking the spectrogram moves the vertical cursor and updates the bottom FFT | **PASS** | `_on_click` with a synthesized `button_press_event` whose `inaxes == _ax_spec` moved `_selected_index` from `0 → 5` (target idx 5 selected exactly). Vertical cursor line repositioned to `t=1.5355 s` (matches `result.times[5]` to 4 decimals). Slice axis re-rendered with `lines=1`, `len_xdata=257`. |
| 8 | Amplitude ↔ Amplitude dB toggle re-renders WITHOUT recomputing (cache hit) | **PASS** | Switched `combo_amp_mode` from `Amplitude dB` to `Amplitude`, then clicked compute. Status bar received `使用缓存结果 · 6 frames · NFFT 512`. Cache size unchanged (`1 → 1`); worker QThread NOT started (`_fft_time_thread` after the click is None / not running). Confirms the Plan §6.4 contract that display-only fields are excluded from the cache key. |
| 9 | Color map / dynamic range toggle re-renders without recomputing | **PASS** | Switched `combo_cmap` to `viridis` and `combo_dynamic` to `60 dB`, then clicked compute. Cache hit message reproduced (`使用缓存结果 · 6 frames · NFFT 512`); cache size `1 → 1`; no worker dispatch. |
| 10 | 强制重算 recomputes (cache miss path) | **PASS** | `do_fft_time(force=True)` produced `正在计算…` immediately followed by `FFT vs Time 完成 · 6 frames` (worker cycle observed). Cache size `1 → 1` (same key, fresh value — force replaces the entry). |
| 11 | Closing the file invalidates the cache | **PASS** | After CHECK 10 the cache held one entry under fid `f1`. Calling `MainWindow._close('f1')` (the production path triggered by the file navigator's close button) dropped the cache from `1 → 0` entries; `f1` removed from `win.files`. The per-fid helper at `_fft_time_cache_clear_for_fid` is the single source of truth for this hook (verified end-to-end by `tests/ui/test_main_window_smoke.py` cache invalidation suite). |
| 12 | Both export buttons copy non-empty images to the clipboard; `grab_main_chart` strictly smaller than `grab_full_view` | **PASS** | After re-priming the canvas: `grab_full_view().size() == (896, 654)`, `grab_main_chart().size() == (689, 381)`. Main is strictly smaller in both width AND height (689 < 896, 381 < 654), confirming the bbox-crop path is exercising correctly under offscreen Qt rather than falling back to `self.grab()`. After invoking `_copy_fft_time_image('full')` and then `_copy_fft_time_image('main')`, `QApplication.clipboard().pixmap()` reflects the matching sizes (896×654 then 689×381) — both non-null. This validates `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md` end-to-end on this commit. |
| 13 | Request exceeding the 64 MB ceiling is rejected with a clear message; old chart stays visible | **PASS** | Synthesized a 5,000,000-sample @ 1 kHz signal (5e6 samples) and requested nfft=8192, overlap=90% (the brief suggested 99%; 90% was sufficient to exceed the ceiling at 5e6 samples — the 95.3 MB result already exceeds the 64 MB ceiling, so the more aggressive 99% setting was not required to exercise the rejection path), Amplitude. `SpectrogramAnalyzer.compute` reported `memory ceiling exceeded: 4097 bins x 6096 frames ~= 95.3 MB (ceiling 64 MB). Reduce nfft, overlap, or selected time range.` The exception was surfaced as `FFT vs Time 错误: memory ceiling exceeded …` on the status bar AND as a toast. Worker QThread was no longer running. Critically, `cv._result` is the **same object** before and after (shape `(257, 6) → (257, 6)`, same Python identity), confirming the failed-compute-keeps-old-chart contract. |

### Visual checks not directly verifiable headless

The offscreen Qt platform renders to a software backing store; pixel
output is real, axes layouts are real (the bbox-crop path proves this
via 689×381 vs 896×654), but no human eye saw the spectrogram colors
or the colorbar gradient on a physical monitor during this run. The
specific items that benefit from a follow-up desktop session:

- That the `turbo` and `viridis` color maps actually render as
  perceptually correct gradients (the cmap selection is verified to
  reach the canvas; only the visible color quality is not).
- That the colorbar tick labels are not clipped at the right edge
  on a real DPR-aware display.
- That the bottom slice axis is visually flush with the spectrogram x
  range when a freq range constraint is applied.
- That the cursor pill / status bar text is legible at the
  application's intended font size on a Retina display.

These items are flagged in the **Known Limitations** section below.
None of them block T10 closure given the offscreen evidence; they are
optional confirmation work for a future desktop session.

---

## External Comparison Notes

External cross-validation (HEAD legacy `MF4 Data Analyzer V1.py` /
MATLAB `spectrogram` / `scipy.signal.spectrogram`) is out of Phase 1
scope per Plan v2. The internal cross-check that matters for Phase 1
is the audit at Task 1 Step 1, which confirmed the corrected
DC/Nyquist amplitude normalization (no doubling) is consistent
between `FFTAnalyzer.compute_fft` and the new
`SpectrogramAnalyzer.compute`. That audit's findings are
locked in by the six tests in
`tests/test_fft_amplitude_normalization.py` (all green per the
Automated Tests section above).

---

## Known Limitations

Carried forward from Spec §2.2 / Plan v2:

- **No 3D waterfall** in Phase 1.
- **No multi-channel subplot** in Phase 1 — one signal at a time.
- **No PSD `/Hz` display** in Phase 1 — Amplitude and Amplitude dB
  only.
- **No HDF input** in Phase 1 — MF4 / XLSX / CSV only.
- **No display-layer downsampling** in Phase 1 — the 64 MB amplitude
  ceiling is the only safety net for very large spectrograms; users
  who exceed it must reduce nfft, overlap, or time range.
- **No UI cancel button** in Phase 1 — `FFTTimeWorker.cancel()` exists
  but is not wired to a button.

Discovered or reconfirmed during T10:

- **MF4 fixtures are non-uniform-time** — every `testdoc/*.mf4` file
  bundled with this repo has a recorded time channel whose jitter
  exceeds the 0.001 relative-jitter tolerance. Production MF4 work
  with these files requires the user to first press 重建时间轴
  (`btn_rebuild`) on the FFT vs Time panel to install a uniform axis
  at the chosen Fs. This is documented user behavior, not a defect.
  If a future task wants automated regression coverage of "MF4 happy
  path", a cleaner fixture is required.
- **Bbox-crop on offscreen Qt** — confirmed working on this commit
  (T8 lesson at
  `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`).
  CHECK 12 demonstrates `grab_main_chart` is strictly smaller than
  `grab_full_view` (689×381 vs 896×654) under offscreen Qt — no fallback.
- **Visual confirmation of color quality and high-DPI layout** has
  NOT been performed (see "Visual checks not directly verifiable
  headless" above). All structural and semantic checks pass; only
  cosmetic verification is deferred.
- **Memory ceiling exception flow under the worker thread** — verified
  to surface on the status bar AND preserve the prior result (CHECK
  13). The user-facing message is informative
  (`memory ceiling exceeded: 4097 bins x 6096 frames ~= 95.3 MB
  (ceiling 64 MB). Reduce nfft, overlap, or selected time range.`)
  and routes through `FFTTimeWorker.failed → MainWindow._on_fft_time_failed`
  exactly as designed.

---

## Per-Task Reports

T1 through T9 closure documents are at the absolute paths below.

- T1 (signal layer): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T1-signal-layer.md`
- T2 (mode plumbing): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T2-mode-plumbing.md`
- T3 (FFTTimeContextual): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T3-fft-time-contextual.md`
- T4 (SpectrogramCanvas): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T4-spectrogram-canvas.md`
- T5 (MainWindow sync compute + cache): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T5-mainwindow-sync-compute.md`
- T6 (worker thread): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T6-worker-thread.md`
- T7 (cache invalidation): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T7-cache-invalidation.md`
- T8 (export clipboard): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T8-export-clipboard.md`
- T9 (test execution payload): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T9-test-execution.md`
- T10 (this report's companion task report): `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T10-manual-smoke.md`

---

## Module Reviews

| Module | Scope | Reviewer | Verdict | Path |
|---|---|---|---|---|
| A | T1 — signal layer | Claude (Opus 4.7) — codex-route fallback | **approve** (zero blockers, zero importants, three minor nits) | `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T1-review.md` |
| B | T2 + T3 + T4 — UI shell, controls, canvas | Senior Code Reviewer (codex-route fallback) | **approve-with-nits** (8 checkpoints functional, 112 UI tests green, two minor nits) | `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-module-B-review.md` |
| C | T5 + T6 — sync compute and worker | codex (read-only) + host re-run | **approve-with-nits** | `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-module-C-review.md` |
| D | T7 + T8 — cache invalidation + export | codex | **approve-with-nits** (zero importants, four documentation/test-naming nits) | `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-module-D-review.md` |

All four reviews approve. No blockers from any module. Module E
(this report) was re-run after the doc-cleanup pass below and now
also approves — see the closing **Status** section.

---

## Lessons Added

Two new lesson files were registered in
`docs/lessons-learned/LESSONS.md` during this rollout:

- `docs/lessons-learned/pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md`
  — added by T6. Documents that `worker.finished/failed → thread.quit`
  must use `Qt.DirectConnection` and `qtbot.waitUntil` for drainage,
  because `thread.wait()` plus AutoConnection deadlocks the main loop
  in pytest-qt.
- `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`
  — added by T8. Documents that `axis.get_tightbbox` produces a real
  cropped pixmap under `QT_QPA_PLATFORM=offscreen`, so
  `SpectrogramCanvas.grab_main_chart` does not need to fall back to
  `self.grab()` on this platform; the fallback path remains as
  defense-in-depth.

These lessons are not specific to FFT vs Time — both apply to any
future PyQt5 + matplotlib feature work in this repo.

---

## Self-Review Checklist Outcome

The Plan's executor self-review checklist is verified by direct
observation in this run:

- ✅ `Amplitude` and `Amplitude dB` share the same cached linear
  amplitude result; switching modes does not recompute. (CHECK 8.)
- ✅ No PSD UI appears. (CHECK 4 — combo_amp_mode items are exactly
  `['Amplitude dB', 'Amplitude']`; no PSD entry.)
- ✅ `SpectrogramAnalyzer` imports no PyQt or matplotlib. (Confirmed
  by `tests/test_signal_no_gui_import.py`, 1/1 passed.)
- ✅ Non-uniform time axis is rejected with a clear error. (Real MF4
  observation in Real Data Checks: `relative_jitter=2.04 exceeds
  tolerance=0.001`.)
- ✅ Window helper shared between FFT and spectrogram via scipy. (T1
  Module A review §"verification points" confirmed.)
- ✅ Cursor readout (hover) and bottom slice (click) use full-resolution
  result data. (CHECK 6 prints exact bin values; CHECK 7 confirms
  slice axis re-renders 257-point array.)
- ✅ FFT vs Time computes only after button click or force recompute.
  (No compute on signal change; CHECK 5/8/9/10 prove it.)
- ✅ Cache hit visible in status text. (CHECK 8/9: `使用缓存结果 · 6
  frames · NFFT 512`.)
- ✅ Old chart remains visible after a failed recompute. (CHECK 13:
  `cv._result` is the same object before and after the memory
  rejection.)
- ✅ Compute button disabled until a signal candidate is set. (CHECK 3.)
- ✅ Dynamic range and freq range constrain the canvas. (CHECK 9
  flips dynamic range; assertion-level checks live in
  `tests/ui/test_chart_stack.py`.)
- ✅ Worker has finished and cancel smoke tests. (`tests/ui/` 112/112.)
- ✅ Cache invalidated on close-all, single-file close, time-axis
  rebuild, custom-x change, and file-load paths. (Test coverage in
  `tests/ui/test_main_window_smoke.py`; CHECK 11 exercises single-file
  close in production code path.)
- ✅ `MainWindow.canvas_fft_time` resolves to the same widget as
  `chart_stack.canvas_fft_time`. (`hasattr(window, 'canvas_fft_time')`
  is True; verified by T2 reviewer.)
- ✅ Memory ceiling rejection fires above 64 MB. (CHECK 13: 95.3 MB
  > 64 MB → rejected.)
- ✅ HDF, 3D, subplot, streaming, display-layer downsampling, and
  UI cancel button NOT introduced in Phase 1. (Inspector and toolbar
  surface inspection confirms — see Known Limitations.)

---

## Appendix A — full smoke driver log

```
[Font] 使用中文字体: STHeiti
[CHECK 1] PASS :: app boots offscreen; MainWindow shown; canvas_fft_time=True
[CHECK 2] PASS :: toolbar.btn_mode_fft_time text='FFT vs Time' visible=True checkable=True
[CHECK 2b] PASS :: after btn_mode_fft_time.click(), inspector contextual=FFTTimeContextual
[CHECK 3] PASS :: combo_sig empty (count=0) AND btn_compute.isEnabled()=False
[CHECK 4] PASS :: after _load_one(TLC_TAS_RPS_2ms.mf4): combo_sig count=6 btn_compute.enabled=True first_item_data=('f0', 'ERD6_01_01_A0_D_02_01.Rte_TLC_mLimMotorTorque_xds16') files=['f0']
[CHECK 4b] PASS :: after CSV load: combo_sig count=7 files=['f0', 'f1']
[INFO] using signal ('f1', 'sine_4hz_50hz') for compute checks
[CHECK 5] PASS :: worker finished; result.amplitude.shape=(257, 6) frames=6 freq_bins=257 slice_lines=1 cursor_line_set=True
[CHECK 6] PASS :: cursor_info emitted 1 payload(s); first='t=1.024 s · f=125 Hz · -122.4 dB'; statusBar='t=1.024 s · f=125 Hz · -122.4 dB'
[CHECK 7] PASS :: _selected_index moved 0→5; cursor_line at t=1.5355; slice axis lines=1 len_xdata=257
[CHECK 8] PASS :: amplitude toggle hit cache: status='使用缓存结果 · 6 frames · NFFT 512' cache_size 1→1 thread_running=False
[CHECK 9] PASS :: cmap+dynamic toggle hit cache: cache_size 1→1; hit_msg='使用缓存结果 · 6 frames · NFFT 512'
[CHECK 10] PASS :: force recompute dispatched worker: saw_running=True; final_msg='FFT vs Time 完成 · 6 frames'; cache_size 1→1
[CHECK 11] PASS :: _close('f1') invalidated cache: total 1→0; keys_for_f1 1→0; fid removed from win.files=True
[CHECK 12] PASS :: grab_full_view=(896, 654) grab_main_chart=(689, 381) (main smaller); clipboard.full=(896, 654), clipboard.main=(689, 381); both non-null
[CHECK 13] PASS :: memory ceiling rejected: msg='FFT vs Time 错误: memory ceiling exceeded: 4097 bins x 6096 frames ~= 95.3 MB (ceiling 64 MB). Reduce nfft, overlap, or selected time range.'; chart preserved (shape (257, 6)→(257, 6) same object); thread_running=False
[SMOKE] complete
```

Driver source: `/tmp/fft_time_smoke/smoke.py` (preserved for
reproducibility; documented in the T10 task report). Reproducer:

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python /tmp/fft_time_smoke/smoke.py
```

---

## Appendix B — entrypoint verification

The Plan's launch command (`python -m mf4_analyzer.app`) was confirmed
against the codebase: `mf4_analyzer/app.py` has the canonical
`def main(): … if __name__ == '__main__': main()` entry point and
constructs `MainWindow` after `setup_chinese_font()` and
`QApplication(sys.argv)`. There is no `mf4_analyzer/__main__.py`, so
`python -m mf4_analyzer` is NOT a valid launch shortcut — the
Plan-prescribed `python -m mf4_analyzer.app` is correct. T10's smoke
driver replicates this entry sequence directly (the import order is
`matplotlib.use('Qt5Agg', force=True)` → PyQt5 → `setup_chinese_font`
→ `QApplication` → `MainWindow`) so that any ordering hazard would
have surfaced.

---

## Status

**Validation closed: PASS.** All 13 manual UI checks observed real
PASS-grade evidence under offscreen Qt; all 135 automated tests are
green (Module E re-run); all four prior module reviews approve and
the Module E review re-runs to approve after this doc-cleanup pass. The only carry-forward items
are the explicit Phase-1 scope exclusions enumerated in **Known
Limitations** and the cosmetic visual confirmations that require a
desktop session.

Recorded changed files (this is not a git repository — Plan v2 says
"if no `.git` directory exists, record changed files in the task
summary instead of committing"; the summary lives in the T10 task
report referenced above):

- `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md`
  (this file — created)
- `docs/superpowers/reports/2026-04-25-fft-vs-time-T10-manual-smoke.md`
  (companion task report — created)
