# Robustness Remediation Phase 1 Design

**Status:** Implemented and integrated on 2026-07-30. W1a/W1b/W1c, W2, W3,
and the W4 evidence report shipped in the working tree. The final default suite
has the exact same 64 pre-existing failing node IDs as the baseline, plus 64
new passing tests (`4,117 passed / 64 failed / 8 skipped / 3 deselected`). W3
was rerouted from `refactor-architect` to `pyqt-ui-engineer` because the former's
write boundary excludes UI-state function bodies. Cocoa startup, logging,
interaction probes, and a real-window W3 harness were verified; Windows
`--windowed` packaging remains unrun and its paths/hooks are test-verified only.

**Baseline commit:** `b5d7956eb8c80c7981d174ed92575e876d171c2b` (`main`, 2026-07-30).
Every measurement quoted here was taken on that SHA with
`.venv/bin/python` (Python 3.12.13, Qt 5.15.14 / PyQt5 5.15.11, numpy 2.5.1,
pyqtgraph 0.14.0) on macOS 27.0 arm64.

**Source audit:** `docs/robustness-audit-2026-07-30.md` (rev2, post-codex-review).
**Companion plan:** `docs/superpowers/plans/2026-07-30-robustness-remediation-phase1.md`

---

## 1. Summary

Phase 1 fixes what has been **reproduced end-to-end**, then builds the
observability floor needed before any structural work, then removes the two
ownerless canvas state slots that reproduction has already proven dead or
unowned. It deliberately does **not** touch `canvas.py`'s size, the 288 broad
silent exception handlers as a batch, or the test suite's white-box style.

Six work packages:

| Package | Deliverable | Type |
|---|---|---|
| **W1a** | `restore_visible_ylims` fits new channels using the composite channel key, not the display label | correctness fix |
| **W1b** | `ChannelMath.moving_avg` output length always equals input length; `integral` always returns float; `signal/channel_math.py` gets its first test file | correctness fix |
| **W1c** | `_ChannelKeyDict.copy` / `update` / `setdefault` stop losing or corrupting same-name entries; the unfixable `dict(d)` collapse is pinned by a baseline test | latent-defect fix |
| **W2** | Cross-platform, rotating, rate-limited diagnostic logging plus `sys.excepthook` / `threading.excepthook` / `qInstallMessageHandler`, wired into 5–10 named state/coordinate seams | infrastructure |
| **W3** | `canvas._refresh` deleted; `_channel_render_profiles` gets an owner; `AnnotationManager._artist` moves into `_owned_names`; a `_CanvasBackref` write-through whitelist test locks the invariant | state hygiene |
| **W4** | A stratified classification of the 1,232 private-attribute assertions, written up as a report | evidence gathering, no production change |

W1a/W1b/W1c are independent and may run in parallel. W2 precedes W3 so the
deletions in W3 land with observability in place. W4 is independent of all of
them and gates Phase 2.

---

## 2. Evidence

### 2.1 W1a — same-name channel Y-axis crosstalk

`ui/pg_canvas/canvas.py:2043-2054`. When only *some* channels in a View have a
saved Y range, the rest go through a "new channel, auto-fit" fallback. That
fallback converts the composite key back to a **display label**:

```python
for key, (handle, line) in view_state_lines.items():   # key IS the composite key
    if key in restored_keys:
        continue
    get_label = getattr(line, "get_label", None)
    channel_name = get_label() if callable(get_label) else key   # <- drops identity
    if self._fit_channel_y_to_visible_x(channel_name, handle, n_y, ...):
```

`_fit_channel_y_to_visible_x` (canvas.py:2064) then does
`self.channel_data.get(name)`. `channel_data` is a `_ChannelKeyDict` whose
`_resolve` is documented *"Last-bound wins for an ambiguous bare-name read"*
(`_shared.py:99-101`). Two files whose `short_name` middle-ellipsis truncation
collides therefore share one display label, and the fallback fits file A's axis
using file B's samples.

Reproduced on a real `TimeDomainCanvasPG` (audit appendix A-11):

```
display name A == display name B == '[measurem…_run_2026] sig'
file A samples in [-1, 1]        file B samples in [100, 200]

before restore:  A=(-1.0, 1.0)                       B=(100.0, 200.0)
after  restore:  A=(95.0000169803578, 204.9999830196422)   B=(100.0, 200.0)
```

Fix viability was verified in the same probe. `channel_data`'s storage keys and
`_channel_view_state_lines`'s keys are the **same set**:

```
channel_data keys     == ['["fid-A","[measurem…_run_2026] sig"]', '["fid-B",...]']
view_state_lines keys == ['["fid-A","[measurem…_run_2026] sig"]', '["fid-B",...]']
equal                 == True

channel_data.get(composite A) -> min/max -1.000/1.000
fit with COMPOSITE key        -> (-1.0999, 1.0999)      <- correct
```

`_fit_channel_y_to_visible_x` has exactly one caller in the whole repository,
so the blast radius is one function plus its single call site.

### 2.2 W1b — `moving_avg` output length, `integral` dtype

`signal/channel_math.py` is 22 lines and has **zero test coverage** — the only
module in `signal/` with no test file referencing it:

```
fft: 80   order: 115   weighting: 29   spectrogram: 23   filters: 18
envelope: 13   adaptive: 2   _envelope_cutils: 2   __init__: 49
channel_math: 0        <- the only zero
```

`tests/ui/test_dialogs.py` calls `dlg._create_single()` twice, but only on error
branches (missing source channel, unknown op index). No `ChannelMath` operation
is ever actually executed by a test.

