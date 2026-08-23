"""Owner tests for UltraView PresentationCaptureFacts hosts and collector."""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import fields

from PyQt5.QtWidgets import QWidget

from mf4_analyzer import diagnostics
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.ultraview_capture_facts import (
    CAPABILITY_OK,
    CAPABILITY_UNSUPPORTED,
    PresentationCaptureFacts,
    build_capture_facts,
    collect_host_capture_facts,
    collect_widget_capture_facts,
)
from mf4_analyzer.ui.ultraview_state import (
    UltraViewBoardState,
    UltraViewWorkspaceState,
)
from tests.ui.test_ultraview_capture import (
    FakeCanvas,
    FakePage,
    _flush,
    _make_coord,
    _ref,
)

_FACTS_LOGGER = "mf4_analyzer.ui.ultraview_capture_facts"
_CAPTURE_LOGGER = "mf4_analyzer.ui.main_window.ultraview_capture_coordinator"
_FACTS_FIELD_NAMES = {item.name for item in fields(PresentationCaptureFacts)}


def _show(widget: QWidget) -> QWidget:
    widget.resize(64, 48)
    widget.show()
    return widget


def test_time_canvas_reports_empty_and_dense_raster_without_curve_count(qapp):
    canvas = _show(TimeDomainCanvasPG())
    facts = canvas.presentation_capture_facts()
    assert facts.host_kind == "time"
    assert facts.capability == CAPABILITY_OK
    assert facts.has_real_result is False
    canvas.quality_status = lambda: {
        "state": "red",
        "curve_count": 6,
        "render_path": "native-non-aa",
    }
    assert canvas.has_plotted_result() is False
    canvas.quality_status = lambda: {
        "state": "green",
        "curve_count": 0,
        "render_path": "dense-raster",
    }
    assert canvas.has_plotted_result() is True
    canvas.deleteLater()


def test_fft_canvas_uncomputed_is_missing_not_failure(qapp):
    canvas = _show(PgLineCanvas())
    facts = canvas.presentation_capture_facts()
    assert facts.host_kind == "fft"
    assert facts.capability == CAPABILITY_OK
    assert facts.has_real_result is False
    assert canvas.has_result() is False
    canvas.deleteLater()


def test_fft_time_and_order_heatmap_hosts_report_distinct_kinds(qapp):
    fft_time = _show(PgHeatmapCanvas(with_slice=True))
    order = _show(PgHeatmapCanvas(with_slice=False))
    fft_facts = fft_time.presentation_capture_facts()
    order_facts = order.presentation_capture_facts()
    assert fft_facts.host_kind == "fft_time"
    assert order_facts.host_kind == "order"
    assert fft_facts.has_real_result is False
    assert order_facts.has_real_result is False
    assert fft_facts.capability == CAPABILITY_OK
    fft_time.deleteLater()
    order.deleteLater()


def test_frf_canvas_uncomputed_is_missing_not_failure(qapp):
    canvas = _show(PgFrfCanvas())
    facts = canvas.presentation_capture_facts()
    assert facts.host_kind == "frf"
    assert facts.capability == CAPABILITY_OK
    assert facts.has_real_result is False
    canvas.deleteLater()


def test_fake_host_reports_ok_facts(qapp):
    canvas = FakeCanvas()
    facts = canvas.presentation_capture_facts()
    assert facts.host_kind == "fake"
    assert facts.capability == CAPABILITY_OK
    assert facts.has_real_result is True
    assert facts.is_stable is True
    assert facts.markup_revision == 0
    assert facts.pill_fingerprint is None
    canvas.deleteLater()


def test_unsupported_host_degrades_with_throttled_warning(qapp, caplog, monkeypatch):
    monkeypatch.setattr(diagnostics, "_THROTTLE_STATE", OrderedDict())
    host = _show(QWidget())
    with caplog.at_level(logging.WARNING, logger=_FACTS_LOGGER):
        facts = collect_host_capture_facts(host)
    assert facts.capability == CAPABILITY_UNSUPPORTED
    assert facts.degrade_reason == "missing-presentation-capture-facts"
    assert facts.has_real_result is False
    assert any("unsupported" in record.getMessage() for record in caplog.records)
    host.deleteLater()


