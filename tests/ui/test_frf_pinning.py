"""FRF pins must be created through real user entry points, with source roles."""
from dataclasses import replace

import pytest
from PyQt5.QtCore import Qt

from mf4_analyzer.ui.chart_stack.pinning.sampling import PinSampleEvaluator
from mf4_analyzer.ui.pinned_cursor_state import collection_from_dict, collection_to_dict, empty_collection
from tests.ui.test_pinned_cursor_geometry import _frf_result, _make_stack
from tests.ui.test_pinned_cursor_panels import _aim, _press_p, _records


CONTEXT = {
    "input_source": ("fid-input", "same-name"),
    "output_source": ("fid-output", "same-name"),
}


def _arm(qtbot, qapp, *, mode="single", log=False, context=CONTEXT):
    cs = _make_stack(qtbot, qapp, height=820)
    cs.set_mode("frf")
    canvas = cs.canvas_frf
    cs.set_cursor_mode_for_canvas(canvas, mode)
    canvas.set_result(
        _frf_result(log=log),
        {"frequency_scale": "log" if log else "linear", "magnitude_scale": "linear"},
        context,
    )
    qtbot.wait(200)
    if mode == "single":
        canvas.set_cursor_frequency(100.0 if log else 2.0)
    else:
        canvas.set_dual_cursor_frequencies(10.0 if log else 1.0, 100.0 if log else 3.0)
    qapp.processEvents()
    return cs, canvas


@pytest.mark.parametrize("mode", ["single", "dual"])
@pytest.mark.parametrize("log", [False, True])
def test_frf_pin_button_captures_physical_hz_and_source_roles(qtbot, qapp, mode, log):
    cs, canvas = _arm(qtbot, qapp, mode=mode, log=log)
    qtbot.mouseClick(cs._pill._pin_btn, Qt.LeftButton)
    records = _records(cs, canvas)
    assert len(records) == 1
    record = records[0]
    assert record.domain == "frf" and record.mode == mode
    assert {(b.role, b.fid, b.channel) for b in record.bindings} == {
        ("input", "fid-input", "same-name"), ("output", "fid-output", "same-name"),
    }
    if mode == "single":
        assert record.x == pytest.approx(100.0 if log else 2.0)
        assert canvas.current_single_cursor_x() is None  # live consumed, mode preserved
        assert canvas._cursor_mode == "single"
        canvas.set_cursor_frequency(record.x)
        assert canvas.current_single_cursor_x() == pytest.approx(record.x)
    else:
        assert (record.ax, record.bx) == pytest.approx((10.0, 100.0) if log else (1.0, 3.0))
        placement = canvas.snapshot_cursor_placement()
        assert (placement["ax"], placement["bx"]) == (record.ax, record.bx)
        assert not any(line.isVisible() for line in canvas._cursor_a_lines + canvas._cursor_b_lines)
        canvas.set_dual_cursor_frequencies(record.ax, record.bx)
    qtbot.mouseClick(cs._pill._pin_btn, Qt.LeftButton)
    assert len(_records(cs, canvas)) == 1  # repeated physical location is deduplicated
    collection = cs.pinned_cursors_for_canvas(canvas)
    restored = collection_from_dict(collection_to_dict(collection))
    cs.set_pinned_cursors_for_canvas(canvas, empty_collection())
    assert not list(canvas._pinned_overlay.iter_lines())
    cs.set_pinned_cursors_for_canvas(canvas, restored)
    qtbot.wait(20)
    assert _records(cs, canvas) == restored.records
    assert len(canvas._pinned_overlay.lines_for(record.record_id)) == (3 if mode == "single" else 6)
    sample = PinSampleEvaluator().evaluate_intent(canvas, restored.records[0])
    assert sample.frf_sample is not None
    cs._pinned_cursors.toggle_record_panel(canvas, record.record_id)
    qtbot.wait(20)
    pill = cs._pinned_cursors.pills_for(canvas)[0]
    assert pill.isVisible() and "|H|" in pill.detail_text()
    cs.set_cursor_mode_for_canvas(canvas, "off")
    assert pill.isVisible()


def test_frf_keyboard_p_creates_pin(qtbot, qapp):
    cs, canvas = _arm(qtbot, qapp)
    cs.activateWindow()
    _aim(qtbot, canvas, 0.5, cs._pinned_cursors)
    cs.setFocus()
    qtbot.wait(200)
    assert cs._pinned_cursors._router.pin_eligible()
    _press_p(canvas._glw.viewport())
    assert len(_records(cs, canvas)) == 1


def test_frf_sources_must_match_saved_roles_when_resampling(qtbot, qapp):
    cs, canvas = _arm(qtbot, qapp)
    qtbot.mouseClick(cs._pill._pin_btn, Qt.LeftButton)
    record = _records(cs, canvas)[0]
    evaluator = PinSampleEvaluator()
    assert evaluator.bound_identity_keys(canvas) == {("fid-input", "same-name"), ("fid-output", "same-name")}
    for context in (
        {"input_source": CONTEXT["output_source"], "output_source": CONTEXT["input_source"]},
        {**CONTEXT, "output_source": ("different-file", "same-name")},
        {},
    ):
        canvas.set_result(_frf_result(), {"frequency_scale": "linear"}, context)
        assert evaluator.evaluate_intent(canvas, record) is None
        qtbot.wait(20)
        owner = cs._pinned_cursors._owner(canvas)
        assert owner.samples[record.record_id].frf_sample is None
    canvas.set_result(_frf_result(), {"frequency_scale": "linear"}, CONTEXT)
    qtbot.wait(20)
    assert evaluator.evaluate_intent(canvas, record).frf_sample is not None
    assert owner.samples[record.record_id].frf_sample is not None
    # Historical role-less records still require the same source identities.
    legacy = replace(record, bindings=tuple(replace(b, role="") for b in record.bindings))
    assert evaluator.evaluate_intent(canvas, legacy).frf_sample is not None
    canvas.set_result(_frf_result(), {"frequency_scale": "linear"}, {})
    assert evaluator.evaluate_intent(canvas, legacy) is None


@pytest.mark.parametrize("mode", ["single", "dual"])
@pytest.mark.parametrize("context", [{}, {"input_source": CONTEXT["input_source"]}, {"output_source": CONTEXT["output_source"]}])
def test_frf_missing_source_metadata_reports_why_pin_is_unavailable(qtbot, qapp, mode, context):
    cs, canvas = _arm(qtbot, qapp, mode=mode, context=context)
    with qtbot.waitSignal(cs._pinned_cursors.pin_feedback) as signal:
        qtbot.mouseClick(cs._pill._pin_btn, Qt.LeftButton)
    assert "来源" in signal.args[0]
    assert not _records(cs, canvas)


def test_frf_single_location_is_separate_from_dual_placement_and_clears(qtbot, qapp):
    cs, canvas = _arm(qtbot, qapp, mode="dual", log=True)
    cs.set_cursor_mode_for_canvas(canvas, "single")
    assert canvas.current_single_cursor_x() is None
    canvas.set_cursor_frequency(100.0)
    assert canvas.current_single_cursor_x() == pytest.approx(100.0)
    canvas.clear()
    assert canvas.current_single_cursor_x() is None
