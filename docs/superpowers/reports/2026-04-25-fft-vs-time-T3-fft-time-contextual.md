# T3 — FFT vs Time inspector controls and presets

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 4 (Steps 1–7).
**Specialist:** pyqt-ui-engineer.
**Date:** 2026-04-25.

## Scope

Replace the T2 skeleton `FFTTimeContextual` body with the full Inspector
panel per design §6.2 (panel groups) and §7 (built-in presets). Preserve
the public surface T2 promised: the four signals, the disabled-by-default
`btn_compute`, and the enabled-state hook in `set_signal_candidates`.

No edits to other inspector classes, `inspector.py`, `canvases.py`,
`main_window.py`, or any signal-layer file.

## Files changed

- `mf4_analyzer/ui/inspector_sections.py` — `FFTTimeContextual` body
  replaced (in place; class signature, the four signals, and the
  `btn_compute` attribute/disabled-by-default behaviour preserved
  verbatim from T2).
- `tests/ui/test_inspector.py` — appended four tests covering the
  parameter getter, the disabled-button matrix, candidate-preservation
  on re-supply, and built-in presets.

No other files were touched. No files moved.

## Symbols touched (per file)

`mf4_analyzer/ui/inspector_sections.py` — only inside `FFTTimeContextual`:

- New widgets / attributes: `combo_sig`, `spin_fs`, `btn_rebuild`,
  `combo_nfft`, `combo_win`, `spin_overlap`, `chk_remove_mean`,
  `combo_amp_mode`, `spin_db_ref`, `chk_freq_auto`, `spin_freq_min`,
  `spin_freq_max`, `combo_dynamic`, `combo_cmap`,
  `btn_preset_diag`, `btn_preset_amp`, `btn_preset_hf`,
  `btn_force`, `btn_export_full`, `btn_export_main`. (`btn_compute`
  was kept from the skeleton.)
- New signals: `rebuild_time_requested(object)`, `signal_changed(object)`.
  (The four T2 signals — `fft_time_requested`,
  `force_recompute_requested`, `export_full_requested`,
  `export_main_requested` — were not redeclared.)
- New / replaced methods: `__init__`, `_update_freq_fields_enabled`,
  `_on_sig_index_changed`, `set_signal_candidates`, `current_signal`,
  `fs`, `set_fs`, `get_params`, `apply_builtin_preset`.
- New class-level constant: `_BUILTIN_PRESETS` mapping
  `'diagnostic' / 'amplitude_accuracy' / 'high_frequency'` to
  parameter dicts.

`tests/ui/test_inspector.py` — added:

- `test_fft_time_context_returns_params`
- `test_fft_time_compute_button_tracks_signal_candidates`
- `test_fft_time_signal_candidates_preserve_selection`
- `test_fft_time_context_builtin_presets`

## Forbidden-symbol check

Per the brief, this subtask must NOT touch:

- `mf4_analyzer/ui/canvases.py`
- `mf4_analyzer/ui/main_window.py`
- `mf4_analyzer/ui/toolbar.py`, `chart_stack.py`, `icons.py`
- `mf4_analyzer/signal/*`
- Any class in `inspector_sections.py` other than `FFTTimeContextual`

Verified by inspection that those files were not opened for write, and by
class-boundary check on `inspector_sections.py`:

```
$ grep -nE "class (FFTTimeContextual|TimeContextual|FFTContextual|OrderContextual|PersistentTop|PresetBar)" \
       mf4_analyzer/ui/inspector_sections.py
42:class PresetBar(QWidget):
268:class PersistentTop(QWidget):
383:class TimeContextual(QWidget):
406:class FFTContextual(QWidget):
559:class OrderContextual(QWidget):
757:class FFTTimeContextual(QWidget):
```

Pre-existing classes (`PresetBar`, `PersistentTop`, `TimeContextual`,
`FFTContextual`, `OrderContextual`) start at the same line numbers as
before the change — confirms no edits leaked across class boundaries.

The four T2 signals are still declared once each, in `FFTTimeContextual`:

```
$ grep -nE "fft_time_requested|force_recompute_requested|export_full_requested|export_main_requested" \
       mf4_analyzer/ui/inspector_sections.py
796:    fft_time_requested = pyqtSignal()
797:    force_recompute_requested = pyqtSignal()
798:    export_full_requested = pyqtSignal()
799:    export_main_requested = pyqtSignal()
959:        self.btn_compute.clicked.connect(self.fft_time_requested)
960:        self.btn_force.clicked.connect(self.force_recompute_requested)
961:        self.btn_export_full.clicked.connect(self.export_full_requested)
962:        self.btn_export_main.clicked.connect(self.export_main_requested)
```

(Plus the four matching docstring mentions at lines 765–768.)

