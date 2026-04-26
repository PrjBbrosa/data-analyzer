# T8 — FFT vs Time export to clipboard

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 9 (Steps 1–5).
**Specialist:** pyqt-ui-engineer.
**Date:** 2026-04-25.

## Scope

Wire the Inspector's two FFT-vs-Time export buttons (relay signals from
T2/T3) to a new `MainWindow._copy_fft_time_image(mode)` that copies the
canvas to the clipboard. Add the two pixmap accessors on
`SpectrogramCanvas` (`grab_full_view`, `grab_main_chart`). Reuse the
`has_result()` guard added in T4 so an empty canvas cannot push a blank
pixmap to the clipboard.

Also cleared the dangling Codex Module-C nit on `main_window.py:217`
that referenced T8 in a future tense — the comment now describes the
actual wiring.

## Files changed

- `mf4_analyzer/ui/canvases.py` — added `SpectrogramCanvas.grab_full_view`
  and `SpectrogramCanvas.grab_main_chart`. No other class touched, no
  edits to `plot_result` / `_color_limits` / `_display_matrix` /
  `_plot_slice` / `select_time_index` / `_on_click` / `_on_motion` /
  `clear` / `full_reset` / `selected_index` / `has_result` /
  `_db_cache`.
- `mf4_analyzer/ui/main_window.py` — added
  `MainWindow._copy_fft_time_image` after `_on_fft_time_thread_done`.
  Replaced the dangling T8-future-tense comment block at the
  fft_time wiring site with the real wiring (`fft_time_export_full_requested`
  and `fft_time_export_main_requested` connect to
  `_copy_fft_time_image`).
- `tests/ui/test_chart_stack.py` — added
  `test_spectrogram_canvas_export_pixmaps` (the test specified in
  Plan Task 9 Step 1, verbatim modulo the `# ---- Task 9` banner).
- `tests/ui/test_main_window_smoke.py` — added two tests:
  - `test_copy_fft_time_image_warns_when_no_result`
  - `test_copy_fft_time_image_pushes_pixmap_when_has_result`

No files moved, no signal-layer edits, no inspector / toolbar /
chart_stack / icons edits (T2 already had the relay signals wired).

## Symbols touched (per file)

`mf4_analyzer/ui/canvases.py`:
- `SpectrogramCanvas.grab_full_view` (new method)
- `SpectrogramCanvas.grab_main_chart` (new method)

`mf4_analyzer/ui/main_window.py`:
- `MainWindow._connect`: replaced the FFT-vs-Time wiring comment block
  and added two `connect(...)` lines for
  `fft_time_export_full_requested` / `fft_time_export_main_requested`.
- `MainWindow._copy_fft_time_image` (new method)

`tests/ui/test_chart_stack.py`:
- `test_spectrogram_canvas_export_pixmaps` (new)

`tests/ui/test_main_window_smoke.py`:
- `test_copy_fft_time_image_warns_when_no_result` (new)
- `test_copy_fft_time_image_pushes_pixmap_when_has_result` (new)

## Forbidden-symbol check

Per the brief, the following symbols are off-limits to T8. Verified
each one is unchanged (line offsets shifted only because new methods
were appended; bodies are untouched).

| Symbol / region | Owner | Touched? |
|---|---|---|
| `SpectrogramCanvas.plot_result` | T4 | NO |
| `SpectrogramCanvas._color_limits` | T4 | NO |
| `SpectrogramCanvas._display_matrix` | T4 | NO |
| `SpectrogramCanvas._plot_slice` | T4 | NO |
| `SpectrogramCanvas.select_time_index` | T4 | NO |
| `SpectrogramCanvas._on_click` | T4 | NO |
| `SpectrogramCanvas._on_motion` | T4 | NO |
| `SpectrogramCanvas.clear` | T4 | NO |
| `SpectrogramCanvas.full_reset` | T4 | NO |
| `SpectrogramCanvas.selected_index` | T4 | NO |
| `SpectrogramCanvas._db_cache` (cache logic) | T4 | NO |
| `SpectrogramCanvas.has_result` | T4 | NO (read only via guard) |
| `MainWindow.do_fft_time` | T5 | NO |
| `MainWindow._render_fft_time` | T5 | NO |
| `MainWindow._get_fft_time_signal` | T5 | NO |
| `MainWindow._normalize_freq_range` | T5 | NO |
| `MainWindow._on_fft_time_cursor_info` | T5 | NO |
| `MainWindow._on_fft_time_signal_changed` | T5 | NO |
| `MainWindow.FFTTimeWorker` (class) | T6 | NO |
| `MainWindow._on_fft_time_finished` / `_failed` / `_progress` / `_thread_done` | T6 | NO |
| `MainWindow._fft_time_cache_*` (key/get/put/clear_for_fid) | T5/T7 | NO |
| `MainWindow.close_all` / `_on_close_all_requested` / `_load_one` / `_close` / `_apply_channel_edits` / `_apply_xaxis` / `_show_rebuild_popover` | T7 cache hooks | NO |
| `inspector*.py`, `toolbar.py`, `chart_stack.py`, `icons.py` | T2/T3 | NO |
| `mf4_analyzer/signal/*` | T1/T2 | NO |

