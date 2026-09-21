---
id: qimage-bits-numpy-view-needs-owned-copy
status: active
owners: [codex]
keywords: [qimage, numpy, frombuffer, bytesPerLine, verifier, lifetime]
paths: [tools/verify_frozen_batch_render.py]
checks: [owned RGB copy after convertToFormat; empty QImage raises]
tests: [tests/test_frozen_batch_render_smoke.py::TestPixelRgbArrayOwnership]
---

# QImage.bits() Views Are Not Stable Pixel Data

Trigger: Turning a `QImage` into a NumPy array for ink, colormap, or layout checks.

Past failure: `_pixel_rgb_array` returned `np.frombuffer(converted.bits())`. After the temporary RGB888 image was destroyed, later allocations reused the buffer; a probe first read `[12,34,56]` and then `[210,120,30]` while the source image was unchanged.

Rule: Copy packed RGB while the `QImage` is alive. Honor `bytesPerLine` padding. Return an array with owned storage. Empty or null images raise a clear `ValueError`. Do not treat allocator-address reuse as the only pass condition. `qt_chart_fonts._ink_pixels` still uses a live-image view; copy it before widening that helper.

Verification: `TestPixelRgbArrayOwnership` reads the array after deleting the source and allocating new QImages; cover padded RGB888, ARGB32, and empty images.
