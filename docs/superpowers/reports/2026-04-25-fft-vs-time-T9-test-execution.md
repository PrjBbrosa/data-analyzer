# FFT vs Time 2D — T9 Test Execution Payload

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 10 Steps 1-3.
**Role:** signal-processing-expert.
**Date:** 2026-04-25.
**Purpose:** structured payload for T10 to paste verbatim into the validation
report under `## Automated Tests`. No code changes were made.

---

## 1. Environment

| Field | Value |
|---|---|
| Python | 3.12.13 (`.venv/bin/python`) |
| pytest | 9.0.3 |
| pluggy | 1.6.0 |
| pytest-qt | 4.5.0 |
| PyQt5 | 5.15.11 (Qt runtime 5.15.18, Qt compiled 5.15.14) |
| Platform | `Darwin DongHangdeMacBook-Air.local 25.5.0 ... arm64` (macOS, Apple Silicon) |
| Working dir | `/Users/donghang/Downloads/data analyzer` |
| `PYTHONPATH` | `.` (repo root) for every invocation |
| `QT_QPA_PLATFORM` | not exported in this run; pytest-qt drove headless Qt via the default platform |
| rootdir | `/Users/donghang/Downloads/data analyzer` |
| cachedir | `.pytest_cache` |

No deprecation warnings, no collection warnings, no skips, no xfails, no
errors during collection. All three commands exited 0.

---

## 2. Per-command results

| # | Command | Exit | Passed | Failed | Skipped | Errored | Duration |
|---|---|---|---|---|---|---|---|
| 1 | `cd "/Users/donghang/Downloads/data analyzer" && PYTHONPATH=. .venv/bin/pytest tests/test_fft_amplitude_normalization.py tests/test_spectrogram.py tests/test_signal_no_gui_import.py -v` | 0 | 16 | 0 | 0 | 0 | 0.92 s |
| 2 | `cd "/Users/donghang/Downloads/data analyzer" && PYTHONPATH=. .venv/bin/pytest tests/ui/ -v` | 0 | 112 | 0 | 0 | 0 | 3.78 s |
| 3 | `cd "/Users/donghang/Downloads/data analyzer" && PYTHONPATH=. .venv/bin/pytest -v` | 0 | 128 | 0 | 0 | 0 | 4.26 s |

Per-file totals from the verbose output (full-suite run, command 3):

| File | Tests |
|---|---|
| `tests/test_fft_amplitude_normalization.py` | 6 |
| `tests/test_signal_no_gui_import.py` | 1 |
| `tests/test_spectrogram.py` | 9 |
| `tests/ui/test_chart_stack.py` | 18 |
| `tests/ui/test_drawers.py` | 6 |
| `tests/ui/test_envelope.py` | 25 |
| `tests/ui/test_file_navigator.py` | 10 |
| `tests/ui/test_inspector.py` | 15 |
| `tests/ui/test_main_window_smoke.py` | 22 |
| `tests/ui/test_toolbar.py` | 4 |
| `tests/ui/test_xlim_refresh.py` | 7 |
| **Total** | **128** |

The signal-only run (16) plus the UI run (112) sum to exactly 128, matching
the full-suite count. There is no test in either subset that the other
double-counts, and no test is collected only by the full-suite run.

---

## 3. Failure detail

No failures, no errors, no skips across all three invocations. Stub table
preserved for T10's report structure:

| Command | Test nodeid | Phase | One-line trace summary |
|---|---|---|---|
| _(none)_ | _(none)_ | _(none)_ | _(none)_ |

There are no pre-existing failures to flag as known. Every test currently
in `tests/` passes on this commit.

---

## 4. Test-count delta vs Plan v2 expectation

| Source | Count | Notes |
|---|---|---|
| Plan v2 baseline (Module D, codex review) | 128 | confirmed in `docs/superpowers/reports/2026-04-25-fft-vs-time-module-D-review.md` |
| Full-suite run on this commit (command 3) | 128 | exact match |
| Delta | **0** | no tests added, removed, or renamed since the Module D review |

Investigation gate cleared — no further file-level breakdown required.

---

## 5. Summary block for T10's "## Automated Tests" section

> All three pytest invocations passed on the validation commit. Total
> automated coverage: **128 tests, 128 passed, 0 failed, 0 skipped,
> 0 errored**, full-suite duration 4.26 s on Python 3.12.13 / pytest 9.0.3
> / PyQt5 5.15.11 / macOS arm64. The signal-processing focused subset
> (`tests/test_fft_amplitude_normalization.py`,
> `tests/test_spectrogram.py`, `tests/test_signal_no_gui_import.py`)
> contributed 16 tests in 0.92 s. The UI subset (`tests/ui/`) contributed
> 112 tests in 3.78 s and exercises the FFT-vs-Time canvas, inspector
> contextual panel, worker thread, cache invalidation, and copy-image
> paths added by T1 through T8. The full-suite count (128) matches the
> Plan v2 baseline confirmed by the Module D review with delta 0,
> confirming no tests were lost or silently skipped during integration.
> Zero pre-existing failures to disclose.

---

## Appendix A — copy-paste reproducer

```bash
cd "/Users/donghang/Downloads/data analyzer"

# Command 1: signal-processing focused subset
PYTHONPATH=. .venv/bin/pytest \
  tests/test_fft_amplitude_normalization.py \
  tests/test_spectrogram.py \
  tests/test_signal_no_gui_import.py -v

# Command 2: UI subset
PYTHONPATH=. .venv/bin/pytest tests/ui/ -v

# Command 3: full suite
PYTHONPATH=. .venv/bin/pytest -v
```

Each command prints `===== N passed in T s =====` and exits 0 on this
commit.
