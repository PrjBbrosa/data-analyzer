"""Pinned-cursor marker geometry (Task 3). Measure painted items, not a detached document."""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSettings, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QMouseEvent, QPainter
from PyQt5.QtWidgets import QApplication, QPushButton, QScrollArea, QWidget

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.pg_canvas.pinned_cursor_overlay import (
    PINNED_OFFSCREEN_TEXT,
    PINNED_UNREPRESENTABLE_TEXT,
    PinnedAxisLabel,
    axis_label_chrome,
    axis_label_outer_size,
    cluster_label_text,
    layout_pinned_axis_labels,
    route_panel_tether,
    tether_candidate_ports,
    _path_hits_rects,
)
from mf4_analyzer.ui.pinned_cursor_state import empty_collection, next_record


_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def production_style(qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


def _settings(_name):
    """Use the UI fixture's per-item QSettings store, never a shared /tmp INI."""
    return QSettings()


def _make_stack(qtbot, qapp, *, width=1100, height=640):
    cs = ChartStack(cursor_settings=_settings(f"{width}x{height}"))
    qtbot.addWidget(cs)
    cs.resize(width, height)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()
    return cs


def _plot_time(canvas, *, mode="overlay", extra=None):
    t = np.linspace(0.0, 1.0, 200)
    rows = [
        ("speed", True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-a"),
    ]
    if extra:
        rows.extend(extra)
    canvas.plot_channels(rows, mode=mode)


def _fft_entries():
    freq = np.array([1.0, 10.0, 50.0, 100.0, 200.0])
    return [
        {
            "freq": freq,
            "amp": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
            "label": "force",
            "channel": "force",
            "fid": "fid-a",
            "color": "#2563eb",
            "time": np.linspace(0.0, 1.0, 8),
            "signal": np.zeros(8),
        }
    ]


def _frf_result(*, log=False):
    from types import SimpleNamespace

    frequencies = (
        np.array([1.0, 10.0, 100.0, 1000.0]) if log
        else np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    )
    transfer = np.ones(frequencies.size, dtype=complex)
    coherence = np.linspace(0.9, 0.4, frequencies.size)
    return SimpleNamespace(
        frequencies=frequencies,
        transfer=transfer,
        coherence=coherence,
        effective=SimpleNamespace(fs=1000.0, df=1.0, segments=4),
        warnings=(),
    )


def _collection(domain, values, *, mode="single"):
    collection = empty_collection()
    unit = "s" if domain == "time" else "Hz"
    channel = "speed" if domain == "time" else "force"
    for value in values:
        payload = {
            "mode": mode,
            "domain": domain,
            "x_unit": unit,
            "bindings": [{"fid": "fid-a", "channel": channel}],
        }
        if mode == "dual":
            payload["ax"] = float(value[0])
            payload["bx"] = float(value[1])
        else:
            payload["x"] = float(value)
        collection, _ = next_record(collection, payload)
    return collection


def _wait_host(qtbot, canvas):
    overlay = canvas._pinned_overlay
    qtbot.waitUntil(lambda: overlay.host_rect() is not None, timeout=3000)
    return overlay.host_rect()


def _scene_x(line):
    vb = line.getViewBox()
    return float(vb.mapViewToScene(QPointF(float(line.value()), 0.0)).x())


def _pin(cs, canvas, values, *, domain="time", mode="single", expand=False):
    cs.set_pinned_cursors_for_canvas(
        canvas, _collection(domain, values, mode=mode),
    )
    QApplication.processEvents()
    if expand:
        controller = cs._pinned_cursors
        for record in cs.pinned_cursors_for_canvas(canvas).records:
            controller.toggle_record_panel(canvas, record.record_id)
        QApplication.processEvents()
        controller.flush_layout()
    return cs.pinned_cursors_for_canvas(canvas).records


def _send_mouse(widget, etype, local, *, button=Qt.LeftButton, buttons=None):
    local = QPoint(local)
    window = widget.window()
    window_pos = widget.mapTo(window, local) if window is not None else QPoint(local)
    global_pos = widget.mapToGlobal(local)
    if buttons is None:
        if etype == QEvent.MouseButtonRelease:
            buttons = Qt.NoButton
        elif etype == QEvent.MouseMove:
            buttons = Qt.LeftButton
        else:
            buttons = button
    event = QMouseEvent(
        etype,
        QPointF(local),
        QPointF(window_pos),
        QPointF(global_pos),
        button,
        Qt.MouseButtons(buttons),
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)
    return QPoint(global_pos)


def _tether_points_in_panel_local(canvas, pill):
    overlay = canvas._pinned_overlay
    glw = canvas._glw
    viewport = glw.viewport()
    points = []
    for item in overlay.tether_items():
        path = item.path()
        for index in range(path.elementCount()):
            element = path.elementAt(index)
            view = glw.mapFromScene(QPointF(element.x, element.y))
            local = pill.mapFromGlobal(viewport.mapToGlobal(view))
            points.append(local)
    return points


def _tether_points_in_canvas(canvas):
    overlay = canvas._pinned_overlay
    glw = canvas._glw
    viewport = glw.viewport()
    points = []
    for item in overlay.tether_items():
        path = item.path()
        count = path.elementCount()
        vertices = []
        for index in range(count):
            element = path.elementAt(index)
            view = glw.mapFromScene(QPointF(element.x, element.y))
            canvas_pt = viewport.mapTo(canvas, view)
            vertices.append((float(canvas_pt.x()), float(canvas_pt.y())))
        for start, end in zip(vertices, vertices[1:]):
            points.append(start)
            for step in (0.25, 0.5, 0.75):
                points.append((
                    start[0] + (end[0] - start[0]) * step,
                    start[1] + (end[1] - start[1]) * step,
                ))
            points.append(end)
    return points


def _dash_composite_stats(pen, *, background="#ffffff", grid=False):
    image = QImage(320, 48, QImage.Format_ARGB32)
    bg = QColor(background)
    image.fill(bg)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    if grid:
        painter.setPen(QColor("#d7dee8"))
        for x in range(0, 320, 16):
            painter.drawLine(x, 0, x, 47)
        for y in range(0, 48, 8):
            painter.drawLine(0, y, 319, y)
    painter.setPen(pen)
    painter.drawLine(12, 24, 308, 24)
    painter.end()
    ink = []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.red() == bg.red() and color.green() == bg.green() and color.blue() == bg.blue():
                continue
            lum = 0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
            bg_lum = 0.2126 * bg.red() + 0.7152 * bg.green() + 0.0722 * bg.blue()
            ink.append((lum, bg_lum - lum))
    if not ink:
        return {"n": 0, "min_lum": 255.0, "mean_lum": 255.0, "mean_delta": 0.0}
    lums = [item[0] for item in ink]
    deltas = [item[1] for item in ink]
    return {
        "n": len(ink),
        "min_lum": min(lums),
        "mean_lum": sum(lums) / len(lums),
        "mean_delta": sum(deltas) / len(deltas),
    }


def _save_pin_evidence(cs, name):
    evidence = _REPO_ROOT / ".state" / "pin-remediation"
    evidence.mkdir(parents=True, exist_ok=True)
    cs.stack.grab().save(str(evidence / name))


def test_native_pin_coordinate_mappings_exit_cleanly_in_subprocess(tmp_path):
    """Keep QWidget ancestry faults out of the pytest process.

    The child exercises the two production paths with a canvas layout margin
    and QGraphicsView viewport frame offset.  A parent-to-child ``mapTo``
    call used to terminate this process with SIGSEGV before Python could
    report an assertion failure.
    """
    script = textwrap.dedent(
        """
        import math
        import os
        from pathlib import Path

        import numpy as np
        from PyQt5.QtCore import QPoint, QPointF, QSettings
        from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

        from mf4_analyzer.ui.chart_stack import ChartStack
        from mf4_analyzer.ui.pinned_cursor_state import empty_collection, next_record


        def events(app, count=4):
            for _ in range(count):
                app.processEvents()


        app = QApplication.instance() or QApplication([])
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(19, 23, 29, 31)
        settings = QSettings(
            str(Path(os.environ["TMPDIR"]) / "pin-native-map.ini"),
            QSettings.IniFormat,
        )
        stack = ChartStack(cursor_settings=settings)
        outer.addWidget(stack)
        root.resize(1180, 760)
        root.show()
        events(app)

        canvas = stack.canvas_time
        canvas.layout().setContentsMargins(11, 13, 17, 19)
        stack.set_cursor_mode_for_canvas(canvas, "single")
        samples = np.linspace(0.0, 1.0, 200)
        canvas.plot_channels([
            ("speed", True, samples, np.sin(2 * np.pi * samples),
             "#1769e0", "rpm", "fid-a"),
        ], mode="overlay")
        events(app)

        collection = empty_collection()
        for value in (*[0.40 + index * 0.002 for index in range(12)], 1.0):
            collection, _ = next_record(collection, {
                "mode": "single",
                "domain": "time",
                "x_unit": "s",
                "bindings": [{"fid": "fid-a", "channel": "speed"}],
                "x": value,
            })
        stack.set_pinned_cursors_for_canvas(canvas, collection)
        overlay = canvas._pinned_overlay
        overlay.reproject()
        events(app)

        glw = canvas._glw
        viewport = glw.viewport()
        assert canvas.isAncestorOf(viewport)
        assert canvas.layout().contentsMargins().left() == 11
        assert viewport.mapFrom(canvas, QPoint(0, 0)) != QPoint(0, 0)
        leaders = [item for item in overlay.layout().items if item.leader]
        assert leaders
        assert len(overlay._leader_items) == len(leaders)
        for geometry, item in zip(leaders, overlay._leader_items):
            x1, y1, x2, y2 = geometry.leader
            expected_a = glw.mapToScene(
                viewport.mapFrom(canvas, QPointF(x1, y1).toPoint())
            )
            expected_b = glw.mapToScene(
                viewport.mapFrom(canvas, QPointF(x2, y2).toPoint())
            )
            actual = item.line()
            assert math.isclose(actual.x1(), expected_a.x(), abs_tol=0.01)
            assert math.isclose(actual.y1(), expected_a.y(), abs_tol=0.01)
            assert math.isclose(actual.x2(), expected_b.x(), abs_tol=0.01)
            assert math.isclose(actual.y2(), expected_b.y(), abs_tol=0.01)

        stack.set_mode("fft")
        fft = stack.canvas_fft
        fft.layout().setContentsMargins(13, 17, 19, 23)
        stack.set_cursor_mode_for_canvas(fft, "single")
        frequency = np.array([1.0, 10.0, 50.0, 100.0, 200.0])
        fft.plot_spectra([
            {
                "freq": frequency,
                "amp": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
                "label": "force",
                "channel": "force",
                "fid": "fid-a",
                "color": "#2563eb",
                "time": np.linspace(0.0, 1.0, 8),
                "signal": np.zeros(8),
            },
        ], xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT")
        events(app)

        host = fft.frequency_cursor_host_rect()
        assert host is not None and host.isValid()
        fft_glw = fft._glw
        fft_viewport = fft_glw.viewport()
        assert fft.isAncestorOf(fft_viewport)
        assert fft.layout().contentsMargins().left() == 13
        assert fft_viewport.mapFrom(fft, QPoint(0, 0)) != QPoint(0, 0)
        viewport_pos = fft_viewport.mapFrom(fft, host.center())
        controller = stack._pinned_cursors
        assert controller._in_data_viewport(fft, "frequency", viewport_pos)
        scene_pos = fft_glw.mapToScene(viewport_pos)
        expected_x = fft._plot_amp.vb.mapSceneToView(scene_pos).x()
        actual_x = controller._physical_x(fft, "frequency", viewport_pos)
        assert actual_x is not None
        assert math.isclose(actual_x, expected_x, abs_tol=1e-9)
        preview_pos = fft_glw.mapFromScene(
            fft._plot_time.vb.sceneBoundingRect().center()
        )
        assert not controller._in_data_viewport(fft, "frequency", preview_pos)

        root.close()
        root.deleteLater()
        events(app)
        print("ok")
        """
    )
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(_REPO_ROOT),
        QT_QPA_PLATFORM="offscreen",
        TMP=str(tmp_path),
        TEMP=str(tmp_path),
        TMPDIR=str(tmp_path),
        MPLCONFIGDIR=str(tmp_path),
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    details = result.stderr + result.stdout
    assert result.returncode != -signal.SIGSEGV, details
    assert result.returncode == 0, details
    assert "ok" in result.stdout


def test_cluster_label_text_consecutive_and_plus_n():
    assert cluster_label_text((3,)) == "P3"
    assert cluster_label_text((3, 4, 5, 6, 7)) == "P3–P7"
    assert cluster_label_text((1, 3, 8)) == "+3"


def test_layout_does_not_shove_infinitely_left(qapp):
    fm = QFontMetrics(QFont())
    endpoints = [
        {
            "record_id": f"id-{index}",
            "ordinal": index + 1,
            "endpoint": "x",
            "text": f"P{index + 1}",
            "canvas_x": 40.0 + index * 2.0,
            "offscreen": None,
        }
        for index in range(12)
    ]
    items = layout_pinned_axis_labels(
        endpoints, axis_left=20, axis_right=120, axis_top=80, axis_height=16,
        fm=fm,
    )
    assert items
    assert all(item.canvas_rect[0] >= 20 for item in items)
    assert all(
        item.canvas_rect[0] + item.canvas_rect[2] <= 120
        for item in items
    )


def test_axis_label_outer_size_matches_the_painted_caption_contract(
    qapp, qtbot, production_style,
):
    """The layout chip and its real QFrame reserve the same outer size."""
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(260, 80)
    label = PinnedAxisLabel(host)
    host.show()
    label.show()
    qapp.processEvents()
    text = "P12·A/B"
    metrics = QFontMetrics(label._caption.font())
    expected_width, expected_height = axis_label_outer_size(text, metrics)
    margins = label.layout().contentsMargins()
    assert expected_width >= (
        metrics.horizontalAdvance(text) + margins.left() + margins.right() + 2
    )
    assert expected_height >= (
        metrics.height() + margins.top() + margins.bottom() + 2
    )

    items = layout_pinned_axis_labels(
        [{
            "record_id": "record-12",
            "ordinal": 12,
            "endpoint": "x",
            "text": text,
            "canvas_x": 120.0,
            "offscreen": None,
        }],
        axis_left=20,
        axis_right=220,
        axis_top=80,
        axis_height=expected_height,
        fm=metrics,
    )
    assert len(items) == 1
    assert items[0].canvas_rect[2:] == (expected_width, expected_height)
    label.apply_geom(items[0])
    qapp.processEvents()
    assert label.size().width() == expected_width
    assert label.size().height() == expected_height
    assert label._caption.contentsRect().width() >= metrics.horizontalAdvance(text)

    # Render the production QLabel, rather than trusting its size hint alone:
    # every caption ink pixel must keep a margin inside the frame content.
    image = QImage(label._caption.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    label._caption.render(painter)
    painter.end()
    ink = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 24
    ]
    assert ink
    assert min(x for x, _y in ink) > 0
    assert max(x for x, _y in ink) < image.width() - 1
    assert min(y for _x, y in ink) >= 0
    assert max(y for _x, y in ink) < image.height()


def test_expanded_panel_tether_targets_the_opened_endpoint_and_cleans_up(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    record = _pin(cs, canvas, [(0.25, 0.75)], mode="dual")[0]
    controller = cs._pinned_cursors

    label = next(
        label for label in controller.axis_labels_for(canvas)
        if label.geom() is not None
        and any(
            member[:2] == (record.record_id, "a")
            for member in label.geom().members
        )
    )
    qtbot.mouseClick(label, Qt.LeftButton, pos=label.rect().center())
    controller.flush_layout(canvas)
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    assert overlay.tether_endpoint_keys_for(record.record_id) == ("a",)
    assert len(overlay.tether_items()) == 1
    assert len(overlay.tether_port_items()) == 1
    tether_path = overlay.tether_items()[0].path()
    target = tether_path.elementAt(tether_path.elementCount() - 1)
    line = overlay.lines_for(record.record_id, "a")[0]
    expected_target = line.getViewBox().mapViewToScene(
        QPointF(float(line.value()), 0.0)
    )
    assert target.x == pytest.approx(expected_target.x(), abs=0.75)

    qtbot.mouseClick(label, Qt.LeftButton, pos=label.rect().center())
    qapp.processEvents()
    assert overlay.tether_endpoint_keys_for(record.record_id) == ()
    assert overlay.tether_items() == ()
    assert overlay.tether_port_items() == ()

    # A restored/programmatic expansion has no selected A/B endpoint, so its
    # neutral port forks to both lines rather than implying an active side.
    controller.toggle_record_panel(canvas, record.record_id)
    controller.flush_layout(canvas)
    qapp.processEvents()
    assert overlay.tether_endpoint_keys_for(record.record_id) == ("a", "b")
    assert len(overlay.tether_items()) == 2
    port_before = overlay._tethers[0].panel_port
    pill = controller.pills_for(canvas)[0]
    start = pill.rect().center()
    qtbot.mousePress(pill, Qt.LeftButton, pos=start)
    qtbot.mouseRelease(pill, Qt.LeftButton, pos=start + QPoint(-30, 16))
    qapp.processEvents()
    assert overlay._tethers[0].panel_port != port_before


def test_time_overlay_line_tracks_physical_x_after_pan_zoom(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(canvas, "single")
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)

    records = _pin(cs, canvas, [0.35])
    overlay = canvas._pinned_overlay
    physical = records[0].x
    lines = overlay.lines_for(records[0].record_id, "x")
    assert lines
    assert lines[0].value() == pytest.approx(physical)
    before = _scene_x(lines[0])
    expected = canvas._pinned_overlay.lines_for(records[0].record_id)[0]
    vb = expected.getViewBox()
    assert before == pytest.approx(
        float(vb.mapViewToScene(QPointF(physical, 0.0)).x()), abs=0.75,
    )

    canvas.set_xlim(0.2, 0.8)
    qapp.processEvents()
    overlay.reproject()
    lines = overlay.lines_for(records[0].record_id, "x")
    assert lines[0].value() == pytest.approx(physical)
    after = _scene_x(lines[0])
    vb = lines[0].getViewBox()
    assert after == pytest.approx(
        float(vb.mapViewToScene(QPointF(physical, 0.0)).x()), abs=0.75,
    )
    assert after != pytest.approx(before, abs=0.05)
    lo, hi = vb.viewRange()[0]
    assert lo <= physical <= hi
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    assert labels
    assert any("P1" in (label.geom().text if label.geom() else "") for label in labels)


def test_time_subplot_draws_a_line_in_each_shared_x_plot(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels(
        [
            ("speed", True, t, np.sin(t), "#1769e0", "rpm", "fid-a"),
            ("torque", True, t, np.cos(t), "#16a34a", "Nm", "fid-a"),
        ],
        mode="subplot",
    )
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [0.4])
    lines = canvas._pinned_overlay.lines_for(records[0].record_id, "x")
    boxes = {id(line.getViewBox()) for line in lines}
    data_boxes = {
        id(handle.view_box)
        for handle in canvas.axes_list
        if not getattr(handle, "placeholder", False)
    }
    assert len(lines) == len(data_boxes)
    assert boxes == data_boxes
    for line in lines:
        assert line.value() == pytest.approx(records[0].x)


def test_fft_lines_only_in_spectrum_and_host_excludes_preview(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    cs.set_mode("fft")
    qapp.processEvents()
    canvas = cs.canvas_fft
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.plot_spectra(
        _fft_entries(), xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT",
    )
    qapp.processEvents()
    host = _wait_host(qtbot, canvas)
    assert host == canvas.frequency_cursor_host_rect()
    preview = canvas._plot_time.vb.sceneBoundingRect()
    glw = canvas._glw
    preview_top = glw.mapTo(
        canvas,
        glw.mapFromScene(preview.topLeft()),
    ).y()
    assert host.bottom() <= preview_top + 8
    records = _pin(cs, canvas, [100.0], domain="frequency")
    overlay = canvas._pinned_overlay
    lines = overlay.lines_for(records[0].record_id)
    assert lines
    for line in lines:
        assert line.getViewBox() is canvas._plot_amp.vb
        assert line.getViewBox() is not canvas._plot_time.vb
        assert line.value() == pytest.approx(100.0)
    stack_host = cs.pinned_cursor_host_on_stack(canvas)
    assert stack_host is not None
    assert stack_host != cs.stack.rect()
    transient = {id(item) for item in canvas.iter_transient_overlay_items()}
    for line in overlay.iter_lines():
        assert id(line) not in transient


def test_frf_linear_and_log_three_plots_keep_hz(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp, height=820)
    cs.set_mode("frf")
    qapp.processEvents()
    canvas = cs.canvas_frf
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_result(
        _frf_result(log=False),
        {"frequency_scale": "linear", "magnitude_scale": "linear"},
        {},
    )
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    assert canvas.frequency_cursor_host_rect() is not None
    records = _pin(cs, canvas, [2.0], domain="frf")
    assert records[0].x == pytest.approx(2.0)
    lines = canvas._pinned_overlay.lines_for(records[0].record_id)
    assert len(lines) == 3
    assert {id(line.getViewBox()) for line in lines} == {
        id(plot.vb) for plot in canvas.plots
    }
    for line in lines:
        assert line.value() == pytest.approx(2.0)

    canvas.set_result(
        _frf_result(log=True),
        {"frequency_scale": "log", "magnitude_scale": "db"},
        {},
    )
    qapp.processEvents()
    records = _pin(cs, canvas, [10.0], domain="frf")
    assert records[0].x == pytest.approx(10.0)
    assert records[0].x != pytest.approx(1.0)
    lines = canvas._pinned_overlay.lines_for(records[0].record_id)
    assert len(lines) == 3
    for line in lines:
        assert line.value() == pytest.approx(canvas._hz_to_view_x(10.0))
        assert line.value() == pytest.approx(1.0)


def test_one_two_eight_twenty_pins_labels_discoverable_ticks_untouched(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    bottom = canvas._primary_xaxis_ax._ax("bottom") if canvas._primary_xaxis_ax else None
    title_before = bottom.labelText if bottom is not None else None
    ticks_before = list(getattr(bottom, "_tickLevels", None) or [])

    for count in (1, 2, 8, 20):
        xs = [0.08 + (0.84 * index / max(1, count - 1)) for index in range(count)]
        records = _pin(cs, canvas, xs)
        assert len(records) == count
        overlay = canvas._pinned_overlay
        assert len(list(overlay.iter_lines())) >= count
        labels = cs._pinned_cursors.axis_labels_for(canvas)
        assert labels
        texts = " ".join(
            (label.geom().text if label.geom() else "") for label in labels
        )
        assert "P" in texts or "+" in texts
        for label in labels:
            assert label.parent() is cs.stack
            assert label.isVisible()
            geom = label.geom()
            assert geom is not None
            document = label._caption
            assert document.text()
        if bottom is not None:
            assert bottom.labelText == title_before
            for label in labels:
                ancestor = label.parentWidget()
                while ancestor is not None:
                    assert ancestor is not bottom
                    ancestor = ancestor.parentWidget()

    if bottom is not None and ticks_before:
        qapp.processEvents()
        assert getattr(bottom, "_tickLevels", None)


def test_same_x_cluster_hover_expands_numbers(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [0.42] * 8)
    assert len(records) == 8
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    clusters = [
        label for label in labels
        if label.geom() is not None and label.geom().kind == "cluster"
    ]
    assert clusters
    cluster = clusters[0]
    assert "–" in cluster.geom().text or cluster.geom().text.startswith("+")
    assert len(cluster.geom().members) == 8
    QApplication.sendEvent(cluster, QEvent(QEvent.Enter))
    qapp.processEvents()
    member_buttons = [
        child for child in cluster.findChildren(QPushButton)
        if child.objectName() == "pinnedAxisLabelMember"
    ]
    assert len(member_buttons) == 8
    local_scroll = cluster.findChild(QScrollArea, "pinnedAxisLabelMembers")
    assert local_scroll is not None
    assert cluster.size() == cluster.sizeHint() or (
        cluster.width() == cluster.geom().canvas_rect[2]
    )
    for button in member_buttons:
        text = button.text()
        fm = QFontMetrics(button.font())
        assert button.width() >= fm.horizontalAdvance(text), (
            f"{text!r} button width {button.width()} < text {fm.horizontalAdvance(text)}"
        )


def test_dense_axis_labels_stagger_across_finite_rows_without_losing_members(qapp):
    fm = QFontMetrics(QFont())
    sample_w, sample_h = axis_label_outer_size("P8", fm)
    spacing = sample_w + 8
    axis_right = 20 + spacing * 5
    endpoints = [
        {
            "record_id": f"id-{index}",
            "ordinal": index + 1,
            "endpoint": "x",
            "text": f"P{index + 1}",
            "canvas_x": 30.0 + index * spacing,
            "offscreen": None,
        }
        for index in range(8)
    ]
    items = layout_pinned_axis_labels(
        endpoints,
        axis_left=20, axis_right=axis_right, axis_top=100, axis_height=sample_h,
        axis_floor=30, fm=fm,
    )
    assert items
    assert len({item.canvas_rect[1] for item in items}) > 1
    seen = {
        (record_id, endpoint)
        for item in items
        for record_id, endpoint, _text, _ordinal in item.members
    }
    assert seen == {(item["record_id"], item["endpoint"]) for item in endpoints}
    rects = [QRect(*item.canvas_rect) for item in items]
    for index, rect in enumerate(rects):
        assert rect.left() >= 20 and rect.right() <= axis_right
        assert rect.top() >= 30
        for other in rects[index + 1:]:
            assert not rect.intersects(other)


def test_single_pin_line_has_opaque_bluegray_and_selected_blue_chrome(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    record = _pin(cs, canvas, [0.5])[0]
    overlay = canvas._pinned_overlay
    line = overlay.lines_for(record.record_id, "x")[0]
    pen = line.pen
    pen = pen() if callable(pen) else pen
    assert pen.color().name() == "#54749d"
    assert pen.color().alpha() == 255
    assert pen.widthF() == pytest.approx(1.5)

    overlay.set_highlight(record.record_id)
    selected = line.pen
    selected = selected() if callable(selected) else selected
    assert selected.color().name() == "#006bea"
    assert selected.color().alpha() == 255
    assert selected.widthF() == pytest.approx(2.25)


def test_offscreen_endpoint_is_not_clamped_and_marks_out_of_view(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [0.15, 0.85], mode="single")
    canvas.set_xlim(0.4, 0.6)
    qapp.processEvents()
    canvas._pinned_overlay.reproject()
    overlay = canvas._pinned_overlay
    left = records[0]
    right = records[1]
    for record, side in ((left, "left"), (right, "right")):
        lines = overlay.lines_for(record.record_id, "x")
        assert lines
        value = float(lines[0].value())
        assert value == pytest.approx(record.x)
        vb = lines[0].getViewBox()
        lo, hi = vb.viewRange()[0]
        assert not (lo <= record.x <= hi)
        assert value != pytest.approx(lo)
        assert value != pytest.approx(hi)
        assert record.record_id in overlay.offscreen_record_ids()
    pills = cs._pinned_cursors.pills_for(canvas)
    assert any(bool(pill.property("pinnedOffscreen")) for pill in pills)
    assert any(pill.toolTip() == PINNED_OFFSCREEN_TEXT for pill in pills)
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    texts = [label.geom().text for label in labels if label.geom()]
    assert any(text.startswith("◀") for text in texts)
    assert any(text.endswith("▶") for text in texts)


def test_host_pending_and_tiny_window_keep_discoverable_ordinals(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.3, 0.6])
    assert cs.pinned_cursor_host_on_stack(canvas) is not None

    cs.resize(80, 80)
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    overlay.reproject()
    layout = overlay.layout()
    if layout.pending:
        assert cs.pinned_cursor_host_on_stack(canvas) is None
        assert cs.pinned_cursor_host_on_stack(canvas) != cs.rect()
    else:
        texts = [item.text for item in layout.items]
        assert texts
        assert any("P" in text or "+" in text for text in texts)
    assert overlay.records()
    assert len(cs.pinned_cursors_for_canvas(canvas).records) == 2


def test_click_label_raises_pill_without_changing_placement(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    cs.set_cursor_mode_for_canvas(canvas, "dual")
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    canvas.restore_cursor_placement({"ax": 0.25, "bx": 0.7})
    before = canvas.snapshot_cursor_placement()
    records = _pin(cs, canvas, [(0.25, 0.7)], mode="dual")
    assert canvas.snapshot_cursor_placement() == before
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    assert labels
    label = labels[0]
    qtbot.mouseClick(label, Qt.LeftButton, pos=label.rect().center())
    qapp.processEvents()
    assert canvas.snapshot_cursor_placement() == before
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    assert pills[0].isVisible()
    assert records[0].ax == pytest.approx(0.25)
    assert records[0].bx == pytest.approx(0.7)


def test_coaxis_dual_extrema_keep_every_member(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    t = np.array([0.0, 0.25, 0.50, 0.75, 1.0], dtype=np.float64)
    group = {"axis_group": 1}
    canvas.plot_channels(
        [
            ("torque", True, t, np.array([1.0, -3.0, 2.0, 5.0, 0.0]),
             "#ef4444", "Nm", "fid-1", group),
            ("angle", True, t, np.array([4.0, 7.0, -2.0, 1.0, 0.0]),
             "#06b6d4", "deg", "fid-1", group),
            ("current", True, t, np.array([2.0, 0.0, 8.0, -4.0, 1.0]),
             "#8b5cf6", "A", "fid-1", group),
        ],
        mode="overlay",
    )
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [(0.20, 0.80)], mode="dual")
    sample = cs._pinned_cursors._owner(canvas).samples[records[0].record_id]
    assert len(sample.extrema) == 3
    markers = canvas._pinned_overlay.extrema_items()
    assert markers
    xs, ys = markers[0].getData()
    assert len(xs) == 6
    assert sorted(ys) == pytest.approx(sorted([-3.0, 5.0, -2.0, 7.0, -4.0, 8.0]))
    transient = {id(item) for item in canvas.iter_transient_overlay_items()}
    for marker in markers:
        assert id(marker) not in transient


def test_dual_ab_merge_and_a_b_colors(qapp, qtbot, production_style):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    equal = _pin(cs, canvas, [(0.4, 0.4)], mode="dual")
    overlay = canvas._pinned_overlay
    assert overlay.lines_for(equal[0].record_id, "a")
    assert overlay.lines_for(equal[0].record_id, "b")
    labels = cs._pinned_cursors.axis_labels_for(canvas)
    assert any(
        label.geom() and "A/B" in label.geom().text for label in labels
    )
    assert any(
        label.geom()
        and {(member[0], member[1]) for member in label.geom().members}
        == {(equal[0].record_id, "a"), (equal[0].record_id, "b")}
        for label in labels
    )
    split = _pin(cs, canvas, [(0.2, 0.8)], mode="dual")
    a_lines = overlay.lines_for(split[-1].record_id, "a")
    b_lines = overlay.lines_for(split[-1].record_id, "b")
    assert a_lines and b_lines
    a_pen = a_lines[0].pen
    b_pen = b_lines[0].pen
    if callable(a_pen):
        a_pen = a_pen()
    if callable(b_pen):
        b_pen = b_pen()
    assert a_pen.color().name() != b_pen.color().name()


def test_unrepresentable_layout_is_not_offscreen_left(qapp):
    fm = QFontMetrics(QFont())
    items = layout_pinned_axis_labels(
        [
            {
                "record_id": "zero",
                "ordinal": 1,
                "endpoint": "x",
                "text": "P1",
                "canvas_x": 40.0,
                "offscreen": "unrepresentable",
            }
        ],
        axis_left=20, axis_right=220, axis_top=80, axis_height=16, fm=fm,
    )
    assert items
    assert items[0].offscreen == "unrepresentable"
    assert items[0].text == PINNED_UNREPRESENTABLE_TEXT
    assert not items[0].text.startswith("◀")


def test_cluster_keys_are_slot_indices_not_member_sets(qapp):
    fm = QFontMetrics(QFont())
    kwargs = dict(
        axis_left=20, axis_right=220, axis_top=80, axis_height=16, fm=fm,
    )
    first = [
        {
            "record_id": f"id-{index}",
            "ordinal": index + 1,
            "endpoint": "x",
            "text": f"P{index + 1}",
            "canvas_x": 40.0 + index * 2.0,
            "offscreen": None,
        }
        for index in range(8)
    ]
    second = [
        {**item, "record_id": f"other-{item['ordinal']}"}
        for item in first
    ]
    items_a = layout_pinned_axis_labels(first, **kwargs)
    items_b = layout_pinned_axis_labels(second, **kwargs)
    assert items_a
    assert [item.key for item in items_a] == [item.key for item in items_b]
    assert all(
        item.key.startswith("slot:")
        or item.key.startswith("edge:")
        or item.key == "tiny"
        for item in items_a
    )
    assert all("id-" not in item.key and "other-" not in item.key for item in items_a)


def test_dual_one_endpoint_offscreen_does_not_mark_whole_pill(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    records = _pin(cs, canvas, [(0.15, 0.5)], mode="dual")
    canvas.set_xlim(0.4, 0.6)
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    overlay.reproject()
    qapp.processEvents()
    record_id = records[0].record_id
    assert record_id not in overlay.offscreen_record_ids()
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    assert not bool(pills[0].property("pinnedOffscreen"))
    assert any(item.offscreen == "left" for item in overlay.layout().items)

    both = _pin(cs, canvas, [(0.05, 0.10)], mode="dual")
    canvas.set_xlim(0.4, 0.6)
    qapp.processEvents()
    overlay.reproject()
    qapp.processEvents()
    assert both[0].record_id in overlay.offscreen_record_ids()
    both_pills = cs._pinned_cursors.pills_for(canvas)
    assert any(bool(pill.property("pinnedOffscreen")) for pill in both_pills)


def test_frf_log_non_positive_frequency_is_unrepresentable(
    qapp, qtbot, production_style,
):
    from mf4_analyzer.ui.pg_canvas.pinned_cursor_overlay import (
        PinnedOverlayEndpoint,
        PinnedOverlayRecord,
    )

    cs = _make_stack(qtbot, qapp, height=820)
    cs.set_mode("frf")
    qapp.processEvents()
    canvas = cs.canvas_frf
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_result(
        _frf_result(log=True),
        {"frequency_scale": "log", "magnitude_scale": "db"},
        {},
    )
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    overlay = canvas._pinned_overlay
    assert overlay._view_x(0.0) is None
    assert overlay._view_x(0.5) is not None
    overlay.set_records((
        PinnedOverlayRecord(
            record_id="zero-hz",
            ordinal=1,
            mode="single",
            domain="frf",
            endpoints=(PinnedOverlayEndpoint("x", 0.0, "P1"),),
        ),
    ))
    qapp.processEvents()
    items = overlay.layout().items
    assert any(item.offscreen == "unrepresentable" for item in items)
    assert not any(
        item.offscreen == "unrepresentable" and item.text.startswith("◀")
        for item in items
    )
    assert any(item.text == PINNED_UNREPRESENTABLE_TEXT for item in items)

    overlay.set_records((
        PinnedOverlayRecord(
            record_id="half-hz",
            ordinal=1,
            mode="single",
            domain="frf",
            endpoints=(PinnedOverlayEndpoint("x", 0.5, "P1"),),
        ),
    ))
    qapp.processEvents()
    left_items = overlay.layout().items
    assert any(item.offscreen == "left" for item in left_items)
    assert not any(item.offscreen == "unrepresentable" for item in left_items)
    assert any(item.text.startswith("◀") for item in left_items)


def test_view_geometry_coalesces_and_reuses_leaders(
    qapp, qtbot, production_style, monkeypatch,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    xs = [0.40 + index * 0.002 for index in range(12)]
    _pin(cs, canvas, xs)
    overlay = canvas._pinned_overlay
    overlay.reproject()
    qapp.processEvents()
    before = [id(item) for item in overlay._leader_items]
    overlay._stop_geom_timer()
    calls = []
    real = type(overlay)._build_layout

    def wrapped(self, host):
        calls.append(host)
        return real(self, host)

    monkeypatch.setattr(type(overlay), "_build_layout", wrapped)
    for _ in range(6):
        overlay._on_view_geometry_changed()
    assert overlay._geom_timer.isActive()
    qapp.processEvents()
    assert len(calls) == 1
    after = [id(item) for item in overlay._leader_items]
    if before and after:
        assert before[0] in after


def _wrap_reflow(pill):
    calls = []
    original = pill.reflow_to_parent

    def wrapped(*args, **kwargs):
        calls.append(pill.geometry().getRect())
        return original(*args, **kwargs)

    pill.reflow_to_parent = wrapped
    return calls


def _image_key(pix):
    img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
    bits = img.bits()
    bits.setsize(img.byteCount())
    return (img.width(), img.height(), hashlib.md5(bytes(bits)).hexdigest())


def test_resize_burst_coalesces_qtextdocument_reflow(
    qapp, qtbot, production_style,
):
    """Same-turn geometry bursts typeset once on the next event-loop turn."""
    cs = _make_stack(qtbot, qapp, width=1100, height=640)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.35], expand=True)
    cs._pill.setVisible(False)
    cs.resize(1000, 600)
    qapp.processEvents()
    cs._pinned_cursors.flush_layout()
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    pill = pills[0]
    assert pill.isVisible()
    calls = _wrap_reflow(pill)
    projector = cs._pinned_cursors._projector

    for delta in range(6):
        cs.resize(1000 + delta * 8, 600)
    assert len(calls) == 0
    assert projector._layout_timer.isActive()

    qapp.processEvents()
    assert len(calls) == 1
    assert not projector._layout_timer.isActive()

    cs.resize(1000, 600)
    qapp.processEvents()
    cs._pinned_cursors.flush_layout()
    oracle_size = pill.size()
    oracle_key = _image_key(pill.grab())
    calls.clear()

    cs.resize(1100, 600)
    qapp.processEvents()
    cs._pinned_cursors.flush_layout()
    calls.clear()
    for width in (1060, 1020, 1000):
        cs.resize(width, 600)
    pix = cs.grab_presentation_pixmap(canvas, scale=1.0)
    assert pix is not None and not pix.isNull()
    assert len(calls) == 1
    assert pill.size() == oracle_size
    assert _image_key(pill.grab()) == oracle_key
    assert not projector._layout_timer.isActive()


def test_flush_layout_cancels_duplicate_pending_and_layout_once(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.4], expand=True)
    cs._pinned_cursors.flush_layout()
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    calls = _wrap_reflow(pill)
    for delta in range(5):
        cs.resize(1080 - delta * 6, 640)
    assert len(calls) == 0
    cs._pinned_cursors.flush_layout()
    assert len(calls) == 1
    cs._pinned_cursors.flush_layout()
    qapp.processEvents()
    assert len(calls) == 1
    assert not cs._pinned_cursors._projector._layout_timer.isActive()


def test_origin_only_safe_rect_does_not_retypeset(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.45], expand=True)
    cs._pinned_cursors.flush_layout()
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    before = pill.geometry()
    calls = _wrap_reflow(pill)
    real_sync = cs._sync_pill_safe_rect

    def shifted(widget, card):
        changed = real_sync(widget, card)
        if widget is not pill:
            return changed
        safe = widget.safe_rect()
        if not safe.isValid():
            return changed
        return widget.set_safe_rect(safe.translated(18, 12))

    cs._sync_pill_safe_rect = shifted
    cs._pinned_cursors.reflow_visible()
    cs._pinned_cursors.flush_layout()
    assert calls == []
    after = pill.geometry()
    assert after.size() == before.size()
    assert after.topLeft() != before.topLeft()


def test_content_change_same_size_still_reflows(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.3], expand=True)
    cs._pinned_cursors.flush_layout()
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    safe = QRect(pill.safe_rect())
    calls = _wrap_reflow(pill)
    pill._primary_original = str(getattr(pill, "_primary_original", "") or "") + " "
    cs._pinned_cursors.reflow_visible()
    cs._pinned_cursors.flush_layout()
    assert len(calls) == 1
    assert pill.safe_rect().size() == safe.size()


def test_collapsed_pin_skips_geometry_reflow(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.25])
    cs._pinned_cursors.flush_layout()
    pills = cs._pinned_cursors.pills_for(canvas)
    assert pills
    pill = pills[0]
    assert not pill.isVisible()
    calls = _wrap_reflow(pill)
    for delta in range(4):
        cs.resize(1090 - delta * 10, 640)
    cs._pinned_cursors.flush_layout()
    qapp.processEvents()
    assert calls == []


def test_awaiting_space_retries_when_pane_grows(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp, width=1100, height=640)
    canvas = cs.canvas_time
    extra = [
        (f"ch{i}", True, np.linspace(0.0, 1.0, 200), np.cos(2 * np.pi * (i + 1) * np.linspace(0.0, 1.0, 200)),
         "#16a34a", "rpm", "fid-a")
        for i in range(8)
    ]
    _plot_time(canvas, extra=extra)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.4], expand=True)
    cs._pinned_cursors.flush_layout()
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    assert pill.isVisible()
    readable_h = pill.height()
    real_sync = cs._sync_pill_safe_rect
    tiny = QRect(8, 41, 36, 18)

    def cramped(widget, card):
        if widget is pill:
            return widget.set_safe_rect(tiny)
        return real_sync(widget, card)

    cs._sync_pill_safe_rect = cramped
    cs._pinned_cursors.reflow_visible()
    cs._pinned_cursors.flush_layout()
    assert pill.awaiting_space() or not pill.isVisible()
    cs._sync_pill_safe_rect = real_sync
    cs._pinned_cursors.reflow_visible()
    cs._pinned_cursors.flush_layout()
    assert pill.isVisible()
    assert not pill.awaiting_space()
    assert pill.height() >= min(readable_h - 2, max(1, pill.safe_rect().height()))
    doc = pill._detail.document
    assert doc.size().height() <= pill._detail.height() + 8


