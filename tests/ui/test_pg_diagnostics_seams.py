"""Failure-injection tests for low-frequency pg-canvas diagnostic seams."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np

from mf4_analyzer import diagnostics
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG


def _messages(caplog):
    return [record.getMessage() for record in caplog.records]


def setup_function():
    diagnostics._THROTTLE_STATE.clear()


def test_get_visible_ylims_logs_key_and_continues(caplog):
    class _BadHandle:
        def get_ylim(self):
            raise RuntimeError("bad getter")

    class _GoodHandle:
        def get_ylim(self):
            return (1.0, 2.0)

    canvas = SimpleNamespace(
        _channel_view_state_lines={
            "file-A::broken": (_BadHandle(), None),
            "file-B::good": (_GoodHandle(), None),
        }
    )

    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        result = TimeDomainCanvasPG.get_visible_ylims(canvas)

    assert result == {"file-B::good": (1.0, 2.0)}
    assert any("file-A::broken" in message for message in _messages(caplog))


def test_restore_visible_ylims_logs_key_and_continues(caplog):
    calls = []

    class _BadHandle:
        def set_ylim(self, *_args):
            raise RuntimeError("bad setter")

    class _GoodHandle:
        def set_ylim(self, *ylim):
            calls.append(("good-set", ylim))

    canvas = SimpleNamespace(
        _channel_view_state_lines={
            "file-A::broken": (_BadHandle(), None),
            "file-B::good": (_GoodHandle(), None),
        },
        _channel_lines={},
        _fit_channel_y_to_visible_x=lambda *args, **kwargs: False,
        _tick_density_controller=SimpleNamespace(density=(10, 10)),
        _overlay_mode=False,
        _dense_raster=SimpleNamespace(
            schedule_rebuild=lambda *args, **kwargs: calls.append("scheduled")
        ),
        visible_range_changed=SimpleNamespace(emit=lambda: calls.append("emitted")),
        _INTERACTION_SETTLE_MS=40,
    )

    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        TimeDomainCanvasPG.restore_visible_ylims(
            canvas,
            {
                "file-A::broken": (-1.0, 1.0),
                "file-B::good": (10.0, 20.0),
            },
        )

    assert ("good-set", (10.0, 20.0)) in calls
    assert "scheduled" in calls and "emitted" in calls
    assert any("file-A::broken" in message for message in _messages(caplog))


class _ChannelData:
    def __init__(self, key, row):
        self.key = key
        self.row = row

    def get(self, key):
        return self.row if key == self.key else None

    def resolve_unique(self, key):
        return key if key == self.key else None


def _fit_canvas(key, row):
    return SimpleNamespace(channel_data=_ChannelData(key, row))


def test_fit_channel_logs_key_when_get_xlim_fails(caplog):
    key = "file-A::speed"

    class _Handle:
        def get_xlim(self):
            raise RuntimeError("no x range")

    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        result = TimeDomainCanvasPG._fit_channel_y_to_visible_x(
            _fit_canvas(key, ([0.0, 1.0], [1.0, 2.0])),
            key,
            _Handle(),
            10,
            frame_to_nice=False,
        )

    assert result is False
    assert any(key in message for message in _messages(caplog))


def test_fit_channel_logs_key_when_array_coercion_fails(caplog):
    key = "file-A::torque"

    class _BadArray:
        def __array__(self, *args, **kwargs):
            raise TypeError("cannot coerce")

    handle = SimpleNamespace(get_xlim=lambda: (0.0, 1.0))
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        result = TimeDomainCanvasPG._fit_channel_y_to_visible_x(
            _fit_canvas(key, (_BadArray(), [1.0, 2.0])),
            key,
            handle,
            10,
            frame_to_nice=False,
        )

    assert result is False
    assert any(key in message for message in _messages(caplog))


def test_fit_channel_logs_key_when_set_ylim_fails(caplog):
    key = "file-B::pressure"

    class _Handle:
        def get_xlim(self):
            return (0.0, 1.0)

        def set_ylim(self, *_args):
            raise RuntimeError("cannot apply y range")

    row = (np.array([0.0, 1.0]), np.array([2.0, 3.0]))
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        result = TimeDomainCanvasPG._fit_channel_y_to_visible_x(
            _fit_canvas(key, row),
            key,
            _Handle(),
            10,
            frame_to_nice=False,
        )

    assert result is False
    assert any(key in message for message in _messages(caplog))


def test_fit_channel_resolves_legacy_label_before_single_data_lookup():
    composite_key = "file-A::speed"
    lookups = []

    class _AliasedChannelData:
        def resolve_unique(self, key):
            return composite_key if key == "speed" else None

        def get(self, key):
            lookups.append(key)
            if key == composite_key:
                return (np.array([0.0, 1.0]), np.array([2.0, 4.0]))
            return None

    applied = []
    handle = SimpleNamespace(
        get_xlim=lambda: (0.0, 1.0),
        set_ylim=lambda lo, hi: applied.append((lo, hi)),
    )

    result = TimeDomainCanvasPG._fit_channel_y_to_visible_x(
        SimpleNamespace(channel_data=_AliasedChannelData()),
        "speed",
        handle,
        10,
        frame_to_nice=False,
    )

    assert result is True
    assert lookups == [composite_key]
    assert applied


def test_sync_x_axis_logs_handle_when_axis_lookup_fails(caplog):
    class _Handle:
        def x_axis_item(self):
            raise RuntimeError("axis missing")

    handle = _Handle()
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        result = TimeDomainCanvasPG._sync_x_axis_item_range(
            SimpleNamespace(), handle, 1.0, 2.0
        )

    assert result is None
    assert any("_Handle@0x" in message for message in _messages(caplog))


def test_sync_x_axis_logs_axis_when_set_range_fails_and_returns(caplog):
    calls = []

    class _Axis:
        def setRange(self, *_args):
            raise RuntimeError("range rejected")

        def update(self):
            calls.append("update")

    axis = _Axis()
    handle = SimpleNamespace(x_axis_item=lambda: axis)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        result = TimeDomainCanvasPG._sync_x_axis_item_range(
            SimpleNamespace(), handle, 1.0, 2.0
        )

    assert result is None
    assert calls == []
    assert any("_Axis@0x" in message for message in _messages(caplog))


def test_sync_x_axis_logs_axis_when_update_fails_after_range_applied(caplog):
    calls = []

    class _Axis:
        def setRange(self, lo, hi):
            calls.append((lo, hi))

        def update(self):
            raise RuntimeError("update rejected")

    axis = _Axis()
    handle = SimpleNamespace(x_axis_item=lambda: axis)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.ui.pg_canvas.canvas"):
        result = TimeDomainCanvasPG._sync_x_axis_item_range(
            SimpleNamespace(), handle, 1.0, 2.0
        )

    assert result is None
    assert calls == [(1.0, 2.0)]
    assert any("_Axis@0x" in message for message in _messages(caplog))