`np.convolve(..., mode='same')` returns `max(len(sig), ws)` elements:

| `len(sig)` | `ws` | `len(out)` |
|---:|---:|---:|
| 3 | 50 | **50** |
| 10 | 100 | **100** |
| 2000 | 5000 | **5000** |
| 1000 | 50 | 1000 |

Reachable from the UI: `ui/dialogs.py:362` calls
`ChannelMath.moving_avg(sig, max(int(p), 3))` where `p` comes from `spin_p`,
whose range is `±1e12` (`dialogs.py:125`) with no per-channel-length bound. The
created channel's data array is then longer than its time axis.

`integral` inherits the input dtype via `np.zeros_like`:

```
t=[0,1,2,3], sig=[0,1,2,3]
int   input -> [0 0 2 4]        dtype=int64     <- the .5 terms are truncated
float input -> [0. 0.5 2. 4.5]
```

This is **not reachable from the dialog** — `dialogs.py:347` does
`.astype(float)` before the call. It is still an API contract defect worth
fixing given zero test coverage, but its severity is latent, not live.

Third boundary: `derivative` raises `IndexError` from inside `np.gradient` on a
0-sample input, and `moving_avg` raises `ValueError: a cannot be empty`. Both
raise rather than corrupt, and `dialogs.py` turns them into
`QMessageBox.critical(str(e))`, so the user sees a numpy-internal message.

### 2.3 W1c — `_ChannelKeyDict` dict-protocol escapes

`_shared.py:25`. The class overrides `__iter__` / `keys` / `values` / `items` /
`__getitem__` / `get` / `__contains__` / `pop` / `__delitem__` / `clear`, but
not `update` / `setdefault` / `copy`. Measured:

```
len(d) = 2   items() = [('torque','A-data'), ('torque','B-data')]

dict(d)                      -> {'torque': 'B-data'}   len 1   A-data lost
{**d}                        -> {'torque': 'B-data'}   len 1
{k: v for k, v in d.items()} -> {'torque': 'B-data'}   len 1
d.copy()                     -> {'torque': 'B-data'}   len 1, plain dict
e.update(d)                  -> {'torque': 'B-data'}   len 1
```

`setdefault` is worse than unprotected — it actively corrupts:

```
d.setdefault('torque', 'X')  -> returns 'X'   (NOT the existing 'B-data')
len(d)                       -> 3
composite_items()            -> [('["fileA","torque"]', 'torque', 'A-data'),
                                 ('["fileB","torque"]', 'torque', 'B-data'),
                                 ('torque',             'torque', 'X')]
```

`dict.setdefault` bypasses the overridden `__contains__`, so it inserts a third
entry keyed by the **bare display name**. `_resolve` then short-circuits on
`dict.__contains__(self, 'torque')` and every subsequent bare-name read returns
`'X'`, masking both real channels.

No live `dict(...)` / `setdefault` call site exists today (grepped). This is a
mine, not a wound.

### 2.4 W2 — no observability floor

- `sys.excepthook` / `qInstallMessageHandler`: **0 occurrences** across
  `mf4_analyzer/`, `tools/`, `scripts/`.
- `mf4_analyzer/app.py` `main()` configures HiDPI, fonts, stylesheet, tooltips,
  icon — and nothing else. No `logging.basicConfig`, no level, no rotation,
  no retention.
- `logging.getLogger` appears in 12 files; in `ui/` only `line_canvas.py` and
  `renderer.py`.
- PyQt 5.5+ calls `abort()` on an unhandled exception escaping a slot, so the
  process can die with no artifact at all.
- The only packaging script is `tools/build_windows_folder.ps1`, and it defaults
  to `--windowed` (line 272), i.e. the GUI subsystem with no console. There is
  no macOS packaging script. Any log location must therefore be correct on
  Windows first.
- `ui/pg_canvas` has **288** `except Exception: pass` handlers (of 296 silent
  ones); many sit inside pan/zoom, draw, and cursor paths.

### 2.5 W3 — dead and ownerless canvas state

`canvas._refresh`: 19 writes across 6 files, **0 production reads**. The only
reader is `tests/ui/test_pg_timedomain_canvas.py:1533-1538`. Deletion safety was
additionally checked three ways:

- no `def _refresh(` anywhere in `mf4_analyzer/` — no method is being shadowed
  by the boolean;
- `_refresh` is not a class attribute of `TimeDomainCanvasPG` nor of any Qt /
  pyqtgraph base — `hasattr(TimeDomainCanvasPG, '_refresh')` is `False` before
  instantiation;
- the neighbouring names `_refresh_pending`, `_refresh_timer`,
  `_refresh_visible_data`, `_refresh_overlay_axis_labels` are all **live** and
  must not be touched.

`_channel_render_profiles`: 3 lazy-creation sites (`renderer.py:527-530`,
`overlay_axes.py:315-318`, `overlay_axes.py:425-428`), 5 read sites
(`dense_raster.py:241/403/435`, `quality.py:88/300`), and no initialization or
reset anywhere. Its entries are `RenderProfile` — a frozen dataclass of 9
scalar/small-tuple fields holding **no ndarray**, ≈380 bytes per entry
(≈3.6 MiB at 10,000 stale entries). So the defect is lifecycle and
comprehensibility, not memory exhaustion.

`_CanvasBackref` write-through, enumerated by AST (audit appendix A-8):

