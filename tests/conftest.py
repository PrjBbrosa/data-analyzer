"""Directory-level fixtures for everything under ``tests/``.

Keep project fixtures that belong to one subtree (UI isolation, acquisition
teardown) in that subtree's conftest. This file exists so a tool or test
that mutates the process-wide ``QApplication`` cannot leak into later items
that never entered ``tests/ui/`` — and so ``tests/ui/conftest.py`` snapshots
a clean baseline rather than an already-polluted one.

The repo-root ``conftest.py`` is not this file. It only repairs pytest's
directory-collector identity; do not add fixtures there.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _restore_app_style_after_test():
    """Snapshot-restore session QApplication chrome after every tests/ item.

    ``tools/verify_ultraview_visuals._ensure_app`` installs production QSS
    onto the process-wide QApplication and does not restore it. Items under
    ``tests/ui/`` snapshot that already-polluted state, so their no-QSS
    geometry contracts fail as if they were order-contaminated. See
    ``docs/analyzer/reviews/2026-08-16-codex-cursor-daily-batch-review.md`` §5.

    No app at setup is recorded as empty/default; teardown restores only
    when the live app differs. ``tests/ui/conftest.py::_isolate_app_style``
    stays as a second, idempotent layer.
    """
    try:
        from PyQt5.QtGui import QFont, QPalette
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        yield
        return

    app = QApplication.instance()
    if app is None:
        baseline = None
    else:
        baseline = (
            app.styleSheet(),
            app.style().objectName(),
            QPalette(app.palette()),
            QFont(app.font()),
        )
    yield
    app = QApplication.instance()
    if app is None:
        return
    if baseline is None:
        if app.styleSheet():
            app.setStyleSheet("")
        return
    sheet, style_name, palette, font = baseline
    if app.styleSheet() != sheet:
        app.setStyleSheet(sheet)
    if app.style().objectName() != style_name:
        app.setStyle(style_name)
    if app.palette() != palette:
        app.setPalette(palette)
    if app.font() != font:
        app.setFont(font)