def test_invalidate_cancels_pending_layout(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.5], expand=True)
    cs._pinned_cursors.flush_layout()
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    calls = _wrap_reflow(pill)
    cs.resize(1000, 600)
    cs.resize(980, 600)
    assert cs._pinned_cursors._projector._layout_timer.isActive()
    cs._pinned_cursors.clear_all()
    qapp.processEvents()
    assert calls == []
    assert not cs._pinned_cursors._projector._layout_timer.isActive()


def test_layout_reentrancy_leaves_one_more_turn(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.33], expand=True)
    cs._pinned_cursors.flush_layout()
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    original = pill.reflow_to_parent
    calls = []

    def wrapped(*args, **kwargs):
        calls.append(1)
        result = original(*args, **kwargs)
        if len(calls) == 1:
            cs._pinned_cursors.reflow_visible()
        return result

    pill.reflow_to_parent = wrapped
    cs.resize(1040, 640)
    cs._pinned_cursors.flush_layout()
    assert len(calls) == 1
    assert cs._pinned_cursors._projector._layout_timer.isActive()
    qapp.processEvents()
    assert not cs._pinned_cursors._projector._layout_timer.isActive()
    qapp.processEvents()
    assert not cs._pinned_cursors._projector._layout_timer.isActive()


def test_resize_does_not_sample_or_mark_intent(
    qapp, qtbot, production_style, monkeypatch,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.28], expand=True)
    cs._pinned_cursors.flush_layout()
    controller = cs._pinned_cursors
    revision = controller.user_intent_revision
    scheduled = []
    evaluated = []
    monkeypatch.setattr(
        controller, "_schedule_reproject",
        lambda *args, **kwargs: scheduled.append(1),
    )
    original_eval = controller._evaluate_intent
    monkeypatch.setattr(
        controller, "_evaluate_intent",
        lambda *args, **kwargs: evaluated.append(1) or original_eval(*args, **kwargs),
    )
    cs.resize(1020, 620)
    cs.resize(1000, 600)
    controller.flush_layout()
    qapp.processEvents()
    assert scheduled == []
    assert evaluated == []
    assert controller.user_intent_revision == revision


