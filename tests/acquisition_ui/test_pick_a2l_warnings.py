"""T2-2 + T2-3 regression: picking an unsuitable A2L raises a modal
warning AND clears the cached ``IF_DATA XCP`` so the next Test
Connection can't reuse stale ``cmd_id`` / ``resp_id``.

We stub :meth:`CockpitMainWindow._warn_a2l_load_problems` so headless
tests don't try to render a QMessageBox; the spy captures the call.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from can_logger.p0 import a2l_probe as a2l_probe_module
from can_logger.p0 import ifdata_xcp as ifdata_module
from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary
from can_logger.p0.ifdata_xcp import (
    DaqEventInfo,
    DaqProcessorInfo,
    IfDataXcp,
)
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def _good_ifdata() -> IfDataXcp:
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


def _good_summary() -> A2LSummary:
    return A2LSummary(
        path="/dummy.a2l",
        total_measurements=1,
        measurements=[
            MeasurementSummary(
                name="x",
                address=0x40000000,
                datatype="UWORD",
                unit="rpm",
                conversion="",
                available_events=("evt",),
            )
        ],
        event_capacity={"evt": 16},
        measurement_events={"x": ("evt",)},
        a2l_has_daq_events=True,
    )


def test_successful_load_no_warning(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(
        ifdata_module,
        "parse_ifdata_xcp_file",
        lambda path: (_good_ifdata(),),
    )
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: _good_summary(),
    )

    window = CockpitMainWindow()
    try:
        spy = MagicMock()
        window._warn_a2l_load_problems = spy  # type: ignore[method-assign]
        a2l = tmp_path / "ok.a2l"
        a2l.write_text("")
        window.apply_a2l_path(a2l)

        spy.assert_not_called()
        assert window._ifdata_xcp is not None
    finally:
        window.deleteLater()


def test_ifdata_parse_failure_warns_and_clears_cache(qapp, monkeypatch, tmp_path):
    """Pre-load a good A2L; then load a broken one. Warning fires and
    ``self._ifdata_xcp`` is None so Test Connection can't reuse it."""

    monkeypatch.setattr(
        ifdata_module,
        "parse_ifdata_xcp_file",
        lambda path: (_good_ifdata(),),
    )
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: _good_summary(),
    )

    window = CockpitMainWindow()
    try:
        spy = MagicMock()
        window._warn_a2l_load_problems = spy  # type: ignore[method-assign]

        first = tmp_path / "first.a2l"
        first.write_text("")
        window.apply_a2l_path(first)
        assert window._ifdata_xcp is not None
        spy.assert_not_called()

        # Now simulate corrupt second A2L.
        def _boom(path):
            raise RuntimeError("xcp block malformed at line 12")

        monkeypatch.setattr(
            ifdata_module, "parse_ifdata_xcp_file", _boom
        )

        broken = tmp_path / "broken.a2l"
        broken.write_text("")
        window.apply_a2l_path(broken)

        # T2-3: stale IF_DATA cleared.
        assert window._ifdata_xcp is None
        # T2-2: warning fired.
        spy.assert_called_once()
        args, _ = spy.call_args
        called_path, called_problems = args
        assert called_path == broken
        joined = "\n".join(called_problems)
        assert "IF_DATA XCP" in joined
        assert "malformed" in joined
        # Includes the "previous A2L cleared" notice.
        assert "上一次 A2L 的 IF_DATA 和 measurement pool 已被清空" in joined
    finally:
        window.deleteLater()


def test_measurement_failure_clears_new_ifdata_and_old_pool(
    qapp, monkeypatch, tmp_path
):
    """IF_DATA success + measurement failure must not leave a mixed A2L state."""

    monkeypatch.setattr(
        ifdata_module,
        "parse_ifdata_xcp_file",
        lambda path: (_good_ifdata(),),
    )
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: _good_summary(),
    )

    window = CockpitMainWindow()
    try:
        spy = MagicMock()
        window._warn_a2l_load_problems = spy  # type: ignore[method-assign]

        first = tmp_path / "first.a2l"
        first.write_text("")
        window.apply_a2l_path(first)
        assert window._ifdata_xcp is not None
        assert len(window.left_pane._pool) == 1

        def _measurement_boom(path, *, limit=None):
            raise RuntimeError("file already exists: stale .a2ldb")

        monkeypatch.setattr(
            a2l_probe_module, "load_measurement_summary", _measurement_boom
        )

        second = tmp_path / "second.a2l"
        second.write_text("")
        window.apply_a2l_path(second)

        assert window._ifdata_xcp is None
        assert len(window.left_pane._pool) == 0
        _, called_problems = spy.call_args.args
        joined = "\n".join(called_problems)
        assert "measurement" in joined
        assert "stale .a2ldb" in joined
        assert "measurement pool 已被清空" in joined
    finally:
        window.deleteLater()


def test_empty_ifdata_blocks_treated_as_failure(qapp, monkeypatch, tmp_path):
    """An A2L that parses fine but yields zero usable IF_DATA blocks
    (e.g. XCPplus-only ECU) is treated as a load failure."""

    monkeypatch.setattr(
        ifdata_module,
        "parse_ifdata_xcp_file",
        lambda path: (),
    )
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: _good_summary(),
    )

    window = CockpitMainWindow()
    try:
        spy = MagicMock()
        window._warn_a2l_load_problems = spy  # type: ignore[method-assign]
        a2l = tmp_path / "xcpplus.a2l"
        a2l.write_text("")
        window.apply_a2l_path(a2l)

        assert window._ifdata_xcp is None
        spy.assert_called_once()
        _, called_problems = spy.call_args.args
        assert any("IF_DATA" in p for p in called_problems)
    finally:
        window.deleteLater()