Verification commands:

```
$ awk '/^class SpectrogramCanvas/,/^class PlotCanvas/' mf4_analyzer/ui/canvases.py \
    | grep -nE "def "
# → Pre-existing (lines 26–259): __init__, clear, _disconnect_mpl_handlers,
#   full_reset, selected_index, has_result, plot_result, _color_limits,
#   _display_matrix, _plot_slice, select_time_index, _on_click, _on_motion.
# → New (lines 286, 297): grab_full_view, grab_main_chart.

$ grep -nE "def do_fft_time|def _render_fft_time|def _get_fft_time_signal|\
def _normalize_freq_range|def _on_fft_time|def _fft_time_cache_|class FFTTimeWorker|\
def _copy_fft_time_image" mf4_analyzer/ui/main_window.py
# → All pre-existing methods at expected lines (offset shifted +3 from
#   T7 baseline due to the wiring-comment-replacement at line 215).
# → _copy_fft_time_image is new at line 1418 (right after
#   _on_fft_time_thread_done at 1406).
```

## Tests

Pre-T8 baseline (per T7 report): 125 passed.

Post-T8: **128 passed** (3 new tests, 0 regressions).

```
$ PYTHONPATH=. .venv/bin/pytest
============================= 128 passed in 4.23s ==============================
```

Subset focused on the touched files:

```
$ PYTHONPATH=. .venv/bin/pytest tests/ui/test_chart_stack.py \
                                tests/ui/test_main_window_smoke.py -v
# → 41 passed (18 in test_chart_stack.py, 23 in test_main_window_smoke.py)
```

The three new tests:

| Test | What it asserts |
|---|---|
| `test_spectrogram_canvas_export_pixmaps` | After `plot_result`, both `grab_full_view()` and `grab_main_chart()` return non-null `QPixmap`. |
| `test_copy_fft_time_image_warns_when_no_result` | `has_result()==False` → warning toast fires; `QApplication.clipboard().setPixmap` is NOT called for either mode. |
| `test_copy_fft_time_image_pushes_pixmap_when_has_result` | After `plot_result`, both `mode='full'` and `mode='main'` push a non-null pixmap, set the Chinese status-bar message, and emit a success toast. |

## UI verification (live app)

