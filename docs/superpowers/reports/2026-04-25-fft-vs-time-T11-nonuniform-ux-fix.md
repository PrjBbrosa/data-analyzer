# FFT vs Time T11 — non-uniform UX fix

Date: 2026-04-25
Specialist: pyqt-ui-engineer
Scope: `mf4_analyzer/ui/main_window.py`,
`tests/ui/test_main_window_smoke.py`.

## What the user saw

When the recorded time channel of an MF4 file has high jitter (e.g.
`relative_jitter ≈ 3.28`), pressing 计算时频图 produced a cryptic toast:

> `non-uniform time axis: relative_jitter=3.28 exceeds tolerance=0.001`

The rejection itself is correct (Spec §5.1 — non-uniform axes can't
be FFT'd directly). The user had to guess that the fix was to press
重建时间轴 in the right inspector panel.

## Fix summary (A + B)

A. Replace the raw error toast with a Chinese-language warning that
   names the rebuild action.
B. Auto-open the 重建时间轴 popover anchored on the FFT vs Time
   contextual's `btn_rebuild`, then auto-retry `do_fft_time` if the
   user clicks Accept.

## Final toast wording

- **Toast (warning)** with parseable jitter:
  > `时间轴非均匀（jitter≈3.28），无法直接做时频分析。已为你打开“重建时间轴”，请确认 Fs 后重试。`
- **Toast (warning)** when the jitter token is missing from the
  error string (defensive fallback — see "regex robustness" below):
  > `时间轴非均匀，无法直接做时频分析。已为你打开“重建时间轴”，请确认 Fs 后重试。`
- **statusBar:** `FFT vs Time · 时间轴非均匀，请重建后重试`

The numeric value is rounded to 2 decimals.

## Where the fix lives — and why ONLY the worker path

The brief asked which entry catches non-uniform errors: sync
`do_fft_time` path, worker `_on_fft_time_failed`, or both.

**Answer: worker `_on_fft_time_failed` only.** Reasoning, top-down:

1. The non-uniform check happens inside
   `SpectrogramAnalyzer.compute` (Spec §5.1).
2. `do_fft_time` (per its own docstring at line 1378) has **no
   synchronous fallback** — the analyzer is invoked exclusively from
   the worker QThread. Cache hits stay synchronous but they short-
   circuit before any analyzer call.
3. `FFTTimeWorker.run` catches `Exception` and forwards `str(exc)` via
   the `failed` signal; the queued slot on the main thread is
   `_on_fft_time_failed`.

Therefore the substring detection and auto-rebuild logic lives at
exactly one place: `_on_fft_time_failed`. There is no helper to share
because there is no second caller.

If a future patch adds a synchronous fallback inside `do_fft_time`,
that path will need the same guard — extracting a small helper at
that point would be cleaner. We deliberately did NOT pre-extract one
to avoid a YAGNI helper that complicates the current one-call site.

## Substring matching robustness

The detection uses
```python
if 'non-uniform time axis' in msg and not getattr(self, '_fft_time_retry_pending', False):
```
NOT a regex against the full message and NOT an exact equality
check.

- The marker `non-uniform time axis` is the analyzer's stable phrase.
- The numeric `relative_jitter=<value>` token is parsed with
  `re.search(r'relative_jitter\s*=\s*([0-9]+(?:\.[0-9]+)?)', msg)`
  and is **optional** — if it is missing, malformed, or future
  reworded, the friendly message simply omits the value but still
  guides the user to 重建时间轴. That decoupling means:
  - Tightening the analyzer tolerance (changing the
    `tolerance=0.001` portion of the message) does not break the UX.
  - Renaming `relative_jitter` to e.g. `jitter_ratio` only loses the
    inline number; the rebuild path still triggers.
  - The substring marker is the only contract; everything else is a
    best-effort enhancement.

## Retry cap — where and why

A single `self._fft_time_retry_pending` flag, set on the instance via
`getattr`/setattr (no `__init__` change needed), caps the auto-retry
at one. Lifecycle:

1. `_on_fft_time_failed` enters the non-uniform branch, sets
   `self._fft_time_retry_pending = True` BEFORE opening the modal.
2. If the user clicks Accept, the retry is scheduled via
   `QTimer.singleShot(0, _retry)`. `_retry` clears the flag in its
   own `finally`. The deferred dispatch is required because
   `_on_fft_time_failed` runs as a queued slot on the main thread
   while the worker thread is still draining its event loop;
   dispatching `do_fft_time` synchronously would hit the
   `isRunning()` re-entry guard and silently no-op.
3. If the rebuild somehow does not fix the jitter (defensive case),
   the retry's worker fails again and re-enters
   `_on_fft_time_failed`. The `getattr(...) and not ...` guard
   refuses to recurse — the second failure surfaces verbatim via
   `self.toast(msg, "error")`. The user sees the raw error after a
   failed retry, which is the correct fallback: it tells them the
   rebuild did not help, instead of trapping them in a popover loop.
4. On Cancel, the flag is cleared in the same `finally` so a future
   click can re-trigger the auto-rebuild.

The cap of 1 is set per the brief: "defensive: cap retries at 1".
A higher cap would not help — if rebuild #1 doesn't make the axis
uniform, neither will rebuild #2 with the same Fs UX. The user is
better served seeing the error than auto-popping forever.

## `_show_rebuild_popover` boolean return — back-compat

The method previously returned `None` on every path; the slot
connection `inspector.rebuild_time_requested.connect(self._show_rebuild_popover)`
discards the return. Adding `return True` (post-Accept) and
`return False` (early bailouts + Rejected) is therefore non-breaking
for existing callers. The new T11 caller is the only one that
consumes it.

The existing test
`test_fft_time_rebuild_popover_resolves_signal_via_fft_time_ctx`
exercises the Rejected branch and does not assert on the return —
verified passing post-edit.

## Test count

- Before: 135 tests passing.
- After: 138 tests passing (3 new).
- New tests:
  - `test_fft_time_non_uniform_friendly_toast`
  - `test_fft_time_non_uniform_auto_opens_rebuild_and_retries`
  - `test_fft_time_non_uniform_user_cancel_does_not_retry`

## Files touched

- `mf4_analyzer/ui/main_window.py`
  - `_show_rebuild_popover` — added `bool` return; preserved every
    side-effect.
  - `do_fft_time` — added `'force': bool(force)` to the
    `_fft_time_pending` stash so the failed handler can replay the
    compute with the same flag.
  - `_on_fft_time_failed` — added the non-uniform substring branch
    described above.
- `tests/ui/test_main_window_smoke.py` — appended three new tests
  plus a `_stub_fft_time_signal` helper.

No edits to forbidden symbols (cache helpers, signal extraction,
render path, FFTTimeWorker, cache-invalidation hook sites).
