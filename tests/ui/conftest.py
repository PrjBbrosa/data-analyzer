"""Shared pytest fixtures for UI tests."""
import gc
import os
import weakref
# Force offscreen Qt platform for headless CI *before* QApplication exists
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.render_profile import DENSE_DISCRETE_POLICY_ENABLED


# Strong references to the top-level widgets alive when a test body returned.
# Read the two hooks below before touching this — it is a lifetime guard, not
# a cache, and it must stay a module-level list so the references outlive the
# item's own frames.
_PINNED_TOPLEVELS = []

# Pin-filter registry: item-owned objects vs session baseline.  The WeakSet is
# the cheap path; a full ``gc.get_objects()`` scan cross-checks it on pin
# tests and on any item that constructed a Router/controller.
_ALL_PIN_ROUTERS = None
_ALL_PIN_CONTROLLERS = None
_ORIG_PIN_ROUTER_INIT = None
_ORIG_PIN_CONTROLLER_INIT = None
_PIN_REGISTRY_INSTALLED = False
_CURRENT_PIN_ITEM = None


def _is_static_source(item) -> bool:
    getter = getattr(item, "get_closest_marker", None)
    if getter is None:
        return False
    return getter("static_source") is not None


def pytest_collection_modifyitems(config, items):
    if DENSE_DISCRETE_POLICY_ENABLED:
        return
    skip = pytest.mark.skip(
        reason="CRC dense_discrete policy parked; ink budget is the active gate",
    )
    for item in items:
        if item.get_closest_marker("crc_dense_discrete_policy"):
            item.add_marker(skip)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Pin live top-level widgets before pytest-qt pumps post-test events.

    ``QtBot.addWidget`` keeps only a **weak** reference (``pytestqt.qtbot``
    stores ``weakref.ref(widget)`` and resolves it in ``_close_widgets``), so
    the moment a test body returns, its parentless ``QWidget`` is reachable
    only through its own reference cycles — a PyQt widget always has some
    (``_ChannelTree._owner`` points back at the ``MultiFileChannelWidget``
    that owns the tree; every bound-method signal connection adds more).
    Refcounting therefore cannot free it, and it stays *shown* with an update
    still queued.

    pytest-qt then calls ``app.processEvents()`` three more times (once after
    ``pytest_runtest_call``, twice inside ``pytest_runtest_teardown``), which
    delivers that queued paint. Now C++ is executing ``QTreeWidget::drawRow``
    → ``_ChannelLeafDelegate.paint``, and every allocation that delegate makes
    (``QRect`` copies, the ``QStyleOptionViewItem`` copy plus
    ``initStyleOption``, ``QFontMetrics``, the elided ``str``) can trip
    CPython's generational collector. A gen-0 collection at that instant
    reaps the garbage cycle holding the widget, sip deletes the C++
    ``QTreeWidget`` and its viewport **underneath the running paint**, and the
    next call through the dangling object — ``QPainter.drawText`` or
    ``QModelIndex.flags`` — faults with ``KERN_INVALID_ADDRESS``.

    That is a hard PyQt invariant, not a channel-tree bug: a Python-owned
    widget must not be collectible while Qt is inside its paint. During the
    test body itself the widget is safe because the test frame holds a strong
    reference; only this post-body window is unguarded. So we re-create that
    strong reference for exactly that window and drop it in
    ``pytest_runtest_teardown`` below, which then reaps at a point where no
    ``QPainter`` is live.

    Bisected to ``f85b5d4e`` (``fix(ui): stabilize channel-tree and
    follow-link chrome``), which routed the Pts column of *every* row type
    through the Python paint path — previously non-channel rows fell through
    to C++ ``super().paint()`` and allocated nothing — pushing the per-row
    allocation count over the gen-0 threshold mid-paint. Do not "fix" a
    recurrence by trimming allocations from a paint method; that only moves
    the threshold.
    """
    if _is_static_source(item):
        return (yield)
    try:
        return (yield)
    finally:
        _PINNED_TOPLEVELS.clear()
        app = QApplication.instance()
        if app is not None:
            _PINNED_TOPLEVELS.extend(app.topLevelWidgets())


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item):
    """Release the pin, then reap immediately — both halves matter.

    *When to release.* This plain wrapper's post-yield half runs after
    pytest-qt's (its teardown hook is a ``trylast`` wrapper, so its post-yield
    goes first) **and** after every fixture finalizer, including
    ``_own_chartstacks``, which pumps ``processEvents()`` of its own. Releasing
    any earlier would reopen the window this guard exists to close.

    *Why collect here.* One ``gc.collect()`` after DeferredDelete and after
    the pin-filter check releases this item's owner lists. The lists have to
    stay intact for the check, then go away before collect: the pytest item
    outlives the test, and a leftover strong ref keeps deleted
    router/controller wrappers alive for the rest of the session. Collecting
    while ``_PINNED_TOPLEVELS`` is still held cannot reap the test's widgets
    and left ``TimeDomainCanvasPG`` instances counted against the dense-raster
    memory caps, so the next canvas was refused admission.
    """
    if _is_static_source(item):
        return (yield)
    try:
        return (yield)
    finally:
        _PINNED_TOPLEVELS.clear()
        app = QApplication.instance()
        if app is not None:
            # pytest-qt and fixture finalizers queue ``deleteLater`` while
            # the top-level paint pin is held.  Release that pin only after
            # their work, then deliver precisely DeferredDelete events before
            # the next item; do not sweep all widgets or delete session-owned
            # objects that this item never owned.
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
        try:
            # The leak check still needs this item's owner lists. Release
            # them on both pass and fail, then collect so the next item does
            # not inherit deleted Python wrappers. Style/QSettings restore
            # stays outside that check so a pin failure is not replaced by a
            # later cleanup error, and collect still runs.
            _finish_item_pin_check(item)
        finally:
            _restore_item_app_style(item)
            _restore_qsettings_default_format(item)
            gc.collect()


def _qt_wrapper_alive(obj) -> bool:
    try:
        return not sip.isdeleted(obj)
    except (ReferenceError, RuntimeError, TypeError):
        return False


def _router_filter_installed(router) -> bool:
    if not _qt_wrapper_alive(router):
        return False
    try:
        return bool(router.application_filter_installed)
    except (ReferenceError, RuntimeError, TypeError):
        return False


def _controller_filter_flag(controller) -> bool:
    if not _qt_wrapper_alive(controller):
        return False
    try:
        return bool(controller._application_filter_installed)
    except (ReferenceError, RuntimeError, TypeError):
        return False


def _ensure_pin_filter_registry() -> None:
    """Wrap Router/controller construction once per process.

    The wrap is installed on the first non-static UI item, before that item's
    body, so ChartStack-created routers are registered.  It is not installed
    for ``static_source`` sessions, which must not import the pin stack.
    """
    global _ALL_PIN_ROUTERS, _ALL_PIN_CONTROLLERS
    global _ORIG_PIN_ROUTER_INIT, _ORIG_PIN_CONTROLLER_INIT
    global _PIN_REGISTRY_INSTALLED
    if _PIN_REGISTRY_INSTALLED:
        return
    from mf4_analyzer.ui.chart_stack.pinned_cursor_controller import (
        PinnedCursorController,
    )
    from mf4_analyzer.ui.chart_stack.pinning.key_router import PinKeyRouter

    _ALL_PIN_ROUTERS = weakref.WeakSet()
    _ALL_PIN_CONTROLLERS = weakref.WeakSet()
    _ORIG_PIN_ROUTER_INIT = PinKeyRouter.__init__
    _ORIG_PIN_CONTROLLER_INIT = PinnedCursorController.__init__

    def _tracking_router_init(self, *args, **kwargs):
        _ORIG_PIN_ROUTER_INIT(self, *args, **kwargs)
        _ALL_PIN_ROUTERS.add(self)
        item = _CURRENT_PIN_ITEM
        if item is not None:
            getattr(item, "_pin_owned_routers").append(self)

    def _tracking_controller_init(self, *args, **kwargs):
        _ORIG_PIN_CONTROLLER_INIT(self, *args, **kwargs)
        _ALL_PIN_CONTROLLERS.add(self)
        item = _CURRENT_PIN_ITEM
        if item is not None:
            getattr(item, "_pin_owned_controllers").append(self)

    PinKeyRouter.__init__ = _tracking_router_init
    PinnedCursorController.__init__ = _tracking_controller_init
    _PIN_REGISTRY_INSTALLED = True


def _installed_from_registry():
    routers = [obj for obj in list(_ALL_PIN_ROUTERS or ()) if _router_filter_installed(obj)]
    controllers = [
        obj for obj in list(_ALL_PIN_CONTROLLERS or ()) if _controller_filter_flag(obj)
    ]
    return routers, controllers


def _installed_from_heap():
    from mf4_analyzer.ui.chart_stack.pinned_cursor_controller import (
        PinnedCursorController,
    )
    from mf4_analyzer.ui.chart_stack.pinning.key_router import PinKeyRouter

    routers = []
    controllers = []
    for obj in gc.get_objects():
        try:
            if type(obj) is PinnedCursorController:
                if _controller_filter_flag(obj):
                    controllers.append(obj)
            elif type(obj) is PinKeyRouter and _router_filter_installed(obj):
                routers.append(obj)
        except (ReferenceError, RuntimeError, TypeError):
            continue
    return routers, controllers


def _should_cross_check_pin_heap(item) -> bool:
    nodeid = getattr(item, "nodeid", "")
    if "pinned_cursor" in nodeid or "qt_fixture_lifecycle" in nodeid:
        return True
    if getattr(item, "_pin_owned_routers", None) or getattr(
        item, "_pin_owned_controllers", None
    ):
        return True
    return False


_ITEM_PIN_RECORD_NAMES = (
    "_pin_owned_routers",
    "_pin_owned_controllers",
    "_pin_filter_baseline_routers",
)


def _release_item_pin_records(item) -> None:
    """Drop this item's pin records without touching the session registry.

    The pytest item object lives for the whole session. The owner lists are
    strong references used only to judge this item's filter delta. Leaving
    them in place keeps deleted router/controller wrappers reachable, so a
    later ``gc.collect()`` cannot reclaim them. Baseline entries are weak
    refs; clearing those lists does not delete a session-owned QObject.
    """
    for name in _ITEM_PIN_RECORD_NAMES:
        records = getattr(item, name, None)
        if isinstance(records, list):
            records.clear()


def _finish_item_pin_check(item) -> None:
    """Judge installed pin filters, then always release the item records.

    ``pytest.fail`` must still propagate. The ``finally`` only clears the
    lists that made the judgment possible.
    """
    try:
        _assert_pinned_cursor_filters_not_accumulated(item)
    finally:
        _release_item_pin_records(item)


def _assert_pinned_cursor_filters_not_accumulated(item):
    """Living app-level pin filters must not accumulate across tests.

    After T3 the unique filter lives on ``PinKeyRouter``. The façade
    ``PinnedCursorController._application_filter_installed`` must track that
    real install.  Item-owned routers/controllers are the delta against the
    pre-item baseline; a leaked owned filter fails even when the total is 1.
    Session-owned baseline objects may remain.  Registry results are
    cross-checked with a full heap scan on pin tests and on items that
    constructed pin objects.
    """
    from mf4_analyzer.ui.chart_stack.pinned_cursor_controller import (
        PinnedCursorController,
    )
    from mf4_analyzer.ui.chart_stack.pinning.key_router import PinKeyRouter

    owned_router_leaks = [
        router
        for router in getattr(item, "_pin_owned_routers", ())
        if _router_filter_installed(router)
    ]
    owned_controller_leaks = [
        controller
        for controller in getattr(item, "_pin_owned_controllers", ())
        if _controller_filter_flag(controller)
    ]
    if owned_router_leaks or owned_controller_leaks:
        pytest.fail(
            f"item-owned pin filters still installed after {item.nodeid}: "
            f"{len(owned_router_leaks)} routers, "
            f"{len(owned_controller_leaks)} controllers"
        )

    if _should_cross_check_pin_heap(item) and _PIN_REGISTRY_INSTALLED:
        heap_routers, heap_controllers = _installed_from_heap()
        reg_routers, reg_controllers = _installed_from_registry()
        if {id(obj) for obj in heap_routers} != {id(obj) for obj in reg_routers}:
            pytest.fail(
                f"PinKeyRouter registry ({len(reg_routers)}) disagrees with "
                f"full heap scan ({len(heap_routers)}) after {item.nodeid}"
            )
        if {id(obj) for obj in heap_controllers} != {
            id(obj) for obj in reg_controllers
        }:
            pytest.fail(
                f"PinnedCursorController registry ({len(reg_controllers)}) "
                f"disagrees with full heap scan ({len(heap_controllers)}) "
                f"after {item.nodeid}"
            )
    elif not _PIN_REGISTRY_INSTALLED:
        # Keep the import-failure probe and the no-registry fallback on the
        # heap scan; PinnedCursorController is imported above so a broken
        # controller import still surfaces here.
        pass

    baseline_router_ids = {
        id(ref())
        for ref in getattr(item, "_pin_filter_baseline_routers", ())
        if ref() is not None and _router_filter_installed(ref())
    }
    current_routers, current_controllers = (
        _installed_from_registry()
        if _PIN_REGISTRY_INSTALLED
        else _installed_from_heap()
    )
    extra = [
        router for router in current_routers if id(router) not in baseline_router_ids
    ]
    if extra:
        pytest.fail(
            f"{len(extra)} PinKeyRouter app filters appeared during "
            f"{item.nodeid} and survived teardown"
        )

    if len(current_controllers) != len(current_routers):
        pytest.fail(
            f"controller filter flag ({len(current_controllers)}) does not match "
            f"Router install ({len(current_routers)}) after {item.nodeid}"
        )


_MODAL_EXEC_FAIL_MS = 800


@pytest.fixture(autouse=True)
def _pin_filter_item_scope(request):
    """Record this item's pin-filter baseline and constructed owners."""
    global _CURRENT_PIN_ITEM
    if _is_static_source(request.node):
        yield
        return
    _ensure_pin_filter_registry()
    routers, _controllers = _installed_from_registry()
    request.node._pin_filter_baseline_routers = [weakref.ref(router) for router in routers]
    request.node._pin_owned_routers = []
    request.node._pin_owned_controllers = []
    _CURRENT_PIN_ITEM = request.node
    try:
        yield
    finally:
        _CURRENT_PIN_ITEM = None


