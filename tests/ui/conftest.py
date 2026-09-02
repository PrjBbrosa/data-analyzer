"""Shared pytest fixtures for UI tests."""
import gc
import os
# Force offscreen Qt platform for headless CI *before* QApplication exists
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.render_profile import DENSE_DISCRETE_POLICY_ENABLED


# Strong references to the top-level widgets alive when a test body returned.
# Read the two hooks below before touching this — it is a lifetime guard, not
# a cache, and it must stay a module-level list so the references outlive the
# item's own frames.
_PINNED_TOPLEVELS = []


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

    *Why collect here.* ``_collect_mpl_cycles_between_tests`` runs its
    ``gc.collect()`` while the pin is still held, so it can no longer reap the
    test's widgets — without this call they would survive into the *next*
    test's body. That is not hypothetical: it made 16 ``test_pg_dense_raster``
    / ``test_pill_switch`` cases fail, because a leftover
    ``TimeDomainCanvasPG`` still counted against the dense-raster memory caps
    and the next canvas was refused admission. Collecting here restores the
    original lifetime — one test's widgets are gone before the next one starts
    — while keeping them alive for the whole danger window.
    """
    try:
        return (yield)
    finally:
        _PINNED_TOPLEVELS.clear()
        gc.collect()


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path, monkeypatch):
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

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(tmp_path))
    yield


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication so each test reuses the instance."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _isolate_app_style(qapp):
    """Undo any application-wide style/stylesheet a test installs.

    ``qapp`` is session-scoped, so ``qapp.setStyleSheet(...)`` /
    ``qapp.setStyle("Fusion")`` outlive the test that called them and silently
    change widget metrics for everything that runs afterwards. That is how
    ``test_alt_view_shortcut_switches_active_section`` and the two BLF dialog
    tests broke ``test_dialog_layout_insets_...``: the app QSS grew the
    dB-reference delete button from 30px to 32px, three files later.

    Tests that legitimately need the real QSS keep doing so; this only
    guarantees they cannot leak it. Restoring per test is cheap — Qt only
    repolishes widgets that still exist.

    This UI-layer snapshot is the second restore. ``tests/conftest.py``
    already rolls the app back after every item under ``tests/`` (including
    ``tests/test_verify_ultraview_visuals.py``, which this fixture never
    sees). Both layers are idempotent; dropping this one would lose the
    three historical leak bugs named above.
    """
    style_name = qapp.style().objectName()
    sheet = qapp.styleSheet()
    yield
    if qapp.styleSheet() != sheet:
        qapp.setStyleSheet(sheet)
    if qapp.style().objectName() != style_name:
        qapp.setStyle(style_name)


@pytest.fixture(autouse=True)
def _own_chartstacks(qapp, monkeypatch):
    """Keep unowned ChartStack widgets alive until queued layout callbacks drain."""
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
        try:
            cs.deleteLater()
        except Exception:
            pass
    created.clear()
    qapp.processEvents()


@pytest.fixture(autouse=True)
def _auto_discard_unsaved_project_on_close(monkeypatch):
    """Shown MainWindow teardown must not block on the Save/Discard/Cancel box.

    Instance-level monkeypatches in dirty-guard tests still win. Unshown
    windows skip the prompt in closeEvent; this covers ``mw.show()`` cases.
    """
    from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

    monkeypatch.setattr(
        ProjectIOMixin,
        "_prompt_unsaved_project",
        lambda self: "discard",
    )
    yield

    # Close every surviving MainWindow while the discard patch is still live.
    # Individual tests may temporarily replace the prompt with Cancel; teardown
    # must not depend on fixture-finalizer ordering or a product-code pytest
    # escape hatch.
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


@pytest.fixture(autouse=True)
def _collect_mpl_cycles_between_tests():
    # matplotlib Figure/FigureCanvasQTAgg hold strong reference cycles
    # (figure.canvas <-> canvas.figure plus mpl_connect lambdas capturing
    # self). Tests that don't register widgets with qtbot leave zombies
    # behind; once enough accumulate, a subsequent paintEvent allocation
    # trips Python's cyclic GC mid-QPainter.drawImage and segfaults on
    # Windows. Forcing a collection between tests keeps the heap clean so
    # no collection fires inside a live paint path.
    yield
    gc.collect()


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
