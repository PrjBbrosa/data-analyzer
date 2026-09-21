"""PinSampleEvaluator canvas dispatch. Fake four-domain owner tests plus a cheap real-canvas smoke."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.chart_stack.pinning.sampling import (
    PIN_STATUS_INCOMPATIBLE_AXIS,
    PIN_STATUS_READY,
    PIN_STATUS_UNAVAILABLE,
    PinSampleEvaluator,
)
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayChannel,
    FrequencyCursorChannel,
    FrfCursorPoint,
    FrfCursorSample,
    PinnedCursorSample,
)
from mf4_analyzer.ui.pinned_cursor_state import empty_collection, next_record


def _channel(fid="f0", name="torque", value=1.5):
    return CursorDisplayChannel(
        identity=(fid, name),
        source_label="src",
        channel_label=name,
        current_value=value,
    )


def _freq_channel(fid="f1", name="vib", **values):
    return FrequencyCursorChannel(
        identity=(fid, name),
        source_label="src",
        channel_label=name,
        **values,
    )


def _intent(domain="time", x=1.0, axis_identity=None):
    payload = {
        "mode": "single",
        "domain": domain,
        "x": x,
        "x_unit": "s" if domain == "time" else "Hz",
        "bindings": [{"fid": "f0", "channel": "torque"}],
        "presentation": "full",
    }
    if axis_identity is not None:
        payload["axis_identity"] = list(axis_identity)
        payload["domain"] = "channel"
        payload["x_unit"] = "mm"
    _collection, intent = next_record(empty_collection(), payload)
    return intent


class _FakeLines:
    def __init__(self, items):
        self._items = items

    def composite_items(self):
        return self._items


class FakeTimeCanvas:
    def __init__(self):
        self._interaction_generation = 3
        self._cursor_data_revision = 7
        self._channel_lines = _FakeLines((
            (("f0", "torque"), "torque", None),
        ))
        self._cursor = SimpleNamespace(
            _hidden_channel_names=lambda: (("f0", "hidden"),),
        )

    def evaluate_single_cursor_sample(self, x):
        return PinnedCursorSample(
            domain="time", mode="single", x=x, channels=(_channel(value=2.0),),
        )

    def evaluate_dual_cursor_sample(self, ax, bx):
        return PinnedCursorSample(
            domain="time", mode="dual", ax=ax, bx=bx,
            channels=(_channel(value=None),),
        )


class FakeChannelCanvas:
    def __init__(self):
        self._cursor = SimpleNamespace(
            x_axis_context=SimpleNamespace(identity=("f0", "steer"), unit="mm"),
        )

    def evaluate_single_cursor_sample(self, x):
        return PinnedCursorSample(
            domain="channel", mode="single", x=x, channels=(_channel(name="force"),),
        )


class FakeFrequencyCanvas:
    def __init__(self):
        self._spectrum_display_generation = 11
        self._spectrum_display_revision = 13
        self._interaction_generation = 1
        self._cursor_data_revision = 2
        self._is_log_frequency = lambda: False
        self._entries = [{"fid": "f1", "channel": "vib"}]

    def evaluate_frequency_cursor_sample(self, x):
        return PinnedCursorSample(
            domain="frequency", mode="single", x=x,
            channels=(_freq_channel(value=x),),
        )

    def evaluate_dual_frequency_cursor_sample(self, ax, bx):
        return PinnedCursorSample(
            domain="frequency", mode="dual", ax=ax, bx=bx,
            channels=(_freq_channel(a_value=ax, b_value=bx, delta_ab=bx - ax),),
        )


class FakeFrfCanvas:
    def evaluate_frequency_cursor_sample(self, x):
        return PinnedCursorSample(
            domain="frf",
            mode="single",
            x=x,
            frf_sample=FrfCursorSample(frequency_hz=x, magnitude=0.5),
        )

    def evaluate_dual_frequency_cursor_sample(self, ax, bx):
        return PinnedCursorSample(
            domain="frf",
            mode="dual",
            ax=ax,
            bx=bx,
            frf_sample=FrfCursorSample(
                a=FrfCursorPoint(frequency_hz=ax),
                b=FrfCursorPoint(frequency_hz=bx),
            ),
        )


class LegacyTimeCanvas:
    def evaluate_single_cursor(self, x):
        return (_channel(value=x),)

    def evaluate_dual_cursor(self, ax, bx):
        return (_channel(value=ax),)


class LegacyFrequencyCanvas:
    def evaluate_frequency_cursor(self, x):
        return (x, (_freq_channel(fid="f1", name="amp", value=x),))

    def evaluate_dual_frequency_cursor(self, ax, bx):
        return (ax, bx, (_freq_channel(fid="f1", name="amp", a_value=ax, b_value=bx),))


class LegacyFrfCanvas:
    def evaluate_frequency_cursor(self, x):
        return FrfCursorSample(frequency_hz=x, magnitude=1.0)

    def evaluate_dual_frequency_cursor(self, ax, bx):
        return FrfCursorSample(
            a=FrfCursorPoint(frequency_hz=ax),
            b=FrfCursorPoint(frequency_hz=bx),
        )


def test_fake_four_domain_single_and_dual_dispatch():
    ev = PinSampleEvaluator()
    time_sample = ev.evaluate(FakeTimeCanvas(), "time", mode="single", x=0.5)
    assert time_sample.domain == "time"
    assert time_sample.x == 0.5
    assert time_sample.channels[0].current_value == 2.0
    dual_time = ev.evaluate(FakeTimeCanvas(), "time", mode="dual", ax=0.1, bx=0.2)
    assert dual_time.mode == "dual"
    assert dual_time.ax == 0.1 and dual_time.bx == 0.2

    channel = ev.evaluate(FakeChannelCanvas(), "channel", mode="single", x=4.0)
    assert channel.domain == "channel"
    assert channel.channels[0].channel_label == "force"

    freq = ev.evaluate(FakeFrequencyCanvas(), "frequency", mode="single", x=40.0)
    assert freq.domain == "frequency"
    assert isinstance(freq.channels[0], FrequencyCursorChannel)
    assert freq.channels[0].value == 40.0
    dual_freq = ev.evaluate(
        FakeFrequencyCanvas(), "frequency", mode="dual", ax=10.0, bx=20.0,
    )
    assert dual_freq.ax == 10.0 and dual_freq.bx == 20.0
    assert isinstance(dual_freq.channels[0], FrequencyCursorChannel)
    assert dual_freq.channels[0].a_value == 10.0
    assert dual_freq.channels[0].b_value == 20.0

    frf = ev.evaluate(FakeFrfCanvas(), "frf", mode="single", x=12.0)
    assert frf.domain == "frf"
    assert frf.frf_sample.frequency_hz == 12.0
    assert ev.sample_has_result(frf)
    dual_frf = ev.evaluate(FakeFrfCanvas(), "frf", mode="dual", ax=1.0, bx=2.0)
    assert dual_frf.frf_sample.a.frequency_hz == 1.0


def test_legacy_wrap_paths_and_sample_fn_cursor_fallback():
    ev = PinSampleEvaluator()
    wrapped = ev.evaluate(LegacyTimeCanvas(), "time", mode="single", x=3.0)
    assert wrapped.domain == "time"
    assert wrapped.channels[0].current_value == 3.0
    dual = ev.evaluate(LegacyTimeCanvas(), "time", mode="dual", ax=1.0, bx=2.0)
    assert dual.mode == "dual"

    freq = ev.evaluate(LegacyFrequencyCanvas(), "frequency", mode="single", x=8.0)
    assert freq.x == 8.0
    assert isinstance(freq.channels[0], FrequencyCursorChannel)
    assert freq.channels[0].value == 8.0
    assert freq.channels[0].channel_label == "amp"
    dual_freq = ev.evaluate(
        LegacyFrequencyCanvas(), "frequency", mode="dual", ax=1.0, bx=2.0,
    )
    assert dual_freq.ax == 1.0 and dual_freq.bx == 2.0

    frf = ev.evaluate(LegacyFrfCanvas(), "frf", mode="single", x=5.0)
    assert frf.frf_sample.frequency_hz == 5.0
    dual_frf = ev.evaluate(LegacyFrfCanvas(), "frf", mode="dual", ax=1.0, bx=9.0)
    assert dual_frf.ax == 1.0 and dual_frf.bx == 9.0

    host = SimpleNamespace(
        evaluate_single_cursor_sample=None,
        _cursor=SimpleNamespace(
            evaluate_single_cursor_sample=lambda x: PinnedCursorSample(
                domain="time", mode="single", x=x, channels=(_channel(),),
            ),
        ),
    )
    via_cursor = ev.evaluate(host, "time", mode="single", x=0.25)
    assert via_cursor.x == 0.25


def test_generations_stamp_and_late_result_match():
    ev = PinSampleEvaluator()
    canvas = FakeFrequencyCanvas()
    assert ev.canvas_generations(canvas) == (11, 13)
    time_canvas = FakeTimeCanvas()
    assert ev.canvas_generations(time_canvas) == (3, 7)
    sample = PinnedCursorSample(domain="time", mode="single", x=1.0)
    stamped = ev.stamp_sample(time_canvas, sample)
    assert stamped.binding_generation == 3
    assert stamped.data_revision == 7
    assert ev.sample_matches_generation(stamped, 3, 7) is True
    assert ev.sample_matches_generation(stamped, 4, 7) is False
    assert ev.sample_matches_generation(stamped, 3, 8) is False
    assert ev.sample_matches_generation(None, 3, 7) is False


def test_bound_and_hidden_identity_keys_read_canvas():
    ev = PinSampleEvaluator()
    time_keys = ev.bound_identity_keys(FakeTimeCanvas())
    assert ("f0", "torque") in time_keys
    hidden = ev.hidden_identity_keys(FakeTimeCanvas())
    assert ("f0", "hidden") in hidden
    freq_keys = ev.bound_identity_keys(FakeFrequencyCanvas())
    assert ("f1", "vib") in freq_keys

    named = SimpleNamespace(channel_data={"fid-a/speed": object()})
    # identity_key on a display string may be None; entries path is the owner.
    data_keys = ev.bound_identity_keys(named)
    assert isinstance(data_keys, set)


def test_axis_status_log_unavailable_and_pending():
    ev = PinSampleEvaluator()
    log_canvas = SimpleNamespace(_is_log_frequency=lambda: True)
    intent = _intent(domain="frequency", x=-1.0)
    assert ev.log_unavailable(log_canvas, intent) is True
    ev.axis_compatible = lambda canvas, item: True
    assert ev.axis_status(log_canvas, intent) == PIN_STATUS_UNAVAILABLE
    linear = SimpleNamespace(_is_log_frequency=lambda: False)
    assert ev.log_unavailable(linear, _intent(domain="frequency", x=10.0)) is False

    pending = SimpleNamespace(state=lambda: "progress")
    assert ev.canvas_compute_pending(pending) is True
    ready = SimpleNamespace(state=lambda: "ready")
    assert ev.canvas_compute_pending(ready) is False


def test_sample_has_result_and_bindings_and_units():
    ev = PinSampleEvaluator()
    empty = PinnedCursorSample(domain="time", mode="single", x=1.0)
    assert ev.sample_has_result(empty) is False
    with_channels = PinnedCursorSample(
        domain="time", mode="single", x=1.0, channels=(_channel(),),
    )
    assert ev.sample_has_result(with_channels) is True
    bindings = ev.bindings_from_sample(with_channels)
    assert bindings[0].fid == "f0"
    assert bindings[0].channel == "torque"
    assert ev.x_unit(None, "time") == "s"
    assert ev.x_unit(None, "frequency") == "Hz"
    channel_canvas = FakeChannelCanvas()
    assert ev.x_unit(channel_canvas, "channel") == "mm"
    assert ev.axis_identity(channel_canvas, "channel") == ("f0", "steer")


def test_axis_compatible_unknown_canvas_is_incompatible():
    ev = PinSampleEvaluator()
    fake = FakeTimeCanvas()
    time_intent = _intent(domain="time")
    # Fakes are not TimeDomainCanvasPG instances, so domain_for is None.
    assert ev.domain_for(fake) is None
    assert ev.axis_compatible(fake, time_intent) is False
    assert ev.axis_status(fake, time_intent) == PIN_STATUS_INCOMPATIBLE_AXIS
    # A matching declared current domain still uses the real isinstance path;
    # status_for_sample with no numeric facts is unavailable once compatible.
    sample = PinnedCursorSample(domain="time", mode="single", x=1.0)
    assert ev.status_for_sample(fake, time_intent, sample) == PIN_STATUS_INCOMPATIBLE_AXIS
    assert PIN_STATUS_READY == "ready"


def test_real_time_canvas_evaluate_parity(qapp):
    from tests.ui.test_custom_x_cursor_contract import _pg_canvas

    canvas = _pg_canvas(qapp)
    t = np.asarray([0.0, 0.5, 1.0], dtype=np.float64)
    y = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
    canvas.plot_channels(
        [("[source-a] speed", True, t, y, "#1769e0", "rpm", "fid-a")],
        mode="overlay",
    )
    QCoreApplication.processEvents()
    ev = PinSampleEvaluator()
    assert ev.domain_for(canvas) == "time"
    sample = ev.evaluate(canvas, "time", mode="single", x=0.5)
    direct_fn = PinSampleEvaluator.sample_fn(canvas, "evaluate_single_cursor_sample")
    direct = direct_fn(0.5)
    assert ev.sample_has_result(sample)
    assert sample.channels[0].current_value == direct.channels[0].current_value
    assert ev.axis_compatible(canvas, _intent(domain="time")) is True
    channel_intent = _intent(domain="channel", axis_identity=("f0", "steer"))
    assert ev.axis_compatible(canvas, channel_intent) is False
    stamped_intent = ev.evaluate_intent(canvas, _intent(domain="time", x=0.5))
    assert stamped_intent is not None
    assert ev.sample_has_result(stamped_intent)
    gen, rev = ev.canvas_generations(canvas)
    stamped = ev.stamp_sample(canvas, sample)
    assert ev.sample_matches_generation(stamped, gen, rev) is True


def test_frequency_wrap_keeps_numeric_and_status_channel_types():
    from mf4_analyzer.ui.pinned_cursor_facts import UNCHECKED_TEXT

    ev = PinSampleEvaluator()
    numeric = ev.wrap_channels(
        "frequency", "single", x=12.0, channels=(_freq_channel(value=3.0),),
    )
    assert isinstance(numeric.channels[0], FrequencyCursorChannel)
    assert numeric.channels[0].value == 3.0
    status_row = CursorDisplayChannel(
        identity=("f1", "vib"),
        source_label="",
        channel_label="vib",
        diagnostic=UNCHECKED_TEXT,
    )
    wrapped = ev.wrap_channels(
        "frequency", "single", x=12.0, channels=(status_row,),
    )
    assert isinstance(wrapped.channels[0], CursorDisplayChannel)
    assert wrapped.channels[0].diagnostic == UNCHECKED_TEXT
    assert not hasattr(wrapped.channels[0], "value")