| Collaborator | declared names | writes through to canvas |
|---|---:|---|
| `Renderer` | 10 | `_channel_render_profiles`, `_display_x_coverage`, `_display_x_coverage_by_channel`, `_last_refresh_signature`, `_refresh`, `_refresh_pending`, `_y_overflow_wall_active` |
| `OverlayAxisManager` | 60 | `_channel_render_profiles`, `_refresh` |
| `CursorController` | 38 | `_refresh` |
| `TickDensityController` | 14 | `_refresh` |
| `AnnotationManager` | 19 | `_artist`, `_last_rclick_scene_pos` |
| `QualityManager` | 15 | (none) |

`AnnotationManager._owned_names` is `{enabled, remarks, press_pos,
press_dragged}` — `_artist` (assigned at `annotations.py:53`) is absent, so the
`RemarkArtist` lives on the canvas and is read back through a two-hop
`__getattr__` fallback. `canvas.py` never uses the name `_artist` itself (the
sibling canvases use `_remark_artist`), so there is no collision today.

Runtime check of the delegate-shadowing surface:

```
declared owned/delegate names total:                 156
names that are NOT methods on TimeDomainCanvasPG:    106
names colliding with canvas.__init__ instance attrs:   0
canvas instance attr count:                           75
```

### 2.6 W4 — R4's causal claim is unproven

Audit appendix A-6 re-run verbatim on this SHA: **1,232** private-attribute
assertions, **894** internal monkeypatch/attribute injections (860 + 34), and
**47** real-render verifications (`grab(` 10 + `toImage()` 16 + `pixelColor` 30,
deduplicated by line). The audit's first version claimed ~92 for the third
number; that was wrong, and the corrected figure widens the gap rather than
narrowing it.

What these numbers do **not** establish: that the test suite is what keeps
`canvas.py` at 4,042 lines, or that a behaviour-level contract layer could be
"the only layer that must stay green" during a refactor. Many of the 1,232
assertions plausibly lock performance state machines, cache-key contracts, and
render-internal invariants that *should* be white-box — this repository's
lessons-learned corpus documents exactly those failures. Nobody has classified
them. Phase 1 therefore buys the classification instead of acting on the guess.

---

## 3. Goals

1. `restore_visible_ylims` never fits one file's axis to another file's data.
2. `ChannelMath.moving_avg` returns exactly `len(sig)` samples for any `ws`.
3. `ChannelMath.integral` returns a float array for any numeric input dtype.
4. `signal/channel_math.py` has a test file covering every public operation and
   its empty/short/large-window boundaries.
5. `_ChannelKeyDict.copy` / `update` / `setdefault` preserve every colliding
   entry; the `dict(d)` collapse that cannot be fixed is pinned by an explicit
   baseline test so a future refactor meets it as a contract, not a surprise.
6. An unhandled exception anywhere in the process — main thread, worker thread,
   or Qt message — lands in a size-capped, rotating file in the correct
   per-platform location, on Windows `--windowed` builds included.
7. Repeated failures on a single seam cannot produce unbounded log volume or a
   measurable interaction slowdown.
8. `canvas._refresh` no longer exists; `_channel_render_profiles` is created in
   `__init__` and cleared in `clear()`; `AnnotationManager._artist` is owned by
   its collaborator.
9. A test fails if any `_CanvasBackref` subclass grows a new write-through
   attribute that is not on an explicit whitelist.
10. A written, reproducible classification of the private-attribute assertions
    exists, with a recommendation for or against a contract-test layer.

---

## 4. Non-goals

Each of these is deliberately excluded, with the reason:

- **Splitting `canvas.py`.** W4 has not run; the premise that tests are what
  blocks it is unproven, and without W2 there is no way to observe whether a
  split broke anything.
- **Adding `logger.debug` to all 288 broad handlers.** Many are on per-frame
  paths. A persistently-firing exception would then produce a log storm and a
  new interaction stall — trading a diagnosis problem for a performance bug.
  W2 instruments 5–10 named seams; the rest wait for a real signal.
- **Narrowing broad `except Exception` clauses.** Behaviour-changing, and
  needs the W2 logs to know which ones actually fire.
- **A behaviour-level contract-test layer or `@pytest.mark.whitebox` rule.**
  Gated on W4.
- **Separating `_ChannelKeyDict`'s identity surface from its label surface.**
  The real fix for `dict(d)` — a plain dict physically cannot hold two equal
  display keys — requires its own design document. W1c only closes the holes
  that can be closed without changing the iteration contract.
- **`MainWindowProtocol` + mypy.** No mypy baseline exists in the repository;
  introducing one is its own project.
- **Making `_CanvasBackref.__setattr__` raise outside a whitelist.** The W3
  whitelist test must run for a while and collect real write-through churn
  first.
- **`clear()` / `__init__` symmetry test.** Depends on W3 settling
  `_channel_render_profiles`; otherwise the whitelist must carve out a known
  defect.
- **`ui/inspector_sections` silent-handler cleanup.** Re-measurement showed
  34 of 37 are narrow `(TypeError, ValueError)` guards on legacy-preset numeric
  coercion, with docstrings. Low value.

---

## 5. Component design

### 5.1 W1a — composite key through the Y-fit fallback

`canvas.py` `restore_visible_ylims`:

```python
for key, (handle, line) in view_state_lines.items():
    if key in restored_keys:
        continue
    if self._fit_channel_y_to_visible_x(
        key,                      # composite key, identity preserved
        handle, n_y, frame_to_nice=self._overlay_mode,
    ):
        changed = True
```

The `get_label()` hop is removed. `_fit_channel_y_to_visible_x`'s first
parameter is renamed `channel_key` to make the contract explicit in the
signature.

**Lookup rule inside the fitter.** Resolve in two steps, failing closed rather
than guessing:

