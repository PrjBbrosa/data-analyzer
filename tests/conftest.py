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

import builtins
import sys

import pytest


def _qapplication_class():
    widgets = sys.modules.get("PyQt5.QtWidgets")
    if widgets is None:
        return None
    return getattr(widgets, "QApplication", None)


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

    Neutral items must not import Qt just to snapshot. If this item later
    constructs the first application in its body, capture that style as soon
    as ``QApplication.__init__`` returns. Checking ``sys.modules`` once at
    setup is not enough — a later import still has to wrap construction.

    The actual restore is deferred to this module's teardown hook: pytest-qt
    and the UI fixtures must finish their close/deleteLater work before
    global Qt appearance is changed.
    """
    original_init = None
    original_import = None

    def _install_init_capture(QApplication):
        nonlocal original_init
        if original_init is not None:
            return
        app = QApplication.instance()
        if app is not None:
            request.node._root_app_style_baseline = _snapshot_app_style(app)
            return
        original_init = QApplication.__init__

        def _capture_first_app(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            if not hasattr(request.node, "_root_app_style_baseline"):
                request.node._root_app_style_baseline = _snapshot_app_style(self)

        QApplication.__init__ = _capture_first_app

    QApplication = _qapplication_class()
    if QApplication is not None:
        _install_init_capture(QApplication)
    else:
        original_import = builtins.__import__

        def _import(name, globals=None, locals=None, fromlist=(), level=0):
            module = original_import(name, globals, locals, fromlist, level)
            if original_init is None:
                qapp_cls = _qapplication_class()
                if qapp_cls is not None:
                    _install_init_capture(qapp_cls)
            return module

        builtins.__import__ = _import

    try:
        yield
    finally:
        if original_import is not None:
            builtins.__import__ = original_import
        if original_init is not None:
            qapp_cls = _qapplication_class()
            if qapp_cls is not None:
                qapp_cls.__init__ = original_init


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item):
    """Restore global appearance after pytest-qt/UI ownership cleanup.

    Never ``return`` from ``finally``: that would swallow an in-flight
    teardown exception and turn a real ERROR into a false pass.
    """
    try:
        return (yield)
    finally:
        baseline = getattr(item, "_root_app_style_baseline", None)
        if baseline is None:
            pass
        else:
            QApplication = _qapplication_class()
            if QApplication is None:
                delattr(item, "_root_app_style_baseline")
            else:
                app = QApplication.instance()
                if app is not None:
                    _restore_app_style(app, baseline)
                delattr(item, "_root_app_style_baseline")