@pytest.fixture(autouse=True)
def _fail_fast_unstubbed_modal_exec(request):
    """Refuse unstubbed synchronous Qt prompts in offscreen tests.

    Combined UI pytest hung 2h+ at 0% CPU in
    ``PresetBar._confirm_axis_preservation`` → ``box.exec_()`` because no
    click ever arrived. Tests that drive a dialog with ``QTimer.singleShot(0)``
    still finish; a forgotten modal fails in <1s instead of hanging.

    ``QMenu`` owns its ``exec`` implementations instead of inheriting the
    ``QDialog`` methods, so it needs its own pre-call guard. Native static
    helpers (file/color/font/input pickers and message-box conveniences) can
    bypass the Python ``QDialog.exec`` wrapper entirely; unlike a constructed
    dialog there is no reliable object to close on a timeout.  Tests must
    explicitly stub those APIs with the intended result.

    ``allow_blocking_modal`` remains an escape hatch only for constructed
    dialogs that a test drives itself. It deliberately cannot permit native
    static helpers or ``QMenu.exec`` because those have no reliable cleanup
    path in headless CI.
    """
    if _is_static_source(request.node):
        yield
        return
    monkeypatch = request.getfixturevalue("monkeypatch")
    request.getfixturevalue("qapp")
    from PyQt5.QtCore import QTimer
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
            (QFileDialog, (
                "getExistingDirectory",
                "getOpenFileName",
                "getOpenFileNames",
                "getSaveFileName",
                "getOpenFileUrl",
                "getOpenFileUrls",
                "getSaveFileUrl",
            )),
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
            # A static ``singleShot`` cannot be cancelled: after an early
            # accept/reject it could reject the next ``exec_`` on the same
            # dialog.  This timer belongs to exactly one invocation and is
            # stopped before the wrapper returns, including exception/deletion
            # paths.  ``dialog`` may have deleted its children while exec'ing.
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


