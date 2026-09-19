"""Low-level owned-object tools for Acquisition Cockpit tests.

This is test-only isolation infrastructure. It does not import ChartStack or
Analyzer MainWindow autouse from ``tests/ui/conftest.py``.
"""

from __future__ import annotations

import gc
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QThread, QThreadPool, QTimer
from PyQt5.QtWidgets import QApplication, QWidget


def is_deleted(obj: object) -> bool:
    """Return True when *obj* is missing or its sip wrapper is gone."""
    if obj is None:
        return True
    try:
        return bool(sip.isdeleted(obj))
    except (RuntimeError, TypeError):
        return True


def drain_deferred_deletes(app: QApplication | None = None) -> None:
    """Deliver queued DeferredDelete events, then pump the GUI thread once."""
    app = app or QApplication.instance()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    if app is not None:
        app.processEvents()


def owned_timers(widget: QWidget) -> list[QTimer]:
    if is_deleted(widget):
        return []
    return list(widget.findChildren(QTimer))


def stop_owned_producers(widget: QWidget) -> None:
    """Stop timers and wait for thread pools. Never ``QThread.terminate()``."""
    if is_deleted(widget):
        return
    for timer in widget.findChildren(QTimer):
        try:
            if timer.isActive():
                timer.stop()
        except RuntimeError:
            continue
    for pool in widget.findChildren(QThreadPool):
        try:
            pool.waitForDone(2_000)
        except RuntimeError:
            continue
    for thread in widget.findChildren(QThread):
        try:
            if thread.isRunning():
                thread.quit()
                thread.wait(2_000)
        except RuntimeError:
            continue


def destroy_owned_widget(widget: QWidget | None, app: QApplication | None = None) -> None:
    """Close *widget*, drain DeferredDelete, and drop the C++ object."""
    app = app or QApplication.instance()
    if widget is None or is_deleted(widget):
        drain_deferred_deletes(app)
        gc.collect()
        return
    stop_owned_producers(widget)
    try:
        widget.close()
    except RuntimeError:
        pass
    try:
        widget.deleteLater()
    except RuntimeError:
        pass
    drain_deferred_deletes(app)
    gc.collect()


def living_widgets_of_type(cls: type) -> list[QWidget]:
    app = QApplication.instance()
    if app is None:
        return []
    living: list[QWidget] = []
    for widget in app.topLevelWidgets():
        if is_deleted(widget):
            continue
        if isinstance(widget, cls):
            living.append(widget)
    return living


def snapshot_app_style(app: QApplication) -> tuple:
    from PyQt5.QtGui import QFont, QPalette

    return (
        app.styleSheet(),
        app.style().objectName(),
        QPalette(app.palette()),
        QFont(app.font()),
    )


def restore_app_style(app: QApplication | None, baseline: tuple | None) -> None:
    if app is None or baseline is None:
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


def isolated_user_env(home: Path, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a child-process env that cannot resolve the real user store."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    tmp = home / "tmp"
    tmp.mkdir(exist_ok=True)
    xdg_config = home / "xdg-config"
    xdg_cache = home / "xdg-cache"
    local_app = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    mpl = home / "mpl"
    for path in (xdg_config, xdg_cache, local_app, roaming, mpl):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["HOMEDRIVE"] = str(home.anchor) if home.anchor else str(home)
    env["HOMEPATH"] = str(home)
    env["XDG_CONFIG_HOME"] = str(xdg_config)
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    env["LOCALAPPDATA"] = str(local_app)
    env["APPDATA"] = str(roaming)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MPLCONFIGDIR"] = str(mpl)
    env["TMPDIR"] = str(tmp)
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    if extra:
        env.update(extra)
    return env


def junit_case_results(path: Path) -> dict[str, str]:
    """Map pytest junit ``testcase@name`` → passed/failed/skipped/error."""
    tree = ET.parse(path)
    results: dict[str, str] = {}
    for case in tree.iter("testcase"):
        name = case.attrib.get("name", "")
        if case.find("failure") is not None:
            results[name] = "failed"
        elif case.find("error") is not None:
            results[name] = "error"
        elif case.find("skipped") is not None:
            results[name] = "skipped"
        else:
            results[name] = "passed"
    return results


def assert_producers_destroyed(widgets: Iterable[QWidget], timers: Iterable[QTimer]) -> None:
    for widget in widgets:
        assert is_deleted(widget), f"owned widget still alive: {type(widget).__name__}"
    for timer in timers:
        assert is_deleted(timer), "owned QTimer still alive after owner destroy"