1. `row = self.channel_data.get(channel_key)` — a composite key hits
   `_ChannelKeyDict._resolve`'s `dict.__contains__` fast path directly.
2. If that misses (a legacy layout whose `_channel_view_state_lines` key is not
   a composite key), fall back to the display label **only when the label is
   unambiguous**. Ambiguity must return `False` — leaving the axis on its
   current range — instead of fitting to arbitrary data.

Step 2 needs one small addition to `_ChannelKeyDict`:

```python
def resolve_unique(self, key):
    """Return the stored composite key for ``key``, or ``None`` when the key is
    absent OR is a display name bound to more than one entry.

    Callers on identity-sensitive paths (Y-fit, per-channel caches) use this
    instead of ``get`` so an ambiguous bare-name read fails closed rather than
    silently taking the last-bound entry.
    """
```

It reuses `_name_index`: a bucket of length 1 resolves, a bucket of length > 1
returns `None`. This is additive; `_resolve`'s existing last-bound-wins
behaviour is unchanged for every current caller.

**Why not just always use the composite key and drop the fallback.** Measured on
this SHA the two key sets are identical, so a hard cutover would work today.
The guarded fallback costs three lines and protects against any caller that
populates `_channel_view_state_lines` differently (overlay vs subplot, project
restore, single-file legacy paths) — and unlike the current code, its failure
mode is "axis unchanged", not "axis wrong".

### 5.2 W1b — `channel_math` contracts

```python
@staticmethod
def integral(t, sig):
    sig = np.asarray(sig, dtype=float)
    r = np.zeros(sig.shape, dtype=float)      # never inherits an integer dtype
    if sig.size < 2:
        return r
    r[1:] = np.cumsum(0.5 * (sig[1:] + sig[:-1]) * np.diff(np.asarray(t, dtype=float)))
    return r

@staticmethod
def moving_avg(sig, ws=50):
    sig = np.asarray(sig, dtype=float)
    if sig.size == 0:
        return sig.copy()
    ws = max(1, min(int(ws), sig.size))       # output length == input length
    return np.convolve(sig, np.ones(ws) / ws, mode='same')
```

> **Correction (2026-07-31):** The sketch above contradicts this spec's own
> `ws >= len(sig)` acceptance contract: clamp-plus-convolve zero-pads and tapers
> the edges instead of returning the whole-signal mean. Phase 1 intentionally
> shipped the test-defined semantics:
>
> ```python
> if ws >= sig.size:
>     return np.full(sig.shape, sig.mean(), dtype=float)
> ```
>
> The `ws == n - 1` / `ws == n` boundary is pinned by the follow-up tests. See
> `2026-07-31-robustness-phase1-followup.md`, Task 4.1.

`derivative` gets an explicit precondition instead of leaking `np.gradient`'s
`IndexError`:

```python
@staticmethod
def derivative(t, sig):
    sig = np.asarray(sig, dtype=float)
    if sig.size < 2:
        raise ValueError(...)      # message language follows existing signal/ convention
    return np.gradient(sig, np.asarray(t, dtype=float))
```

`dialogs.py` already wraps the call in `except Exception` →
`QMessageBox.critical(str(e))`, so a clear `ValueError` message surfaces to the
user with no UI change. **No `dialogs.py` change is in scope for W1b** — the
clamp lives in the algorithm, where every future caller gets it.

Design decision: **clamp, do not raise, for an oversized `ws`.** A large window
on a short channel is a meaningful request ("smooth this heavily"); the correct
answer is "average over everything you have", not an error dialog. Raising would
also change existing behaviour for the `len(sig) > ws` case nobody reported a
problem with.

### 5.3 W1c — `_ChannelKeyDict` write surface

```python
def copy(self):
    """Return a same-type copy; a plain-dict copy would collapse colliding
    display names into one entry."""
    clone = type(self)()
    for composite_key, label, value in self.composite_items():
        clone.set_with_label(composite_key, label, value)
    return clone

def update(self, other=(), **kwargs):
    """Preserve composite identity when ``other`` is a _ChannelKeyDict.

    Iterating ``other.items()`` would yield display labels and collapse two
    colliding channels into one slot — the exact bug this class exists to fix.
    """
    if isinstance(other, _ChannelKeyDict):
        for composite_key, label, value in other.composite_items():
            self.set_with_label(composite_key, label, value)
    elif hasattr(other, "keys"):
        for k in other.keys():
            self[k] = other[k]
    else:
        for k, v in other:
            self[k] = v
    for k, v in kwargs.items():
        self[k] = v

def setdefault(self, key, default=None):
    """Resolve through the name index first.

    ``dict.setdefault`` bypasses ``__contains__`` and would insert a THIRD
    entry keyed by the bare display name, which then wins every later
    bare-name read and masks both real channels.
    """
    composite_key = self._resolve(key)
    if composite_key is not None:
        return dict.__getitem__(self, composite_key)
    self[key] = default
    return default
```

Plus an explicit, safe converter so refactorers have somewhere to go:

```python
def as_composite_dict(self):
    """Plain dict keyed by composite key — lossless, unlike ``dict(self)``."""
    return {ck: v for ck, _label, v in self.composite_items()}
```

**`dict(d)` / `{**d}` are left collapsing, by design.** As long as `keys()`
yields display labels, any conversion into a plain `dict` must collapse two
equal labels; this is a property of `dict`, not a missing override. W1c pins the
behaviour with a test that asserts the collapse and names `as_composite_dict()`
as the alternative, so the next refactor reads a contract instead of
rediscovering a bug. Changing the iteration surface is Phase 2 and needs its own
design document.