def test_plotted_host_without_facts_api_is_not_silent_no_result(
    qapp, caplog, monkeypatch
):
    monkeypatch.setattr(diagnostics, "_THROTTLE_STATE", OrderedDict())

    class _PlottedWithoutFacts(QWidget):
        def has_result(self) -> bool:
            return True

    host = _show(_PlottedWithoutFacts())
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    ref = _ref("view-a")
    coord.bind_canvas(host, ref)
    with caplog.at_level(logging.DEBUG, logger=_CAPTURE_LOGGER):
        coord.request_capture(ref, host, "no-facts-api")
    _flush()
    skipped = [
        record
        for record in caplog.records
        if "capture skipped" in record.getMessage()
    ]
    assert skipped
    assert skipped[0].levelno == logging.WARNING
    assert "no-result" not in skipped[0].getMessage()
    assert "missing-presentation-capture-facts" in skipped[0].getMessage()
    assert coord.store.get(ref) is None or coord.store.get(ref).image is None
    host.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_unrelated_import_error_from_facts_method_propagates(qapp):
    class _Boom(QWidget):
        def presentation_capture_facts(self):
            raise ImportError("unrelated optional backend")

    host = _show(_Boom())
    try:
        raised = False
        try:
            collect_host_capture_facts(host)
        except ImportError as exc:
            raised = True
            assert "unrelated optional backend" in str(exc)
        assert raised
    finally:
        host.deleteLater()


def test_widget_facts_aggregate_fake_page_panes(qapp):
    from tests.ui.test_ultraview_capture import FakePage

    panes = [FakeCanvas("#111111"), FakeCanvas("#222222")]
    page = FakePage(panes)
    facts = collect_widget_capture_facts(page)
    assert facts.capability == CAPABILITY_OK
    assert facts.has_real_result is True
    page.deleteLater()
    for pane in panes:
        pane.deleteLater()


def test_build_capture_facts_defaults_markup_and_pill():
    facts = build_capture_facts(
        host_kind="x",
        visible_and_sized=True,
        has_real_result=True,
        quality_settled=True,
        interaction_idle=True,
    )
    assert facts.markup_revision == 0
    assert facts.pill_fingerprint is None


def test_canvas_facts_include_markup_revision_and_empty_pill(qapp):
    canvases = [
        _show(TimeDomainCanvasPG()),
        _show(PgLineCanvas()),
        _show(PgHeatmapCanvas(with_slice=True)),
        _show(PgHeatmapCanvas(with_slice=False)),
        _show(PgFrfCanvas()),
    ]
    try:
        for canvas in canvases:
            facts = canvas.presentation_capture_facts()
            assert facts.markup_revision == 0
            assert facts.pill_fingerprint is None
            assert canvas.capture_markup_revision() == 0
        time_canvas, line_canvas = canvases[0], canvases[1]
        time_canvas._annotations.markup_revision = 5
        assert time_canvas.presentation_capture_facts().markup_revision == 5
        line_canvas.markup_revision = 3
        assert line_canvas.presentation_capture_facts().markup_revision == 3
    finally:
        for canvas in canvases:
            canvas.deleteLater()


def test_paged_widget_facts_aggregate_markup_revisions(qapp):
    panes = [FakeCanvas(), FakeCanvas()]
    panes[0].markup_revision = 1
    panes[1].markup_revision = 2
    page = FakePage(panes)
    facts = collect_widget_capture_facts(page)
    assert facts.markup_revision == (1, 2)
    assert facts.pill_fingerprint is None
    page.deleteLater()
    for pane in panes:
        pane.deleteLater()


def test_capture_facts_are_not_written_onto_board_or_project_payload(qapp):
    board_names = {item.name for item in fields(UltraViewBoardState)}
    workspace_names = {item.name for item in fields(UltraViewWorkspaceState)}
    leaked = _FACTS_FIELD_NAMES & (board_names | workspace_names)
    assert leaked == set()
    window, coord = _make_coord()
    canvas = FakeCanvas()
    ref = _ref("view-a")
    window.view_manager.get(0).view_id = "view-a"
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "seed")
    _flush()
    payload = coord.to_project_payload()
    blob = json.dumps(payload)
    for name in (
        "has_real_result",
        "quality_settled",
        "interaction_idle",
        "PresentationCaptureFacts",
        "degrade_reason",
        "pill_fingerprint",
    ):
        assert name not in blob
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()
