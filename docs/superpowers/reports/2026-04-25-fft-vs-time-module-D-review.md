# Verdict: approve-with-nits

Module D's runtime behavior is acceptable: the seven cache invalidation hooks are present, the per-fid helper matches the cache-key shape, FFT-vs-Time popover routing is correct in code, export-to-clipboard is guarded, and the full suite is green when run with the repository's required import path.

The remaining issues are test-contract and documentation precision nits. I did not find a source-code blocker that should stop the module from landing.

## Important

None.

## Nits

1. `tests/ui/test_main_window_smoke.py:453` uses `test_fft_time_rebuild_popover_resolves_signal_via_fft_time_ctx`, but the review checklist asked for `test_fft_time_show_rebuild_popover_routes_to_fft_time_ctx`. The behavior is covered at `tests/ui/test_main_window_smoke.py:519-525`, but the exact expected symbol is absent. Fix: rename the test or add a thin alias if the suite/report tooling keys on the requested name.

2. `tests/ui/test_main_window_smoke.py:684-696` verifies clipboard pushes, non-null pixmaps, status-bar text, and success toast, but it does not verify the `2000` timeout passed at `mf4_analyzer/ui/main_window.py:1441`. Fix: monkeypatch `win.statusBar.showMessage` and assert `(message, 2000)` for both modes.

3. `tests/ui/test_chart_stack.py:269-270` only asserts both export pixmaps are non-null. The offscreen-Qt lesson says tight-bbox cropping is expected to work and produce a smaller main-chart pixmap; see `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md:23-28`. Fix: strengthen the test to compare `grab_main_chart().size()` against `grab_full_view().size()` when the bbox path is available, plus a separate fallback test for degenerate/null crop if desired.

4. A few comments/docstrings are stale after T7/T8:
   - `mf4_analyzer/ui/main_window.py:96-97` still says invalidation lives in T7 and "no clear() calls in this task"; current code now has clear calls at `mf4_analyzer/ui/main_window.py:411`, `mf4_analyzer/ui/main_window.py:474`, and `mf4_analyzer/ui/main_window.py:569`.
   - `mf4_analyzer/ui/main_window.py:1170-1172` says `_fft_time_cache_clear_for_fid` is used for custom-x change, but `_apply_xaxis` uses wholesale clear at `mf4_analyzer/ui/main_window.py:474`.
   - `mf4_analyzer/ui/canvases.py:1324-1329` says offscreen Qt may force full-canvas fallback, but the lesson at `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md:23-28` records that tight-bbox works under offscreen after `plot_result`.

## Spec-Compliance Scorecard

