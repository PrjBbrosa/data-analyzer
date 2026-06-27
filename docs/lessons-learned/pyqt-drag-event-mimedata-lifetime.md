---
id: pyqt-drag-event-mimedata-lifetime
status: active
owners: [codex]
keywords: [pyqt, drag-drop, qdragenterevent, qdropevent, qmimedata, pytest-qt, segfault]
paths: [tests/ui/**, mf4_analyzer/ui/**]
checks:
  - retain QMimeData references on synthetic QDragEnterEvent and QDropEvent objects
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_drop_import.py -q
---

# PyQt Drag Event MimeData Lifetime

Trigger: Writing pytest-qt tests that manually construct `QDragEnterEvent`,
`QDropEvent`, or related drag/drop events with `QMimeData`.

Past failure: A synthetic drag test passed a temporary `QMimeData` directly into
`QDragEnterEvent`; after the helper returned, Qt retained a pointer whose Python
wrapper could be collected. Calling `acceptProposedAction()` then segfaulted
instead of producing a normal assertion failure.

Rule: Keep the `QMimeData` alive for at least as long as the synthetic event,
for example by assigning `event._mime_ref = mime` in the test helper.

Verification: Run the focused drag/drop UI test under offscreen Qt and confirm
it exits normally rather than crashing.
