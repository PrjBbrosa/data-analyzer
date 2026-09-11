---
id: progress-label-implicit-indent-clips-ink
status: active
owners: [codex]
keywords: [QLabel, progress, QSS, indent, clipping, percent]
paths: [mf4_analyzer/ui/compute_progress.py, tests/ui/test_compute_progress.py]
checks: []
tests: [tests/ui/test_compute_progress.py::test_progress_label_keeps_all_ink_at_requested_width]
---

# Progress Label Must Account For Implicit QLabel Indent

Trigger: Changing progress label geometry, text budgets, masks, or QSS padding.

Past failure: Repeated spacing and vertical-mask fixes left the trailing percent clipped. QSS padding produced a nonzero QLabel frameWidth; default indent=-1 shifted text by half an x, but sizeHint and elision only budgeted text advance. Complete label.text() and disjoint widget rectangles concealed the missing ink.

Rule: When layout and padding own spacing, explicitly disable QLabel automatic indent. Do not patch this failure by adding arbitrary width or weakening the clipping mask. The earlier compute-progress chrome lesson's contentsRect budget assumes there is no additional QLabel indent/margin.

Verification: Compare painted text ink at the requested width against an expanded reference through the parent widget (including the child mask), using production QSS. Cover loading phases and 0/25/99/100 percent; run the probe with both offscreen Qt and native Cocoa. On 2026-09-10 the regression failed before the fix, then all 12 cases passed on both backends.
