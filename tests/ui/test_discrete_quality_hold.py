"""Discrete AA settles once, after a page-transition hold is released."""

import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


def _entry():
    freq = np.linspace(0, 500, 256)
    amp = np.exp(-((freq - 120) / 15.0) ** 2)
    time = np.linspace(0, 1.0, 1000)
    signal = np.sin(2 * np.pi * 12.0 * time)
    return {
        "label": "f1",
        "color": "#2563eb",
        "freq": freq,
        "amp": amp,
        "time": time,
        "signal": signal,
    }


def test_time_domain_hold_defers_discrete_settle_until_release(qapp):
    canvas = TimeDomainCanvasPG()
    try:
        token = object()
        canvas.hold_discrete_quality(token)
        canvas._quality.settle_after_discrete_render()
        assert canvas._quality.discrete_timer.isActive() is False
        assert canvas._quality.timer.interval() == 150
        assert canvas._quality._discrete_quality_deferred is True
        qapp.processEvents()
        assert canvas._quality.aa_on is False

        canvas.release_discrete_quality(token)
        assert canvas._quality.discrete_timer.isActive() is True
        canvas.release_discrete_quality(token)
        assert canvas._quality._discrete_quality_hold is None
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_line_canvas_hold_keeps_aa_off_until_release(qapp):
    canvas = PgLineCanvas()
    try:
        canvas.resize(640, 480)
        canvas.show()
        qapp.processEvents()
        token = object()
        canvas.hold_discrete_quality(token)
        canvas.plot_spectra(
            [_entry()], xlim=(0.0, 500.0), amp_label="Amplitude", title="FFT",
        )
        qapp.processEvents()
        assert canvas._aa_on is False
        assert canvas._discrete_aa_timer.isActive() is False
        assert canvas._aa_idle_timer.interval() == 150
        assert canvas._discrete_quality_deferred is True

        canvas.release_discrete_quality(token)
        assert canvas._discrete_aa_timer.isActive() is True
        qapp.processEvents()
        assert canvas._aa_on is True
        assert canvas._discrete_aa_timer.isActive() is False
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_redirect_keeps_only_the_latest_hold(qapp):
    canvas = PgLineCanvas()
    try:
        canvas.resize(640, 480)
        canvas.show()
        qapp.processEvents()
        first = object()
        second = object()
        canvas.hold_discrete_quality(first)
        canvas.plot_spectra(
            [_entry()], xlim=(0.0, 500.0), amp_label="Amplitude", title="FFT",
        )
        canvas.release_discrete_quality(first)
        canvas.hold_discrete_quality(second)
        qapp.processEvents()
        assert canvas._aa_on is False
        assert canvas._discrete_aa_timer.isActive() is False
        canvas.release_discrete_quality(second)
        assert canvas._discrete_aa_timer.isActive() is True
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_motion_off_still_arms_discrete_timer_immediately(qapp):
    canvas = PgLineCanvas()
    try:
        canvas.resize(640, 480)
        canvas.show()
        qapp.processEvents()
        canvas.plot_spectra(
            [_entry()], xlim=(0.0, 500.0), amp_label="Amplitude", title="FFT",
        )
        assert canvas._discrete_aa_timer.isActive() is True
        assert canvas._aa_on is False
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_chart_stack_hold_follows_transition_token(qapp):
    from mf4_analyzer.ui.chart_stack.stack import ChartStack

    stack = ChartStack()
    try:
        calls = []

        class _Canvas:
            def hold_discrete_quality(self, token):
                calls.append(("hold", token))

            def release_discrete_quality(self, token):
                calls.append(("release", token))

        fake = _Canvas()
        stack._transition_target_canvases = lambda section: (fake,)
        token = object()
        stack._hold_discrete_quality(token, "fft")
        assert calls == [("hold", token)]
        stack._release_discrete_quality_hold()
        assert calls == [("hold", token), ("release", token)]
        stack._release_discrete_quality_hold()
        assert calls == [("hold", token), ("release", token)]
    finally:
        stack.deleteLater()
        qapp.processEvents()
