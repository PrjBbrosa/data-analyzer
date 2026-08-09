import pytest

from mf4_analyzer.ui_kit import load_stylesheet


def test_method_buttons_emit_signal(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup
    g = MethodButtonGroup()
    qtbot.addWidget(g)
    seen = []
    g.methodChanged.connect(seen.append)
    g.set_method("order_time")
    assert seen[-1] == "order_time"


def test_method_button_click_is_idempotent_but_programmatic_set_refreshes(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup

    group = MethodButtonGroup()
    qtbot.addWidget(group)
    seen = []
    group.methodChanged.connect(seen.append)

    # A user clicking the already active FFT button is a no-op.
    group._buttons["fft"].click()
    assert seen == []

    # Full preset application uses the programmatic setter, which remains an
    # explicit refresh boundary even when the method is unchanged.
    group.set_method("fft")
    assert seen == ["fft"]


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


def test_param_form_order_time_has_no_manual_rpm_controls(qtbot):
    """Design 2026-08-03 D-C1: batch order analysis dropped manual RPM.
    The panel must show neither the RPM-mode selector nor the manual-RPM
    spinbox, and the underlying widgets must not exist at all (not just be
    hidden) -- this is a removal, not a visibility toggle."""
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("order_time")

    assert "rpm_mode" not in form.visible_field_names()
    assert "manual_rpm" not in form.visible_field_names()
    assert "rpm_mode" not in form._widgets
    assert "manual_rpm" not in form._widgets
    assert not hasattr(form, "_w_rpm_mode")
    assert not hasattr(form, "_w_manual_rpm")
    assert not hasattr(form, "_sync_rpm_mode")


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
    sheet._input_panel._rpm_factor_spin.setValue(1.0 / 6.0)
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
    assert {
        "window", "nfft_mode", "nfft", "t_win_s", "overlap",
        "weighting",
    } == visible


def test_param_form_weighting_visible_for_all_methods(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)

    for method in ("fft", "fft_time", "order_time"):
        form.set_method(method)
        assert "weighting" in form.visible_field_names()


def test_param_form_weighting_round_trips(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("order_time")

    assert form.get_params()["weighting"] == "None"
    form.apply_params({"weighting": "A"})

    assert form.get_params()["weighting"] == "A"


def test_batch_binary_params_use_segmented_choices_without_changing_combo_state(
    qtbot,
):
    """Binary Batch params keep their combo API but render one full field slot."""
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("frf")
    form.resize(288, 900)
    form.show()
    qtbot.wait(20)

    for name in (
        "estimator", "nfft_mode", "magnitude_scale", "frequency_scale",
        "phase_mode",
    ):
        combo = getattr(form, f"_w_{name}")
        choice = getattr(form, f"_choice_{name}")
        host = form._field_hosts[name]
        assert choice.bound_combo() is combo
        assert combo.isHidden() is True
        assert choice.isVisibleTo(form) is True
        assert choice.height() == 32
        assert choice.mapTo(form, choice.rect().topLeft()).x() == (
            host.mapTo(form, host.rect().topLeft()).x()
        )
        assert choice.mapTo(form, choice.rect().topRight()).x() == (
            host.mapTo(form, host.rect().topRight()).x()
        )

    estimator_events = QSignalSpy(form.paramsChanged)
    form._choice_estimator.buttons()[1].click()
    assert len(estimator_events) == 1
    assert form._w_estimator.currentData() == "h2"
    assert form.get_params()["estimator"] == "h2"
    assert "输出端噪声" in form._choice_estimator.buttons()[0].toolTip()
    assert "输入端噪声" in form._choice_estimator.buttons()[1].toolTip()

    form._w_nfft_mode.setCurrentIndex(1)
    assert form._choice_nfft_mode.buttons()[1].isChecked()
    assert form.get_params()["nfft_mode"] == "manual"

    form.set_method("fft")
    assert [button.text() for button in form._choice_nfft_mode.buttons()] == [
        "Auto", "Fixed",
    ]
    weight_choice = form._choice_weighting
    assert form._w_weighting.isHidden() is True
    assert weight_choice.isVisibleTo(form) is True
    weight_choice.buttons()[1].click()
    assert form.get_params()["weighting"] == "A"


def test_batch_sheet_weighting_options_match_main_panel(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    expected = [
        win.inspector.fft_ctx.combo_weighting.itemText(i)
        for i in range(win.inspector.fft_ctx.combo_weighting.count())
    ]
    sheet = BatchSheet(parent=win, files={}, current_preset=None)
    qtbot.addWidget(sheet)

    combo = sheet._analysis_panel._param_form._w_weighting
    actual = [combo.itemText(i) for i in range(combo.count())]

    assert actual == expected


def test_param_form_fft_time_overlap_ignores_legacy_remove_mean(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("fft_time")
    form.apply_params({"overlap": 0.75, "remove_mean": False, "nfft": 512})
    out = form.get_params()
    assert out["overlap"] == 0.75
    assert "remove_mean" not in out
    assert out["nfft"] == 512


def test_batch_sheet_pipeline_summary_uses_friendly_fft_time_label(qtbot):
    """_METHOD_LABELS in sheet.py must include fft_time so the pipeline
    ANALYSIS strip shows the product label '时频 · <window>' instead of falling
    back to the raw 'fft_time' key (codex rev-2 minor finding).

    PipelineStrip API (from pipeline_strip.py): the three cards live on
    ``strip.cards: list[PipelineCard]``; index 1 is the ANALYSIS card,
    and its visible summary text is ``cards[1].summary_label.text()``.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.apply_method("fft_time")
    # Method-button signals now coalesce into one pipeline refresh.
    qtbot.waitUntil(
        lambda: "时频" in sheet.strip.cards[1].summary_label.text(),
        timeout=1000,
    )
    summary = sheet.strip.cards[1].summary_label.text()
    assert "时频" in summary
    assert "fft_time" not in summary  # raw key must NOT leak through


def test_batch_sheet_pipeline_summary_localizes_order_rpm_issue(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.apply_method("order_time")

    expected_summary = "阶次 · RPM 通道未配置"
    # Wait for the debounced method-status projection.
    qtbot.waitUntil(
        lambda: sheet.strip.cards[1].summary_label.text() == expected_summary,
        timeout=1000,
    )
    summary = sheet.strip.cards[1].summary_label.text()
    assert summary == expected_summary
    assert "rpm_channel" not in summary


def test_batch_sheet_pipeline_summary_localizes_missing_outputs(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet._output_panel._chk_data.setChecked(False)
    sheet._output_panel._chk_image.setChecked(False)

    expected_summary = "未选择导出内容"
    # Both checkbox signals share one delayed output-stage refresh.
    qtbot.waitUntil(
        lambda: sheet.strip.cards[2].summary_label.text() == expected_summary,
        timeout=1000,
    )
    summary = sheet.strip.cards[2].summary_label.text()
    assert summary == expected_summary
    assert "outputs" not in summary


def test_batch_method_buttons_include_time_and_user_labels(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup

    group = MethodButtonGroup()
    qtbot.addWidget(group)

    assert tuple(group._buttons) == (
        "time", "fft", "fft_time", "order_time", "frf",
    )
    assert tuple(button.text() for button in group._buttons.values()) == (
        "时域", "频谱", "时频", "阶次", "频响",
    )


def test_batch_method_buttons_are_equal_and_unclipped_at_narrow_width(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup

    group = MethodButtonGroup()
    qtbot.addWidget(group)
    group.resize(288, 44)
    group.show()
    qtbot.wait(20)

    widths = [button.width() for button in group._buttons.values()]
    # Qt distributes indivisible pixels across equal-stretch cells.
    assert max(widths) - min(widths) <= 1
    for button in group._buttons.values():
        assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 8
        assert button.font().stretch() in {0, 100}
    assert len({button.font().stretch() for button in group._buttons.values()}) == 1


def test_batch_method_zone_uses_symmetric_markers_and_active_dot(qtbot, qapp):
    """Batch keeps equal-width modes while sharing the toolbar's mode chrome."""
    from mf4_analyzer.ui_kit import load_stylesheet
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup

    old_stylesheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        group = MethodButtonGroup()
        qtbot.addWidget(group)
        group.show()

        for width in (288, 806):
            group.resize(width, 44)
            qtbot.wait(20)
            left_divider, right_divider = group._mode_zone_dividers
            segment = group._mode_segment
            left_gap = segment.x() - (left_divider.x() + left_divider.width())
            right_gap = right_divider.x() - (segment.x() + segment.width())
            assert left_gap == right_gap == 12
            assert left_divider.height() == right_divider.height() == 16
            widths = [button.width() for button in group._buttons.values()]
            assert max(widths) - min(widths) <= 1

        assert group._mode_active_dots["fft"].isVisible()
        assert not group._mode_active_dots["time"].isVisible()
        group._buttons["frf"].click()
        assert group._mode_active_dots["frf"].isVisible()
        assert not group._mode_active_dots["fft"].isVisible()
    finally:
        group.close()
        qapp.setStyleSheet(old_stylesheet)


def test_batch_frf_param_form_uses_canonical_compute_and_display_fields(qtbot):
    from mf4_analyzer.batch_recipe import normalize_batch_params
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("frf")
    assert {
        "estimator", "window", "t_win_s", "overlap", "nfft_mode", "nfft",
        "magnitude_scale",
        "frequency_scale", "phase_mode", "coherence_threshold",
        "fade_low_coherence",
    } == form.visible_field_names()

    form.apply_params({
        "estimator": "h2", "periodic_window": False,
        "nfft_mode": "manual", "nfft": 4096, "detrend": "none",
        "magnitude_scale": "linear", "frequency_scale": "linear",
        "phase_mode": "wrapped", "coherence_threshold": 0.6,
        "fade_low_coherence": False, "render_group_by": "source",
    })
    params = form.get_params()
    assert form._w_nfft_mode.currentText() == "手动"
    assert params["nfft_mode"] == "manual"
    assert params == normalize_batch_params(params, "frf")


def test_batch_time_method_exposes_exact_sparse_render_fields(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)

    form.set_method("time")

    expected = {
        "render_grouping_cards", "render_layout", "x_source", "x_channel",
        "x_origin",
    }
    assert form._form.rowCount() == 5
    assert {
        name for name in expected if form._form.indexOf(form._widgets[name]) >= 0
    } == expected
    assert form.visible_field_names() == expected - {"x_channel"}
    assert form._w_render_layout.isEnabled() is False
    assert form._w_x_channel.isHidden() is True
    assert form._w_x_origin.isHidden() is False
    assert form.get_params() == {}


def test_time_x_dependency_uses_one_stable_right_grid_slot(qtbot):
    """The X-source dependent editor must not jump to the left column."""
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_x_channel_candidates(("speed",), {})
    form.resize(280, 260)
    form.show()
    qtbot.wait(20)

    channel_host = form._field_hosts["x_channel"]
    origin_host = form._field_hosts["x_origin"]
    source_host = form._field_hosts["x_source"]
    layout_host = form._field_hosts["render_layout"]

    # Both semantic fields retain their adapter identities but share row 2,
    # column 1 in the visible two-column grid.
    for host in (channel_host, origin_host):
        index = form._grid.indexOf(host)
        assert index >= 0
        assert form._grid.getItemPosition(index) == (2, 1, 1, 1)

    assert origin_host.isVisibleTo(form) is True
    assert channel_host.isVisibleTo(form) is False
    time_slot = origin_host.geometry()

    form.apply_params({"x_source": "channel", "x_channel": "speed"})
    qtbot.wait(20)

    channel_slot = channel_host.geometry()
    assert channel_host.isVisibleTo(form) is True
    assert origin_host.isVisibleTo(form) is False
    assert sum(
        host.isVisibleTo(form) for host in (channel_host, origin_host)
    ) == 1
    assert channel_slot.x() == source_host.geometry().x()
    assert channel_slot.x() > layout_host.geometry().x()
    assert all(
        abs(actual - expected) <= 1
        for actual, expected in zip(
            (channel_slot.x(), channel_slot.y(), channel_slot.width(), channel_slot.height()),
            (time_slot.x(), time_slot.y(), time_slot.width(), time_slot.height()),
        )
    )


def test_batch_analysis_panel_drops_preset_source_note_widget(qtbot):
    # C3: the "从单文件预设槽 1 借名" note was redundant with the
    # "与单次分析同步" badge already shown next to the preset title. The
    # widget itself must be gone, not just emptied -- an empty QLabel would
    # still reserve a row of height in this compact layout.
    from PyQt5.QtWidgets import QLabel

    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.set_method("order_time")

    assert not hasattr(panel, "_preset_source_note")
    assert panel.findChildren(QLabel, "BatchPresetSourceNote") == []
    # Only the head row (title + sync badge) and the preset-card row remain.
    assert panel._preset_host.layout().count() == 2


def test_preset_cards_use_contract_fonts_and_heights(qtbot):
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel, _PresetCard

    panel = AnalysisPanel()
    qtbot.addWidget(panel)

    assert _PresetCard._TITLE_POINT_SIZE == 9
    assert _PresetCard._SUMMARY_POINT_SIZE == 8
    for button in panel._preset_buttons.values():
        assert button.minimumHeight() == 66
        assert button.maximumHeight() == 66
        assert button.property("compact") is False
        assert button.property("textAlignment") == "center"
        button.set_compact_mode(True)
        assert button.minimumHeight() == 40
        assert button.maximumHeight() == 40
        assert button.property("compact") is True


@pytest.mark.parametrize(
    ("method", "params"),
    (
        ("fft", {
            "window": "flattop", "nfft_mode": "auto", "nfft": None,
            "t_win_s": 2.25, "overlap": 0.4, "avg_mode": "峰值保持",
            "avg_overlap": 75, "amplitude_definition": "rms",
            "weighting": "A",
        }),
        ("fft_time", {
            "window": "blackman", "nfft_mode": "fixed", "nfft": 4096,
            "t_win_s": 0.75, "overlap": 0.8, "weighting": "A",
        }),
        ("order_time", {
            "window": "bartlett", "nfft_mode": "fixed", "nfft": 2048,
            "max_order": 45.0, "order_res": 0.025, "time_res": 0.2,
            "samples_per_rev": 1024, "weighting": "A",
        }),
        ("time", {
            "render_group_by": "source", "render_layout": "subplot",
            "x_source": "channel", "x_channel": "speed",
        }),
    ),
)
def test_phase2_all_method_controls_round_trip(qtbot, method, params):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method(method)
    if method == "time":
        form.set_x_channel_candidates(("speed",), {})
    form.apply_params(params)

    assert form.get_params() == params


def test_time_params_return_only_active_semantic_deviations_and_reset(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_x_channel_candidates(("speed",), {})

    form.apply_params({
        "render_group_by": "source",
        "render_layout": "subplot",
        "x_source": "channel",
        "x_channel": "speed",
        "x_origin": "absolute",
    })
    assert form.get_params() == {
        "render_group_by": "source",
        "render_layout": "subplot",
        "x_source": "channel",
        "x_channel": "speed",
    }

    form.apply_params({
        "render_group_by": "none",
        "x_source": "time",
        "x_origin": "zero",
    })
    assert form.get_params() == {}


def test_time_apply_params_empty_patch_remains_incremental(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_x_channel_candidates(("speed",), {})
    form.apply_params({
        "render_group_by": "source",
        "render_layout": "subplot",
        "x_source": "channel",
        "x_channel": "speed",
        "x_origin": "absolute",
    })

    form.apply_params({})

    assert form._w_render_group_by.currentData() == "source"
    assert form._w_render_layout.currentData() == "subplot"
    assert form._w_x_source.currentData() == "channel"
    assert form._w_x_channel.currentData() == "speed"
    assert form._w_x_origin.currentData() == "absolute"
    assert form._pending_x_channel == "speed"
    assert form.x_channel_validation_message() == ""


def test_time_params_omit_inactive_layout_channel_and_origin(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_x_channel_candidates(("speed",), {})

    form.apply_params({
        "render_group_by": "none",
        "render_layout": "subplot",
        "x_source": "time",
        "x_channel": "speed",
        "x_origin": "absolute",
    })
    assert form.get_params() == {"x_origin": "absolute"}

    form.apply_params({"x_source": "channel", "x_channel": "speed"})
    assert form.get_params() == {
        "x_source": "channel",
        "x_channel": "speed",
    }


def test_time_form_accepts_and_ignores_legacy_preprocess(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")

    form.apply_params({
        "time_preprocess": {
            "scale": 2.5,
            "offset": -1.25,
            "remove_mean": True,
            "sample_mode": "target_fs",
            "target_fs": 200.0,
            "decimation_factor": 3,
        },
    })

    assert form.get_params() == {}


def test_time_x_channel_candidates_show_partial_disabled_and_keep_common(qtbot):
    from PyQt5.QtCore import Qt

    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_x_channel_candidates(("speed", "rpm"), {"temperature": "(1/2)"})

    common_index = form._w_x_channel.findData("speed")
    partial_index = form._w_x_channel.findData("temperature")
    assert common_index >= 0
    assert partial_index >= 0
    assert form._w_x_channel.itemText(partial_index) == "temperature (1/2)"
    assert form._w_x_channel.model().item(common_index).flags() & Qt.ItemIsEnabled
    assert not (
        form._w_x_channel.model().item(partial_index).flags() & Qt.ItemIsEnabled
    )

    form.apply_params({"x_source": "channel", "x_channel": "speed"})
    form.set_x_channel_candidates(("rpm", "speed"), {"temperature": "(1/2)"})
    assert form.get_params() == {
        "x_source": "channel",
        "x_channel": "speed",
    }
    assert form.x_channel_validation_message() == ""


def test_time_pending_noncommon_x_channel_clears_with_one_change_signal(qtbot):
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.apply_params({"x_source": "channel", "x_channel": "stale_speed"})
    assert form.get_params() == {
        "x_source": "channel",
        "x_channel": "stale_speed",
    }

    spy = QSignalSpy(form.paramsChanged)
    form.set_x_channel_candidates(("rpm",), {"stale_speed": "(1/2)"})

    assert len(spy) == 1
    assert form.get_params() == {"x_source": "channel"}
    assert "stale_speed" in form.x_channel_validation_message()


def test_time_current_x_channel_becoming_stale_emits_once(qtbot):
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_x_channel_candidates(("speed", "rpm"), {})
    form.apply_params({"x_source": "channel", "x_channel": "speed"})

    spy = QSignalSpy(form.paramsChanged)
    form.set_x_channel_candidates(("rpm",), {"speed": "(1/2)"})

    assert len(spy) == 1
    assert form.get_params() == {"x_source": "channel"}
    assert "speed" in form.x_channel_validation_message()


def test_time_user_clearing_x_channel_drops_pending_and_reports_missing(qtbot):
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_x_channel_candidates(("speed",), {})
    form.apply_params({"x_source": "channel", "x_channel": "speed"})
    assert form.get_params() == {
        "x_source": "channel",
        "x_channel": "speed",
    }

    spy = QSignalSpy(form.paramsChanged)
    form._w_x_channel.setCurrentIndex(0)

    assert len(spy) == 1
    assert form.get_params() == {"x_source": "channel"}
    assert form._pending_x_channel == ""
    assert form.x_channel_validation_message() == "请选择 X 通道"


@pytest.mark.parametrize("method", ("fft", "fft_time", "order_time"))
def test_non_time_render_hides_both_x_dependency_rows_and_time_restores(
    qtbot, method,
):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.apply_params({"x_source": "channel"})
    assert form._w_x_channel.isHidden() is False
    assert form._w_x_origin.isHidden() is True

    form.set_method(method)

    assert form._form.indexOf(form._w_x_channel) == -1
    assert form._form.indexOf(form._w_x_origin) == -1
    assert form._w_x_channel.isHidden() is True
    assert form._w_x_origin.isHidden() is True

    form.set_method("time")
    assert form._w_x_channel.isHidden() is False
    assert form._w_x_origin.isHidden() is True


def test_time_dependency_rows_resync_after_method_round_trip(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.apply_params({"render_group_by": "source", "x_source": "channel"})
    form.set_method("fft")
    form.set_method("time")

    assert form._w_render_layout.isEnabled() is True
    assert form._w_x_channel.isHidden() is False
    assert form._w_x_origin.isHidden() is True


def test_batch_builtin_preset_bar_uses_shared_provider_and_partial_apply(qtbot):
    from mf4_analyzer.analysis_presets import get_builtin_preset
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.set_method("order_time")
    # ``weighting`` is not declared by the order_time builtin patches, so it
    # is the field that proves "partial apply" only touches declared keys.
    panel.apply_params({"window": "kaiser", "weighting": "A"})
    emitted = []
    panel.presetApplied.connect(lambda key, patch: emitted.append((key, patch)))
    panel._preset_buttons["torque"].click()
    params = panel.get_params()

    expected = get_builtin_preset("order_time", "torque").params_copy()
    assert emitted == [("torque", expected)]
    assert params["nfft_mode"] == "auto"
    assert params["nfft"] is None
    for key in ("max_order", "order_res", "time_res", "samples_per_rev"):
        assert params[key] == expected[key]
    # C2: order_time now declares `window`, so applying the "frequency"
    # (torque) preset overwrites a previously custom window with flattop,
    # aligned with fft / fft_time. This is the deliberate behavior change.
    assert params["window"] == "flattop"
    # A field the preset patch does NOT declare stays untouched.
    assert params["weighting"] == "A"


def test_batch_time_hides_complete_preset_host_and_fft_restores_it(qtbot):
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.set_method("time")

    assert panel._preset_host.isHidden() is True
    assert panel._preset_title.parentWidget() is panel._preset_host
    assert all(
        button.parentWidget() is panel._preset_host
        for button in panel._preset_buttons.values()
    )

    panel.set_method("fft")
    assert panel._preset_host.isHidden() is False


def test_batch_method_and_preset_selectors_use_distinct_control_types(qtbot):
    from PyQt5.QtWidgets import QPushButton

    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)

    assert panel._method_title.text() == "分析方法"
    assert panel._preset_title.text() == "分析预设"
    assert all(
        isinstance(button, QPushButton)
        for button in panel._method_group._buttons.values()
    )
    assert all(
        isinstance(button, QPushButton)
        for button in panel._preset_buttons.values()
    )
    assert not any(button.isChecked() for button in panel._preset_buttons.values())


def test_batch_window_options_match_canonical_analysis_factory(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)

    assert {
        form._w_window.itemText(i) for i in range(form._w_window.count())
    } == {"hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop"}
    assert form._w_window.findText("rectangular") == -1


def test_method_button_labels_fit_narrow_batch_column_with_production_qss(
    qapp, qtbot,
):
    from pathlib import Path

    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup

    old_stylesheet = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        group = MethodButtonGroup()
        qtbot.addWidget(group)
        group.resize(288, group.sizeHint().height())
        group.show()
        qtbot.wait(20)

        widths = [button.width() for button in group._buttons.values()]
        assert max(widths) - min(widths) <= 1
        for button in group._buttons.values():
            text_width = button.fontMetrics().horizontalAdvance(button.text())
            assert button.width() >= text_width + 4
    finally:
        group.close()
        qapp.setStyleSheet(old_stylesheet)


def test_preset_radio_labels_fit_narrow_batch_column_with_production_qss(
    qapp, qtbot,
):
    from pathlib import Path

    from PyQt5.QtGui import QFont, QFontMetrics

    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel, _PresetCard

    old_stylesheet = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        panel = AnalysisPanel()
        qtbot.addWidget(panel)
        # BatchSheet enters compact mode at the supported 288 px pane width;
        # retain the 10 pt centred title while hiding the second text level.
        panel.set_compact_mode(True)
        panel.resize(288, 650)
        panel.show()
        qtbot.wait(20)

        for button in panel._preset_buttons.values():
            title_metrics = QFontMetrics(QFont(
                button.font().family(), _PresetCard._TITLE_POINT_SIZE,
                QFont.Bold,
            ))
            assert button.width() >= title_metrics.horizontalAdvance(button.text()) + 16
            assert button.property("compact") is True
            assert button.summary_visible() is False
            assert button.property("textAlignment") == "center"
    finally:
        panel.close()
        qapp.setStyleSheet(old_stylesheet)
