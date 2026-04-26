# Module B Review — FFT vs Time UI Shell + Controls + Canvas

**Date:** 2026-04-25
**Reviewer:** Senior Code Reviewer (fallback for stalled codex review).
**Scope:** T2 (mode plumbing), T3 (FFTTimeContextual full body), T4 (SpectrogramCanvas full body).
**Specialist reports consulted:**
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T2-mode-plumbing.md`
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T3-fft-time-contextual.md`
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/reports/2026-04-25-fft-vs-time-T4-spectrogram-canvas.md`
**Reference docs:**
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`
- `/Users/donghang/Downloads/data analyzer/docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md` (Tasks 3, 4, 5)

## Verdict

**approve-with-nits** — proceed to T5.

Module B delivers a coherent, surgical implementation of the FFT-vs-Time UI
shell. All 8 review checkpoints pass functionally, full pytest suite is green
(112 passed, exit 0), and boundary discipline is exemplary. The two flagged
follow-ups from T3 and T4 are honest and accurate. There are no blockers.
The Important items below are scope-handoffs for downstream tasks (T5/T6/T7),
not defects in Module B.

## Test Run

Project root: `/Users/donghang/Downloads/data analyzer`
Interpreter: `.venv/bin/python` (Python 3.12.13, PyQt5 5.15.11, pytest 9.0.3)

### Full suite

```
PYTHONPATH=. .venv/bin/pytest tests/ -q
112 passed in 3.83s
EXIT=0
```

### Module-B focused subset

```
PYTHONPATH=. .venv/bin/pytest \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_main_window_smoke.py -v
45 passed in 2.13s
EXIT=0
```

### Signal-layer regression check (no GUI imports leak)

```
PYTHONPATH=. .venv/bin/pytest \
  tests/test_spectrogram.py \
  tests/test_fft_amplitude_normalization.py \
  tests/test_signal_no_gui_import.py -v
16 passed in 0.92s
EXIT=0
```

The 12 new tests claimed by Module B are all present and green:
- `test_toolbar_exposes_fft_time_mode` — PASS
- `test_chart_stack_exposes_fft_time_card` — PASS
- `test_spectrogram_canvas_plots_main_and_slice` — PASS
- `test_spectrogram_canvas_applies_dynamic_and_freq_range` — PASS
- `test_spectrogram_canvas_emits_cursor_info_on_hover` — PASS
- `test_inspector_exposes_fft_time_context` — PASS
- `test_fft_time_context_returns_params` — PASS
- `test_fft_time_compute_button_tracks_signal_candidates` — PASS
- `test_fft_time_signal_candidates_preserve_selection` — PASS
- `test_fft_time_context_builtin_presets` — PASS
- `test_main_window_promotes_fft_time_canvas` — PASS
- (existing) `test_chart_stack_has_three_canvases` updated to assert count==4 — PASS

## Blockers

None.

## Important

1. **`canvas_fft_time.cursor_info` is currently a dangling signal — no UI
   surface consumes the readout.**
   `mf4_analyzer/ui/canvases.py:1041` declares `cursor_info = pyqtSignal(str)`,
   `mf4_analyzer/ui/canvases.py:1276-1298` emits the
   `t / f / value unit` readout on hover, and the test at
   `tests/ui/test_chart_stack.py:217` is the only consumer.
   `mf4_analyzer/ui/chart_stack.py:387-388` only wires `canvas_time.cursor_info`
   to the floating pill (`_on_cursor_info` is also gated to `current_mode() == 'time'`
   at `mf4_analyzer/ui/chart_stack.py:454`). Design §6.4 calls out
   "Mouse move readout shows nearest time/frequency/value" as a Phase 1
   requirement, so a UI surface (status bar, mode-aware pill, or new
   readout strip) must be added.
   Severity: this is a **handoff gap**, not a Module B defect — the plan
   reserves "MainWindow.do_fft_time + status / readout wiring" for T5/T6.
   Flag here so T5/T6 dispatch briefs explicitly include "wire
   `canvas_fft_time.cursor_info` to a visible surface" rather than
   leaving it to discovery.

