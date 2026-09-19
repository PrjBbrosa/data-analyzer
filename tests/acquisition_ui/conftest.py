"""Shared fixtures for Cockpit UI tests.

Protection matrix (QWidget / timer / worker / modal / style) uses only the
low-level owned-object helper. It does not import ChartStack or Analyzer
MainWindow autouse from ``tests/ui/conftest.py``.
"""

from __future__ import annotations

import functools
import gc
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.acquisition_capture import thresholds
from tests._helpers.acq_owned_objects import (
    destroy_owned_widget,
    drain_deferred_deletes,
    restore_app_style,
    snapshot_app_style,
)


# Strong refs so sparkline/custom paint cannot collect a live C++ widget
# between the test body returning and pytest-qt pumping events.
_PINNED_TOPLEVELS: list[object] = []


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication so each test reuses the instance."""
    app = QApplication.instance() or QApplication([])
    yield app
    # Session owner must survive items; do not delete the application here.


@pytest.fixture(autouse=True)
def _isolate_threshold_state(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    thresholds.reset_defaults()
    yield
    thresholds.reset_defaults()


@pytest.fixture(autouse=True)
def _isolate_qsettings_paths(tmp_path, monkeypatch, request):
    """Keep Cockpit tests off the developer QSettings / registry store."""
    from PyQt5.QtCore import QSettings

    previous = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(tmp_path))
    request.node._acq_qsettings_default_format = previous
    yield


@pytest.fixture(autouse=True)
def _isolate_app_style(qapp, request):
    request.node._acq_app_style_baseline = snapshot_app_style(qapp)
    yield


@pytest.fixture(autouse=True)
def _own_cockpit_widgets(qapp, monkeypatch):
    """Track Cockpit windows and review modals created by an item."""
    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
    from mf4_analyzer.acquisition_ui.review_modal import ReviewModal

    created: list[object] = []

    def _wrap_init(orig_init):
        @functools.wraps(orig_init)
        def _tracking_init(self, *args, **kwargs):
            orig_init(self, *args, **kwargs)
            created.append(self)

        return _tracking_init

    monkeypatch.setattr(
        CockpitMainWindow, "__init__", _wrap_init(CockpitMainWindow.__init__)
    )
    monkeypatch.setattr(ReviewModal, "__init__", _wrap_init(ReviewModal.__init__))
    yield created
    qapp.processEvents()
    for widget in created:
        destroy_owned_widget(widget, qapp)
    created.clear()
    drain_deferred_deletes(qapp)
    gc.collect()


_MODAL_EXEC_FAIL_MS = 800


@pytest.fixture(autouse=True)
def _fail_fast_unstubbed_modal_exec(qapp, monkeypatch, request):
    """Refuse unstubbed synchronous Qt prompts in offscreen Cockpit tests."""
    from PyQt5.QtWidgets import (
        QColorDialog,
        QDialog,
        QFileDialog,
        QFontDialog,
        QInputDialog,
        QMenu,
        QMessageBox,
    )

    def _fail_before_native_modal(*_args, _api_name, **_kwargs):
        raise RuntimeError(
            f"{_api_name} attempted in {request.node.nodeid}. "
            "Stub this native modal API with the intended user decision."
        )

    def _guard_native_static_methods() -> None:
        for klass, methods in (
            (QMessageBox, ("about", "aboutQt", "critical", "information", "question", "warning")),
            (
                QFileDialog,
                (
                    "getExistingDirectory",
                    "getOpenFileName",
                    "getOpenFileNames",
                    "getSaveFileName",
                    "getOpenFileUrl",
                    "getOpenFileUrls",
                    "getSaveFileUrl",
                ),
            ),
            (QInputDialog, ("getDouble", "getInt", "getItem", "getMultiLineText", "getText")),
            (QColorDialog, ("getColor",)),
            (QFontDialog, ("getFont",)),
        ):
            for method in methods:
                monkeypatch.setattr(
                    klass,
                    method,
                    lambda *_args, _api_name=f"{klass.__name__}.{method}()", **_kwargs:
                    _fail_before_native_modal(*_args, _api_name=_api_name, **_kwargs),
                )

    _guard_native_static_methods()

    def _guarded_menu_exec(*_args, **_kwargs):
        _fail_before_native_modal(*_args, _api_name="QMenu.exec()", **_kwargs)

    monkeypatch.setattr(QMenu, "exec_", _guarded_menu_exec)
    monkeypatch.setattr(QMenu, "exec", _guarded_menu_exec)

    if request.node.get_closest_marker("allow_blocking_modal"):
        yield
        return

    original = QDialog.exec_

    def _guarded(dialog, *args, **kwargs):
        timed_out = False
        timeout = QTimer(dialog)
        timeout.setSingleShot(True)

        def _timeout():
            nonlocal timed_out
            if sip.isdeleted(dialog):
                return
            timed_out = True
            try:
                dialog.reject()
            except RuntimeError:
                pass

        timeout.timeout.connect(_timeout)
        timeout.start(_MODAL_EXEC_FAIL_MS)
        try:
            result = original(dialog, *args, **kwargs)
        finally:
            if not sip.isdeleted(timeout):
                timeout.stop()
                timeout.deleteLater()
        if timed_out:
            title = ""
            try:
                title = dialog.windowTitle()
            except RuntimeError:
                title = "<deleted>"
            raise RuntimeError(
                f"QDialog.exec_() blocked in {request.node.nodeid} "
                f"({type(dialog).__name__} title={title!r}). "
                "Stub the confirmation seam, or mark allow_blocking_modal."
            )
        return result

    monkeypatch.setattr(QDialog, "exec_", _guarded)
    monkeypatch.setattr(QDialog, "exec", _guarded)
    yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    try:
        return (yield)
    finally:
        _PINNED_TOPLEVELS.clear()
        app = QApplication.instance()
        if app is not None:
            _PINNED_TOPLEVELS.extend(app.topLevelWidgets())


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item):
    try:
        return (yield)
    finally:
        _PINNED_TOPLEVELS.clear()
        app = QApplication.instance()
        drain_deferred_deletes(app)
        gc.collect()
        baseline = getattr(item, "_acq_app_style_baseline", None)
        restore_app_style(app, baseline)
        if hasattr(item, "_acq_app_style_baseline"):
            delattr(item, "_acq_app_style_baseline")
        previous = getattr(item, "_acq_qsettings_default_format", None)
        if previous is not None:
            from PyQt5.QtCore import QSettings

            QSettings.setDefaultFormat(previous)
            delattr(item, "_acq_qsettings_default_format")
