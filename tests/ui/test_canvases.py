"""Tests for shared canvas helpers that survive the matplotlib canvas retirement.

The matplotlib TimeDomainCanvas and PlotCanvas classes were retired in
Phase D (2026-06-18). Tests that drove those classes via mpl-internal APIs
(MouseEvent, callbacks.process, fig.bbox, axes.transData) were removed with
them per the mpl-event-coupled-tests-survive-renderer-swap lesson.

Surviving here: helper-level tests that do NOT require a canvas instance.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from mf4_analyzer.ui.canvases import _format_dual_html


def test_dual_cursor_html_labels_endpoint_delta_with_hollow_triangle():
    html = _format_dual_html([
        ("torque", 1.0, 3.0, 2.0, 4.0, " Nm", "#123456"),
    ])

    assert "RMS" not in html
    assert "△" in html
    assert "4 Nm" in html
