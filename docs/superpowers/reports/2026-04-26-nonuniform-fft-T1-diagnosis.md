# T1 — Diagnosis: 非均匀时间轴下手动输入 Fs 仍无法计算

**Date:** 2026-04-26
**Subtask:** T1 (read-only diagnosis; T2 implements the fix).
**Sample file:** `testdoc/TLC_TAS_RPS_2ms.mf4` (jitter ≈ 2.36 → far above
`SpectrogramAnalyzer.compute`'s default `time_jitter_tolerance = 1e-3`).

## Executive summary

**Root cause: H1 fires.** The Inspector's `spin_fs` in any of the three
contextual panels (`fft_ctx`, `fft_time_ctx`, `order_ctx`) is a pure
display widget — its `set_fs(fs)` writes to `spin_fs.setValue(fs)`,
its `fs()` getter reads `spin_fs.value()`, and **no `valueChanged` /
`editingFinished` slot is wired anywhere in the codebase**. Manual Fs
entry never propagates to `FileData.rebuild_time_axis(fs)`. The next
click on "FFT vs Time 计算" therefore re-runs `do_fft_time` against the
unchanged `fd.time_array` (still raw non-uniform timestamps) and the
worker re-raises `non-uniform time axis: relative_jitter=2.36 …` —
exactly the toast the user sees.

H2, H3, H4, H5 do not fire as the user's reported symptom. H4 has a
**latent contract bug** (the documented "retry capped at 1" guarantee
is broken because `_fft_time_retry_pending` is cleared synchronously in
`_retry`'s `finally` before the dispatched worker can fail) but it
does NOT cause the user-visible "manual Fs cannot compute" loop —
that's H1's territory. Recorded here so T2 can decide whether to
co-fix or defer.

Severity ordering: **H1 (primary) > H4 (latent, related, defer-or-fix
in same PR) > H2 ≈ H3 ≈ H5 (do not fire)**.

## Per-hypothesis evidence

### H1 — Inspector `spin_fs` is decorative; only popover Accept rebuilds. **FIRES.**

**Evidence chain (consumer-side grep, per
`signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`):**

1. The only write site for `fd.time_array` after construction is
   `FileData.rebuild_time_axis` at
   `mf4_analyzer/io/file_data.py:37–42`:

   ```python
   def rebuild_time_axis(self, fs):
       self.fs = fs
       n = len(self.data)
       self.time_array = np.arange(n, dtype=float) / fs
       self._time_source = 'manual'
   ```

   No other assignment to `self.time_array` exists in `file_data.py`.

2. Grep `rebuild_time_axis` across the entire `mf4_analyzer/`:
   - `mf4_analyzer/ui/main_window.py:441` — inside
     `_show_rebuild_popover`'s `QDialog.Accepted` branch ONLY.

   That is the **single** call site. Inspector contextuals never call
   it.

3. Inspector contextual `spin_fs` lifecycle in
   `mf4_analyzer/ui/inspector_sections.py`:
   - `FFTContextual.spin_fs`: created at line 842, range/value/suffix
     set at 843–845; `fs()` returns `spin_fs.value()` at 961–962;
     `set_fs(fs)` does `blockSignals + setValue + blockSignals` at
     964–967. **No `valueChanged.connect` or `editingFinished.connect`.**
   - `OrderContextual.spin_fs`: lines 1021–1025, getter 1182–1183,
     setter 1185–1188. Same shape — **no signal wiring**.
   - `FFTTimeContextual.spin_fs`: lines 1286–1290, getter 1485–1486,
     setter 1488–1491. Same shape — **no signal wiring**.

   `grep "spin_fs.valueChanged\|spin_fs.editingFinished"
   mf4_analyzer/ui/inspector_sections.py` returns **0 hits**.

4. `do_fft_time` consumes `t` from `_get_fft_time_signal`
   (`mf4_analyzer/ui/main_window.py:1659–1680`):

   ```python
   t = np.asarray(fd.time_array, dtype=float)
   sig = np.asarray(fd.data[ch].to_numpy(copy=False), dtype=float)
   return fid, ch, t, sig, fd
   ```

   Then at line 1763–1770 builds `SpectrogramParams(fs=float(p['fs']),
   …)` where `p = self.inspector.fft_time_ctx.get_params()`. So manual
   Fs **does** reach the analyzer's `params.fs`. But `t = fd.time_array`
   is unchanged — still the raw non-uniform timestamps from the MF4.

5. Inside the worker, `SpectrogramAnalyzer._validate_time_axis`
   (`mf4_analyzer/signal/spectrogram.py:135–157`):

   ```python
   nominal_dt = 1.0 / float(fs)
   dt = np.diff(arr)
   ...
   relative_jitter = float(np.max(np.abs(dt - nominal_dt)) / nominal_dt)
   if relative_jitter > tolerance:
       raise ValueError(
           f'non-uniform time axis: relative_jitter={relative_jitter:.3g} ...'
       )
   ```

   The validator computes jitter as
   `max|dt - 1/fs_user| / (1/fs_user)`. Even if the user types a Fs
   that exactly matches the file's nominal sampling, the raw
   `fd.time_array` carries the original timestamp jitter, so
   `relative_jitter` stays ≈ 2.36 — no choice of input Fs can satisfy
   the validator. Only **rebuilding `fd.time_array` to `arange(n)/fs`**
   makes `dt` uniform.

6. Toast reproduction trace (no GUI run needed):
   - User clicks "FFT vs Time 计算" → `do_fft_time(force=False)`.
   - Worker raises `ValueError('non-uniform time axis: relative_jitter=2.36 …')`.
   - `worker.failed` → `_on_fft_time_failed` (line 1860). The `'non-uniform time axis' in msg`
     branch fires (line 1887). Toast emitted, popover auto-opened
     anchored on `fft_time_ctx.btn_rebuild` (line 1936).
   - **User cannot reach the popover (Bug #2 — offscreen)**, dismisses
     it (Reject) → line 1946 clears `_fft_time_retry_pending`.
     `_show_rebuild_popover` returns False → no `_retry` scheduled.
   - User types Fs into `fft_time_ctx.spin_fs` (or any contextual's
     `spin_fs`). This updates only the QDoubleSpinBox value;
     `fd.time_array` is untouched.
   - User clicks "FFT vs Time 计算" again → `do_fft_time` → same
     `_get_fft_time_signal` returns the same raw `t` → same
     `non-uniform time axis` ValueError → same toast → same offscreen
     popover. Loop.

**Verdict:** H1 is the primary root cause. The fix is to have either
(a) `spin_fs.editingFinished` (or a new "应用 Fs" button) trigger the
same side-effects the popover Accept does, OR (b) push the
non-uniform check up into `do_fft_time` so it routes through the same
`_show_rebuild_popover` path before dispatching the worker (forcing
the user through a corrective popover that DOES write `fd.time_array`).

### H2 — Stale `SpectrogramResult` cached against the old non-uniform `time_range` shadows the rebuild. **DOES NOT FIRE.**

**Evidence:**

1. Cache key shape (`mf4_analyzer/ui/main_window.py:1609–1626`):
   ```python
   (fid, channel, time_range_tuple, fs, nfft, window, overlap,
    remove_mean, db_reference)
   ```
   where `time_range = (float(t[0]), float(t[-1]))` (line 1748) when
   `range_enabled` is False. For the user's failing file, `t = fd.time_array`
   is the raw non-uniform axis BEFORE any rebuild.

2. Crucially, the failing path **never reaches `_fft_time_cache_put`**
   — the worker raises BEFORE producing a `SpectrogramResult`. The
   `failed` signal goes to `_on_fft_time_failed` (line 1860), which
   does NOT touch the cache. So no entry is ever written under the
   "stale" key.

3. Even if a prior successful compute existed (e.g. user had a
   different file open earlier with same `(fid, channel, fs, …)` —
   impossible across `fid`s since `fid` is unique per file), the
   popover Accept branch at line 449 calls
   `self._fft_time_cache_clear_for_fid(target_fid)`. Consumer-side
   grep:
   - Producer (the clear method) defined at line 1645–1657.
   - Consumed at lines 449 (popover Accept), 635 (channel-edit
     refresh), 668, 883.
   - The popover Accept site is correctly placed BEFORE
     `self.plot_time()` on line 458 and BEFORE any retry; the cache
     cannot shadow.

4. After the rebuild, the new `fd.time_array = arange(n)/fs`, so
   `time_range = (0.0, (n-1)/fs)` — a different tuple than the old
   raw `(t[0], t[-1])`. Even WITHOUT the explicit clear, the cache
   key would not match.

**Verdict:** H2 is correctly handled by the existing
`_fft_time_cache_clear_for_fid` invocation at line 449. The lesson
about "cache reachable + invalidated but not consumed on the hot path"
does not apply here — the consumer (`_fft_time_cache_get` at line 1751
inside `do_fft_time`) IS on the hot path, and the invalidation IS
consumed before the retry. No stale shadow.

### H3 — Regular `do_fft` (FFT, not FFT vs Time) blows up on non-monotonic `t`. **DOES NOT FIRE.**

**Evidence:**

1. `do_fft` body (`main_window.py:1132–1205`):

   ```python
   def do_fft(self):
       t, sig, fs = self._get_sig()
       if sig is None or len(sig) < 10:
           self.toast("请选择有效信号", "warning"); return
       if self.inspector.top.range_enabled() and t is not None:
           lo, hi = self.inspector.top.range_values()
           m = (t >= lo) & (t <= hi)
           sig = sig[m]
       fft_params = self.inspector.fft_ctx.get_params()
       ...
       fs = self.inspector.fft_ctx.fs()
       ...
       freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
   ```

2. The range-mask branch (`m = (t >= lo) & (t <= hi)`) is robust to
   non-monotonic `t`: it produces a boolean array of the same length;
   `sig[m]` gathers matching samples in their original order. No
   exception is raised — non-uniformity is invisible to `compute_fft`,
   which uses sample indices and `fs` only. The "请选择有效信号" toast
   only fires if `len(sig) < 10` after the range filter — possible if
   the user picks a very narrow range, but not the typical user
   complaint here.

3. With range disabled (the default), `t` is not consumed at all —
   the FFT is computed directly on `sig` with the inspector-supplied
   `fs`.

**Verdict:** H3 is not the cause of "fft 也做不出". The user's
"fft 做不出" is most likely the FFT vs Time button (the toast
screenshot is from the FFT vs Time tab) being re-triggered with the
same root cause as H1, OR the user pressing "FFT 计算" with a narrow
range that drops below 10 samples — but neither maps to a non-uniform
specific bug.

### H4 — `_fft_time_retry_pending` lifecycle leaks. **LATENT BUG, but DOES NOT explain the user's symptom.**

**Evidence — the documented contract is broken:**

The header comment at lines 1881–1884 promises:
> `self._fft_time_retry_pending` caps the retry at 1 — if the rebuild
> somehow fails to fix the jitter, the second compute's error
> surfaces verbatim so the user is not trapped in an auto-rebuild
> loop.

The actual lifecycle (lines 1933–1946):

```python
self._fft_time_retry_pending = True
accepted = False
try:
    accepted = self._show_rebuild_popover(anchor, mode='fft_time')
finally:
    if accepted:
        def _retry():
            try:
                self.do_fft_time(force=force)
            finally:
                self._fft_time_retry_pending = False
        QTimer.singleShot(0, _retry)
    else:
        self._fft_time_retry_pending = False
```

`_retry` runs synchronously up to `thread.start()` inside `do_fft_time`
(line 1811). `thread.start()` returns immediately — the worker has NOT
yet even called `run()`, let alone failed. `_retry`'s `finally` then
runs and clears `_fft_time_retry_pending = False` BEFORE the worker
emits `failed`. So if the second compute also fails, the failed
handler enters the auto-retry branch ANEW (because the flag is
False), opens the popover AGAIN, and the cycle continues.

The lesson `pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot`
correctly fixed the `isRunning()` re-entry bug by deferring the retry
via `QTimer.singleShot(0)`, but it did NOT account for the fact that
the deferred call's `finally` runs synchronously upon dispatch, not
upon worker completion. The flag should be cleared inside
`_on_fft_time_failed` / `_on_fft_time_finished`, not inside `_retry`.

**Why this is NOT the user-visible cause:** The user reports the loop
even WITHOUT any popover Accept (they cannot reach the popover, which
is offscreen — Bug #2). The Reject path at line 1946 clears the flag
correctly. So the H4 leak only manifests when a user actually clicks
Accept twice (which is gated by Bug #2 too, since they can't see the
popover). The user's symptom is fully explained by H1; H4 is a
secondary issue that should be co-fixed by T2 because the touched
file is the same and the boundary is identical.

### H5 — Cross-contextual Fs sync gap. **DOES NOT FIRE for this user.**

**Evidence:**

The popover Accept loop (lines 450–457) walks all three contextuals:

```python
for ctx in (self.inspector.fft_ctx,
            self.inspector.fft_time_ctx,
            self.inspector.order_ctx):
    sig_data = ctx.current_signal()
    if sig_data is not None and sig_data[0] == target_fid:
        ctx.set_fs(new_fs)
```

So all contextuals whose selected fid matches `target_fid` get the
new `fs` pushed. The user is operating on a single file, so all three
contextuals point at the same `fid` — all get synced.

The H5 gap (a contextual whose `current_signal()` is None or points
at a DIFFERENT `fid`) only matters in multi-file workflows where the
user switches a contextual to another file's channel between popover
Accepts. Not the user's current reproduction. Filed as out-of-scope
for T2.

## Proposed minimal fix sketch (T2 implements)

Two viable shapes, in preference order. T2 picks one — both stay
inside the signal-processing-expert envelope.

### Option A (preferred — surface the rebuild as a single funnel)

Add a non-uniformity pre-flight to `do_fft_time` that fires BEFORE
`thread.start()`:

- File: `mf4_analyzer/ui/main_window.py`.
- Function: `do_fft_time` (around line 1734, between
  `_get_fft_time_signal` and the cache-key build at 1749).
- Sketch (1–2 lines of intent, no code committed): after
  `t, sig, fd = ...`, call a new helper `self._check_uniform_or_prompt(fd, t, mode='fft_time')`
  that runs the same `np.diff(t)` jitter check as
  `SpectrogramAnalyzer._validate_time_axis` (against `fd.fs`,
  threshold `1e-3`); on failure, route through `_show_rebuild_popover`
  and only proceed if Accept returned True. This collapses the
  "worker raises → failed handler reopens popover" round-trip into a
  single synchronous pre-check. Eliminates the H4 lifecycle bug as a
  bonus because the retry shape disappears.
- Files the fix will touch:
  - `mf4_analyzer/ui/main_window.py` — add `_check_uniform_or_prompt`
    helper, modify `do_fft_time` to call it at the top, simplify (or
    delete) the `'non-uniform time axis' in msg` branch in
    `_on_fft_time_failed`.
  - `mf4_analyzer/io/file_data.py` — optional: add a tiny
    `is_time_axis_uniform(tolerance=1e-3) -> bool` method on
    `FileData` that owns the jitter test (signal-processing concern,
    fits this expert's scope). Cleaner than duplicating the
    `np.diff` test in `main_window.py`.

### Option B (simpler — make spin_fs an active control)

Wire `spin_fs.editingFinished` (or a new "应用 Fs" QPushButton) on
each contextual to a new MainWindow slot that mirrors the popover
Accept side-effects:

- Call `fd.rebuild_time_axis(new_fs)`.
- Update `top.spin_end.setMaximum(...)`.
- `_fft_time_cache_clear_for_fid(target_fid)`.
- Push `set_fs(new_fs)` to the OTHER two contextuals (gated on fid match).
- `plot_time()`.
- Status / toast.

- Files the fix will touch:
  - `mf4_analyzer/ui/main_window.py` — add a new
    `_apply_inspector_fs(mode, fid, new_fs)` slot; connect it from
    inspector. **Note:** wiring a `valueChanged`/`editingFinished`
    signal on a `QDoubleSpinBox` is a UI-side change to
    `inspector_sections.py`; if T2 chooses Option B, it MUST flag
    pyqt-ui-engineer for the connect call inside the contextual
    constructor (per the squad-orchestrator decomposition note). If
    Option A is chosen, no inspector edits are needed and T2 stays
    fully in its lane.

**Recommendation:** Option A. It eliminates the worker round-trip,
fixes H1 (manual Fs path becomes irrelevant — user cannot reach the
non-uniform compute without going through the popover), and
incidentally fixes the H4 latent leak. Stays inside
signal-processing-expert's boundary (no inspector UI edits).

## Expected `symbols_touched` for T2

If Option A:
- `mf4_analyzer/ui/main_window.py` — symbols:
  `MainWindow.do_fft_time`,
  `MainWindow._check_uniform_or_prompt` (new),
  `MainWindow._on_fft_time_failed` (simplification — delete the
  non-uniform retry branch).
- `mf4_analyzer/io/file_data.py` — symbols:
  `FileData.is_time_axis_uniform` (new, optional).

If Option B:
- `mf4_analyzer/ui/main_window.py` — symbols:
  `MainWindow._apply_inspector_fs` (new),
  plus connect line in `__init__`.
- `mf4_analyzer/ui/inspector_sections.py` — would touch existing
  `FFTContextual.__init__`, `OrderContextual.__init__`,
  `FFTTimeContextual.__init__` to wire `editingFinished`. **Must
  be flagged to pyqt-ui-engineer** per the orchestrator's
  rework-detection note.

## Files the fix will touch (consolidated)

- **Always:** `mf4_analyzer/ui/main_window.py`.
- **Option A optional:** `mf4_analyzer/io/file_data.py`.
- **Option B only:** `mf4_analyzer/ui/inspector_sections.py` (UI work,
  must flag).

## Lessons consulted (per startup protocol)

- `docs/lessons-learned/README.md` — read protocol.
- `docs/lessons-learned/LESSONS.md` — index.
- `docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`
  (H2 verification — grepped both `_fft_time_cache_clear_for_fid`
  producer and `_fft_time_cache_get` consumer, plus
  `rebuild_time_axis` consumer-side).
- `docs/lessons-learned/pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md`
  (H2 — confirmed cache invalidation is event-conditional via the
  popover Accept gate, not handler entry).
- `docs/lessons-learned/pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot.md`
  (H4 — re-read; identified the `_retry` `finally` clears the flag
  too early, but this latent issue is NOT the user's symptom).
- `docs/lessons-learned/orchestrator/decompositions/2026-04-26-nonuniform-fft-blocked-and-popover-offscreen.md`
  (audit decomposition — followed the H1–H5 hypothesis matrix).

## Out-of-scope for T1

- Bug #2 (popover offscreen) — owned by T3, pyqt-ui-engineer.
- Multi-file Fs sync gap (H5 generalized) — defer to a separate task.
- Adding a UI test for the Inspector→FFT-vs-Time integration — owned
  by T4 after T2 lands.
