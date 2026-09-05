"""Anchored popovers stay inside the injected work area (S07)."""
from __future__ import annotations

from PyQt5 import sip
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack.cursor_display import CursorDisplayPopover
from mf4_analyzer.ui_kit.dialog_geometry import IntRect, SCREEN_MARGIN, as_rect


_AVAILABLE = IntRect(0, 0, 800, 600)


def _patch_available(monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: _AVAILABLE,
    )


def _safe_area():
    return _AVAILABLE.adjusted(
        SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN,
    )


def _assert_frame_in_safe(widget):
    frame = as_rect(widget.frameGeometry())
    safe = _safe_area()
    assert safe.contains_rect(frame), (
        f"frame=({frame.x},{frame.y},{frame.width},{frame.height}) "
        f"safe=({safe.x},{safe.y},{safe.width},{safe.height})"
    )


def _bottom_right_anchor(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(72, 24)
    host.move(720, 560)
    host.show()
    return host


def _wait_deferred_refit(qtbot, popover):
    qtbot.waitUntil(lambda: not popover._refit_pending, timeout=1000)


def test_cursor_popover_stays_in_safe_area_after_show_for(qapp, qtbot, monkeypatch):
    _patch_available(monkeypatch)
    host = _bottom_right_anchor(qtbot)
    qtbot.waitExposed(host)
    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    popover.show_for(host, "single")
    qapp.processEvents()
    assert popover.isVisible()
    _assert_frame_in_safe(popover)


def test_cursor_popover_stays_in_safe_area_after_deferred_refit(
    qapp, qtbot, monkeypatch,
):
    _patch_available(monkeypatch)
    host = _bottom_right_anchor(qtbot)
    qtbot.waitExposed(host)
    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    popover.show_for(host, "dual")
    qapp.processEvents()
    popover.set_cursor_mode("single")
    _wait_deferred_refit(qtbot, popover)
    qapp.processEvents()
    assert popover.isVisible()
    _assert_frame_in_safe(popover)


def test_tick_density_popover_stays_in_safe_area(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.chart_stack.toolbar import _TickDensityPopover
    from mf4_analyzer.ui_kit.dialog_geometry import fit_popover

    _patch_available(monkeypatch)
    host = _bottom_right_anchor(qtbot)
    qtbot.waitExposed(host)
    popover = _TickDensityPopover(host)
    qtbot.addWidget(popover)
    if popover.layout() is not None:
        popover.layout().activate()
    fit_popover(popover, host, gap=4)
    popover.show()
    qtbot.waitExposed(popover)
    _assert_frame_in_safe(popover)


def test_cursor_popover_hides_when_anchor_is_destroyed(qapp, qtbot, monkeypatch):
    _patch_available(monkeypatch)
    host = _bottom_right_anchor(qtbot)
    qtbot.waitExposed(host)
    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    popover.show_for(host, "dual")
    qapp.processEvents()
    assert popover.isVisible()
    sip.delete(host)
    qapp.processEvents()
    assert not sip.isdeleted(popover)
    assert not popover.isVisible()