def test_font_revision_forces_typeset(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    _pin(cs, canvas, [0.22], expand=True)
    cs._pinned_cursors.flush_layout()
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    calls = _wrap_reflow(pill)
    font = QFont(pill.font())
    font.setPointSize(max(8, font.pointSize()) + 3)
    pill.setFont(font)
    cs._pinned_cursors.reflow_visible()
    cs._pinned_cursors.flush_layout()
    assert len(calls) == 1


def test_route_panel_tether_stays_outside_a_covering_panel():
    """The old A-path (158,65)→(86,3) sat entirely inside a 318×66 card."""
    panel = QRectF(0.0, 0.0, 318.0, 66.0)
    host = QRectF(-20.0, -20.0, 800.0, 400.0)
    ports = tether_candidate_ports(panel)
    port, paths = route_panel_tether(
        panel_rect=panel,
        ports=ports,
        obstacles=(),
        target_xs=(86.0,),
        host_rect=host,
    )
    assert port is not None
    assert paths
    for path in paths:
        assert len(path) >= 2
        for point in path:
            assert not panel.contains(QPointF(*point))


def test_route_panel_tether_avoids_live_panel_obstacle():
    panel = QRectF(20.0, 20.0, 90.0, 50.0)
    live = (160.0, 30.0, 110.0, 80.0)
    host = QRectF(0.0, 0.0, 480.0, 280.0)
    ports = tether_candidate_ports(panel)
    port, paths = route_panel_tether(
        panel_rect=panel,
        ports=ports,
        obstacles=(live,),
        target_xs=(220.0,),
        host_rect=host,
    )
    assert port is not None
    blocked = QRectF(*live)
    if paths:
        for path in paths:
            assert not _path_hits_rects(path, (blocked,))
    else:
        assert port.point is not None
        assert not blocked.contains(QPointF(*port.point))


def test_route_panel_tether_host_edge_keeps_path_inside_or_explains():
    panel = QRectF(6.0, 6.0, 70.0, 40.0)
    host = QRectF(0.0, 0.0, 100.0, 55.0)
    obstacles = ((55.0, 4.0, 42.0, 48.0),)
    ports = tether_candidate_ports(panel)
    port, paths = route_panel_tether(
        panel_rect=panel,
        ports=ports,
        obstacles=obstacles,
        target_xs=(96.0,),
        host_rect=host,
    )
    assert port is not None
    slack = host.adjusted(-1.5, -1.5, 1.5, 1.5)
    for path in paths:
        assert len(path) >= 2
        for point in path:
            assert slack.contains(QPointF(*point))
    if not paths:
        assert port.point is not None


@pytest.mark.parametrize(
    "text",
    ("P12·A", "P12·B", "P12·A/B", "电机转矩", "P12·A/B-超长名称"),
)
def test_production_overlay_metrics_match_widget_and_hit_rect(
    qapp, qtbot, production_style, text,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    overlay = canvas._pinned_overlay
    fm, margins = overlay._axis_label_style()
    width, height = axis_label_outer_size(text, fm, content_margins=margins)
    items = layout_pinned_axis_labels(
        [{
            "record_id": "record-12",
            "ordinal": 12,
            "endpoint": "x",
            "text": text,
            "canvas_x": 160.0,
            "offscreen": None,
        }],
        axis_left=20,
        axis_right=420,
        axis_top=80,
        axis_height=height,
        fm=fm,
        content_margins=margins,
    )
    assert len(items) == 1
    assert items[0].canvas_rect[2:] == (width, height)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(480, 120)
    host.show()
    label = PinnedAxisLabel(host)
    label.show()
    qapp.processEvents()
    label.apply_geom(items[0])
    qapp.processEvents()
    assert label.size().width() == width
    assert label.size().height() == height
    assert label.rect() == QRect(0, 0, width, height)
    image = QImage(label.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    label.render(painter)
    painter.end()
    ink = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 24
    ]
    assert ink
    assert min(x for x, _y in ink) >= 0
    assert max(x for x, _y in ink) <= width - 1
    assert min(y for _x, y in ink) >= 0
    assert max(y for _x, y in ink) <= height - 1


def test_tether_path_leaves_the_expanded_panel_and_follows_drag(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp, width=1200, height=720)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    record = _pin(cs, canvas, [(0.25, 0.75)], mode="dual", expand=False)[0]
    controller = cs._pinned_cursors
    label = next(
        item for item in controller.axis_labels_for(canvas)
        if item.geom() is not None
        and any(
            member[:2] == (record.record_id, "a")
            for member in item.geom().members
        )
    )
    qtbot.mouseClick(label, Qt.LeftButton, pos=label.rect().center())
    controller.flush_layout(canvas)
    qapp.processEvents()
    pill = controller.pills_for(canvas)[0]
    overlay = canvas._pinned_overlay
    assert overlay.tether_endpoint_keys_for(record.record_id) == ("a",)
    _save_pin_evidence(cs, "tether-a-after.png")
    inside = [
        point for point in _tether_points_in_panel_local(canvas, pill)
        if pill.rect().adjusted(1, 1, -1, -1).contains(point)
    ]
    assert inside == []
    port_before = overlay._tethers[0].panel_port
    start = pill.rect().center()
    _send_mouse(pill, QEvent.MouseButtonPress, start)
    _send_mouse(pill, QEvent.MouseMove, start + QPoint(48, 24))
    qapp.processEvents()
    assert overlay._tethers[0].panel_port != port_before
    inside_drag = [
        point for point in _tether_points_in_panel_local(canvas, pill)
        if pill.rect().adjusted(1, 1, -1, -1).contains(point)
    ]
    assert inside_drag == []
    _send_mouse(pill, QEvent.MouseButtonRelease, start + QPoint(48, 24))
    qapp.processEvents()


def test_tether_obstacles_include_mapped_live_panel(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp, width=1200, height=720)
    canvas = cs.canvas_time
    cs.set_cursor_mode_for_canvas(canvas, "single")
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    record = _pin(cs, canvas, [0.22], expand=True)[0]
    controller = cs._pinned_cursors
    controller.flush_layout(canvas)
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    assert overlay._tethers
    live = controller._live_pill(canvas)
    assert live is not None
    live.show()
    safe = live.safe_rect()
    assert safe.isValid()
    live.move(
        safe.center().x() - live.width() // 2,
        safe.center().y() - live.height() // 2,
    )
    live.raise_()
    qapp.processEvents()
    controller._projector.sync_tethers(id(canvas), canvas)
    mapped = controller._projector._mapped_widget_obstacle(
        canvas, cs.stack, live,
    )
    assert mapped is not None
    tether = overlay._tethers[0]
    assert mapped in tether.obstacles
    assert all(not hasattr(item, "winId") for item in tether.obstacles)
    live_rect = QRectF(*mapped)
    for point in _tether_points_in_canvas(canvas):
        assert not live_rect.adjusted(1, 1, -1, -1).contains(QPointF(*point))


def test_idle_tether_composite_is_visible_and_active_is_stronger(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp, width=1200, height=720)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    record = _pin(cs, canvas, [0.28], expand=True)[0]
    controller = cs._pinned_cursors
    controller.flush_layout(canvas)
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    assert overlay.tether_items()
    idle_pen = overlay.tether_items()[0].pen()
    idle_stats = _dash_composite_stats(idle_pen)
    idle_grid = _dash_composite_stats(idle_pen, grid=True)
    controller._projector.set_hover(canvas, record.record_id)
    qapp.processEvents()
    active_pen = overlay.tether_items()[0].pen()
    active_stats = _dash_composite_stats(active_pen)
    assert idle_pen.color().red() == 0x60
    assert idle_pen.color().green() == 0x78
    assert idle_pen.color().blue() == 0x92
    assert active_pen.color().red() == idle_pen.color().red()
    assert idle_stats["n"] >= 400
    assert idle_stats["min_lum"] <= 185
    assert idle_stats["mean_delta"] >= 70
    assert idle_grid["min_lum"] <= 175
    assert active_pen.widthF() > idle_pen.widthF()
    assert active_pen.color().alpha() > idle_pen.color().alpha()
    assert active_stats["min_lum"] <= idle_stats["min_lum"] - 20
    assert active_stats["mean_delta"] > idle_stats["mean_delta"]


def test_selected_panel_does_not_reshape_the_tether_port(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp, width=1200, height=720)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    record = _pin(cs, canvas, [0.28], expand=True)[0]
    controller = cs._pinned_cursors
    controller.flush_layout(canvas)
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    ports = overlay.tether_port_items()
    assert len(ports) == 1
    idle_rect = ports[0].rect()
    idle_pen = ports[0].pen()
    idle_fill = ports[0].brush().color()
    controller._projector.set_hover(canvas, record.record_id)
    qapp.processEvents()
    ports = overlay.tether_port_items()
    assert len(ports) == 1
    assert ports[0].rect() == idle_rect
    assert ports[0].pen().widthF() == pytest.approx(idle_pen.widthF())
    assert ports[0].pen().color() == idle_pen.color()
    assert ports[0].brush().color() == idle_fill
    path_pen = overlay.tether_items()[0].pen()
    assert path_pen.widthF() > idle_pen.widthF()


def _standalone_axis_label(qtbot, qapp, text="P12", *, endpoint="x"):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(360, 90)
    label = PinnedAxisLabel(host)
    label._test_host = host
    host.show()
    label.show()
    qapp.processEvents()
    metrics = QFontMetrics(label._caption.font())
    width, height = axis_label_outer_size(text, metrics)
    items = layout_pinned_axis_labels(
        [{
            "record_id": "record-12",
            "ordinal": 12,
            "endpoint": endpoint,
            "text": text,
            "canvas_x": 140.0,
            "offscreen": None,
        }],
        axis_left=20,
        axis_right=320,
        axis_top=50,
        axis_height=height,
        fm=metrics,
    )
    assert items
    label.apply_geom(items[0])
    qapp.processEvents()
    return label, items[0]


def _render_axis_label(label):
    image = QImage(label.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    label.render(painter)
    painter.end()
    return image


def _color_distance(left, right):
    return (
        abs(left.red() - right.red())
        + abs(left.green() - right.green())
        + abs(left.blue() - right.blue())
    )


def _sample_label_fill(image, label):
    pip = label.pip_rect()
    box = label.hit_rect()
    x = min(int(pip.right()) + 2, box.right() - 3)
    y = int(pip.center().y())
    return image.pixelColor(
        min(max(0, x), image.width() - 1),
        min(max(0, y), image.height() - 1),
    )


def _pip_interior_color(image, label):
    pip = label.pip_rect().adjusted(2, 2, -2, -2)
    x = int(pip.center().x())
    y = int(pip.center().y())
    return image.pixelColor(
        min(max(0, x), image.width() - 1),
        min(max(0, y), image.height() - 1),
    )


def _mean_luma(image, rect):
    left = max(0, int(rect.left()))
    top = max(0, int(rect.top()))
    right = min(image.width(), int(rect.right()) + 1)
    bottom = min(image.height(), int(rect.bottom()) + 1)
    values = []
    for y in range(top, bottom):
        for x in range(left, right):
            color = image.pixelColor(x, y)
            if color.alpha() < 24:
                continue
            values.append(
                0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            )
    assert values
    return sum(values) / len(values)


@pytest.mark.parametrize("text", ("P12", "P12·A/B", "P1"))
def test_axis_label_tristate_colors_pip_and_collapsed_hover_stays_hollow(
    qapp, qtbot, production_style, text,
):
    label, geom = _standalone_axis_label(qtbot, qapp, text)
    true_x = geom.true_x
    members = geom.members
    collapsed = axis_label_chrome(panel_open=False, highlighted=False)
    collapsed_hover = axis_label_chrome(panel_open=False, highlighted=True)
    opened = axis_label_chrome(panel_open=True, highlighted=False)
    active = axis_label_chrome(panel_open=True, highlighted=True)

    assert collapsed.pip_filled is False
    assert collapsed_hover.pip_filled is False
    assert opened.pip_filled is True
    assert active.pip_filled is True
    assert collapsed.ring is None
    assert opened.ring is None
    assert active.ring == "#D3E2F7"
    assert collapsed_hover.fill == collapsed.fill
    assert "展开" in label.toolTip() and "面板" in label.toolTip()

    image = _render_axis_label(label)
    fill = _sample_label_fill(image, label)
    pip = _pip_interior_color(image, label)
    assert _color_distance(fill, QColor(collapsed.fill)) < 90
    assert _color_distance(pip, QColor(collapsed.fill)) < _color_distance(
        pip, QColor(collapsed.ink)
    )
    assert _color_distance(pip, QColor(collapsed.ink)) > 60

    label.set_highlighted(True)
    qapp.processEvents()
    hovered = _render_axis_label(label)
    hover_pip = _pip_interior_color(hovered, label)
    hover_fill = _sample_label_fill(hovered, label)
    assert _color_distance(hover_fill, QColor(collapsed.fill)) < 90
    assert _color_distance(hover_fill, QColor(active.fill)) > 200
    assert _color_distance(hover_pip, QColor(collapsed.fill)) < _color_distance(
        hover_pip, QColor(collapsed.ink)
    )
    assert label.geom().true_x == true_x
    assert label.geom().members == members

    label.set_highlighted(False)
    label.set_panel_open(True)
    qapp.processEvents()
    assert "收起" in label.toolTip() and "保留固定读数" in label.toolTip()
    opened_img = _render_axis_label(label)
    opened_fill = _sample_label_fill(opened_img, label)
    opened_pip = _pip_interior_color(opened_img, label)
    assert _color_distance(opened_fill, QColor(opened.fill)) < 90
    assert _color_distance(opened_pip, QColor(opened.ink)) < _color_distance(
        opened_pip, QColor(opened.fill)
    )

    label.set_highlighted(True)
    qapp.processEvents()
    active_img = _render_axis_label(label)
    active_fill = _sample_label_fill(active_img, label)
    ring = active_img.pixelColor(1, label.height() // 2)
    assert _color_distance(active_fill, QColor(active.fill)) < 110
    assert _color_distance(ring, QColor(active.ring)) < 140
    assert label.geom().true_x == true_x
    assert label.size().width() == geom.canvas_rect[2]
    assert label.size().height() == geom.canvas_rect[3]


@pytest.mark.parametrize("text", ("P12", "P12·A/B", "P12·A"))
def test_axis_label_outer_size_includes_pip_ring_and_hit_rect(
    qapp, qtbot, production_style, text,
):
    label, geom = _standalone_axis_label(qtbot, qapp, text)
    metrics = QFontMetrics(label._caption.font())
    width, height = axis_label_outer_size(text, metrics)
    assert (width, height) == geom.canvas_rect[2:]
    assert label.size().width() == width
    assert label.size().height() == height
    assert label.rect() == QRect(0, 0, width, height)
    idle_hit = label.hit_rect()
    assert idle_hit.width() < width
    assert idle_hit.height() < height
    assert label.rect().contains(idle_hit)
    pip = label.pip_rect()
    assert idle_hit.contains(pip.toRect())
    assert label.rect().contains(pip.toRect())

    label.set_panel_open(True)
    label.set_highlighted(True)
    qapp.processEvents()
    assert label.hit_rect() == label.rect()
    assert label.size().width() == width
    image = _render_axis_label(label)
    ink = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 24
    ]
    assert ink
    assert min(x for x, _y in ink) >= 0
    assert max(x for x, _y in ink) <= width - 1
    assert min(y for _x, y in ink) >= 0
    assert max(y for _x, y in ink) <= height - 1
    assert min(x for x, _y in ink) <= 1
    assert max(x for x, _y in ink) >= width - 2


def test_axis_label_grayscale_hollow_solid_and_fill_remain_distinct(
    qapp, qtbot, production_style,
):
    collapsed, _geom = _standalone_axis_label(qtbot, qapp, "P12")
    opened, _opened_geom = _standalone_axis_label(qtbot, qapp, "P12")
    active, _active_geom = _standalone_axis_label(qtbot, qapp, "P12")
    opened.set_panel_open(True)
    active.set_panel_open(True)
    active.set_highlighted(True)
    qapp.processEvents()

    collapsed_img = _render_axis_label(collapsed).convertToFormat(QImage.Format_Grayscale8)
    opened_img = _render_axis_label(opened).convertToFormat(QImage.Format_Grayscale8)
    active_img = _render_axis_label(active).convertToFormat(QImage.Format_Grayscale8)
    collapsed_pip = _mean_luma(collapsed_img, collapsed.pip_rect().adjusted(2, 2, -2, -2))
    opened_pip = _mean_luma(opened_img, opened.pip_rect().adjusted(2, 2, -2, -2))
    collapsed_fill = _sample_label_fill(collapsed_img, collapsed)
    opened_fill = _sample_label_fill(opened_img, opened)
    active_fill = _sample_label_fill(active_img, active)
    collapsed_fill = (
        0.299 * collapsed_fill.red()
        + 0.587 * collapsed_fill.green()
        + 0.114 * collapsed_fill.blue()
    )
    opened_fill = (
        0.299 * opened_fill.red()
        + 0.587 * opened_fill.green()
        + 0.114 * opened_fill.blue()
    )
    active_fill = (
        0.299 * active_fill.red()
        + 0.587 * active_fill.green()
        + 0.114 * active_fill.blue()
    )
    assert collapsed_pip > opened_pip + 18
    assert opened_fill < collapsed_fill - 6
    assert active_fill < opened_fill - 25


def test_dual_endpoint_highlight_keeps_ab_line_colors(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_time(canvas)
    qapp.processEvents()
    _wait_host(qtbot, canvas)
    record = _pin(cs, canvas, [(0.32, 0.68)], mode="dual")[0]
    overlay = canvas._pinned_overlay
    a_line = overlay.lines_for(record.record_id, "a")[0]
    b_line = overlay.lines_for(record.record_id, "b")[0]
    a_idle = a_line.pen() if callable(a_line.pen) else a_line.pen
    a_idle = a_idle.color() if hasattr(a_idle, "color") else a_idle
    b_idle = b_line.pen() if callable(b_line.pen) else b_line.pen
    b_idle = b_idle.color() if hasattr(b_idle, "color") else b_idle
    cs._pinned_cursors._projector.set_hover(canvas, record.record_id)
    qapp.processEvents()
    a_hot = a_line.pen() if callable(a_line.pen) else a_line.pen
    a_hot = a_hot.color() if hasattr(a_hot, "color") else a_hot
    b_hot = b_line.pen() if callable(b_line.pen) else b_line.pen
    b_hot = b_hot.color() if hasattr(b_hot, "color") else b_hot
    assert a_idle.red() == a_hot.red()
    assert a_idle.green() == a_hot.green()
    assert a_idle.blue() == a_hot.blue()
    assert b_idle.red() == b_hot.red()
    assert b_idle.green() == b_hot.green()
    assert b_idle.blue() == b_hot.blue()
    assert a_hot.blue() > a_hot.red()
    assert b_hot.red() > b_hot.blue()
    assert a_hot.alpha() > a_idle.alpha()
    assert b_hot.alpha() > b_idle.alpha()