The disabled-button hook is the LAST statement of
`set_signal_candidates`, so the ordering invariant T2 promised is
preserved:

```
$ grep -n "self.btn_compute.setEnabled" mf4_analyzer/ui/inspector_sections.py
936:        self.btn_compute.setEnabled(False)
1007:        self.btn_compute.setEnabled(self.combo_sig.count() > 0)
```

`inspector.py` was NOT modified — T2 left no TODOs there. Verified the
four relay connections survive intact:

```
$ grep -n "fft_time" mf4_analyzer/ui/inspector.py
12:    FFTTimeContextual,
22:    fft_time_requested = pyqtSignal()
23:    fft_time_force_requested = pyqtSignal()
24:    fft_time_export_full_requested = pyqtSignal()
25:    fft_time_export_main_requested = pyqtSignal()
61:        self.fft_time_ctx = FFTTimeContextual(self._scroll_body)
65:        self.contextual_stack.addWidget(self.fft_time_ctx)
92:        # FFT vs Time relays — Task 4 fills in the real controls; the
93:        # signals are declared on the skeleton so this wiring stays valid.
94:        self.fft_time_ctx.fft_time_requested.connect(self.fft_time_requested)
95:        self.fft_time_ctx.force_recompute_requested.connect(self.fft_time_force_requested)
96:        self.fft_time_ctx.export_full_requested.connect(self.fft_time_export_full_requested)
97:        self.fft_time_ctx.export_main_requested.connect(self.fft_time_export_main_requested)
100:        idx = {'time': 0, 'fft': 1, 'fft_time': 2, 'order': 3}[mode]
107:        return {0: 'time', 1: 'fft', 2: 'fft_time', 3: 'order'}[self.contextual_stack.currentIndex()]
```

## Tests

Baseline (before this task): full suite 105 passing, inspector subset 12.

Inspector subset after this task — 16 passing (12 baseline + 4 new):

```
$ PYTHONPATH=. .venv/bin/pytest tests/ui/test_inspector.py -v
...
tests/ui/test_inspector.py::test_inspector_exposes_fft_time_context PASSED
tests/ui/test_inspector.py::test_fft_time_context_returns_params PASSED
tests/ui/test_inspector.py::test_fft_time_compute_button_tracks_signal_candidates PASSED
tests/ui/test_inspector.py::test_fft_time_signal_candidates_preserve_selection PASSED
tests/ui/test_inspector.py::test_fft_time_context_builtin_presets PASSED
============================== 16 passed in 0.98s ==============================
```

Full suite — 112 passing. (Note: the +7 over baseline = 4 from this task
in `test_inspector.py` + 3 from the parallel T4 sister task in
`test_chart_stack.py` (`test_spectrogram_canvas_*`); none of those are
my files. No regressions in unrelated subsets.)

```
$ PYTHONPATH=. .venv/bin/pytest
============================= 112 passed in 4.06s ==============================
```

## UI verification

Display environment: `DISPLAY=`, no Wayland session — no real windowing
server in this sandbox, so I exercised the panel under
`QT_QPA_PLATFORM=offscreen` instead, which is the same backend used by
the test fixtures and is sufficient to surface signal/slot, layout, and
property-binding defects.

Affected feature exercised end-to-end:

1. `Inspector()` instantiation → `set_mode('fft_time')` → panel switches
   in.
2. `btn_compute` initial state: disabled.
3. `set_signal_candidates([])` → still disabled.
4. `set_signal_candidates([(text, (fid, ch)), ...])` → enabled.
5. `combo_sig.setCurrentIndex(1)` → `current_signal()` returns the
   second tuple.
6. Re-supply with a superset of candidates → previously-selected tuple
   stays selected (covers
   `test_fft_time_signal_candidates_preserve_selection`).
7. `chk_freq_auto` toggle → `spin_freq_min` / `spin_freq_max`
   `setEnabled` flips correctly (auto checked → disabled).
8. `apply_builtin_preset` for each of `diagnostic`,
   `amplitude_accuracy`, `high_frequency` → `get_params()` reflects
   the §7 preset values.
9. `get_params()` keys are the exact 13 expected by
   `MainWindow._fft_time_cache_key`: no extras, no missing.
10. Full-app smoke: `MainWindow()` → `toolbar.btn_mode_fft_time.click()`
    → `inspector.current_mode() == 'fft_time'`. Clicking each of
    `btn_compute / btn_force / btn_export_full / btn_export_main` fires
    the matching `Inspector.fft_time_*` relay signal.

All checks passed. `ui_verified: true`.

## Key decisions

- **Kept the four T2 signals exactly as declared** (no rename, no
  re-typing). The relay wiring in `inspector.py` is by attribute name
  on the contextual widget — re-declaring would silently shadow.
