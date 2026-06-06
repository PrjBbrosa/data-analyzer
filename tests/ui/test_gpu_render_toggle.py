import inspect

import numpy as np
from PyQt5.QtCore import QCoreApplication, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _gpu_canvas(qapp):
    c = TimeDomainCanvasPG()
    c.resize(640, 360)
    c.show()
    QCoreApplication.processEvents()
    return c


class _SwappingGlw:
    """Tiny GraphicsLayoutWidget fake: useOpenGL swaps the viewport object."""

    def __init__(self):
        self.calls = []
        self.cpu_viewport = QWidget()
        self.gpu_viewport = QWidget()
        for viewport in (self.cpu_viewport, self.gpu_viewport):
            viewport.resize(120, 80)
            viewport.show()
        self._viewport = self.cpu_viewport

    def useOpenGL(self, on):
        self.calls.append(bool(on))
        self._viewport = self.gpu_viewport if on else self.cpu_viewport

    def viewport(self):
        return self._viewport

    def update(self):
        pass


def test_set_gpu_render_tracks_requested_applied_and_is_idempotent(qapp):
    c = _gpu_canvas(qapp)
    glw = _SwappingGlw()
    c._glw = glw
    c._gpu_viewport_filter_target = None
    assert c._gpu_render_requested is False
    assert c._gpu_render_on is False
    c.set_gpu_render(True)
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is True
    assert c._gpu_viewport_filter_target is glw.gpu_viewport
    c.set_gpu_render(True)
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is True
    c.set_gpu_render(False)
    assert c._gpu_render_requested is False
    assert c._gpu_render_on is False
    assert glw.calls == [True, False]


def test_gpu_render_rebinds_viewport_event_filter_after_switch(qapp, monkeypatch):
    c = _gpu_canvas(qapp)
    glw = _SwappingGlw()
    c._glw = glw
    c._gpu_viewport_filter_target = None
    c._install_viewport_event_filter()
    seen = []
    monkeypatch.setattr(
        c,
        "_handle_viewport_double_click",
        lambda pos: seen.append(pos),
    )
    c.set_gpu_render(True)
    viewport = glw.gpu_viewport
    assert c._gpu_viewport_filter_target is viewport
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(12, 12))
    QCoreApplication.processEvents()
    assert seen, "double-click must still enter eventFilter after viewport swap"


def test_set_gpu_render_failure_keeps_applied_false_and_can_retry(qapp):
    c = _gpu_canvas(qapp)

    class BoomThenOk:
        def __init__(self):
            self.calls = []

        def useOpenGL(self, on):
            self.calls.append(bool(on))
            if len(self.calls) == 1:
                raise RuntimeError("no GL here")

        def viewport(self):
            return None

        def update(self):
            pass

    glw = BoomThenOk()
    c._glw = glw
    c._gpu_render_requested = False
    c._gpu_render_on = False
    c._gpu_viewport_filter_target = None

    c.set_gpu_render(True)
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is False

    c._apply_gpu_viewport()
    assert c._gpu_render_on is True
    assert glw.calls == [True, True]


def test_grab_pixmap_roundtrips_gl_off_then_on_when_gpu(qapp):
    c = _gpu_canvas(qapp)
    calls = []
    real_glw = c._glw

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        def useOpenGL(self, on):
            calls.append(bool(on))

        def __getattr__(self, k):
            return getattr(self._inner, k)

    c._glw = Spy(real_glw)
    c._gpu_render_requested = True
    c._gpu_render_on = True
    pix = c.grab_pixmap()
    assert pix is not None and not pix.isNull()
    assert calls == [False, True]
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is True


def test_grab_pixmap_no_gl_toggle_when_cpu(qapp):
    c = _gpu_canvas(qapp)
    calls = []
    real_glw = c._glw

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        def useOpenGL(self, on):
            calls.append(bool(on))

        def __getattr__(self, k):
            return getattr(self._inner, k)

    c._glw = Spy(real_glw)
    c._gpu_render_requested = False
    c._gpu_render_on = False
    c.grab_pixmap()
    assert calls == []