@pytest.fixture(autouse=True)
def _isolate_qsettings(request):
    """Keep UI tests from polluting the real MF4Analyzer/DataAnalyzer store.

    Constructing a persistent UI widget (Inspector param sections,
    PersistentTop, PresetBar) and toggling it calls ``set_expanded`` /
    ``setValue`` on the ``QSettings`` returned by ``_preset_settings()``. On
    Windows the native backend is the registry, so a UI test that expands a
    section writes ``inspector/{fft,order,fft_time}/params_expanded=true`` into
    the live store; the next real app launch then opens that section expanded,
    appearing to violate the default-collapsed spec even though the code
    default is correct (lesson ``codex-qt-render-probes-isolate-qsettings``).

    ``QSettings(org, app)`` ignores ``setDefaultFormat`` — it hard-binds the
    native backend — so redirecting it requires monkeypatching the
    ``_preset_settings`` factory itself, in every module that imported it by
    name *and* the package re-export the tests pull from. Each test gets its
    own throwaway INI. ``setDefaultFormat`` + ``setPath`` additionally divert
    any bare ``QSettings()`` (hint bars) away from the registry.
    """
    if _is_static_source(request.node):
        yield
        return
    tmp_path = request.getfixturevalue("tmp_path")
    monkeypatch = request.getfixturevalue("monkeypatch")
    from PyQt5.QtCore import QSettings
    import mf4_analyzer.ui.batch_settings as _batch_settings_mod
    import mf4_analyzer.ui.inspector_sections as _pkg
    import mf4_analyzer.ui.inspector_sections._helpers as _helpers_mod
    import mf4_analyzer.ui.inspector_sections.collapsible as _collapsible_mod
    import mf4_analyzer.ui.inspector_sections.presets as _presets_mod
    import mf4_analyzer.ui.inspector_sections.persistent_top as _persistent_top_mod

    ini = str(tmp_path / "qsettings.ini")

    def _temp_settings(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    for mod in (_pkg, _helpers_mod, _collapsible_mod, _presets_mod,
                _persistent_top_mod):
        if hasattr(mod, "_preset_settings"):
            monkeypatch.setattr(mod, "_preset_settings", _temp_settings)

    # ``BatchSheet`` restores remembered display preferences on open and
    # writes them back on close, so every ``BatchSheet(...)`` in this suite
    # would otherwise round-trip through the real MF4Analyzer/DataAnalyzer
    # store. Tests that assert ON the persistence still inject their own
    # ``BatchPanelPrefsStore``; this only covers the implicit default.
    monkeypatch.setattr(_batch_settings_mod, "_default_settings", _temp_settings)

    previous_default_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(tmp_path))
    try:
        yield
    finally:
        # ``setPath`` has no getter and therefore cannot be truthfully
        # snapshotted.  Restoring the default format after every complete item
        # prevents the next non-UI test from selecting this item's stale INI
        # path; the next UI item installs its own path before using it.
        request.node._qsettings_default_format = previous_default_format


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication so each test reuses the instance."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _isolate_app_style(request):
    """Undo any application-wide style/stylesheet a test installs.

    ``qapp`` is session-scoped, so ``qapp.setStyleSheet(...)`` /
    ``qapp.setStyle("Fusion")`` outlive the test that called them and silently
    change widget metrics for everything that runs afterwards. That is how
    ``test_alt_view_shortcut_switches_active_section`` and the two BLF dialog
    tests broke ``test_dialog_layout_insets_...``: the app QSS grew the
    dB-reference delete button from 30px to 32px, three files later.

    Tests that legitimately need the real QSS keep doing so; this only
    guarantees they cannot leak it.  Restoration is deferred until this
    module's teardown hook has delivered owned DeferredDelete events.

    This UI-layer snapshot is the second restore. ``tests/conftest.py``
    already rolls the app back after every item under ``tests/`` (including
    ``tests/test_verify_ultraview_visuals.py``, which this fixture never
    sees). Both layers are idempotent; dropping this one would lose the
    three historical leak bugs named above.
    """
    if _is_static_source(request.node):
        yield
        return
    qapp = request.getfixturevalue("qapp")
    from PyQt5.QtGui import QFont, QPalette

    request.node._ui_app_style_baseline = (
        qapp.styleSheet(),
        qapp.style().objectName(),
        QPalette(qapp.palette()),
        QFont(qapp.font()),
    )
    yield