- **`set_signal_candidates` ordering:** the
  `self.btn_compute.setEnabled(self.combo_sig.count() > 0)` line is the
  LAST statement, after combo population and signal re-attachment. This
  is the T2-flagged invariant; placing it earlier would leave a window
  in which `combo_sig.count() > 0` but `btn_compute` is still in its
  pre-setEnabled state.
- **`signal_changed` / `_on_sig_index_changed` mirror `FFTContextual`,
  not the T2 skeleton.** T2's skeleton had no `signal_changed`. The
  real panel needs it for the same Fs auto-sync that `FFTContextual`
  uses (MainWindow listens via `Inspector.signal_changed` with mode
  parameter), but this is a wiring requirement at this level — `T5/T6`
  decide whether the inspector relays it as `signal_changed` with
  mode `'fft_time'`. I did NOT add the inspector-level relay; that
  would touch `inspector.py` and the brief restricts edits there to
  TODO cleanup only, of which there were none.
- **Preserve-selection match by userData (the `(fid, ch)` tuple), not by
  display text.** The plan's preservation test
  re-supplies the candidate list with the same userData but identical
  display text; tuple equality on userData is robust to either case.
- **Manual freq range fields auto-disabled when `chk_freq_auto` is
  checked** (small UX hint, no functional dependency). Initial state
  reflects the default `chk_freq_auto.isChecked() == True`, so manual
  fields start disabled — visually consistent with the design's
  "自动 / 手动锁定" text.
- **`spin_db_ref` widget added** even though the design copy reads
  "dB reference: 1 unit" as a fixed value. The plan's `get_params`
  schema includes `db_reference`, and the cache-key in T5 uses it via
  `params.get('db_reference', 1.0)`. Exposing a spinbox is the
  forward-compatible choice and keeps the value editable from the UI;
  default stays `1.0` so behaviour matches the design copy.
- **`spin_freq_max == 0.0` means "use Nyquist"** — chosen because the
  cache-key test in T5 (Step 1) uses `freq_max=0.0` for the auto case;
  the SpectrogramCanvas (T4) is expected to translate `0.0 → fs/2`.
  This is a contract between this panel and SpectrogramCanvas; no
  bookkeeping needed at the panel level.
- **Three preset buttons in a single row** rather than a `QComboBox`
  selector — direct one-click application, matches the design §6.2
  "预设" group spec, and the existing `FFTContextual` `PresetBar`
  pattern is reserved for user-saved slots (not re-used here in v1
  per the brief's narrower preset scope of §7 built-ins).
- **`btn_force / btn_export_full / btn_export_main` placed after the
  primary `btn_compute`** in their own row, with `role: tool` styling
  so they don't compete visually with the primary action. The existing
  `style.qss` already defines `role=tool` and `role=primary`, so no
  stylesheet edits were needed.

## Flagged issues

None blocking. Two forward notes (informational, not flags):

- **For T5 / T6 (cache + analysis path):** The design's "dynamic range"
  switches to linear color limits in `Amplitude` mode (per design §7
  closing paragraph). The current panel keeps the same
  `combo_dynamic` ('80 dB' / '60 dB' / 'Auto') in both modes; the
  consumer (SpectrogramCanvas + MainWindow) is expected to decide how
  to interpret 'Auto' under linear amplitude. No panel-side change
  required because the design treats the dynamic value as a string
  token, and `dynamic` is already part of the `get_params` dict.
- **For T6 (Fs auto-sync):** the new `signal_changed` signal on
  `FFTTimeContextual` is wired but NOT relayed by `Inspector` — to
  keep this subtask within `inspector_sections.py` only. If the
  MainWindow Fs-auto-sync logic for `fft_time` is enabled in T6,
  `inspector.py` will need a one-line relay
  `self.fft_time_ctx.signal_changed.connect(lambda d: self.signal_changed.emit('fft_time', d))`.
  This is mentioned here so the T6 specialist can add it inside their
  own `inspector.py` edit window without rework risk.

## Boundary discipline notes

This task touched the same `inspector_sections.py` file already touched
by T2. To stay within rework-detection rules:

- All edits were confined to the `FFTTimeContextual` class body.
- The four T2 signals were preserved verbatim (no re-declaration).
- The `btn_compute` attribute name and its disabled-by-default behaviour
  were preserved verbatim.
- The T2 `set_signal_candidates` enabled-state hook was preserved as
  the LAST statement of the new body, exactly as the T2 report's
  "flagged issues" section requested.

The forbidden-symbol enumeration in the T2 docstring was the cue list I
worked through; every name on it now exists exactly once, in
`FFTTimeContextual`, with the contracts the plan specifies.
