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


def _snapshot_app_style(app):
    from PyQt5.QtGui import QFont, QPalette

    return (
        app.styleSheet(),
        app.style().objectName(),
        QPalette(app.palette()),
        QFont(app.font()),
    )


def _restore_app_style(app, baseline) -> None:
    sheet, style_name, palette, font = baseline
    if app.styleSheet() != sheet:
        app.setStyleSheet(sheet)
    if app.style().objectName() != style_name:
        app.setStyle(style_name)
    if app.palette() != palette:
        app.setPalette(palette)
    if app.font() != font:
        app.setFont(font)


@pytest.fixture(autouse=True)
def _restore_app_style_after_test(request):
    """Snapshot-restore session QApplication chrome after every tests/ item.

    ``tools/verify_ultraview_visuals._ensure_app`` installs production QSS
    onto the process-wide QApplication and does not restore it. Items under
    ``tests/ui/`` snapshot that already-polluted state, so their no-QSS
    geometry contracts fail as if they were order-contaminated. See
    ``docs/analyzer/reviews/2026-08-16-codex-cursor-daily-batch-review.md`` §5.

    When an item creates the first application in its test body, capture its
    freshly constructed style as soon as ``QApplication.__init__`` returns.
    The actual restore is deliberately deferred to this module's teardown
    hook: pytest-qt and the UI fixtures must finish their close/deleteLater
    work before global Qt appearance is changed.
    """
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        yield
        return

    app = QApplication.instance()
    original_init = None
    if app is not None:
        request.node._root_app_style_baseline = _snapshot_app_style(app)
    else:
        original_init = QApplication.__init__

        def _capture_first_app(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            if not hasattr(request.node, "_root_app_style_baseline"):
                request.node._root_app_style_baseline = _snapshot_app_style(self)

        QApplication.__init__ = _capture_first_app

    try:
        yield
    finally:
        if original_init is not None:
            QApplication.__init__ = original_init


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item):
    """Restore global appearance after pytest-qt/UI ownership cleanup."""
    try:
        return (yield)
    finally:
        baseline = getattr(item, "_root_app_style_baseline", None)
        if baseline is not None:
            try:
                from PyQt5.QtWidgets import QApplication
            except ImportError:
                pass
            else:
                app = QApplication.instance()
                if app is not None:
                    _restore_app_style(app, baseline)
            delattr(item, "_root_app_style_baseline")
