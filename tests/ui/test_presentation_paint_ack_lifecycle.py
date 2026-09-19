"""F-X-2: hideEvent during construct/teardown must not raise."""
from __future__ import annotations

from PyQt5.QtGui import QHideEvent

from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG


def test_hide_event_during_construct_and_teardown_does_not_raise(qapp):
    constructing = TimeDomainCanvasPG()
    del constructing._presentation_paint_ack_epoch
    constructing.hideEvent(QHideEvent())

    tearing_down = TimeDomainCanvasPG()
    del tearing_down._presentation_paint_ack_epoch
    tearing_down.hideEvent(QHideEvent())