### 5.4 W2 — diagnostics infrastructure

New module `mf4_analyzer/diagnostics.py`. It must import cleanly without PyQt so
non-GUI entry points (`batch.py`, CLI tools, tests) can use the logger; the Qt
message handler lives behind a function that imports PyQt lazily.

**Public surface**

```python
def resolve_log_dir() -> Path
def setup_logging(*, level: str | None = None) -> Path
def install_excepthooks(*, on_error: Callable[[str], None] | None = None) -> None
def install_qt_message_handler() -> None
def throttled(logger, key, level, msg, *args, exc_info=False) -> None
```

**Log location** — Windows first, since that is the only packaged target:

| Platform | Directory | Source |
|---|---|---|
| Windows | `%LOCALAPPDATA%\TraceLab\logs` | `os.environ['LOCALAPPDATA']`, fallback `~/AppData/Local` |
| macOS | `~/Library/Logs/TraceLab` | Apple convention for logs (not `Application Support`) |
| Linux/other | `${XDG_STATE_HOME:-~/.local/state}/TraceLab/logs` | XDG |

`TRACELAB_LOG_DIR` overrides all three. If the directory cannot be created or
written, `setup_logging` degrades to stderr-only and **must not raise** — a
diagnostics failure must never prevent the app from starting.

**Rotation and retention.** `logging.handlers.RotatingFileHandler`,
`maxBytes=5 MiB`, `backupCount=5` → a hard 30 MiB ceiling, no time-based
cleanup needed. File level defaults to `INFO`, raised to `DEBUG` by
`TRACELAB_LOG_LEVEL=DEBUG`. `WARNING` and above also go to stderr when a console
exists.

**Rate limiting.** `throttled()` keys on `(logger.name, key)` where callers pass
a stable `key` — conventionally `f"{__name__}:{lineno}:{type(exc).__name__}"`.
Per key: log the first `BURST = 3` events, then suppress; when the
`WINDOW = 60 s` elapses, emit one summary line (`"suppressed N occurrences in
60s"`) and reopen the burst. State is a bounded dict (`MAX_KEYS = 512`, oldest
evicted) so a pathological key space cannot itself leak. The whole function must
be cheap on the suppressed path — one dict lookup, one integer compare, no
string formatting until a record is actually emitted.

> **Correction (2026-07-31):** A summary triggered only by the next call of the
> same key is insufficient for a burst that goes quiet. The follow-up extends
> the public surface with `flush_throttle_summaries()` and adds an amortized
> cross-key sweep, exactly-once atexit registration, and a pending-count summary
> before oldest-key eviction. Counts are collected under `_THROTTLE_LOCK` and
> logged after release. The new performance gate is median ≤2× baseline and
> <1 µs/call; see `2026-07-31-robustness-phase1-followup.md`, Task 2.

**Hooks.** `install_excepthooks` sets `sys.excepthook` and
`threading.excepthook`, chaining to the previous hook so pytest and IDE
integrations keep working. The optional `on_error` callback lets `app.py` pass
`window.toast` (`ui/main_window/window.py:551`) so the user sees
"发生内部错误，详情已记录到日志" with the log path. `install_qt_message_handler`
maps `QtDebugMsg`/`QtInfoMsg` → `debug`/`info`, `QtWarningMsg` → `warning`,
`QtCriticalMsg`/`QtFatalMsg` → `error`, and routes everything through
`throttled` keyed on the Qt category plus the message's first 80 characters —
Qt repeats identical warnings per frame.

**Wiring in `app.py`.** `setup_logging()` runs first in `main()`, before
`_configure_high_dpi()`, so import-time failures are captured.
`install_qt_message_handler()` runs immediately after `QApplication` is created.
`install_excepthooks(on_error=...)` runs after `MainWindow()` exists so the
toast target is available.

**Seam instrumentation — selection rule.** A seam qualifies only if
(a) it is a state or coordinate path whose silent failure produces a wrong
visible result, and (b) it is **not** inside a per-frame loop
(`_refresh_visible_data`'s per-channel body, mouse-move handlers, paint
overrides). Candidates, all in `ui/pg_canvas`:

> **Correction (2026-07-31):** Clause (b) has one evidence-backed exception:
> sanctioned seam #6, `_sync_x_axis_item_range`, is reached once per sibling
> axis per drag tick. It remains instrumented because every failure is routed
> through the bounded throttle. The measured suppressed-path baseline was
> median 197.4 ns/call; at 60 fps × 8 axes that is about 94.8 µs/s (≈0.01% of
> one core). New per-frame seams still require an explicit name, rate limiting,
> and a recorded cost. See `2026-07-31-robustness-phase1-followup.md`, Task 5.

| # | Site | Why |
|---|---|---|
| 1 | `canvas.py:2024` `get_visible_ylims` per-channel getter | a swallowed getter silently drops a saved range |
| 2 | `canvas.py:2035` `restore_visible_ylims` per-channel `set_ylim` | the exact handler that routes into the buggy auto-fit branch |
| 3 | `canvas.py:2069` `_fit_channel_y_to_visible_x` `get_xlim` | fit silently skipped |
| 4 | `canvas.py:2076` same, array coercion | fit silently skipped |
| 5 | `canvas.py:2098` same, `set_ylim` | fit computed then silently discarded |
| 6 | `canvas.py` `_sync_x_axis_item_range` axis-handle and `setRange` handlers | X axis label desync |
| 7 | `overlay_axes.py` overlay tick repin failure path | overlay tick misalignment, a recurring lesson topic |
| 8 | `chart_stack/stack.py` `enter_split` / `exit_split` | split-screen state divergence |