def _restore_item_app_style(item) -> None:
    baseline = getattr(item, "_ui_app_style_baseline", None)
    if baseline is None:
        return
    app = QApplication.instance()
    if app is not None:
        sheet, style_name, palette, font = baseline
        if app.styleSheet() != sheet:
            app.setStyleSheet(sheet)
        if app.style().objectName() != style_name:
            app.setStyle(style_name)
        if app.palette() != palette:
            app.setPalette(palette)
        if app.font() != font:
            app.setFont(font)
    delattr(item, "_ui_app_style_baseline")


def _restore_qsettings_default_format(item) -> None:
    previous_default_format = getattr(item, "_qsettings_default_format", None)
    if previous_default_format is None:
        return
    from PyQt5.QtCore import QSettings

    QSettings.setDefaultFormat(previous_default_format)
    delattr(item, "_qsettings_default_format")


@pytest.fixture(autouse=True)
def _own_chartstacks(monkeypatch, request):
    """Keep unowned ChartStack widgets alive until queued layout callbacks drain."""
    if _is_static_source(request.node):
        yield
        return
    qapp = request.getfixturevalue("qapp")
    from mf4_analyzer.ui.chart_stack import ChartStack

    created = []
    orig_init = ChartStack.__init__

    def _tracking_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(ChartStack, "__init__", _tracking_init)
    yield
    qapp.processEvents()
    for cs in created:
        if not sip.isdeleted(cs):
            cs.deleteLater()
    created.clear()
    qapp.processEvents()