| Item | Status | one-line note |
|---|---|---|
| 1. Cache invalidation completeness | PASS | All seven requested hooks clear the cache: rebuild accepted branch `mf4_analyzer/ui/main_window.py:331-335`, `_on_close_all_requested` `405-412`, `_apply_xaxis` `463-474`, `_load_one` `512-519`, `_close` `541-552`, `close_all` `565-569`, `_apply_channel_edits` `761-767`. Extra `invalidate_envelope_cache` canaries at `650`, `671`, and `708` are time-domain selection/layout/range changes; range is already in the FFT-vs-Time key at `1138-1148`/`1261-1273`. |
| 2. Targeted helper correctness | PASS | `_fft_time_cache_key` returns `(fid, channel, time_range_tuple, fs, nfft, window, overlap, remove_mean, db_reference)` at `mf4_analyzer/ui/main_window.py:1138-1148`; `_fft_time_cache_clear_for_fid` collects keys with `k[0] == fid` and pops only those at `1177-1179`. |
| 3. Popover mode routing | FAIL | Runtime code is correct: `mode == 'fft_time'` reads `inspector.fft_time_ctx.current_signal()` at `mf4_analyzer/ui/main_window.py:308-313`, and the post-accept Fs loop includes `fft_time_ctx` at `336-343`; however the exact requested test name is absent, with an equivalent test at `tests/ui/test_main_window_smoke.py:453-525`. |
| 4. Boundary discipline | N/A | The directory is not a Git worktree, so I cannot independently prove historical non-modification. Current boundaries match the T7/T8 reports: T7 report scope/attestation at `docs/superpowers/reports/2026-04-25-fft-vs-time-T7-cache-invalidation.md:13-25` and `115-149`; T8 report forbidden-symbol table at `docs/superpowers/reports/2026-04-25-fft-vs-time-T8-export-clipboard.md:63-95`. Current inspected regions are cache helpers `mf4_analyzer/ui/main_window.py:1131-1179`, worker/callbacks `28-77` and `1233-1415`, T4 canvas body `1069-1298`, export additions `1303-1370` and `1418-1442`. |
| 5. Export pixmap correctness | PASS | `grab_full_view` returns `self.grab()` at `mf4_analyzer/ui/canvases.py:1303-1312`; `grab_main_chart` uses tight-bbox crop as primary path and falls back on missing result/axis, degenerate rect, null pixmap, or exception at `1314-1370`; `test_spectrogram_canvas_export_pixmaps` confirms non-null pixmaps after `plot_result` at `tests/ui/test_chart_stack.py:253-270`. |
| 6. Clipboard guard | PASS | `_copy_fft_time_image` returns after warning toast when `has_result()` is false at `mf4_analyzer/ui/main_window.py:1431-1433`, before `QApplication.clipboard().setPixmap` at `1440`; `test_copy_fft_time_image_warns_when_no_result` spies on `setPixmap` and asserts no calls at `tests/ui/test_main_window_smoke.py:617-649`. |
| 7. Success path | PASS | Source calls `QApplication.clipboard().setPixmap(pix)`, `statusBar.showMessage(msg, 2000)`, and success toast at `mf4_analyzer/ui/main_window.py:1434-1442`; the two exact messages are assigned at `1436` and `1439`. Test coverage verifies pixmap push/current message/toast at `tests/ui/test_main_window_smoke.py:652-696`, but not the `2000` timeout argument. |
| 8. Inspector relay | PASS | Signals exist at `mf4_analyzer/ui/inspector.py:22-25`; `fft_time_ctx.export_full_requested` and `.export_main_requested` connect to the relays at `mf4_analyzer/ui/inspector.py:100-103`. |
| 9. Comment cleanup | PASS | The old Module C "T8 territory" placeholder is gone; current wiring/comment block has real export connections at `mf4_analyzer/ui/main_window.py:215-229`. |
| 10. Tests | PASS | `pytest` is not on PATH (`zsh: command not found: pytest`), and `python` is not on PATH. `.venv/bin/pytest` exists but fails without `PYTHONPATH=.` due `ModuleNotFoundError: mf4_analyzer`. Actual verification command `PYTHONPATH=. .venv/bin/pytest` collected 128 tests and passed all 128 in 13.07s. |
| 11. Cosmetic/hygiene | PASS | No unused imports or dead branches found in the T7/T8 additions by inspection. Type hints match the surrounding code style. Magic capacity `12` is intentionally documented at `mf4_analyzer/ui/main_window.py:90-99`. Stale comments/docstrings are listed under Nits. |
| 12. Test quality | FAIL | Each named test uses `qtbot.addWidget` and isolates one primary behavior (`tests/ui/test_main_window_smoke.py:415-450`, `453-525`, `617-696`; `tests/ui/test_chart_stack.py:253-270`), and clipboard mutation is monkeypatched. Gaps: requested rebuild test name is absent, export success does not assert the `2000` timeout, and the bbox export test does not assert the offscreen tight-bbox behavior recorded in the lesson. |

## Recommendation for main Claude

Accept Module D's implementation behavior. If strict checklist conformance matters, ask the relevant specialist to make a small test/doc cleanup pass: rename the rebuild-popover test to the requested name, assert the status-bar timeout, strengthen the bbox-crop assertion, and refresh the stale comments/docstrings. No source behavior changes are required from this review.