2. **`FFTTimeContextual.signal_changed` and `FFTTimeContextual.rebuild_time_requested`
   exist on the contextual widget but are not relayed by `Inspector`.**
   - `mf4_analyzer/ui/inspector_sections.py:800-801` declare both signals.
   - `mf4_analyzer/ui/inspector_sections.py:973-974` emits `signal_changed`
     from `_on_sig_index_changed`.
   - `mf4_analyzer/ui/inspector_sections.py:829-831` emits
     `rebuild_time_requested(self.btn_rebuild)` from the rebuild button.
   - `mf4_analyzer/ui/inspector.py:72-97` (`_wire`) does NOT relay either —
     only the four T2 signals (`fft_time_requested`, `force_recompute_requested`,
     `export_full_requested`, `export_main_requested`) are connected.
   T3 flagged this honestly (T3 report §"Flagged issues" → "For T6 (Fs
   auto-sync)"). The flag is technically accurate: leaving them unrelayed
   is harmless because no consumer is listening, but T6 must add the
   relays in `inspector.py` (one line for `signal_changed` and one for
   `rebuild_time_requested` paralleling the existing `fft_ctx`/`order_ctx`
   patterns at `inspector.py:81-82` and `inspector.py:86-87`).
   Severity: **Important for T6**, not a Module B blocker.

3. **`spin_freq_min == spin_freq_max == 0.0` after default startup, with no
   guard against `freq_max < freq_min`.**
   `mf4_analyzer/ui/inspector_sections.py:880-891` initializes both
   spinboxes to range `(0, 1e9)` with `freq_max` defaulting to `0.0`
   (the "use Nyquist" sentinel). If a user toggles
   `chk_freq_auto` off and accidentally sets `freq_min > 0` while leaving
   `freq_max = 0`, the inspector emits a contradictory `(lo>0, hi=0)` pair.
   `SpectrogramCanvas._color_limits` and `plot_result`
   (`mf4_analyzer/ui/canvases.py:1169-1173, 1244-1248`) handle this by
   falling back to Nyquist when `hi <= lo or hi <= 0`, so behavior
   stays sane — but the user sees the auto-fallback silently, which
   may be confusing. T5/T6 should consider adding a UI hint or
   `spin_freq_min.setMaximum(spin_freq_max.value() - eps)` clamp once
   the manual mode toggles. Severity: low — covered by canvas fallback,
   listed for awareness.

## Nits

1. **`_on_motion` emits empty string on every motion event when result is
   None.**
   `mf4_analyzer/ui/canvases.py:1276-1281` emits `''` whenever
   `_result is None or event.inaxes is not _ax_spec`. Pre-result, every
   pointer motion across the canvas re-emits empty. Harmless once a
   subscriber arrives (text already empty), but mildly noisy on the
   signal queue. Optional: track `_last_emitted_text` and suppress
   identical re-emits.

2. **Magic numbers `80.0` / `60.0` in `_color_limits` are tied to
   combobox tokens by string equality.**
   `mf4_analyzer/ui/canvases.py:1198-1201` hard-codes `dynamic == '80 dB'`
   → `zmax-80.0`, etc. The matching tokens live at
   `mf4_analyzer/ui/inspector_sections.py:893`
   (`combo_dynamic.addItems(['80 dB', '60 dB', 'Auto'])`). Verified the
   tokens match exactly today, but the coupling is brittle: a future
   token rename ("80 dB span", "Span 80 dB") would silently break the
   color-limits selection. A small constants module
   (`DYNAMIC_TOKENS = {'80 dB': 80.0, '60 dB': 60.0, 'Auto': None}`)
   shared by both files would defuse this. Style only — no behavioral
   defect today.