Display environment: macOS desktop session (`Darwin`, `cocoa`-capable).
Agent bash drives `QT_QPA_PLATFORM=offscreen` because the harness
cannot host an interactive cocoa window; this is the same platform
the test fixtures use, sufficient to surface signal/slot, layout,
and clipboard-mutation defects (per T3/T4/T7 reports' precedent).

End-to-end exercise:

```
no-result guard ok; toasts =
  [('尚无 FFT vs Time 结果可导出', 'warning'),
   ('尚无 FFT vs Time 结果可导出', 'warning')]
full mode pushed pixmap; size = 640 x 404
main mode pushed pixmap; size = 510 x 253
inspector → mainwindow relay ok; relay grabs = 2
statusBar last message = 已复制 FFT vs Time 主图
toasts =
  [('已复制 FFT vs Time 完整视图', 'success'),
   ('已复制 FFT vs Time 主图', 'success'),
   ('已复制 FFT vs Time 完整视图', 'success'),
   ('已复制 FFT vs Time 主图', 'success')]
ALL OK
```

What the live exercise covers:

1. **No-result path:** with no `SpectrogramResult` plotted, both
   `mode='full'` and `mode='main'` emit a warning toast and DO NOT
   touch the clipboard (`pushed == []`).
2. **Plotted-result path, full mode:** `setPixmap` receives a 640×404
   QPixmap (whole canvas).
3. **Plotted-result path, main mode:** `setPixmap` receives a 510×253
   QPixmap — strictly smaller than full, confirming the bbox crop
   excluded the lower frequency-slice region. The bbox crop succeeded
   under offscreen Qt; the full-canvas fallback inside
   `grab_main_chart` was NOT exercised on this platform.
4. **Inspector relay:** clicking
   `inspector.fft_time_ctx.btn_export_full` / `.btn_export_main`
   propagates through `Inspector.fft_time_export_full_requested` /
   `fft_time_export_main_requested` (T2 wiring) and ultimately calls
   `_copy_fft_time_image(mode='full' / 'main')`. Two clicks → two
   `setPixmap` calls.
5. **Status-bar / toast:** Chinese success strings (`已复制 FFT vs Time
   完整视图` / `主图`) reach both the status bar (`showMessage(..., 2000)`)
   and the toast helper (`level='success'`).

`ui_verified: true`.

## Key decisions

- **`grab_main_chart` bbox crop with full-canvas fallback.** The plan's
  Step 2 explicitly permits "if axis-bbox cropping is fragile under
  pytest-qt headless, return `self.grab()` in Phase 1 and document the
  limitation". I implemented the bbox crop with a defensive fallback
  inside the same method:
  - Read `self._ax_spec.get_tightbbox(renderer)` and (if present)
    `self._colorbar.ax.get_tightbbox(renderer)`; union the two.
  - Convert matplotlib's bottom-left figure-pixel coords to Qt's
    top-left widget-pixel coords (`fig_h - y1`).
  - Fall back to `self.grab()` if (a) `_ax_spec` is `None` (no plot
    yet), (b) the resulting rect is degenerate (`qw < 10` or
    `qh < 10`), (c) `self.grab(rect)` returns a null pixmap, or
    (d) any exception is raised in the bbox/transform path.
  - Live-app exercise above showed the bbox crop succeeded under
    `QT_QPA_PLATFORM=offscreen` (510×253 main vs 640×404 full); the
    fallback is preserved as defense-in-depth for platforms where
    layout is not realized.
- **Clipboard mutation guarded by `has_result()`.** The `MainWindow`
  guard ensures that even if a future caller invokes
  `_copy_fft_time_image` before the canvas is ready, the clipboard
  is not overwritten with garbage. The canvas-side `grab_main_chart`
  also defensive-falls back to `grab_full_view` rather than producing
  a null pixmap; the two layers compose correctly.
- **`statusBar` is an attribute, not a method.** Codebase convention
  per the brief and the T5 cache-hit test: `self.statusBar.showMessage(msg, 2000)`,
  not `self.statusBar()`. The plan template's example used `()` —
  honored the codebase quirk over the plan template.
- **Comment cleanup at line 215.** Replaced the
  "T8's `_copy_fft_time_image` ... not implemented in this task ...
  wire them via lambdas using getattr" block with the actual two
  `connect(...)` lines and a one-line comment that says what the
  wiring does. No `getattr` indirection — the method now exists.
- **Did NOT redeclare relay signals on `Inspector`.** T2 already
  declared `fft_time_export_full_requested` and
  `fft_time_export_main_requested` and wired them to
  `fft_time_ctx.export_full_requested` / `.export_main_requested`
  (`inspector.py:24–25, 102–103`). T3 confirmed the wiring; this
  task only had to subscribe in `MainWindow._connect`.
- **Lambda-wrapped `mode` argument** when connecting export signals.
  The PyQt5 `pyqtSignal` connection emits a tuple; binding `mode='full'`
  / `mode='main'` via `lambda` keeps the slot signature explicit and
  avoids relying on positional-keyword coercion at the connect site.
- **Test choices:**
  - `test_copy_fft_time_image_warns_when_no_result` monkeypatches
    `cb.setPixmap` so we can assert it was NOT called — the only
    way to verify the guard's clipboard side without polluting the
    real OS clipboard.
  - `test_copy_fft_time_image_pushes_pixmap_when_has_result`
    monkeypatches `cb.setPixmap` for the same reason and also lets
    us assert the pixmap is non-null and that calls accumulate
    across modes.
  - Both tests use `monkeypatch.setattr(win, 'toast', ...)` to
    capture toasts without depending on the timer-driven
    `_toast.show_message` widget.
  - `test_spectrogram_canvas_export_pixmaps` is the verbatim
    plan-Step-1 test; kept as-is.

## Flagged issues

None blocking.

One forward note for **T9 / T10** (validation report owner — the user-
facing manual verification step):

- The bbox crop in `grab_main_chart` worked under offscreen Qt in the
  agent bash sandbox, but the validation report should still record a
  manual user check on the cocoa desktop platform: open the app,
  compute an FFT vs Time result, click the two export buttons, paste
  into Preview / a clipboard inspector, and confirm the "main" image
  shows only the spectrogram + colorbar (no time-slice strip below).
  If a user-reported regression turns up where main and full produce
  identical pixmaps on macOS, the symptom would be the
  `qw < 10 or qh < 10` fallback firing — flag back to pyqt-ui at that
  point with a screenshot and the canvas size; we can tighten the
  bbox-degenerate threshold or migrate to `Bbox.union` from
  `matplotlib.transforms` if needed.

## Boundary discipline notes

This was T8 in the FFT-vs-Time sequence (T1 signal layer → T2 plumbing
→ T3 inspector → T4 canvas → T5 main_window sync compute → T6 worker
→ T7 cache invalidation → **T8 export, this task** → T9 + T10 review
and validation).

The same files (`canvases.py`, `main_window.py`) have been touched by
multiple specialists. Boundary discipline:

- All `canvases.py` edits confined to `SpectrogramCanvas` body, after
  `_on_motion`, before `class PlotCanvas`. Two new methods
  (`grab_full_view`, `grab_main_chart`); no edits to any of the 13
  pre-existing methods. Forbidden-symbol grep above demonstrates this.
- All `main_window.py` edits confined to (a) the FFT-vs-Time wiring
  block in `_connect` (replaced a comment block plus two new
  `connect(...)` lines), and (b) one new method
  (`_copy_fft_time_image`) appended after `_on_fft_time_thread_done`.
  No edits to forbidden T5/T6/T7 methods.
- The Inspector relay signals (`fft_time_export_full_requested`,
  `fft_time_export_main_requested`) were already wired by T2; this
  task only subscribed to them.
- Tests added in append-only mode (no edits to existing tests).
