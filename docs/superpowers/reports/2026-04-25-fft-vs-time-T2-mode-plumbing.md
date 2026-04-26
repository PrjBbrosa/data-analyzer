# T2 — FFT vs Time mode plumbing (skeleton + canvas promotion)

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 3 (Steps 1–11).
**Specialist:** refactor-architect.
**Date:** 2026-04-25.

## Scope

End-to-end plumbing for the new fourth UI mode `fft_time`, plus the
`canvas_fft_time` promotion onto `MainWindow` (the gap that broke the
first plan revision). Skeleton bodies only — Task 4 fleshes out
`FFTTimeContextual`, Task 5 fleshes out `SpectrogramCanvas`,
Task 5/6/7/8 fill in `MainWindow` analysis methods and cache hooks.

## Files changed

- `mf4_analyzer/ui/icons.py` — added `Icons.mode_fft_time()` factory.
- `mf4_analyzer/ui/toolbar.py` — added `btn_mode_fft_time`, included it
  in icon-size loop, `_mode_group`, `_wire()` and `_set_mode()` mappings;
  updated `mode_changed` docstring.
- `mf4_analyzer/ui/canvases.py` — added `SpectrogramCanvas` SKELETON
  (signal + `__init__` + `clear` + `full_reset` + `selected_index` +
  `has_result`).
- `mf4_analyzer/ui/chart_stack.py` — imported `SpectrogramCanvas`,
  instantiated `canvas_fft_time` and `_fft_time_card`, inserted into
  the QStackedWidget at index 2 (between fft and order), added it to
  `copy_image_requested` wiring loop and `full_reset_all()`; updated
  `_MODE_TO_INDEX` to `{'time': 0, 'fft': 1, 'fft_time': 2, 'order': 3}`.
- `mf4_analyzer/ui/inspector_sections.py` — added `FFTTimeContextual`
  SKELETON with the four required signals and a disabled-by-default
  `btn_compute`; trivial `set_signal_candidates`.
- `mf4_analyzer/ui/inspector.py` — imported `FFTTimeContextual`,
  declared the four relay signals, instantiated `fft_time_ctx`, added
  it to the contextual stack at index 2, wired the four relays,
  updated `set_mode`/`contextual_widget_name` to include `fft_time`,
  added `current_mode()` getter (the inspector test expects it).
- `mf4_analyzer/ui/main_window.py` — **single line added** after the
  existing canvas-promotion block:
  `self.canvas_fft_time = self.chart_stack.canvas_fft_time`.
- `tests/ui/test_toolbar.py` — added `test_toolbar_exposes_fft_time_mode`.
- `tests/ui/test_chart_stack.py` — added `test_chart_stack_exposes_fft_time_card`;
  bumped count assertion in pre-existing `test_chart_stack_has_three_canvases`
  from `3` to `4` (test name kept intentionally — git history alignment).
- `tests/ui/test_inspector.py` — added `test_inspector_exposes_fft_time_context`.
- `tests/ui/test_main_window_smoke.py` — added
  `test_main_window_promotes_fft_time_canvas`.

## Symbols touched (per file)

- `mf4_analyzer/ui/icons.py`: `Icons.mode_fft_time` (new classmethod).
- `mf4_analyzer/ui/toolbar.py`: `Toolbar.btn_mode_fft_time` (attr),
  `Toolbar.__init__` (extended icon-size and `_mode_group` lists),
  `Toolbar._wire` (extended mapping), `Toolbar._set_mode` (extended
  mapping), `mode_changed` signal docstring.
- `mf4_analyzer/ui/canvases.py`: `SpectrogramCanvas` (new class with
  `cursor_info` signal, `__init__`, `clear`, `full_reset`,
  `selected_index`, `has_result`).
- `mf4_analyzer/ui/chart_stack.py`: import line
  (`SpectrogramCanvas`), `_MODE_TO_INDEX`, `ChartStack.__init__`
  (added `canvas_fft_time`, `_fft_time_card`, stack insert,
  copy-image wiring), `ChartStack.full_reset_all` (added
  `canvas_fft_time.full_reset()`).
- `mf4_analyzer/ui/inspector_sections.py`: `FFTTimeContextual` (new
  class with `fft_time_requested`, `force_recompute_requested`,
  `export_full_requested`, `export_main_requested` signals,
  `__init__`, `set_signal_candidates`).
