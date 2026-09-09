---
id: codex-batch-header-surface-cascade
status: active
owners: [codex]
keywords: [batch, header, qss, background, focus, render]
paths: [mf4_analyzer/ui/drawers/batch/*, mf4_analyzer/ui_kit/style.qss]
checks: []
tests: [tests/ui/test_batch_header_render.py]
---

# Batch Header Surfaces Must Survive the Global QSS

Trigger: Styling nested toolbar/method-row widgets or method button states.

Past failure: The method row's blue surface was interrupted by white child
containers from the global QWidget rule. Inline pipeline colors also bypassed
the shared style, and method selection had no surface or keyboard-focus feedback.

Rule: Give layout-only children explicit transparent backgrounds; keep component
colors in scoped QSS and style hover, pressed, focus, and disabled states there.
Verify actual composed pixels, not only selector strings. Preserve compact
geometry and isolate QSettings in native Qt screenshot probes.

Verification: Run tests/ui/test_batch_header_render.py and the method/toolbar
owner tests. Inspect the native Windows widget at 100%, 125%, and 150% scaling.