The plan requires 5–10 of these, each converted from `except Exception: pass` to
`except Exception: throttled(...); <same control flow>` — **control flow
unchanged**, so the change cannot alter behaviour.

**Performance gate.** `scripts/benchmark_timedomain_interaction.py` exists and
must be run before and after. Any regression beyond run-to-run noise blocks the
package.

### 5.5 W3 — state hygiene

**Delete `canvas._refresh`.** Remove all 19 assignments (`window.py:2022`;
`canvas.py:385,1000,2247,2299,2499`; `overlay_axes.py` ×8; `cursor.py` ×2;
`renderer.py:717`; `tick_density.py` ×2) and the assertion at
`tests/ui/test_pg_timedomain_canvas.py:1533-1538`. Do not touch
`_refresh_pending` / `_refresh_timer` / `_refresh_visible_data` /
`_refresh_overlay_axis_labels`. Post-condition: `grep -rn "\._refresh\b"` over
`mf4_analyzer/` and `tests/` returns nothing.

**Give `_channel_render_profiles` an owner.**
- `canvas.__init__`: `self._channel_render_profiles = {}`.
- `canvas.clear()`: `self._channel_render_profiles.clear()`.
- Replace the 3 lazy-creation blocks with direct access; replace the 5
  `getattr(..., {})` reads with direct attribute reads.
- `dense_raster.py` reaches the canvas as `self.canvas`, not through
  `_CanvasBackref`, so its reads become `self.canvas._channel_render_profiles`.
- The three existing test references (`test_pg_timedomain_canvas.py:6592`,
  `test_high_variation_envelope.py:293/310`) read the dict and must keep
  passing unchanged.
- Mutating the shared dict in place (`profiles[ck] = profile`) is not an
  attribute write, so no new write-through appears.

Behaviour note: clearing on `clear()` discards profiles that today survive a
file switch. Since every profile is re-derived on the next render pass and
`source_revision` already invalidates entries per channel, this costs one
classification per channel on the first frame after a clear — measurable, and
covered by the same interaction benchmark as W2.

**Move `_artist` into `AnnotationManager._owned_names`.** Verify first that
nothing outside `annotations.py` reads `canvas._artist`; the audit's grep found
no such reader in sources or tests.

**Write-through whitelist test** — new `tests/ui/test_pg_canvas_backref_invariants.py`:

1. **AST invariant.** Reuse the audit appendix A-8 scan. For each
   `_CanvasBackref` subclass, `self.X = ...` targets minus
   `_owned_names ∪ _delegate_names` must equal an explicit expected set
   declared in the test. After W3 that expected set is:

   ```python
   EXPECTED_WRITE_THROUGH = {
       "Renderer": {"_display_x_coverage", "_display_x_coverage_by_channel",
                    "_last_refresh_signature", "_refresh_pending",
                    "_y_overflow_wall_active"},
       "OverlayAxisManager": set(),
       "CursorController": set(),
       "TickDensityController": set(),
       "AnnotationManager": {"_last_rclick_scene_pos"},
       "QualityManager": set(),
   }
   ```

   `_refresh` disappears with the deletion, `_channel_render_profiles`
   disappears once the canvas owns it, `_artist` disappears once it is owned.
   A new unlisted write-through fails the test with the attribute name, so the
   author must either own it or declare it deliberately.

2. **Shadowing invariant.** Instantiate a real `TimeDomainCanvasPG` and assert
   every collaborator's `_delegate_names` is disjoint from
   `vars(canvas)` — the currently-lucky 0 becomes an enforced 0.

The test must fail loudly on an unrecognised class name too, so adding a new
`_CanvasBackref` subclass cannot bypass the check by omission.

### 5.6 W4 — test coupling classification

Read-only study. No production or test code changes.

**Population.** The 1,232 lines matching
`grep -rn "assert [a-z_]*\._[a-z_]*" tests --include="*.py"`.

**Strata**, so `canvas.py`'s bulk cannot swamp the result:

| Stratum | Source area |
|---|---|
| S1 | `tests/ui/test_pg_timedomain_canvas.py` |
| S2 | other `tests/ui/*pg*` / canvas-adjacent files |
| S3 | `tests/ui/test_chart_stack*.py` |
| S4 | `tests/ui/` main-window / inspector / widgets |
| S5 | everything outside `tests/ui/` |

**Sampling.** ≥30 per stratum (all of it if a stratum has fewer), drawn with a
**fixed seed recorded in the report** so the sample is reproducible.

**Classification** — exactly one label per assertion:

- **A · implementation-detail coupling** — asserts a private attribute where an
  equivalent public observation exists. Would break on a pure move/rename.
- **B · intentional white-box invariant** — asserts a performance state machine,
  cache key, or render-internal invariant with no public equivalent. Often
  traceable to a lessons-learned entry. Breaking it *should* be loud.
- **C · migratable** — currently private, but a public behaviour-level assertion
  could replace it at reasonable cost.

For every sampled item record: file:line, target attribute, stratum, label, and
a one-line reason. Any referenced lessons-learned file gets cited — a B label
backed by a lesson is the strongest evidence in the study.

**Coverage data is optional.** Neither `pytest-cov` nor `coverage` is installed
in `.venv`. Adding a dev dependency is the user's call; the classification does
not need it. If approved, `coverage run -m pytest tests/ui -x -q` plus a
report on `mf4_analyzer/ui/pg_canvas` would quantify how much of the canvas is
exercised only through white-box paths.

