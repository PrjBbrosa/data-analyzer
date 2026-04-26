# T4 — FFT vs Time SpectrogramCanvas body

**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`, Task 5 (Steps 1–7).
**Specialist:** pyqt-ui-engineer.
**Date:** 2026-04-25.
**Note on naming:** the brief calls this "Plan Task 5" / "T4". Plan
section is Task 5; orchestrator slug is T4. Same work.

## Scope

Filled in the `SpectrogramCanvas` body that T2 left as a skeleton:

- `plot_result(result, amplitude_mode, cmap, dynamic, freq_range)` — the
  upper 2D `imshow` axis with colorbar, plus the lower 1D
  frequency-slice axis at `selected_index=0`, plus a white
  vertical cursor line at `times[0]`.
- `_color_limits(z, mode, dynamic)` — `(zmax-N, zmax)` for
  `'80 dB'` / `'60 dB'` in dB mode, `(nanmin, nanmax)` otherwise.
- `_display_matrix(result, mode)` — lazy dB cache keyed by
  `(id(result), db_reference)`, stored on the canvas (`self._db_cache`),
  not on the result.
- `_plot_slice()` — redraws the lower axis at the selected frame.
- `select_time_index(idx)` — clamps to `[0, frames-1]`, moves the
  cursor line, redraws the slice.
- `_on_click(event)` — selects the nearest time frame.
- `_on_motion(event)` — emits `cursor_info(str)` with
  `t / f / value unit`; emits empty string when the pointer leaves
  `_ax_spec` or before a result is plotted.
- mpl event wiring via figure-level `mpl_connect` with cids tracked on
  `self._cid_click` / `self._cid_motion`.
- `clear()` / `full_reset()` — reset all state; `full_reset()`
  disconnects and re-arms the mpl handlers per T2's flagged note.

## Files changed

- `mf4_analyzer/ui/canvases.py` — `SpectrogramCanvas` body filled in;
  no other classes touched.
- `tests/ui/test_chart_stack.py` — three new tests:
  `test_spectrogram_canvas_plots_main_and_slice`,
  `test_spectrogram_canvas_applies_dynamic_and_freq_range`,
  `test_spectrogram_canvas_emits_cursor_info_on_hover`.

## Symbols touched (per file)

- `mf4_analyzer/ui/canvases.py` — new attributes on
  `SpectrogramCanvas`: `_ax_spec`, `_ax_slice`, `_colorbar`,
  `_cursor_line`, `_cid_click`, `_cid_motion`. New methods:
  `_disconnect_mpl_handlers`, `plot_result`, `_color_limits`,
  `_display_matrix`, `_plot_slice`, `select_time_index`, `_on_click`,
  `_on_motion`. Extended methods: `__init__` (added cid tracking and
  axes/artist field declarations), `clear` (extended to reset
  axes/artist refs), `full_reset` (now disconnects-and-rearms cids).
- `tests/ui/test_chart_stack.py` — three new test functions; no
  changes to existing tests.

## Forbidden-symbol check

The brief restricted edits to **only** `SpectrogramCanvas` inside
`canvases.py`, plus the three named tests in `test_chart_stack.py`.
Forbidden neighbors and out-of-scope files:

| Forbidden symbol / region | Status |
|---|---|
| `TimeDomainCanvas` (lines 149–1017) | unchanged |
| `PlotCanvas` (lines 1301+) | unchanged |
| `OrderCanvas` | not present in this file |
| `CHART_FACE` / `GRID_LINE` / `PRIMARY` constants | imported (read-only) |
| `mf4_analyzer/ui/inspector_sections.py` (`FFTTimeContextual` — T3) | unchanged |
| `mf4_analyzer/ui/inspector.py`, `main_window.py`, `chart_stack.py`, `toolbar.py`, `icons.py` | unchanged |
| `mf4_analyzer/signal/*` | unchanged |

Verification commands run from project root:

```
grep -nE "plot_result|_color_limits|_display_matrix|_plot_slice|select_time_index|_db_cache|_disconnect_mpl_handlers|_cid_click|_cid_motion" mf4_analyzer/ui/canvases.py
# → all hits between line 1018 (class SpectrogramCanvas) and 1300
#   (just above class PlotCanvas on line 1301). No leakage into
#   TimeDomainCanvas (149–1017) or PlotCanvas (1301+).

grep -nE "^class " mf4_analyzer/ui/canvases.py
# → 149 TimeDomainCanvas, 1018 SpectrogramCanvas, 1301 PlotCanvas
#   — same three classes as before; no new classes introduced.
```

The pre-existing `TimeDomainCanvas._on_click` / `_on_motion` /
`PlotCanvas._on_click` are unrelated to my new
`SpectrogramCanvas._on_click` / `_on_motion` (the names are common
across mpl widgets); no shared helpers were introduced.

## Lessons-learned consultation

Per the startup protocol I read:

- `pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md` — the
  doc explicitly excludes figure-level `fig.canvas.mpl_connect()`
  events from the disconnect-before-rebuild discipline ("but NOT to
  figure-level events connected via `fig.canvas.mpl_connect()`,
  which have their own deletion semantics"). Searched canvases.py for
  any new `Axes.callbacks.connect` introductions:

  ```
  grep -n "callbacks.connect" mf4_analyzer/ui/canvases.py
  # → only pre-existing TimeDomainCanvas hits at lines 648 / 655.
  #   SpectrogramCanvas uses figure-level mpl_connect exclusively
  #   (lines 1063, 1064, 1104, 1105).
  ```

  T2's flagged note still asked for explicit cid bookkeeping on
  `full_reset`. I honored it: `_disconnect_mpl_handlers()` walks the
  two cid attributes, calls `self.mpl_disconnect`, and zeros them; the
  re-init at the end of `full_reset` re-arms them. So the canvas is
  safe even under the stricter axes-level lifetime rule, in case a
  future contributor mistakenly migrates to `Axes.callbacks`.

- `signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md` —
  the canvas-local `_db_cache` is read on the hot path. Verification:

  ```
  grep -n "_display_matrix\|_db_cache" mf4_analyzer/ui/canvases.py
  # → _display_matrix is the sole reader of _db_cache (line 1218).
  # → _display_matrix is called from plot_result (1148), _plot_slice
  #   (1234), and _on_motion (1286). Each of those is the canvas's
  #   per-render / per-interaction path, so the cache is on the hot
  #   path by construction.
  ```

  The cache is keyed by `(id(result), db_reference)`. Replotting the
  same result reuses the dB matrix; a new `SpectrogramResult` (different
  Python `id`) or a different reference invalidates implicitly. The
  cache lives on the canvas, NOT on `SpectrogramResult` — the result
  object stays immutable in observable behavior so the MainWindow's LRU
  result cache (Tasks 6–8) sees consistent payloads.

## Tests

Pre-T4 baseline (chart_stack only): `14 passed`.

Post-T4: `17 passed` (`14` pre-existing + `3` new).

```
PYTHONPATH=. .venv/bin/pytest tests/ui/test_chart_stack.py -v
# → 17 passed in 1.55s, no warnings
```

Full suite still green:

```
PYTHONPATH=. .venv/bin/pytest tests/ -v
# → 112 passed in 4.32s
```

Detail of the three new tests:

| Test | What it asserts |
|---|---|
| `test_spectrogram_canvas_plots_main_and_slice` | `fig.axes >= 2`, `selected_index() == 0` after `plot_result(amplitude_mode='amplitude')`. |
| `test_spectrogram_canvas_applies_dynamic_and_freq_range` | dB mode + `dynamic='60 dB'` → image clim span exactly `60.0`; `freq_range=(0, 150)` → ylim hi `<= 150`. |
| `test_spectrogram_canvas_emits_cursor_info_on_hover` | Synthesized `MouseEvent` at `(t=0.1, f=50)` → `cursor_info` emits a string containing `0.1` (matches the `"t=0.1"` precision-formatted readout). |

## Key decisions

- **Cid tracking even though figure-level mpl_connect survives
  `fig.clear()`.** The lessons-learned doc says we don't strictly need
  this for `mpl_connect`, but T2's flagged note explicitly asked for it.
  Cost is negligible (two attributes) and it future-proofs against any
  refactor that migrates to `Axes.callbacks`.
- **`_db_cache` key uses `id(result)`, not a value-based hash.** Per
  T1's choice of immutable result objects + MainWindow LRU caching of
  results, two different `SpectrogramResult` instances are never
  byte-identical from the canvas's perspective without a new `id`,
  and value-hashing a `(freq_bins × frames)` float32 array would defeat
  the cache. The plan's literal in Step 4 also uses `id(result)`.
- **`tight_layout` warning suppression.** mpl emits a `UserWarning`
  when colorbars sit alongside non-uniform subplot grids (our 3:1
  height-ratio gridspec triggers it). The `try/except` already swallowed
  the exception; I added a local `warnings.simplefilter('ignore', ...)`
  so the warning doesn't pollute test logs.
- **`select_time_index` clamps before mutating state.** This means
  programmatic out-of-range indices from MainWindow signal relays (e.g.
  on stale dispatches after a result swap) won't desync the cursor
  line.
- **`_on_motion` emits empty string on `inaxes is not _ax_spec`.**
  Matches the brief's "cursor_info signal emits the empty string when
  the pointer leaves `_ax_spec`" requirement. Also emits empty when
  `_result is None` so the readout pill clears between mode switches.
- **Defensive `if z.shape[0] == 0 or z.shape[1] == 0` in `_on_motion`.**
  `np.argmin` on an empty array would raise; guard rather than rely on
  callers to never construct empty results.

## UI verification

Per the system prompt's verification requirement, I exercised the
canvas in a live `QApplication`. macOS desktop session is a usable Qt
platform (`Darwin`, `cocoa` backend); used `QT_QPA_PLATFORM=offscreen`
in the bash invocation only because the agent's bash tool can't host
an interactive cocoa window.

Standalone canvas exercise:

```
init ok
linear plot ok; n_axes = 3
dB plot ok; clim span = 80.00; ylim = (0.0, 75.0)
select_time_index ok at 10
bounds clamp ok
db cache key1=(<id>, 1.0), key2=(<id>, 1.0), same id: True
full_reset ok; cids re-armed: 10 11
cursor_info empty-emit on no-result ok; seen[-1]= ''
ALL OK
```

End-to-end MainWindow round-trip:

```
MainWindow constructed
mode after click = fft_time
canvas_fft_time present: True
chart_stack widget index: 2
inspector contextual: fft_time
mode after back = time
OK
```

Both exit cleanly; no Qt warnings, no matplotlib warnings, no Python
warnings. `ui_verified: true`.

## Flagged issues

None blocking. One forward note for T6 (MainWindow synchronous compute
path):

- **For T6 (`pyqt-ui-engineer` for MainWindow analysis methods):**
  After computing a fresh `SpectrogramResult` and calling
  `canvas_fft_time.plot_result(...)`, you do NOT need to manually
  invalidate `canvas_fft_time._db_cache` — the `id(result)` change
  invalidates it implicitly. If you later add a "re-render same result
  with different `db_reference`" code path (e.g. a future
  `db_reference` UI control), note that the cache key includes
  `db_reference` so it will refresh automatically. The cache only
  needs an explicit clear if you start mutating
  `result.params.db_reference` in place — which T1 forbids by making
  `SpectrogramParams` a frozen dataclass. So no clear is needed in
  practice.

## Boundary discipline notes

This was T4 in a four-task sequence on `canvases.py`:
- T1 (signal layer) → no overlap with canvases.py.
- T2 (mode plumbing) → wrote the `SpectrogramCanvas` skeleton.
- **T4 (this task) → filled the body, kept entirely inside
  `SpectrogramCanvas` (lines 1018–1300).**
- T5–T8 (MainWindow analysis methods) → will not touch canvases.py.

The forbidden-symbol grep above demonstrates surgical scope: every new
method and attribute is namespaced under `SpectrogramCanvas`; no shared
helpers were introduced; no neighbor classes were touched.
