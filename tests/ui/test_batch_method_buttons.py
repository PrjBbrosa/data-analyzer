def test_method_buttons_emit_signal(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup
    g = MethodButtonGroup()
    qtbot.addWidget(g)
    seen = []
    g.methodChanged.connect(seen.append)
    g.set_method("order_time")
    assert seen[-1] == "order_time"


def test_param_form_renders_per_method(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import (
        MethodButtonGroup, DynamicParamForm,
    )
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("fft")
    assert "window" in form.visible_field_names()
    assert "nfft" in form.visible_field_names()
    assert "max_order" not in form.visible_field_names()
    form.set_method("order_time")
    assert {"max_order", "order_res", "time_res", "rpm_factor"}.issubset(
        form.visible_field_names())
