---
role: signal-processing
tags: [envelope, downsample, pixel-width, pyqtgraph, viewbox, preview, geometry]
created: 2026-06-12
updated: 2026-06-12
cause: insight
supersedes: []
---

# An unrealized pyqtgraph ViewBox reports a phantom ~45 px width that over-decimates small traces

## Context
Replacing the FFT time-preview's per-source full-resolution antialiased
raster with a `build_envelope(xlim=None, pixel_width=ViewBox_width)`
decimation: when the bucket count is read from
`PlotItem.vb.sceneBoundingRect().width()`, an un-shown / not-yet-laid-out
canvas returns ~45 px, not 0 and not the eventual real width. A
1000-point preview trace then decimated to ~90 points, breaking
exact-passthrough tests that (correctly) expect small sources rendered
untouched.

## Lesson
A pyqtgraph ViewBox's `sceneBoundingRect().width()` is NOT a reliable
"is it realized?" probe — a collapsed/un-shown layout yields a small
non-zero phantom (~45 px) that silently survives a `w >= 1` guard and
makes a viewport-pixel-width envelope over-aggressive on small inputs.
The pixel-width quantum only means "one bucket per pixel" once the
GraphicsLayout has actually been laid out. Gate the measured width with
a believable-realized FLOOR (e.g. 200 px) and route anything under it to
a generous fallback bucket count, so a small trace passes through
`build_envelope`'s `n <= 2*pixel_width` shortcut instead of being
decimated against a phantom viewport.

## How to apply
When deriving an envelope/decimation bucket count from a pyqtgraph
ViewBox pixel width, do not trust `width() >= 1`; treat a width below a
minimum-realized floor as "unrealized" and fall back to a constant large
enough that traces up to `2 × fallback` render untouched. The
multi-million-point sources that motivate the decimation always exceed
the floor anyway, so the floor costs nothing on the hot case and
protects the small/test case.