def _pixmap_has_nonblank_content(pix):
    from PyQt5.QtGui import QColor, QImage

    img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
    if img.width() <= 1 or img.height() <= 1:
        return False
    step_x = max(1, img.width() // 80)
    step_y = max(1, img.height() // 50)
    for y in range(0, img.height(), step_y):
        for x in range(0, img.width(), step_x):
            c = QColor(img.pixel(x, y))
            if c.alpha() > 0 and (c.red() < 245 or c.green() < 245 or c.blue() < 245):
                return True
    return False


def test_gpu_grab_pixmap_cpu_roundtrip_returns_nonblank_content(qapp):
    c = _gpu_canvas(qapp)
    t = np.linspace(0, 1, 200)
    c.plot_channels([
        ("speed", True, t, np.sin(t * 20), "#1769e0", "rpm", "f")
    ])
    QCoreApplication.processEvents()
    real_glw = c._glw

    class Spy:
        def __init__(self, inner):
            self._inner = inner
            self.calls = []

        def useOpenGL(self, on):
            self.calls.append(bool(on))

        def __getattr__(self, k):
            return getattr(self._inner, k)

    c._glw = Spy(real_glw)
    c._gpu_render_requested = True
    c._gpu_render_on = True

    pix = c.grab_pixmap(scale=1.0)

    assert pix is not None and not pix.isNull()
    assert pix.width() > 1 and pix.height() > 1, "must not return 1x1 fallback"
    assert c._glw.calls == [False, True]
    assert _pixmap_has_nonblank_content(pix), "GPU export fallback must contain chart pixels"


def test_configure_gl_surface_format_sets_msaa(qapp):
    from PyQt5.QtGui import QSurfaceFormat

    from mf4_analyzer.app import _configure_gl_surface_format

    _configure_gl_surface_format()
    assert QSurfaceFormat.defaultFormat().samples() == 4


def test_main_configures_gl_surface_format_before_qapplication():
    import mf4_analyzer.app as appmod

    src = inspect.getsource(appmod.main)
    assert src.index("_configure_high_dpi()") < src.index("_configure_gl_surface_format()")
    assert src.index("_configure_gl_surface_format()") < src.index("QApplication(")


def test_gpu_render_pref_roundtrip(tmp_path, qapp):
    from PyQt5.QtCore import QSettings

    from mf4_analyzer.ui.main_window import (
        gpu_render_settings,
        read_gpu_render_pref,
        write_gpu_render_pref,
    )

    path = str(tmp_path / "gpu.ini")
    settings = QSettings(path, QSettings.IniFormat)
    assert read_gpu_render_pref(settings) is False

    write_gpu_render_pref(settings, on=True)
    settings.sync()

    settings2 = QSettings(path, QSettings.IniFormat)
    assert read_gpu_render_pref(settings2) is True

    default_settings = gpu_render_settings()
    assert default_settings.organizationName() == "MF4Analyzer"
    assert default_settings.applicationName() == "DataAnalyzer"


def test_inspector_has_gpu_toggle_emitting_signal(qapp):
    from mf4_analyzer.ui.inspector import Inspector

    inspector = Inspector()
    received = []
    inspector.gpu_render_toggled.connect(lambda on: received.append(on))

    assert hasattr(inspector, "gpu_toggle")
    inspector.gpu_toggle.setChecked(True)

    assert received == [True]


def test_inspector_set_gpu_toggle_checked_is_silent(qapp):
    from mf4_analyzer.ui.inspector import Inspector

    inspector = Inspector()
    received = []
    inspector.gpu_render_toggled.connect(lambda on: received.append(on))

    inspector.set_gpu_toggle_checked(True)

    assert inspector.gpu_toggle.isChecked() is True
    assert received == []


def test_main_window_gpu_toggle_wired(qapp, monkeypatch):
    import mf4_analyzer.ui.main_window as main_window
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    state = {"value": False}
    applied = []

    monkeypatch.setattr(
        main_window,
        "read_gpu_render_pref",
        lambda settings=None: state["value"],
    )

    def write_pref(settings=None, *, on):
        state["value"] = bool(on)

    monkeypatch.setattr(main_window, "write_gpu_render_pref", write_pref)

    def fake_set_gpu_render(self, on):
        self._gpu_render_requested = bool(on)
        self._gpu_render_on = bool(on)
        applied.append(bool(on))

    monkeypatch.setattr(TimeDomainCanvasPG, "set_gpu_render", fake_set_gpu_render)

    window = main_window.MainWindow()
    try:
        assert window.inspector.gpu_toggle.isChecked() is False
        assert applied == [False]

        window.inspector.gpu_toggle.setChecked(True)
        qapp.processEvents()
        assert state["value"] is True
        assert window.canvas_time._gpu_render_on is True
        assert applied[-1] is True

        window.inspector.gpu_toggle.setChecked(False)
        qapp.processEvents()
        assert state["value"] is False
        assert window.canvas_time._gpu_render_on is False
        assert applied[-1] is False
    finally:
        window.close()
