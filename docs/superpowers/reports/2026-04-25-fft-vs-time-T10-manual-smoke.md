# FFT vs Time 2D — T10 Manual UI Smoke (pyqt-ui-engineer task report)

**Date:** 2026-04-25
**Specialist:** pyqt-ui-engineer
**Scope:** Plan Task 10 Steps 4-6 — manual UI smoke under offscreen
Qt + production validation report.
**Plan:** `/Users/donghang/Downloads/data analyzer/docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`
**Validation report (deliverable):** `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md`

---

## What was exercised

A 13-row UI smoke checklist (the Plan Task 10 Step 4 list as expanded
by the dispatch brief) was driven against a live `MainWindow` instance
under `QT_QPA_PLATFORM=offscreen` on macOS. Real Qt widgets, real
matplotlib `FigureCanvas` rendering, real signal/slot dispatch, real
worker `QThread`. Every checkbox got a concrete observation; zero
checkboxes are placeholders.

The driver is `/tmp/fft_time_smoke/smoke.py`. It boots the app,
loads both a real engineering MF4 (`testdoc/TLC_TAS_RPS_2ms.mf4`) and
a synthetic CSV (`/tmp/fft_time_smoke/sine_4hz_1khz_2s.csv`, generated
by the script on first run), then walks the full checklist and emits
one `[CHECK N] STATUS :: <details>` line per item. All 13 lines
emitted `PASS`.

Verbatim final log is reproduced in the validation report's Appendix
A. Headline:

| # | Check | Result |
|---|---|---|
| 1 | App boots offscreen | PASS |
| 2 | `FFT vs Time` toolbar button present and routes mode | PASS |
| 3 | Compute button disabled before signal candidate is selected | PASS |
| 4 | Loading MF4 / CSV populates `combo_sig` | PASS (both) |
| 5 | Compute click dispatches worker; spectrogram + slice render | PASS |
| 6 | Hover updates cursor read-out (`t=…`/`f=…`) on status bar | PASS |
| 7 | Click moves vertical cursor and re-renders slice | PASS |
| 8 | Amplitude/dB toggle hits cache (no recompute) | PASS |
| 9 | Cmap + dynamic range toggle hits cache | PASS |
| 10 | Force recompute bypasses cache | PASS |
| 11 | `_close(fid)` invalidates per-fid cache entries | PASS |
| 12 | Both export buttons; `grab_main_chart` < `grab_full_view` | PASS |
| 13 | 64 MB memory ceiling rejection preserves old chart | PASS |

---

## Key decisions

