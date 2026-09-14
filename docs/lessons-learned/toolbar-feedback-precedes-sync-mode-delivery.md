---
id: toolbar-feedback-precedes-sync-mode-delivery
status: active
owners: [codex]
keywords: [toolbar, navigation, selection-indicator, mode-changed, animation, signal, reentrancy]
paths:
  - mf4_analyzer/ui/toolbar.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_toolbar.py -q
---

# Toolbar Feedback Precedes Synchronous Mode Delivery

Trigger: Changing Toolbar section selection, selection-indicator animation, or
the synchronous delivery order of ``mode_changed``.

Past failure: ``Toolbar._apply_mode`` emitted ``mode_changed`` before starting
the indicator.  Its MainWindow receiver synchronously switched and restored
section content, so the new content could already be present before navigation
feedback even began.

Rule: After committing the checked button and active dot, start or snap the
selection indicator before emitting ``mode_changed``.  Keep the business signal
synchronous, and do no additional indicator work after receiver delivery so a
receiver may re-navigate or destroy the Toolbar safely.

Verification: Run the Toolbar feedback-order, reentrant-navigation, and
receiver-destruction tests in ``tests/ui/test_toolbar.py``.  The
Section/View integration check in ``tests/ui/test_section_entry_presentation.py``
must continue to prove manager-confirmed marker placement precedes real Time
and FFT restore.
