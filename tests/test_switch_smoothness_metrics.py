"""The probe must count heatmap AA and identify the paint's transition phase."""
from types import SimpleNamespace as NS

from scripts._switch_paint_metrics import canvas_aa_state, transition_paint_facts


def test_slice_aa_uses_the_curve_actually_painted():
    child = NS(opts={"antialias": True})
    canvas = NS(_slice_aa_on=False, _slice_curve=NS(curve=child))
    assert canvas_aa_state(canvas) is True
    child.opts["antialias"] = False
    canvas._slice_aa_on = True
    assert canvas_aa_state(canvas) is False
    canvas._slice_curve = None
    assert canvas_aa_state(canvas) is False


def test_line_time_and_unknown_aa_are_distinct():
    assert canvas_aa_state(NS(_aa_on=False)) is False
    assert canvas_aa_state(NS(_quality=NS(aa_on=True))) is True
    assert canvas_aa_state(None) is None
    assert canvas_aa_state(NS()) is None


def test_fade_target_is_not_the_outgoing_snapshot():
    controller = NS(is_active=lambda: True, is_pending=lambda: False)
    stack = NS(
        _card_for_canvas=lambda canvas: NS(_chart_mode=canvas.section),
        page_transition=lambda: controller,
        _discrete_quality_hold_token=NS(request_generation=7),
    )
    target = NS(section="fft_time", window=lambda: NS(chart_stack=stack))
    source = NS(section="time", window=lambda: NS(chart_stack=stack))
    stack._discrete_quality_hold_canvases = (target,)
    facts = transition_paint_facts(target)
    assert facts == dict(section="fft_time", phase="fade", generation=7, target=True, held=True)
    assert transition_paint_facts(source)["target"] is False
    controller.is_active = lambda: False
    assert transition_paint_facts(target)["phase"] == "awaiting-paint"
    stack._discrete_quality_hold_token = None
    stack._discrete_quality_hold_canvases = ()
    assert transition_paint_facts(target)["phase"] == "idle"