**Output** → `docs/reports/2026-07-30-test-coupling-classification.md`: per-stratum
A/B/C counts with confidence intervals, the seed and commands, 5–10 concrete
examples per label, and a recommendation that answers three questions:

1. Is a behaviour-level contract-test layer worth building, and for which
   surfaces?
2. Should new tests be barred from private-attribute assertions (i.e. is a
   `@pytest.mark.whitebox` rule justified, or would it just annotate category B
   everywhere)?
3. Is the `canvas.py` split actually test-blocked, or is that a myth the audit
   inherited?

**A truthful negative result is a success.** If category B dominates, the answer
is "the white-box style is largely load-bearing; do not build a contract layer",
and Phase 2 drops those items.

---

## 6. Error handling and diagnostics

- W1a's fail-closed path (ambiguous label, missing row) returns `False`, leaving
  the axis untouched, and — once W2 lands — records one throttled warning naming
  the channel key. Ordering: W1a ships first without the log line, and W2's
  seam list includes these handlers.
- W1b raises `ValueError` only where the existing code already raised something
  worse (`derivative` on <2 samples). No new exception type reaches the UI.
- W1c changes no exception behaviour.
- W2's own failures are contained: an unwritable log directory degrades to
  stderr; the throttle map is bounded; the Qt handler must never raise back into
  Qt.
- W3 changes no exception behaviour.

---

## 7. Test design

### W1a

- **Regression (new)** — `tests/ui/test_pg_multifile_samename_curves.py` (the
  file already exists with 9 passing tests and the right fixtures): two files
  with colliding `short_name`, ranges `[-1,1]` and `[100,200]`; restore only
  file B's ylim; assert file A's axis stays within its own range and
  specifically that it does **not** land in `(90, 210)`.
- Both plot modes (`subplot`, `overlay`).
- Non-colliding two-file and single-file layouts still auto-fit correctly
  (guards against a hard-cutover regression).
- `resolve_unique` unit tests: absent → `None`; unique display name → composite
  key; ambiguous display name → `None`; composite key → itself.
- The existing `test_restore_visible_ylims_fits_new_overlay_channel_to_visible_x`
  (`test_pg_timedomain_canvas.py:2486`) must keep passing untouched — it is the
  single-file contract this change must not disturb.

### W1b

New `tests/signal/test_channel_math.py` (the directory exists):

- `moving_avg` output length equals input length across
  `(len, ws) ∈ {(3,50), (10,100), (2000,5000), (1000,50), (1,1), (5,1)}`.
- `moving_avg` on an empty array returns an empty float array, no raise.
- `moving_avg(sig, ws)` with `ws >= len(sig)` equals the whole-window mean at
  every position, i.e. `np.full(len(sig), sig.mean())` within tolerance — pins
  the clamp semantics, not just the length.
- `integral` returns `float64` for int input and matches the float result
  exactly on `t=[0,1,2,3], sig=[0,1,2,3]` → `[0, 0.5, 2, 4.5]`.
- `integral` against an analytic case: `sig = t` over a fine grid → `t²/2`
  within tolerance.
- `derivative` on `sin` → `cos` within tolerance; `<2` samples raises
  `ValueError`.
- `scale` / `offset` / trivial cases for completeness — this is the module's
  first test file, so it should cover the whole public surface.

### W1c

- `copy()` returns a `_ChannelKeyDict` with both colliding entries and identical
  `composite_items()`.
- `update()` from another `_ChannelKeyDict` preserves both entries; from a plain
  dict and from an iterable of pairs behaves as before.
- `setdefault` on an existing display name returns the **existing** value and
  does not change `len`; on an absent key inserts once. Explicitly assert
  `len(d) == 2` afterwards — the phantom-entry regression.
- `as_composite_dict()` round-trips both entries.
- **Baseline test** documenting the accepted limitation: `dict(d)`, `{**d}`, and
  `{k: v for k, v in d.items()}` all collapse to `len == 1`, with a comment
  pointing at `as_composite_dict()`. This test asserts current behaviour on
  purpose; if a future change makes it fail, that change is Phase 2's surface
  separation and the test should be updated deliberately.

### W2

- `resolve_log_dir` returns the right path per platform with `sys.platform`
  monkeypatched, and honours `TRACELAB_LOG_DIR`.
- `setup_logging` into a `tmp_path` writes a file; rotation triggers at the
  configured `maxBytes` and never exceeds `backupCount` files.
- An unwritable directory degrades to stderr and does not raise.
- `throttled`: first `BURST` calls emit; the next N are suppressed; after the
  window a summary line with the correct count appears; the key map stays
  bounded at `MAX_KEYS`.
- `sys.excepthook` and `threading.excepthook` both produce a file record with a
  full traceback, and chain to the previously-installed hook.
- The Qt message handler maps each `QtMsgType` to the right level and throttles
  repeats.
- Each instrumented seam: inject a failure (monkeypatch the inner call to
  raise), assert the same control flow as before **and** a log record naming the
  channel/axis.
- `scripts/benchmark_timedomain_interaction.py` before/after, numbers recorded
  in the plan's verification section.

### W3

- `grep` post-condition test or an explicit assertion that
  `TimeDomainCanvasPG` has no `_refresh` attribute after construction.
- `_channel_render_profiles` exists as `{}` immediately after `__init__`, is
  populated by a render, and is empty after `clear()`.
- The three existing profile-reading tests keep passing.
- `AnnotationManager._artist` is on the instance, not on the canvas:
  `'_artist' in vars(manager)` and `'_artist' not in vars(canvas)`. Remark
  add/remove/clear behaviour unchanged.
