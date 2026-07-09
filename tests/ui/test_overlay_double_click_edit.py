"""Double-click a curve (or its Y axis) in overlay mode → edit THAT curve.

Replaces the retired Alt(Option)+drag select gesture (removed 2026-07-09).
The 图表选项 dialog now targets the exact curve double-clicked — not just the
left axis — resolved two ways:

  * double-click on a channel's Y-axis GUTTER (laid out in its own column, so
    unambiguous) → that channel's axis handle;
  * double-click on a curve BODY in the shared plot area → the nearest visible
    curve within the pick radius.

The resolved curve is emphasised (``select_overlay_channel(notify=False)``)
while its dialog is open and cleared afterwards, and merely opening the dialog
must NOT toggle the pan/zoom tool (notify=False → no toolbar handoff).

Two channels with DISTINCT shapes (ramp up / ramp down) are used so overlay
mode engages (≥2 curves) and the per-channel Y normalisation keeps the curves
visually separable — a point on one is unambiguously nearest to it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QCoreApplication, QPointF

from mf4_analyzer.io.file_data import FileData


def _make_file(stem: str, ch: str, sig: np.ndarray, idx: int) -> FileData:
    t = np.linspace(0.0, 1.0, len(sig), dtype=np.float64)
    df = pd.DataFrame({"time": t, ch: np.asarray(sig, dtype=float)})
    return FileData(f"{stem}.csv", df, ["time", ch], {ch: "u"}, idx=idx)


def _row(fd: FileData, ch: str, fid: str):
    sig = fd.data[ch].to_numpy(copy=False).astype(float, copy=False)
    return (
        fd.get_prefixed_channel(ch),
        True,
        fd.time_array,
        sig,
        fd.get_color_palette()[0],
        fd.channel_units.get(ch, ""),
        fid,
    )


def _two_channel_overlay(qapp):
    """Overlay canvas: A='[A] speed' ramps UP, B='[B] torque' ramps DOWN."""
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    n = 1_200
    t = np.linspace(0.0, 1.0, n, dtype=np.float64)
    fa = _make_file("A", "speed", t * 1000.0, 0)
    fb = _make_file("B", "torque", (1.0 - t) * 7.0, 1)
    canvas = TimeDomainCanvasPG()
    canvas.resize(720, 420)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(
        [_row(fa, "speed", "fa"), _row(fb, "torque", "fb")], mode="overlay"
    )
    QCoreApplication.processEvents()
    canvas._primary_xaxis_ax.set_xlim(0.0, 1.0)
    QCoreApplication.processEvents()
    return canvas, fa.get_prefixed_channel("speed"), fb.get_prefixed_channel("torque")


def _on_curve_scene_pos(canvas, name, x_target):
    handle = canvas._channel_lines[name][0]
    pdi = handle.get_lines()[0].plot_data_item
    xd, yd = pdi.getData()
    xd = np.asarray(xd, dtype=float)
    yd = np.asarray(yd, dtype=float)
    i = int(np.argmin(np.abs(xd - x_target)))
    return handle.view_box.mapViewToScene(QPointF(float(xd[i]), float(yd[i])))


def _axis_gutter_scene_center(canvas, name):
    axis = canvas._channel_lines[name][0].y_axis_item()
    return axis.sceneBoundingRect().center()


# -- resolution logic (no dialog) -----------------------------------------


def test_axis_gutter_resolves_that_exact_channel(qapp):
    """A point in a channel's Y-axis gutter resolves that channel's handle."""
    canvas, _name_a, name_b = _two_channel_overlay(qapp)

    handle, name = canvas._resolve_double_click_target(
        _axis_gutter_scene_center(canvas, name_b)
    )
    assert name == name_b
    assert handle is canvas._channel_lines[name_b][0]


def test_curve_body_resolves_that_curve(qapp):
    """A point on the ascending 'speed' curve (lower region at x=0.25) resolves
    that curve — not the left-axis fallback, not the descending curve."""
    canvas, name_a, _name_b = _two_channel_overlay(qapp)

    handle, resolved = canvas._resolve_double_click_target(
        _on_curve_scene_pos(canvas, name_a, x_target=0.25)
    )
    assert resolved == name_a
    assert handle is canvas._channel_lines[name_a][0]


def test_blank_area_falls_back_to_no_specific_curve(qapp):
    """A double-click far from every curve/gutter resolves no specific curve
    (name None) so the caller keeps the 'never a dead click' left-axis
    fallback."""
    canvas, _name_a, _name_b = _two_channel_overlay(qapp)

    _handle, resolved = canvas._resolve_double_click_target(
        QPointF(-10_000.0, -10_000.0)
    )
    assert resolved is None


# -- full gesture: dialog target + edit-highlight -------------------------


def test_double_click_curve_opens_options_and_highlights_then_clears(qapp, monkeypatch):
    canvas, name_a, _name_b = _two_channel_overlay(qapp)

    from mf4_analyzer.ui import _axis_interaction

    seen = {}

    def fake_edit(parent, handle):
        seen["handle"] = handle
        seen["selected_during"] = canvas._overlay_axes.selected_channel
        return True

    monkeypatch.setattr(
        _axis_interaction, "edit_chart_options_dialog", fake_edit, raising=False
    )

    scene_pos = _on_curve_scene_pos(canvas, name_a, x_target=0.25)
    canvas._handle_viewport_double_click(canvas._glw.mapFromScene(scene_pos))
    QCoreApplication.processEvents()

    assert seen.get("handle") is canvas._channel_lines[name_a][0]
    assert seen.get("selected_during") == name_a
    # Highlight cleared once the dialog closes (no stuck emphasis).
    assert canvas._overlay_axes.selected_channel is None


def test_double_click_axis_gutter_opens_options_for_that_channel(qapp, monkeypatch):
    canvas, _name_a, name_b = _two_channel_overlay(qapp)

    from mf4_analyzer.ui import _axis_interaction

    seen = {}
    monkeypatch.setattr(
        _axis_interaction, "edit_chart_options_dialog",
        lambda parent, handle: seen.setdefault("handle", handle) or True,
        raising=False,
    )

    scene_pos = _axis_gutter_scene_center(canvas, name_b)
    canvas._handle_viewport_double_click(canvas._glw.mapFromScene(scene_pos))
    QCoreApplication.processEvents()

    assert seen.get("handle") is canvas._channel_lines[name_b][0]


def test_double_click_edit_highlight_does_not_emit_selection_signal(qapp, monkeypatch):
    """Opening a curve's dialog must not fire ``overlay_channel_selected``
    (which would toggle the pan/zoom tool) — the highlight uses notify=False."""
    canvas, name_a, _name_b = _two_channel_overlay(qapp)

    emitted = []
    canvas.overlay_channel_selected.connect(emitted.append)

    from mf4_analyzer.ui import _axis_interaction

    monkeypatch.setattr(
        _axis_interaction, "edit_chart_options_dialog",
        lambda parent, handle: True, raising=False,
    )

    scene_pos = _on_curve_scene_pos(canvas, name_a, x_target=0.25)
    canvas._handle_viewport_double_click(canvas._glw.mapFromScene(scene_pos))
    QCoreApplication.processEvents()

    assert emitted == [], f"edit-highlight must not emit selection; got {emitted!r}"
