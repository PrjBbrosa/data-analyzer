---
role: pyqt-ui
tags: [pyqtgraph, paintevent, perf-probe, qt-virtual-dispatch, class-swap, graphicsview, instrumentation, raster-timing, viewport]
created: 2026-06-23
updated: 2026-06-23
cause: insight
supersedes: []
---

# Timing a pyqtgraph paint frame needs a CLASS-level paintEvent override (`__class__` swap), not an instance attribute or a swapped viewport

## Context
Adding a gated render-timing probe (`TRACELAB_PERF`) to measure the real
first-frame raster wall of a dense time-domain plot. The natural hook —
wrap the GraphicsView viewport's `paintEvent` by assigning a function to
the instance attribute (`viewport.paintEvent = wrapped`) — logged ZERO
paint hits even under a forced `repaint()`/`grab()`.

## Lesson
Qt dispatches the virtual `paintEvent` from C++ and only routes to Python
when the override exists at the TYPE level; assigning `paintEvent` on an
instance (or `setViewport()` with a plain-`QWidget` subclass whose
`paintEvent` you override) is never consulted — measured 0 hits. The
working hook is a runtime `__class__` swap: build a dynamic subclass of
the live widget's class with a class-level `paintEvent` that brackets
`base.paintEvent(self, ev)` with `perf_counter`, then set
`glw.__class__ = Probe`. In pyqtgraph the `GraphicsLayoutWidget` (`_glw`)
IS the `QGraphicsView` and painting happens in ITS `paintEvent` (onto its
own viewport), so hook `_glw`, not `_glw.viewport()`. An event filter on
the viewport DOES see `QEvent.Paint` (useful to confirm delivery) but
cannot wrap the paint to time it — the filter returns before Qt runs the
real paint. Offscreen caveat: after a settle, `grab()` is a cached blit
(~1 ms) and `repaint()` may be a no-op if nothing is dirty — the genuine
dense raster frame fires LATER as a deferred paint once the event loop
runs (selftest: forced repaint #1 = 1.3 ms partial, deferred #2 = 70 ms
real wall). Give each paint line an absolute timestamp so the deferred
real frame is still attributable even though it lands after the timing
section closes.

## How to apply
To time a real Qt/pyqtgraph paint frame, override `paintEvent` at the
CLASS level — runtime `widget.__class__ = DynamicSubclass(base)` on the
live `GraphicsView` (`_glw`), never an instance-attribute assignment or a
viewport swap. Use an event filter only to PROVE paint delivery, not to
time it. When measuring offscreen, don't trust a single `repaint()`/`grab()`
number; log every paint with an absolute timestamp and expect the heavy
dense frame to arrive deferred after the event loop turns.
