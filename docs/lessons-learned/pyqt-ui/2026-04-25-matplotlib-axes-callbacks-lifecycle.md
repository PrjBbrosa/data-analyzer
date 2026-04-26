---
name: matplotlib-axes-callbacks-lifecycle
description: Matplotlib Axes.callbacks (xlim_changed, ylim_changed, etc.) are per-axes and are NOT auto-disconnected when fig.clear() destroys the axes; you must explicitly disconnect before structural rebuild.
type: feedback
---

When `fig.clear()` is called, matplotlib destroys the existing `Axes` objects but leaves the `Axes.callbacks` registry's connection records dangling. There are two failure modes if you ignore this:

1. **Callback accumulation** — every replot adds a new `xlim_changed` connection without removing old ones. After N replots, an xlim change fires N callbacks, each holding a stale axes reference. Even if individual callbacks early-return on a missing axes, the work multiplies.
2. **Lost wiring** — callers that assume `xlim_changed` is connected to the *current* primary axis will silently fail because the connection was made against the old (now destroyed) axis. The new axis has no listener.

**Why:** matplotlib's callback registry is owned by the `CallbackRegistry` instance attached to a specific `Axes`. `fig.clear()` releases the axes object reference from the figure but the `Axes.callbacks` dict and its handlers persist as long as anything else holds the axes alive (closures, our own bookkeeping, etc.). There is no "fig.clear-aware" auto-cleanup.

**How to apply:** In any `clear()` / structural rebuild path, store the connection id when you connect:

```python
self._xlim_cid = ax.callbacks.connect('xlim_changed', self._on_xlim_changed)
```

Then before `fig.clear()` and before re-running `add_subplot`/`twinx` on the new figure, explicitly disconnect:

```python
def _disconnect_xlim_listener(self):
    if self._xlim_cid is not None and self._primary_xaxis_ax is not None:
        try:
            self._primary_xaxis_ax.callbacks.disconnect(self._xlim_cid)
        except Exception:
            pass  # axes may already be GC'd
    self._xlim_cid = None
    self._primary_xaxis_ax = None
```

Catch `Exception` defensively — if the axes was already garbage-collected, `disconnect` may raise. The fallback is a no-op, since GC of the axes also released its callback registry.

Re-connect against the freshly-built axis at the end of the rebuild path. Same pattern applies to `ylim_changed`, `xlim_changed`, mouse-button-related Axes-bound events, and `Axes.callbacks` in general — but NOT to figure-level events connected via `fig.canvas.mpl_connect()`, which have their own deletion semantics.
