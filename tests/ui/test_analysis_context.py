"""Behaviour of the cross-section analysis helpers (package E, D-E1).

Step 1 of the ``AnalysisContext`` extraction: these expectations are measured
against the live ``MainWindow`` so the extraction has a behavioural baseline to
preserve.  Once the helpers move onto ``AnalysisContext`` this module is
rewritten to construct that object directly, with fake collaborators and no
``MainWindow`` anywhere -- which is the whole point of the extraction.

Covered: time-range normalisation and masking boundaries, section->page and
section->inspector-context routing, pane time-range lookup, channel reference
facts, and the dB-reference resolution fallback chain.
"""

from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.ui.main_window import MainWindow


@pytest.fixture
def win(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


# -- time-range normalisation ------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ((), None),
        ((1.0, 2.0), (1.0, 2.0)),
        (["1.5", "3.5"], (1.5, 3.5)),
        ((2.0, 2.0), None),          # empty span collapses
        ((3.0, 1.0), None),          # inverted span rejected
        ((float("nan"), 1.0), None),
        ((0.0, float("inf")), None),
        (("a", "b"), None),          # unparseable
        ((1.0,), None),              # too short
    ],
)
def test_normalize_time_range(win, value, expected):
    assert win._normalize_analysis_time_range(value) == expected


@pytest.mark.parametrize(
    "section, uses",
    [("fft", True), ("fft_time", True), ("order", True), ("time", False)],
)
def test_section_uses_time_range(win, section, uses):
    assert win._analysis_section_uses_time_range(section) is uses


# -- masking -----------------------------------------------------------------

def test_mask_time_range_is_inclusive_on_both_ends(win):
    t = np.arange(6, dtype=float)          # 0..5
    sig = t * 10.0

    mt, msig = win._mask_time_range(t, sig, time_range=(1.0, 4.0))

    assert mt.tolist() == [1.0, 2.0, 3.0, 4.0]
    assert msig.tolist() == [10.0, 20.0, 30.0, 40.0]


def test_mask_time_range_passes_arrays_through_when_range_is_invalid(win):
    t = np.arange(4, dtype=float)
    sig = t.copy()

    # An inverted range normalises to None -> no masking at all.
    mt, msig = win._mask_time_range(t, sig, time_range=(3.0, 1.0))

    assert mt is t and msig is sig


def test_mask_time_range_masks_every_extra_array_alike(win):
    t = np.arange(5, dtype=float)
    a, b = t * 2.0, t * 3.0

    mt, ma, mb = win._mask_time_range(t, a, b, time_range=(2.0, 3.0))

    assert mt.tolist() == [2.0, 3.0]
    assert ma.tolist() == [4.0, 6.0]
    assert mb.tolist() == [6.0, 9.0]


def test_mask_time_range_tolerates_absent_time_base(win):
    assert win._mask_time_range(None, time_range=(0.0, 1.0)) == (None,)


def test_mask_time_range_can_select_nothing(win):
    t = np.arange(3, dtype=float)

    mt, = win._mask_time_range(t, time_range=(10.0, 20.0))

    assert mt.size == 0


# -- section routing ---------------------------------------------------------

def test_analysis_page_routes_each_section(win):
    assert win._analysis_page("fft") is win.chart_stack.page_fft
    assert win._analysis_page("fft_time") is win.chart_stack.page_fft_time
    assert win._analysis_page("order") is win.chart_stack.page_order


def test_analysis_ctx_routes_each_section(win):
    assert win._analysis_ctx("fft") is win.inspector.fft_ctx
    assert win._analysis_ctx("fft_time") is win.inspector.fft_time_ctx
    assert win._analysis_ctx("order") is win.inspector.order_ctx


def test_unknown_section_raises(win):
    with pytest.raises(KeyError):
        win._analysis_page("nope")


# -- pane time range ---------------------------------------------------------

def test_pane_time_range_is_none_for_a_section_without_time_ranges(win):
    assert win._pane_time_range_for("time") is None


