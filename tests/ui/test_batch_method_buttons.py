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
    # rpm_factor moved to InputPanel (Wave 2 Task 5); exclude from this set.
    assert {"max_order", "order_res", "time_res"}.issubset(
        form.visible_field_names())


def test_param_form_no_longer_renders_rpm_factor(qtbot):
    """rpm_factor moved to the InputPanel — method_buttons must not
    render it any more (avoids two competing UI sources of the same key)."""
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("order_time")
    assert "rpm_factor" not in form.visible_field_names()


def test_batch_sheet_get_preset_includes_rpm_factor_from_input_panel(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet._input_panel._rpm_unit_combo.setCurrentText("deg/s")
    sheet.apply_method("order_time")
    preset = sheet.get_preset()
    assert abs(preset.params["rpm_factor"] - 1.0 / 6.0) < 1e-9


def test_method_buttons_includes_fft_time(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup
    g = MethodButtonGroup()
    qtbot.addWidget(g)
    assert "fft_time" in g._buttons
    seen = []
    g.methodChanged.connect(seen.append)
    g.set_method("fft_time")
    assert seen[-1] == "fft_time"
    assert g.current_method() == "fft_time"


def test_param_form_fft_time_fields(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("fft_time")
    visible = form.visible_field_names()
    assert {"window", "nfft", "overlap", "remove_mean"} == visible


def test_param_form_fft_time_overlap_and_remove_mean_round_trip(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("fft_time")
    form.apply_params({"overlap": 0.75, "remove_mean": False, "nfft": 512})
    out = form.get_params()
    assert out["overlap"] == 0.75
    assert out["remove_mean"] is False
    assert out["nfft"] == 512


def test_batch_sheet_pipeline_summary_uses_friendly_fft_time_label(qtbot):
    """_METHOD_LABELS in sheet.py must include fft_time so the pipeline
    ANALYSIS strip shows 'FFT vs Time · <window>' instead of falling
    back to the raw 'fft_time' key (codex rev-2 minor finding).

    PipelineStrip API (from pipeline_strip.py): the three cards live on
    ``strip.cards: list[PipelineCard]``; index 1 is the ANALYSIS card,
    and its visible summary text is ``cards[1].summary_label.text()``.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.apply_method("fft_time")
    summary = sheet.strip.cards[1].summary_label.text()
    assert "FFT vs Time" in summary
    assert "fft_time" not in summary  # raw key must NOT leak through
