"""Unit tests for :class:`AnalysisContext` (package E, D-E1).

These expectations were first measured against the live ``MainWindow`` (see the
commit that introduced this file) and are unchanged here -- only the object
under test changed.  That is the payoff of the extraction: the cross-section
analysis logic now has real constructor arguments, so it can be exercised with
a handful of fakes instead of a whole Qt main window.

**This module must never import MainWindow.**  ``test_analysis_context_needs_
no_main_window`` enforces it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer import db_reference
from mf4_analyzer.ui.db_reference_settings import DbReferenceCatalogSnapshot
from mf4_analyzer.ui.main_window.analysis_context import AnalysisContext


# -- fakes -------------------------------------------------------------------

class _Editor:
    def __init__(self, value=1.0):
        self._value = value

    def value(self):
        return self._value


class _DbReferenceControl:
    def __init__(self, mode="auto", manual_value=1.0):
        self._mode = mode
        self.editor = _Editor(manual_value)

    def mode(self):
        return self._mode


class _SectionCtx:
    def __init__(self, name):
        self.name = name
        self.db_reference_control = _DbReferenceControl()


class _Inspector:
    def __init__(self):
        self.fft_ctx = _SectionCtx("fft")
        self.fft_time_ctx = _SectionCtx("fft_time")
        self.frf_ctx = _SectionCtx("frf")
        self.order_ctx = _SectionCtx("order")


class _Page:
    def __init__(self, name, focused=0):
        self.name = name
        self._focused = focused

    def focused_index(self):
        return self._focused


class _ChartStack:
    def __init__(self):
        self.page_fft = _Page("fft")
        self.page_fft_time = _Page("fft_time")
        self.page_frf = _Page("frf")
        self.page_order = _Page("order")


class _Pane:
    def __init__(self, time_range=None):
        self.time_range = time_range


class _ViewState:
    def __init__(self, panes):
        self.panes = panes


class _Manager:
    def __init__(self, panes):
        self.active = 0
        self._state = _ViewState(panes)

    def get(self, _idx):
        return self._state


class _Store:
    def __init__(self, prefer_channel_metadata=True):
        self._prefer = prefer_channel_metadata

    def snapshot(self):
        return DbReferenceCatalogSnapshot(
            system_catalog=db_reference.FACTORY_CATALOG_V1,
            user_catalog=(),
            prefer_channel_metadata=self._prefer,
            revision=1,
        )


class _FileData:
    def __init__(self, channel_metadata=None, channel_units=None, audio=False):
        self.channel_metadata = channel_metadata or {}
        self.channel_units = channel_units or {}
        self._audio = audio

    def is_audio_source(self):
        return self._audio


@pytest.fixture
def files():
    return {}


@pytest.fixture
def inspector():
    return _Inspector()


@pytest.fixture
def chart_stack():
    return _ChartStack()


@pytest.fixture
def managers():
    return {
        "fft": _Manager([_Pane(), _Pane()]),
        "fft_time": _Manager([_Pane()]),
        "frf": _Manager([_Pane()]),
        "order": _Manager([_Pane()]),
    }


@pytest.fixture
def ctx(inspector, chart_stack, managers, files):
    return AnalysisContext(
        inspector=inspector,
        chart_stack=chart_stack,
        analysis_managers=managers,
        db_reference_store=_Store(),
        files_provider=lambda: files,
    )


# -- the extraction's own premise -------------------------------------------

def test_analysis_context_needs_no_main_window():
    """No import of the window -- prose in docstrings may still name it."""
    imports = [
        line.strip()
        for line in Path(__file__).read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    ]

    assert not [line for line in imports if "MainWindow" in line]
    assert not [line for line in imports if "main_window.window" in line]
    assert not [line for line in imports if line.endswith("import main_window")]


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
def test_normalize_time_range(value, expected):
    assert AnalysisContext.normalize_time_range(value) == expected


@pytest.mark.parametrize(
    "section, uses",
    [
        ("fft", True),
        ("fft_time", True),
        ("frf", True),
        ("order", True),
        ("time", False),
    ],
)
def test_section_uses_time_range(section, uses):
    assert AnalysisContext.section_uses_time_range(section) is uses


def test_frf_section_routes_to_its_context_and_page(ctx, inspector, chart_stack):
    assert ctx.section_ctx("frf") is inspector.frf_ctx
    assert ctx.page("frf") is chart_stack.page_frf


# -- masking -----------------------------------------------------------------

def test_mask_time_range_is_inclusive_on_both_ends(ctx):
    t = np.arange(6, dtype=float)          # 0..5
    sig = t * 10.0

    mt, msig = ctx.mask_time_range(t, sig, time_range=(1.0, 4.0))

    assert mt.tolist() == [1.0, 2.0, 3.0, 4.0]
    assert msig.tolist() == [10.0, 20.0, 30.0, 40.0]


def test_mask_time_range_passes_arrays_through_when_range_is_invalid(ctx):
    t = np.arange(4, dtype=float)
    sig = t.copy()

    # An inverted range normalises to None -> no masking at all.
    mt, msig = ctx.mask_time_range(t, sig, time_range=(3.0, 1.0))

    assert mt is t and msig is sig


def test_mask_time_range_masks_every_extra_array_alike(ctx):
    t = np.arange(5, dtype=float)
    a, b = t * 2.0, t * 3.0

    mt, ma, mb = ctx.mask_time_range(t, a, b, time_range=(2.0, 3.0))

    assert mt.tolist() == [2.0, 3.0]
    assert ma.tolist() == [4.0, 6.0]
    assert mb.tolist() == [6.0, 9.0]


def test_mask_time_range_tolerates_absent_time_base(ctx):
    assert ctx.mask_time_range(None, time_range=(0.0, 1.0)) == (None,)


def test_mask_time_range_can_select_nothing(ctx):
    t = np.arange(3, dtype=float)

    mt, = ctx.mask_time_range(t, time_range=(10.0, 20.0))

    assert mt.size == 0


# -- section routing ---------------------------------------------------------

def test_page_routes_each_section(ctx, chart_stack):
    assert ctx.page("fft") is chart_stack.page_fft
    assert ctx.page("fft_time") is chart_stack.page_fft_time
    assert ctx.page("order") is chart_stack.page_order


def test_section_ctx_routes_each_section(ctx, inspector):
    assert ctx.section_ctx("fft") is inspector.fft_ctx
    assert ctx.section_ctx("fft_time") is inspector.fft_time_ctx
    assert ctx.section_ctx("order") is inspector.order_ctx


def test_unknown_section_raises(ctx):
    with pytest.raises(KeyError):
        ctx.page("nope")


# -- pane time range ---------------------------------------------------------

def test_pane_time_range_is_none_for_a_section_without_time_ranges(ctx):
    assert ctx.pane_time_range_for("time") is None


def test_pane_time_range_reads_the_requested_pane(ctx, managers):
    managers["fft"].get(0).panes[0].time_range = (1.0, 5.0)

    assert ctx.pane_time_range_for("fft", 0) == (1.0, 5.0)


def test_pane_time_range_normalises_a_stored_bad_span(ctx, managers):
    managers["fft"].get(0).panes[0].time_range = (5.0, 1.0)

    assert ctx.pane_time_range_for("fft", 0) is None


def test_pane_time_range_rejects_an_out_of_range_pane_index(ctx):
    assert ctx.pane_time_range_for("fft", 99) is None


def test_pane_time_range_defaults_to_the_focused_pane(ctx, managers, chart_stack):
    managers["fft"].get(0).panes[0].time_range = (1.0, 2.0)
    managers["fft"].get(0).panes[1].time_range = (7.0, 9.0)
    chart_stack.page_fft._focused = 1

    assert ctx.pane_time_range_for("fft") == (7.0, 9.0)


# -- channel reference facts -------------------------------------------------

def test_channel_reference_facts_are_empty_for_an_unknown_file(ctx):
    facts = ctx.channel_reference_facts("missing", "torque")

    assert (facts.quantity, facts.unit) == ("", "")


def test_channel_reference_facts_read_metadata_first(ctx, files):
    files["f1"] = _FileData(
        channel_metadata={"torque": {"unit": "Nm", "quantity": "torque"}},
        channel_units={"torque": "ignored"},
    )

    facts = ctx.channel_reference_facts("f1", "torque")

    assert (facts.quantity, facts.unit) == ("torque", "Nm")


def test_channel_reference_facts_fall_back_to_channel_units(ctx, files):
    files["f1"] = _FileData(channel_units={"speed": "rpm"})

    assert ctx.channel_reference_facts("f1", "speed").unit == "rpm"


def test_channel_reference_facts_decode_toolchain_safe_units(ctx, files):
    """``U_`` prefix and ``Y`` for ``/`` are identifier-safe encodings."""
    files["f1"] = _FileData(channel_units={"rate": "U_degYsec"})

    assert ctx.channel_reference_facts("f1", "rate").unit == "deg/sec"


def test_channel_reference_facts_carry_the_audio_flag(ctx, files):
    files["f1"] = _FileData(channel_units={"mic": "Pa"}, audio=True)

    assert ctx.channel_reference_facts("f1", "mic").is_audio_source is True


def test_channel_reference_facts_survive_a_raising_audio_probe(ctx, files):
    class _Boom(_FileData):
        def is_audio_source(self):
            raise RuntimeError("nope")

    files["f1"] = _Boom(channel_units={"mic": "Pa"})

    assert ctx.channel_reference_facts("f1", "mic").is_audio_source is False


def test_channel_reference_facts_tolerate_a_missing_channel(ctx, files):
    files["f1"] = _FileData()

    facts = ctx.channel_reference_facts("f1", None)

    assert (facts.quantity, facts.unit) == ("", "")


def test_channel_reference_facts_follow_a_rebound_files_mapping(
    inspector, chart_stack, managers,
):
    """The provider indirection exists because ``files`` gets rebound."""
    files = {"f1": _FileData(channel_units={"speed": "rpm"})}
    holder = {"files": files}
    ctx = AnalysisContext(
        inspector=inspector,
        chart_stack=chart_stack,
        analysis_managers=managers,
        db_reference_store=_Store(),
        files_provider=lambda: holder["files"],
    )
    assert ctx.channel_reference_facts("f1", "speed").unit == "rpm"

    holder["files"] = {}

    assert ctx.channel_reference_facts("f1", "speed").unit == ""


# -- dB reference resolution -------------------------------------------------

def test_resolve_db_reference_honours_manual_mode(ctx, inspector):
    control = inspector.fft_ctx.db_reference_control
    control._mode = "manual"
    control.editor._value = 4.0

    resolution = ctx.resolve_db_reference_for_source("fft", None)

    assert resolution.value == pytest.approx(4.0)
    assert resolution.source == "manual"


def test_resolve_db_reference_without_a_source_falls_back_to_generic(ctx):
    resolution = ctx.resolve_db_reference_for_source("fft", None)

    assert resolution.source in ("generic", "fallback")
    assert resolution.value == pytest.approx(1.0)


def test_resolve_db_reference_auto_uses_channel_metadata(ctx, files):
    files["f1"] = _FileData(
        channel_metadata={"mic": {"unit": "Pa", "db_reference": 2e-5}},
    )

    resolution = ctx.resolve_db_reference_for_source("fft", ("f1", "mic"))

    assert resolution.value == pytest.approx(2e-5)
    assert resolution.source == "metadata"


def test_resolve_db_reference_ignores_metadata_when_the_store_says_so(
    inspector, chart_stack, managers,
):
    files = {
        "f1": _FileData(
            channel_metadata={"mic": {"unit": "Pa", "db_reference": 2e-5}},
        )
    }
    ctx = AnalysisContext(
        inspector=inspector,
        chart_stack=chart_stack,
        analysis_managers=managers,
        db_reference_store=_Store(prefer_channel_metadata=False),
        files_provider=lambda: files,
    )

    resolution = ctx.resolve_db_reference_for_source("fft", ("f1", "mic"))

    assert resolution.source != "metadata"


def test_resolve_db_reference_resolves_per_section_control(ctx, inspector):
    inspector.order_ctx.db_reference_control._mode = "manual"
    inspector.order_ctx.db_reference_control.editor._value = 9.0

    assert ctx.resolve_db_reference_for_source("order", None).value == pytest.approx(9.0)
    # fft's own control is untouched and still resolves through Auto.
    assert ctx.resolve_db_reference_for_source("fft", None).source != "manual"
