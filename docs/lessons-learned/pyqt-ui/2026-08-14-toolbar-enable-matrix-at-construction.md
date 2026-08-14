---
id: pyqt-ui/2026-08-14-toolbar-enable-matrix-at-construction
status: active
owners: [codex]
keywords: [toolbar, enable-state, construction, save, has_file, QPushButton]
paths: [mf4_analyzer/ui/toolbar.py, tests/ui/test_toolbar.py, tests/ui/test_open_and_save_entry.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_toolbar.py tests/ui/test_open_and_save_entry.py -q]
tests: [tests/ui/test_toolbar.py, tests/ui/test_open_and_save_entry.py]
---

# Toolbar Enable Matrix At Construction

Trigger: Changing toolbar button enable/disable rules, `set_enabled_for_mode`, or any gated QPushButton whose live state is applied only on a later event.

Past failure: 保存 is gated on `has_file`, but `Toolbar` left the split at Qt's default enabled. First launch with an empty session showed an active Save until the user switched analysis modules, which was the first call to `set_enabled_for_mode`.

Rule: Apply the enable-state matrix at construction for the empty-session row. Do not wait for the first mode change, file activation, or other later event to correct a QPushButton that starts enabled.

Verification: Assert a freshly constructed `Toolbar` and empty `MainWindow` have Save disabled; enable after load and disable after close-all. Run `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_toolbar.py tests/ui/test_open_and_save_entry.py -q`.