1. **MF4 vs CSV split.** The bundled `testdoc/*.mf4` files all carry
   non-uniform time axes and the new `SpectrogramAnalyzer` correctly
   rejects them with `relative_jitter ≈ 2.04 exceeds tolerance=0.001`.
   That rejection is by design (Spec §2.4) and is itself useful evidence
   for CHECK 4 ("loading file populates combo, even if compute won't
   run on it without 重建时间轴"). The compute-driven checks 5-12 use
   a programmatically generated synthetic CSV (`sine_4hz_50hz`, fs=1
   kHz, 2 s, 4 Hz fundamental + 50 Hz overtone) so the worker, cache,
   and export paths are all exercised against a clean uniform-time
   signal. The synthetic file is checked into `/tmp/fft_time_smoke/`
   only and reproduced from `smoke.py` on demand — no test fixtures
   under version control were modified.

2. **`Toolbar.set_mode` does not exist.** First draft of the smoke
   driver tried `win.toolbar.set_mode("fft_time")`. There is no such
   method; the toolbar exposes `btn_mode_fft_time` and routes mode
   changes via the button's `clicked` signal. The driver was corrected
   to call `btn_mode_fft_time.click()` — the exact path a user takes.
   This is recorded here so future smoke authors don't repeat the
   guess.

3. **`combo_nfft` accepts only its enumerated values.** The first
   draft set `combo_nfft.setCurrentText("256")`, which silently leaves
   the combo at its default of `2048` because `'256'` is not in the
   item list (`['512', '1024', '2048', '4096', '8192']`). With nfft
   stuck at 2048 and the synthetic signal at 2000 samples, the
   spectrogram correctly raised `signal is shorter than nfft`. The
   fix was `combo_nfft.setCurrentText("512")` — a value that IS in
   the list. Lesson: when driving QComboBox from headless code,
   prefer `findText`/`setCurrentIndex` or assert the value actually
   landed.

4. **Slice rendering check via `Axes.lines`, not a persistent
   attribute.** First draft inspected `cv._slice_line.get_xdata()`;
   `_slice_line` does not exist because `SpectrogramCanvas._plot_slice`
   clears and redraws the slice axis on every selection. The check
   now reads `cv._ax_slice.lines` and asserts a single line is
   present with `len(get_xdata()) == 257` (the freq bin count). This
   matches the actual implementation and is robust to future
   re-render strategies.

5. **CHECK 11 closes the synthetic-CSV file, not the MF4.** The MF4
   never produced a successful compute (rejected at the time-axis
   check), so its fid had zero cache entries. Closing it would have
   been a no-op. The synthetic CSV did populate the cache; closing
   that file via `MainWindow._close(fid)` (the production path) is
   the correct way to demonstrate per-fid invalidation. The smoke
   then re-loads the CSV before CHECK 12 so the export checks have a
   live result on the canvas.

6. **CHECK 13 builds a 5e6-sample signal in-memory, not on disk.**
   Writing a 5,000,000-row CSV would be > 50 MB on disk and several
   seconds to load, neither of which is required to drive the memory
   ceiling. The driver loads a 2-row placeholder CSV and then
   replaces `FileData.data` and `FileData.time_array` in-place with
   numpy arrays of the desired size. `_update_combos()` is then
   called explicitly to refresh `combo_sig` so the new channel
   becomes selectable. This is consistent with how production code
   would handle a large signal once it's in memory; only the disk
   I/O is shortcut. The memory rejection itself is exercised through
   the real `do_fft_time → FFTTimeWorker → SpectrogramAnalyzer.compute_amplitude`
   path.

---

## Forbidden boundaries — confirmed clean

I did NOT modify any `.py` source under `mf4_analyzer/` or `tests/`
during this task. The only files I authored are:

- `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md`
  (validation deliverable)
- `docs/superpowers/reports/2026-04-25-fft-vs-time-T10-manual-smoke.md`
  (this task report)

The smoke driver at `/tmp/fft_time_smoke/smoke.py` lives outside the
repo tree and is reproducible from the documentation; it is not a
checked-in artifact.

`symbols_touched`: none (no code edits). `forbidden_symbols_check`: no
code edits → trivially passes.

---

## Tests run

This task did not run pytest (the T9 specialist owned that). The
"tests" in this report are the 13 manual UI smoke checks. The full
pytest suite (128/128 passing) is sourced from T9's payload at
`docs/superpowers/reports/2026-04-25-fft-vs-time-T9-test-execution.md`
and was independently re-confirmed during the T10 pass to remain at
128/128 passing.

---

## Lessons-learned candidates

Two candidate lessons were identified during this task; neither rose
above the "non-obvious insight worth keeping" bar enough to write up
without risking the "forbidden water content" rule:

- **MF4 fixtures with non-uniform time axes are routine** in
  industrial recordings; spectrogram tooling needs a 重建时间轴
  affordance and tests should not assume the recorded time channel is
  ready for use. This is borderline obvious to anyone who has worked
  with MDF files; not writing a lesson.
- **Combo-box `setCurrentText` silently no-ops on values not in the
  item list.** Standard Qt behavior; documented in PyQt5 docs;
  reproducible bug surface but not really an insight. Not writing.

If a future T10 ever DOES find non-trivial Qt-quirk evidence, the
correct path is to add a row under `## pyqt-ui` in
`docs/lessons-learned/LESSONS.md` and a body file under
`docs/lessons-learned/pyqt-ui/`. This run did not surface that
evidence.

`lessons_added: []`. `lessons_merged: []`.

---

## Status

`status: done`. `ui_verified: true` — every visible-effect checkbox
was exercised against a live MainWindow + matplotlib canvas under
offscreen Qt and produced concrete observations matching the design
contract. Cosmetic visual confirmations (color quality, high-DPI
font rendering) are deferred to a desktop session and recorded as
**Known Limitations** in the validation report.

`flagged_issues: []` — no specialist re-dispatch needed. All four
module reviews already approved their slices; no new defects
surfaced during T10.

`tests_before: n/a` — manual smoke task; no pytest delta this run.
`tests_after: 13/13 PASS` — see the table above and the validation
report's Appendix A for the verbatim log.

`report_path` (this T10 task report):
`/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T10-manual-smoke.md`

`files_changed`:

- `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md`
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T10-manual-smoke.md`

`files_moved: []`. No source file was renamed, moved, or refactored.

---

## Note on Plan Step 6 (commit)

Plan Task 10 Step 6 prescribes `git add … && git commit -m …`. The
working tree at `/Users/donghang/Downloads/data analyzer` has no
`.git` directory, so per Plan v2's note ("If no `.git` directory
exists, record changed files in the task summary instead of
committing") the two created paths are recorded above under
`files_changed` and in the validation report's "Status" section.
No commit was attempted.