3. **`SpectrogramResult` is a `@dataclass` (not `frozen=True`) per
   `mf4_analyzer/signal/spectrogram.py:61-93`.**
   This was deliberate — frozen dataclasses are slower to construct,
   and worker construction sits on the hot path. Note for awareness:
   the `_db_cache` invalidation contract relies on
   `id(result)` changing, NOT on byte-level immutability of `result.amplitude`.
   No code paths in Module B mutate `result.amplitude` or
   `result.params`, and the canvas does not rely on equality
   semantics. Flag-only.

4. **`chk_remove_mean` default is checked, but `combo_amp_mode` default
   is `'Amplitude dB'` — there's no preset that maps directly to the
   default state.**
   `mf4_analyzer/ui/inspector_sections.py:854-855, 864`. The default
   panel state is "Hann · NFFT 2048 · 75% · Amp dB · 80 dB · turbo"
   which happens to coincide with the `'diagnostic'` preset (verified
   via runtime smoke). Consider documenting in the panel docstring
   that "panel defaults match the diagnostic preset" so future readers
   don't think the defaults are arbitrary.

5. **`apply_builtin_preset(name)` silently ignores unknown names.**
   `mf4_analyzer/ui/inspector_sections.py:1076-1078`. Defensive, and the
   docstring documents it. T3 chose this so callers don't have to guard
   in early UI states. No issue, just noting it as a deliberate UX choice.

6. **`Inspector.current_mode()` is a thin alias over
   `contextual_widget_name()`.**
   `mf4_analyzer/ui/inspector.py:103-107`. Two methods returning the
   same thing is mildly redundant; `current_mode` was added because the
   plan's Step 7 test expects that name. Both names are public and
   could converge in a follow-up cleanup, but keeping both costs nothing
   and removing either would break a downstream caller.

7. **Inline `import warnings` inside `plot_result`.**
   `mf4_analyzer/ui/canvases.py:1181`. Imports at module top are
   conventional. Kept inline to scope the warning suppression context;
   acceptable.

8. **Inline `from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer`
   inside `_display_matrix`.**
   `mf4_analyzer/ui/canvases.py:1219`. Lazy import sidesteps a potential
   import cycle and keeps the canvas module faster to import. Document
   in a comment why it's lazy (one line) so a future reviewer doesn't
   "fix" it by hoisting.

## Spec-Compliance Scorecard

