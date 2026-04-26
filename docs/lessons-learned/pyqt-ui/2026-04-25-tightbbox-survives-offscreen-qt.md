---
role: pyqt-ui
tags: [matplotlib, bbox, export, clipboard, offscreen]
created: 2026-04-25
updated: 2026-04-25
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

## Lesson

`Axes.get_tightbbox(self.fig.canvas.get_renderer())` returns usable
figure-pixel coords on the offscreen Qt platform once `plot_result`
has run; you do NOT have to surrender to a full-canvas grab on
headless platforms. Keep the bbox path as the primary, with a
defensive fallback (degenerate rect / null pixmap / exception) — both
test environments and real desktop sessions get the cropped image.

## How to apply

For any new "grab a region of a FigureCanvas to the clipboard" task:
implement the bbox crop first, fall back to `self.grab()` only when
the rect is degenerate (`qw < 10 or qh < 10`), the resulting pixmap
is null, or the bbox/transform path raises. Do NOT default to
`self.grab()` based on a guess that headless Qt cannot realize the
layout — the offscreen platform is sufficient for matplotlib to
compute tight bboxes once any axis has been rendered.
