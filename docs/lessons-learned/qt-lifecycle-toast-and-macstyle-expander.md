---
id: qt-lifecycle-toast-and-macstyle-expander
status: active
owners: [codex]
keywords: [qt, toast, weakref, lifecycle, BatchSheet, teardown, margin_provider, QMacStyle, channelTree, Abort, offscreen]
paths: [mf4_analyzer/ui/widgets/toast.py, mf4_analyzer/ui/widgets/channel_tree.py, mf4_analyzer/ui_kit/qt_lifecycle.py]
checks: []
tests: [tests/ui/test_batch_toolbar.py, tests/ui/test_channel_widget.py::test_selected_file_parent_keeps_a_visible_expander]
---

# Toast providers stay weak; selected expanders avoid QMacStyle primitives

Trigger: ``Toast(margin_provider=bound_method)``; Darwin channel-tree
selected-branch overpaint via ``QStyle.drawPrimitive``.

Past failure:
1. BatchSheet→Toast→bound ``_own_toast_bottom_margin``→BatchSheet kept a
   Python cycle after Qt deleted the sheet → teardown
   ``RuntimeError: wrapped C/C++ object of type BatchSheet has been deleted``.
2. ``QMacStyle.PE_IndicatorBranch`` in ``_paint_selected_expander`` could
   ``Fatal Python error: Aborted`` under restricted offscreen hosts once the
   selected branch fill was styled.

Rule:
- ``Toast`` stores ``margin_provider`` through ``as_weak_callable``.
- Selected-row expander overpaint uses a vector chevron, not
  ``QMacStyle.drawPrimitive``.

Verification:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_batch_toolbar.py \
  tests/ui/test_channel_widget.py::test_selected_file_parent_keeps_a_visible_expander -q
```