| # | Item | Status | Note |
|---|------|--------|------|
| 1 | Canvas promotion (`canvas_fft_time` end-to-end chain) | PASS | `mf4_analyzer/ui/main_window.py:81` adds the alias right after the existing canvas-promotion block; `test_main_window_promotes_fft_time_canvas` (line 105) PASSED; chain toolbar→chart_stack→MainWindow.canvas_fft_time is the same `SpectrogramCanvas` instance. |
| 2 | Boundary discipline (T2/T3/T4 disjoint surfaces) | PASS | Forbidden-symbol grep returned 0 leaks: `do_fft_time`, `_render_fft_time`, `_fft_time_cache`, `_get_fft_time_signal`, `FFTTimeWorker`, `_copy_fft_time_image` are all absent from `main_window.py`. T3 confined edits to `FFTTimeContextual` (no other class touched). T4 confined edits to `SpectrogramCanvas` (lines 1018-1300; `TimeDomainCanvas` 149-1017 and `PlotCanvas` 1301+ unchanged). |
| 3 | `FFTTimeContextual.get_params` keys (13 exact) | PASS | Runtime verified — keys returned: `signal, fs, nfft, window, overlap, remove_mean, amplitude_mode, db_reference, freq_auto, freq_min, freq_max, dynamic, cmap`. `set_signal_candidates` preserves selection by userData; `btn_compute.setEnabled` is the LAST statement (line 1007). `apply_builtin_preset` accepts `'diagnostic'`, `'amplitude_accuracy'`, `'high_frequency'` and values match design §7. `chk_freq_auto` toggles disable manual fields (`mf4_analyzer/ui/inspector_sections.py:968-971, 964-965`). `combo_dynamic` tokens `'80 dB' / '60 dB' / 'Auto'` (line 893) match canvas `_color_limits` consumer exactly. |
| 4 | `SpectrogramCanvas` correctness | PASS | `clear()` resets `_result`, `_selected_index`, `_db_cache`, axes/cursor refs and calls `fig.clear()` (lines 1069-1078); `plot_result` calls `self.clear()` first (line 1136). dB cache keyed by `(id(result), db_reference)` and stored on the canvas, not the result (lines 1217-1224). `_color_limits`: dB+'80 dB' → `(zmax-80, zmax)`, dB+'60 dB' → `(zmax-60, zmax)`, dB+'Auto' → `(nanmin, nanmax)`, linear → `(nanmin, nanmax)` (lines 1196-1205). `freq_range` fallback when `hi<=0 or hi<=lo` applied to both `_ax_spec.set_ylim` (line 1173) and `_ax_slice.set_xlim` (line 1248). Figure-level `mpl_connect` for click+motion with cids `_cid_click` / `_cid_motion` tracked (lines 1063-1064); `full_reset` disconnects and re-arms (lines 1099-1106). `cursor_info` emits empty on inaxes-mismatch and `_result is None` (lines 1276-1281). `select_time_index` clamps to `[0, frames-1]` (line 1260). |
| 5 | Tests run green | PASS | `pytest tests/ -v` exit 0, 112 passed, 0 failed, 0 errors, 0 warnings. Module-B subset: 45 passed. Signal-layer regression: 16 passed. |
| 6 | Cross-task flagged issues are honest | PASS | T3's flag re `signal_changed` not relayed by Inspector — verified accurate (declared at `inspector_sections.py:801`, emitted from `_on_sig_index_changed` at `:973-974`, no `inspector.py` listener). T4's flag re no manual `_db_cache` invalidation needed — verified accurate (`id(result)` is the cache axis; no in-place mutation paths exist on `SpectrogramResult.amplitude` or `.params` in either source or tests; grep over `mf4_analyzer/` and `tests/` returned 0 hits). |
| 7 | Cosmetic / hygiene | PASS-with-nits | See Nits 1-8. No unused imports, type hints absent on most methods (consistent with neighbor classes — no regression), docstrings consistent. Magic numbers `80.0`/`60.0` should ideally be a shared constants table. |
| 8 | Test quality (isolation / qtbot.addWidget / no global leaks) | PASS | All four new chart-stack tests use `qtbot.addWidget`; the three SpectrogramCanvas tests instantiate the canvas standalone (no MainWindow). `test_main_window_promotes_fft_time_canvas` uses `qtbot.addWidget(win)` and asserts identity end-to-end. `test_fft_time_*` tests instantiate `FFTTimeContextual()` standalone and use `qtbot.addWidget`. No global QApplication state mutation. Synthesized `MouseEvent` for hover test (`test_chart_stack.py:241`) is the established pattern in this repo. |

## Recommendation for Main Claude

**Approve and proceed to T5.** Module B is surgically scoped, fully tested,
and matches the spec. The two non-blocking handoffs (Important items 1 and
2) belong in the T5/T6 dispatch briefs:

- T6 brief should include: "add `inspector.py` relays for
  `fft_time_ctx.signal_changed` (mode `'fft_time'`) and
  `fft_time_ctx.rebuild_time_requested` (mode `'fft_time'`), paralleling
  the existing `fft_ctx` / `order_ctx` wiring at
  `mf4_analyzer/ui/inspector.py:81-82, 86-87`".
- T5 or T6 brief should include: "wire `canvas_fft_time.cursor_info(str)`
  to a visible UI surface — either the existing `MainWindow.statusBar` or
  a new mode-aware extension of `chart_stack.CursorPill` — per design §6.4".

No re-dispatch of T2/T3/T4 specialists is needed. The mechanical nits
(constants table for dynamic tokens; document panel-default-vs-preset
relationship) can be folded into a future cleanup PR or addressed
opportunistically when T7/T8 touch the same files.
