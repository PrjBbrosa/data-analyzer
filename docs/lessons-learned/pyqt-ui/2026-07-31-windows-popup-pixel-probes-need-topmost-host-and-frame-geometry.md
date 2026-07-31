---
role: pyqt-ui
tags: [pyqt, windows, popup, rounded-corners, qscreen, grabwindow, dpr, frame-geometry, topmost]
created: 2026-07-31
updated: 2026-07-31
cause: insight
supersedes: []
---

## Context

A Windows desktop capture of a rounded SignalPicker popup appeared to find
white rectangular backing pixels. The probe host was behind another foreground
window and its coordinates treated the client origin as the native window
frame, so it sampled an unrelated surface or title bar instead of the popup
corners.

## Lesson

For real Windows `QScreen.grabWindow(0)` acceptance, make the high-contrast
host `Qt.WindowStaysOnTopHint`, verify an unobscured client-area reference
pixel, and derive outer-corner samples from `frameGeometry()` after DPR
conversion. Record the full desktop, crop, platform, Qt, DPI, branch SHA,
host reference, geometry, and all four pixels. Do not use `widget.grab()` or
an offscreen platform for this check.

## How to apply

Run `python scripts/probe_signal_picker_popup_shell.py` from an interactive
Windows desktop. Its JSON must show the host reference and each sampled outer
corner matching the configured host RGB within tolerance.
