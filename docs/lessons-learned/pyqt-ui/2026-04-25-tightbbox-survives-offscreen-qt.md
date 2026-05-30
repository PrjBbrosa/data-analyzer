---
role: pyqt-ui
tags: [matplotlib, bbox, export, clipboard, offscreen, hidpi, scale, render, grab]
created: 2026-04-25
updated: 2026-05-30
cause: insight
supersedes: []
---

## Context

Plan Task 9 (FFT vs Time export) hedged that "if axis-bbox cropping is
fragile under pytest-qt headless, fall back to `self.grab()` in Phase 1".
Implementing `SpectrogramCanvas.grab_main_chart` I kept the fallback
but tested whether the bbox crop actually works under
`QT_QPA_PLATFORM=offscreen` — and it does: the renderer returns valid
figure-pixel coords, the cropped pixmap is strictly smaller than the
full grab (510x253 vs 640x404), and the lower frequency-slice region
is correctly excluded.

Extended 2026-05-30 (spec §E hi-DPI copy/save): adding a `scale` arg to
`TimeDomainCanvasPG.grab_pixmap` to render crisp DPI-independent bitmaps
(2× capped to a 2560px width ceiling) exposed a fallback-bypass trap. The
naive scaled path called `widget.render(painter)` onto a larger QImage
directly — which under offscreen Qt happily produces a blank full-canvas
bitmap even when the widget is unrealizable, silently skipping the 1×1
degenerate fallback the test gates on.

## Lesson

`Axes.get_tightbbox(self.fig.canvas.get_renderer())` returns usable
figure-pixel coords on the offscreen Qt platform once `plot_result`
has run; you do NOT have to surrender to a full-canvas grab on
headless platforms. Keep the bbox/region path primary with a defensive
fallback (degenerate rect / null pixmap / exception).

For a SCALED render the realizability probe still has to be the same
`grab()` the 1× path uses: call `widget.grab()` first, check
`isNull()`/size, and only then magnify it via `QPainter.scale +
widget.render` into a `round(w*s)×round(h*s)` QImage. `widget.render()`
alone is NOT a realizability probe — it fabricates a blank bitmap and
defeats the fallback. The 1×1 degenerate fallback must stay 1×1
regardless of the requested scale.

## How to apply

For any "grab a (region of a) canvas to clipboard/disk" task:
implement the region/bbox grab first, fall back to a plain grab only on
degenerate rect (`qw < 10 or qh < 10`), null pixmap, or exception. When
the task also asks for a hi-DPI/scaled bitmap, gate the magnified render
behind a successful `grab()` probe (never `render()` straight to a
scaled QImage), keep the 1×1 fallback un-scaled, and CAP the factor
(floor 1×, output-width ceiling) so export stays fast. Test geometry
(scaled dimensions, cap enforcement, 1×1 fallback) — never pixel bytes.
