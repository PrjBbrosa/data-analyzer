---
name: cache-invalidation-must-be-event-conditional-not-call-conditional
description: Invalidating a viewport/render cache from inside a handler that is itself replayed by internal QTimer hops will wipe the cache on every replay; gate invalidation on a last-value diff, not on handler entry.
type: feedback
---

When a UI handler doubles as both an event entry point AND the target of internal `QTimer.singleShot(0, handler)` re-entries (typical Qt pattern for "schedule after current event loop tick"), unconditional cache invalidation at the top of the handler defeats the cache entirely.

Concrete instance from time-domain refactor:

```python
def plot_time(self):
    canvas.invalidate_envelope_cache("plot mode changed")  # WRONG
    canvas.invalidate_envelope_cache("range filter changed")  # WRONG
    ...
```

`plot_time` is invoked both by user actions AND by `_on_mode_changed` doing `QTimer.singleShot(0, self.plot_time)`. The latter happens for any mode toggle, replot button, etc. Unconditional invalidation here means every replay of `plot_time` wipes the cache, so subsequent xlim_changed → `_envelope_cached` always misses.

**Why:** A cache invariant is "anything that changes the cache key was edited." Internal re-runs of the handler do not change the cache key — they re-enter with the SAME state. Only an actual change to the underlying data should invalidate. Tying invalidation to handler entry instead of state change conflates "handler ran" with "state changed."

**How to apply:** Maintain a `_last_<state>` instance field. Compute the current state tuple at the top of the handler. Compare against `_last_<state>`; only call `invalidate_*` when they differ. Guard the comparison with `_last_<state> is not None` so the first call doesn't fire a pointless wipe (the cache is empty anyway and the first cache entry will be keyed against the current state). Update `_last_<state>` to the current value at the same point regardless of whether invalidation fired.

```python
def plot_time(self):
    cur_mode = self.chart_stack.plot_mode()
    if self._last_plot_mode is not None and self._last_plot_mode != cur_mode:
        canvas.invalidate_envelope_cache("plot mode changed")
    self._last_plot_mode = cur_mode

    cur_range = (range_enabled, lo, hi) if range_enabled else (False,)
    if self._last_range_state is not None and self._last_range_state != cur_range:
        canvas.invalidate_envelope_cache("range filter changed")
    self._last_range_state = cur_range
    ...
```

Generalizes beyond viewport caches: any "state-derived" cache wired through a handler that gets replayed by Qt's event-loop scheduling needs the same diff-gate.