- `mf4_analyzer/ui/inspector.py`: import line (`FFTTimeContextual`);
  new signals `fft_time_requested`, `fft_time_force_requested`,
  `fft_time_export_full_requested`, `fft_time_export_main_requested`;
  `Inspector.__init__` (instantiation + stack insert + relay wiring);
  `Inspector.set_mode` (added 'fft_time' index), `Inspector.current_mode`
  (new getter), `Inspector.contextual_widget_name` (extended dict).
- `mf4_analyzer/ui/main_window.py`: `MainWindow._init_ui` only — single
  attribute alias `self.canvas_fft_time = self.chart_stack.canvas_fft_time`.

## Forbidden-symbol check

Per the brief, the following symbols are **off-limits** to T2 (they
belong to T4/T5/T6/T7/T8). I greped each one in the touched files and
confirmed zero introductions in the diff. Pre-existing matches in
unrelated classes (`TimeDomainCanvas._on_click`, `PlotCanvas._on_click`)
are unchanged.

| Symbol | File expected | Found in T2 diff? |
|---|---|---|
| `SpectrogramCanvas.plot_result` | canvases.py | NO |
| `SpectrogramCanvas._color_limits` | canvases.py | NO |
| `SpectrogramCanvas._display_matrix` | canvases.py | NO |
| `SpectrogramCanvas._plot_slice` | canvases.py | NO |
| `SpectrogramCanvas.select_time_index` | canvases.py | NO |
| `SpectrogramCanvas._on_click` | canvases.py | NO |
| `SpectrogramCanvas._on_motion` | canvases.py | NO |
| `SpectrogramCanvas._db_cache` (fill logic) | canvases.py | NO (declared as `None` only) |
| `FFTTimeContextual.combo_sig` | inspector_sections.py | NO |
| `FFTTimeContextual.combo_nfft` | inspector_sections.py | NO |
| `FFTTimeContextual.combo_win` | inspector_sections.py | NO |
| `FFTTimeContextual.spin_overlap` | inspector_sections.py | NO |
| `FFTTimeContextual.combo_amp_mode` | inspector_sections.py | NO |
| `FFTTimeContextual.combo_dynamic` | inspector_sections.py | NO |
| `FFTTimeContextual.combo_cmap` | inspector_sections.py | NO |
| `FFTTimeContextual.chk_freq_auto` | inspector_sections.py | NO |
| `FFTTimeContextual.spin_freq_min` / `spin_freq_max` | inspector_sections.py | NO |
| `FFTTimeContextual.btn_force` / `btn_export_full` / `btn_export_main` | inspector_sections.py | NO |
| `FFTTimeContextual.get_params` / `apply_builtin_preset` | inspector_sections.py | NO |
| `FFTTimeContextual.current_signal` / `set_fs` | inspector_sections.py | NO |
| `MainWindow.do_fft_time` | main_window.py | NO |
| `MainWindow._render_fft_time` | main_window.py | NO |
| `MainWindow._fft_time_cache_*` | main_window.py | NO |
| `MainWindow._get_fft_time_signal` | main_window.py | NO |
| `MainWindow.FFTTimeWorker` | main_window.py | NO |
| `MainWindow._copy_fft_time_image` | main_window.py | NO |

Verification commands run from project root:

```
grep -nE "plot_result|_color_limits|_display_matrix|_plot_slice|select_time_index|_on_click|_on_motion" mf4_analyzer/ui/canvases.py
# → only pre-existing matches in TimeDomainCanvas / PlotCanvas + the
#   docstring marker inside SpectrogramCanvas listing the forbidden names.

awk '/^class SpectrogramCanvas/,/^class [^S]|\Z/' mf4_analyzer/ui/canvases.py \
  | grep -cE "def plot_result|def _color_limits|def _display_matrix|def _plot_slice|def select_time_index|def _on_click|def _on_motion"
# → 0

awk '/^class FFTTimeContextual/,/^class [^F]|\Z/' mf4_analyzer/ui/inspector_sections.py \
  | grep -nE "combo_sig|combo_nfft|combo_win|spin_overlap|combo_amp_mode|combo_dynamic|combo_cmap|chk_freq_auto|spin_freq_min|spin_freq_max|btn_force|btn_export_full|btn_export_main|get_params|apply_builtin_preset|current_signal|set_fs"
# → only docstring marker + one inline comment reference; no symbols
#   declared in the class body.

grep -nE "do_fft_time|_render_fft_time|_fft_time_cache|_get_fft_time_signal|FFTTimeWorker|_copy_fft_time_image" mf4_analyzer/ui/main_window.py
# → 0
```

