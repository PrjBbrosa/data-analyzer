---
id: qt-popup-singleton-validates-cpp-lifetime
status: active
owners: [codex]
keywords: [PyQt5, popup, singleton, sip.isdeleted, event-filter, teardown]
paths: [mf4_analyzer/ui_kit/glass_tooltip.py, tests/ui/test_glass_tooltip.py]
checks: ["TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_glass_tooltip.py -q"]
tests: [tests/ui/test_glass_tooltip.py]
---

# Qt Popup Singletons Validate The C++ Lifetime

Trigger: Keeping a parentless QWidget or popup in a Python class-level singleton
and accessing it from an application-wide Qt event filter.

Past failure: Qt deleted the popup's C++ object while the Python singleton still
held its wrapper. A later Hide or Leave event called `isVisible()` on that stale
wrapper and raised `RuntimeError: wrapped C/C++ object ... has been deleted`.

Rule: Clear the singleton from the popup's `destroyed` signal, validate cached
Qt wrappers with `sip.isdeleted()` before reuse, and let teardown/hide paths
query an existing popup without creating a replacement during shutdown.

Verification: Delete the popup with `sip.delete()` in a focused Qt test. Assert
that the singleton is cleared, the explicit creation path returns a new live
popup, and a Hide event neither raises nor recreates the popup.
