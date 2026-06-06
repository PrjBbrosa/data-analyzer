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