The single docstring inside `SpectrogramCanvas` and the docstring
inside `FFTTimeContextual` deliberately enumerate the forbidden
symbols as a marker for the next reviewer / Task 4–5 specialists, in
line with the boundary discipline lessons:

- `orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`

## Tests

Baseline (pre-T2): full suite `pytest` from `PYTHONPATH=.`, 101 tests
pass.

Post-T2: full suite, 105 tests pass (4 new tests).

UI plumbing subset (the four files in the brief):

```
PYTHONPATH=. pytest tests/ui/test_toolbar.py tests/ui/test_chart_stack.py \
                    tests/ui/test_inspector.py \
                    tests/ui/test_main_window_smoke.py -v
# → 38 passed
```

Including the canvas-promotion smoke test:

```
PYTHONPATH=. pytest tests/ui/test_main_window_smoke.py::test_main_window_promotes_fft_time_canvas -v
# → 1 passed
```

## Key decisions

- **Stack ordering chosen as `time / fft / fft_time / order`.** This
  matches the plan's `_MODE_TO_INDEX` literal verbatim and keeps the
  pre-existing `_fft_card` test (`cs.stack.widget(1)`) valid. The new
  card lives at index 2; `order` shifts to index 3.
- **Pre-existing `test_chart_stack_has_three_canvases` was updated
  in-place** to `assert cs.count() == 4` rather than renamed. The
  test name is now historically misleading, but renaming would be a
  larger churn and the assertion change is the minimal-impact path.
  A clarifying comment was added.
- **`Inspector.current_mode()` was added** because the plan's Step 7
  test asserts `inspector.current_mode() == 'fft_time'`. Implemented
  as a thin alias over `contextual_widget_name()` so we did not have
  to introduce a new state field; this keeps the change additive and
  the existing `set_mode` / `contextual_widget_name` API intact.
- **Skeleton-only discipline:** every new method body is the minimum
  the plan dictates. `SpectrogramCanvas` does not connect any
  matplotlib events. `FFTTimeContextual.set_signal_candidates` only
  toggles the compute button enabled state — no combo-box population.
  Task 4 (UI parameters / presets) and Task 5 (canvas rendering and
  click/motion handlers) own everything else.
- **`Toolbar.set_enabled_for_mode`** was NOT extended for `'fft_time'`
  — the existing `is_time = (mode == 'time')` check correctly
  disables `btn_cursor_reset` and `btn_axis_lock` for any non-time
  mode (`'fft'`, `'fft_time'`, `'order'`). No code change needed.
- **`mode_fft_time` icon** uses three horizontal bands of decreasing
  length anchored to a y-axis spine — a time-frequency stack glyph
  visually distinct from `mode_fft` (vertical bars) and `mode_order`
  (3x3 grid).

## Flagged issues

None blocking. Two follow-ups for downstream specialists:

- **For T4 (`pyqt-ui-engineer` / `signal-processing-expert`, whichever
  owns `FFTTimeContextual` body):** The skeleton's
  `set_signal_candidates` only flips `btn_compute.setEnabled` based on
  truthiness. When you replace the body with the real combo-box
  population, remember to keep the enabled-state hook so the
  end-to-end mode-change → button-enable flow keeps working.
- **For T5 (`pyqt-ui-engineer` for canvas rendering):**
  `SpectrogramCanvas.full_reset` currently just calls `clear()` then
  `draw_idle()`. When you wire blitting / matplotlib callbacks in
  Task 5, ensure `full_reset` also clears any registered
  `mpl_connect` cids per
  `pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md`. The
  skeleton intentionally registers no callbacks so this is a
  forward-compat note, not a current bug.

## Boundary discipline notes

This task is the second of a sequence (T1 signal layer → T2 mode
plumbing → T3 UI panel → T4 canvas rendering → T5–T8 main_window
analysis). The same files (`canvases.py`, `inspector_sections.py`,
`main_window.py`) are touched by multiple tasks. To keep
rework-detection from firing falsely, both new classes
(`SpectrogramCanvas`, `FFTTimeContextual`) carry a docstring listing
the forbidden symbols verbatim — this is the "name the rewriter"
pattern from the boundary-disjoint lesson, applied at the source
file rather than the orchestrator brief level.
