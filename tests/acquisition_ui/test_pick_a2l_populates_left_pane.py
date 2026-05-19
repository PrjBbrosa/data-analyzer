"""T1-1 + T1-2 regression: picking an A2L populates the left pane.

Pre-fix bug:
``CockpitMainWindow._on_pick_a2l`` only cached ``IF_DATA XCP`` and
updated the title chip — it never called
:func:`can_logger.p0.a2l_probe.load_measurement_summary` and never
pushed a pool into :class:`LeftPane`. The result was a green-state
cockpit with an empty measurement list, even on valid real A2Ls.

The companion bug was ``load_measurement_summary`` defaulting to
``limit=20``. ERD6's real A2L has 323 measurements; even after the
``set_pool`` wiring landed, the operator would only have seen the
alphabetically-first 20. The default is now ``limit=None`` (full
pool).

These tests cover both pieces by monkeypatching
``load_measurement_summary`` to return a synthetic summary and
asserting the cockpit's left pane reflects it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from can_logger.p0 import a2l_probe as a2l_probe_module
from can_logger.p0 import ifdata_xcp as ifdata_module
from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary
from can_logger.p0.ifdata_xcp import (
    DaqEventInfo,
    DaqProcessorInfo,
    IfDataXcp,
)
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def _stub_ifdata() -> IfDataXcp:
    return IfDataXcp(
        cmd_id=0x6C7,
        resp_id=0x6C6,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=0,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(
            DaqEventInfo(
                number=0,
                name="evt",
                cycle_time_ms=10.0,
                max_odt_entries=16,
                properties=(),
            ),
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0,
            max_event_channel=1,
            granularity_odt_entry_size_daq=1,
            overload_indication="NO_OVERLOAD_INDICATION",
        ),
    )


@pytest.fixture(autouse=True)
def _stub_parse_ifdata(monkeypatch):
    """Most tests in this file inject a known-good A2LSummary; pair
    that with a known-good IF_DATA block so the post-T2-2 warn path
    stays inert. Tests that want the warning fire to override this
    fixture inline."""

    monkeypatch.setattr(
        ifdata_module,
        "parse_ifdata_xcp_file",
        lambda path: (_stub_ifdata(),),
    )


def _synthetic_summary(count: int) -> A2LSummary:
    measurements = [
        MeasurementSummary(
            name=f"sig_{i:03d}",
            address=0x40000000 + i * 4,
            datatype="UWORD",
            unit="rpm" if i % 2 == 0 else "",
            conversion="",
            available_events=("Rte_OsTask_BSW_10ms",),
        )
        for i in range(count)
    ]
    return A2LSummary(
        path="/dummy.a2l",
        total_measurements=count,
        measurements=measurements,
        event_capacity={"Rte_OsTask_BSW_10ms": 16},
        measurement_events={m.name: ("Rte_OsTask_BSW_10ms",) for m in measurements},
        a2l_has_daq_events=True,
    )


def test_apply_a2l_path_populates_left_pane_full_pool(qapp, monkeypatch, tmp_path):
    """323-row real-A2L scale must end up in the left pane, not truncated."""

    summary = _synthetic_summary(323)
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: summary,
    )

    window = CockpitMainWindow()
    try:
        dummy_a2l = tmp_path / "dummy.a2l"
        dummy_a2l.write_text("")  # empty; _load_first_ifdata_xcp gracefully → None

        window.apply_a2l_path(dummy_a2l)

        assert window.left_pane._pool == tuple(summary.measurements)
        assert len(window.left_pane._pool) == 323
    finally:
        window.deleteLater()


def test_apply_a2l_path_propagates_daq_events_flag(qapp, monkeypatch, tmp_path):
    """A2L without DAQ events disables the "有 DAQ" filter chip."""

    summary = A2LSummary(
        path="/dummy.a2l",
        total_measurements=2,
        measurements=[
            MeasurementSummary(
                name="x",
                address=0x40000000,
                datatype="UWORD",
                unit="",
                conversion="",
                available_events=(),
            ),
            MeasurementSummary(
                name="y",
                address=0x40000004,
                datatype="UWORD",
                unit="",
                conversion="",
                available_events=(),
            ),
        ],
        event_capacity={},
        measurement_events={},
        a2l_has_daq_events=False,
    )
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: summary,
    )

    window = CockpitMainWindow()
    try:
        dummy_a2l = tmp_path / "no_daq.a2l"
        dummy_a2l.write_text("")
        window.apply_a2l_path(dummy_a2l)

        assert window.left_pane._a2l_has_daq_events is False
    finally:
        window.deleteLater()


def test_apply_a2l_path_parse_failure_clears_pool_atomically(
    qapp, monkeypatch, tmp_path
):
    """If measurement parsing raises, stale pool must not survive."""

    seeded = _synthetic_summary(3)
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: seeded,
    )

    window = CockpitMainWindow()
    try:
        first = tmp_path / "first.a2l"
        first.write_text("")
        window.apply_a2l_path(first)
        assert len(window.left_pane._pool) == 3

        def _boom(path, *, limit=None):
            raise RuntimeError("pya2l parse error: corrupt header")

        monkeypatch.setattr(a2l_probe_module, "load_measurement_summary", _boom)

        broken = tmp_path / "broken.a2l"
        broken.write_text("")
        window.apply_a2l_path(broken)

        # Atomic load: a partial A2L failure leaves no stale selectable pool.
        assert len(window.left_pane._pool) == 0
        assert window._a2l_name == "broken.a2l"
    finally:
        window.deleteLater()


def test_load_measurement_summary_default_limit_is_none():
    """Sanity: the default signature change is wired through."""

    import inspect

    sig = inspect.signature(a2l_probe_module.load_measurement_summary)
    assert sig.parameters["limit"].default is None