def test_pane_time_range_reads_the_requested_pane(win):
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].time_range = (1.0, 5.0)

    assert win._pane_time_range_for("fft", 0) == (1.0, 5.0)


def test_pane_time_range_normalises_a_stored_bad_span(win):
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].time_range = (5.0, 1.0)

    assert win._pane_time_range_for("fft", 0) is None


def test_pane_time_range_rejects_an_out_of_range_pane_index(win):
    assert win._pane_time_range_for("fft", 99) is None


# -- channel reference facts -------------------------------------------------

class _FileData:
    def __init__(self, channel_metadata=None, channel_units=None, audio=False):
        self.channel_metadata = channel_metadata or {}
        self.channel_units = channel_units or {}
        self._audio = audio

    def is_audio_source(self):
        return self._audio


def test_channel_reference_facts_are_empty_for_an_unknown_file(win):
    facts = win._channel_reference_facts("missing", "torque")

    assert (facts.quantity, facts.unit) == ("", "")


def test_channel_reference_facts_read_metadata_first(win):
    win.files["f1"] = _FileData(
        channel_metadata={"torque": {"unit": "Nm", "quantity": "torque"}},
        channel_units={"torque": "ignored"},
    )

    facts = win._channel_reference_facts("f1", "torque")

    assert (facts.quantity, facts.unit) == ("torque", "Nm")


def test_channel_reference_facts_fall_back_to_channel_units(win):
    win.files["f1"] = _FileData(channel_units={"speed": "rpm"})

    facts = win._channel_reference_facts("f1", "speed")

    assert facts.unit == "rpm"


def test_channel_reference_facts_decode_toolchain_safe_units(win):
    """``U_`` prefix and ``Y`` for ``/`` are identifier-safe encodings."""
    win.files["f1"] = _FileData(channel_units={"rate": "U_degYsec"})

    assert win._channel_reference_facts("f1", "rate").unit == "deg/sec"


def test_channel_reference_facts_carry_the_audio_flag(win):
    win.files["f1"] = _FileData(channel_units={"mic": "Pa"}, audio=True)

    assert win._channel_reference_facts("f1", "mic").is_audio_source is True


def test_channel_reference_facts_survive_a_raising_audio_probe(win):
    class _Boom(_FileData):
        def is_audio_source(self):
            raise RuntimeError("nope")

    win.files["f1"] = _Boom(channel_units={"mic": "Pa"})

    assert win._channel_reference_facts("f1", "mic").is_audio_source is False


def test_channel_reference_facts_tolerate_a_missing_channel(win):
    win.files["f1"] = _FileData()

    facts = win._channel_reference_facts("f1", None)

    assert (facts.quantity, facts.unit) == ("", "")


# -- dB reference resolution -------------------------------------------------

def test_resolve_db_reference_honours_manual_mode(win):
    ctrl = win.inspector.fft_ctx.db_reference_control
    ctrl.set_mode("manual")
    ctrl.editor.setValue(4.0)

    resolution = win._resolve_db_reference_for_source("fft", None)

    assert resolution.value == pytest.approx(4.0)
    assert resolution.source == "manual"


def test_resolve_db_reference_without_a_source_falls_back_to_generic(win):
    win.inspector.fft_ctx.db_reference_control.set_mode("auto")

    resolution = win._resolve_db_reference_for_source("fft", None)

    assert resolution.source in ("generic", "fallback")
    assert resolution.value == pytest.approx(1.0)


def test_resolve_db_reference_auto_uses_channel_metadata(win):
    win.files["f1"] = _FileData(
        channel_metadata={"mic": {"unit": "Pa", "db_reference": 2e-5}},
    )
    win.inspector.fft_ctx.db_reference_control.set_mode("auto")

    resolution = win._resolve_db_reference_for_source("fft", ("f1", "mic"))

    assert resolution.value == pytest.approx(2e-5)
    assert resolution.source == "metadata"