@pytest.fixture(autouse=True)
def _auto_discard_unsaved_project_on_close(request):
    """Shown MainWindow teardown must not block on the Save/Discard/Cancel box.

    Instance-level monkeypatches in dirty-guard tests still win. Unshown
    windows skip the prompt in closeEvent; this covers ``mw.show()`` cases.
    This uses an independent ``pytest.MonkeyPatch.context()`` rather than the
    test's shared ``monkeypatch`` fixture: ``monkeypatch.undo()`` must not tear
    down the suite-level discard guard before a shown window closes.
    """
    if _is_static_source(request.node):
        yield
        return
    from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            ProjectIOMixin,
            "_prompt_unsaved_project",
            lambda self: "discard",
        )
        yield

        # Close every surviving MainWindow while the discard patch is still
        # live. Individual tests may temporarily replace the prompt with
        # Cancel; teardown must not depend on fixture-finalizer ordering or a
        # product-code pytest escape hatch.
        app = QApplication.instance()
        if app is None:
            return
        from mf4_analyzer.ui.main_window import MainWindow
        from mf4_analyzer.ui.main_window.project_dirty import DirtyGuardResult

        for widget in app.topLevelWidgets():
            if not isinstance(widget, MainWindow):
                continue
            widget.confirm_leave_unsaved_project = (
                lambda: DirtyGuardResult.PROCEED_DISCARDED
            )
            widget.close()
        app.processEvents()


@pytest.fixture
def loaded_csv(tmp_path):
    """Create a small CSV for file-load tests."""
    import pandas as pd
    import numpy as np
    t = np.linspace(0, 1.0, 1000)
    df = pd.DataFrame({"time": t, "speed": 1000 * np.sin(2 * np.pi * 5 * t), "torque": 50 + 5 * np.cos(2 * np.pi * 3 * t)})
    p = tmp_path / "sample.csv"
    df.to_csv(p, index=False)
    return str(p)
