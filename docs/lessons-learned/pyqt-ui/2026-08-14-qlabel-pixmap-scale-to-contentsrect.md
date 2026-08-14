---
id: pyqt-ui/2026-08-14-qlabel-pixmap-scale-to-contentsrect
status: active
owners: [codex]
keywords: [QLabel, pixmap, contentsRect, QSS, padding, UltraView, ultraViewCardImage]
paths: [mf4_analyzer/ui/chart_stack/ultraview/widgets.py, mf4_analyzer/ui_kit/style.qss, tests/ui/test_ultraview_viewport.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py::test_card_preview_keeps_top_pixels_inside_qss_padding -q]
tests: [tests/ui/test_ultraview_viewport.py]
---

# QLabel Pixmap Scale To ContentsRect

Trigger: Fitting a pixmap into a `QLabel` that has QSS `padding`, especially UltraView `QLabel#ultraViewCardImage`.

Past failure: `_fit_card_image` scaled to `self._image.size()`. QSS `padding: 8px` inset `contentsRect`, `AlignCenter` then clipped ~8px off the top and bottom. Time-domain top spine and the top Y tick disappeared under a white band that looked like a header overlay but was just padding crop.

Rule: Scale the pixmap to `contentsRect().size()`, not `size()`. Keep the padding as inset, do not raise the image under the header. After stylesheet polish, assert a distinctive top row remains visible inside `contentsRect`.

Verification: `test_card_preview_keeps_top_pixels_inside_qss_padding`.