- The two backref invariant tests from §5.5.
- Full default suite green (`pytest`), since W3 touches five `pg_canvas` files.

### W4

No tests — the deliverable is a report. The plan's verification step is that the
sampling commands in the report reproduce the same sample from the recorded
seed.

---

## 8. Documentation changes

- `docs/robustness-audit-2026-07-30.md` — already revised to rev2; §10 links
  this spec and its plan.
- `CLAUDE.md` — replace "164 个 pytest 用例" with a non-numeric description
  (actual: 3,714 test functions). Do **not** touch the 12-View wording; that was
  re-verified as correct.
- New lessons-learned entries (with `LESSONS.md` index lines):
  - `docs/lessons-learned/pyqt-ui/` — display-label fallbacks on
    identity-sensitive paths reintroduce the composite-key bug the storage class
    was built to fix; `_ChannelKeyDict.setdefault` inserting a bare-name phantom
    entry.
  - `docs/lessons-learned/signal-processing/` — `np.convolve(mode='same')`
    returns `max(len(sig), ws)`, so any window parameter reachable from the UI
    needs a length clamp.
  - `docs/lessons-learned/refactor/` — an audit without a commit SHA cannot be
    acted on; two of rev1's headline numbers had already drifted or were wrong
    when re-measured.
- If W2 adds `TRACELAB_LOG_DIR` / `TRACELAB_LOG_LEVEL`, document both plus the
  per-platform log paths in `docs/analyzer/` and mention the log location in the
  in-app help if it lists diagnostics.

---

## 9. Acceptance criteria

**W1a** — Same-name two-file crosstalk regression test fails on the parent
commit and passes after. File A's restored axis is within its own data range in
both plot modes. Ambiguous-label lookups return `False` rather than fitting. The
existing single-file auto-fit test is untouched and green.

**W1b** — `len(moving_avg(sig, ws)) == len(sig)` for every tested pair.
`integral` returns `float64` for integer input. `tests/signal/test_channel_math.py`
covers all five public operations plus boundaries. No `dialogs.py` change.

**W1c** — `copy` / `update` / `setdefault` preserve both colliding entries;
`setdefault` on an existing display name returns the existing value and leaves
`len` unchanged; `as_composite_dict()` is lossless; the collapse baseline test
documents `dict(d)` explicitly.

**W2** — A deliberately-injected exception in a slot produces a full traceback
in the platform-correct rotating file, on a Windows `--windowed` build included.
Rotation caps total size at 30 MiB. A seam failing 10,000 times produces
`BURST` records plus periodic summaries, not 10,000 records.
`benchmark_timedomain_interaction.py` shows no regression beyond noise.
5–10 seams instrumented, each with a test, each with control flow unchanged.

**W3** — `grep -rn "\._refresh\b" mf4_analyzer/ tests/` is empty.
`_channel_render_profiles` is `{}` after `__init__`, empty after `clear()`, with
zero `getattr` access remaining. `_artist` lives on the manager. Both backref
invariant tests pass and fail correctly when a write-through is added
artificially. Full default suite green.

**W4** — Report exists with per-stratum A/B/C counts, ≥30 samples per stratum, a
recorded seed that reproduces the sample, and an explicit yes/no recommendation
on each of the three questions in §5.6.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| W1a's hard cutover to composite keys breaks a layout where the key sets differ | Guarded unambiguous-label fallback (§5.1); tests cover subplot, overlay, single-file, non-colliding two-file |
| W1b's clamp changes results for existing large-`ws` users | Only the `ws > len(sig)` case changes, and there the old output was length-mismatched — unusable downstream. Clamp semantics pinned by an explicit mean-value test |
| W2 logging becomes the new performance problem | Throttle on the suppressed path is one dict lookup; no formatting until emit; hot-path seams excluded by rule; benchmark gate before/after |
| W2 log files fill the user's disk | 5 MiB × 5 files hard ceiling; no time-based growth |
| W2's `excepthook` interferes with pytest or IDE debugging | Chain to the previous hook; install only from `app.main()`, never at import time |
| W3's `clear()` now drops render profiles that used to survive a file switch | One re-classification per channel on the first frame after clear; covered by the same benchmark gate |
| W3's 19-site deletion misses a site or hits a live neighbour | Post-condition grep; the four live `_refresh_*` names listed explicitly in the plan |
| W4 concludes "no action needed" after a day of work | That is a valid, useful outcome — it retires an unproven premise that would otherwise justify weeks of refactoring |
| Numbers in this spec drift before execution | Baseline SHA recorded at the top; the plan's first task re-verifies the four headline counts before any edit |

---

## 11. Ownership

Per `CLAUDE.md`'s agent-squad routing, no `.py` file is edited by the main
session. Dispatch:

| Package | Expert | Rationale |
|---|---|---|
| W1a | `pyqt-ui-engineer` | `pg_canvas` coordinate path |
| W1b | `signal-processing-expert` | `signal/` numerics, TDD-first |
| W1c | `pyqt-ui-engineer` | `pg_canvas/_shared.py` storage class |
| W2 | `pyqt-ui-engineer` | Qt message handler + `app.py` wiring + toast |
| W3 | `refactor-architect` | cross-module state relocation across 5 `pg_canvas` files |
| W4 | `refactor-architect` | test-suite structure analysis |

W1a and W1c both touch `pg_canvas` but different files
(`canvas.py` + `_shared.py::resolve_unique` vs `_shared.py` write surface). To
avoid a rework collision on `_shared.py`, **W1c runs first and adds
`resolve_unique` as part of its diff**, then W1a consumes it. The plan sequences
them accordingly.
