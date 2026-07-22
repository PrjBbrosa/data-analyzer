---
id: codex-qmessagebox-qss-content-width
status: active
owners: [codex]
keywords: [pyqt, qmessagebox, qss, button, text-elision, dbc, rendered-screenshot]
paths:
  - mf4_analyzer/ui_kit/message_box_buttons.py
  - mf4_analyzer/ui/main_window/_project_io_mixin.py
  - tests/ui/test_blf_batch_import.py
checks:
  - render batch-DBC dialogs with the shared stylesheet and inspect button text bounds
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_blf_batch_import.py -q
---

# QMessageBox QSS Content Width

Trigger: Adding or changing text buttons in a styled QMessageBox, especially
batch BLF/DBC confirmation and mismatch dialogs.

Past failure: The QSS ``min-width`` was interpreted as content width before
horizontal padding, while QMessageBox allocated the resulting outer minimum.
The test compared text width to the outer widget rectangle, so it passed even
though ``统一选 DBC`` and longer batch-mismatch labels were painted clipped.

Rule: Set each relevant message-box button's content minimum from its active
font's text width plus slack. Render with the shared stylesheet; do not judge
capacity from ``contentsRect`` or an unstyled test alone.

Verification: Run the batch-import UI test and capture both initial and
mismatch dialogs. For every button, assert its outer width is at least text
width plus the QSS horizontal padding, borders, and slack.
