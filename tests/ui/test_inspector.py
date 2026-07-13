"""Tests for the Inspector skeleton (Phase 1) and section widgets (Phase 2)."""
import pytest

from mf4_analyzer.ui.inspector import Inspector


def test_inspector_constructs(qapp):
    insp = Inspector()
    assert insp is not None


def test_inspector_switch_mode_changes_contextual(qapp):
    insp = Inspector()
    insp.set_mode('time')
    assert insp.contextual_widget_name() == 'time'
    insp.set_mode('fft')
    assert insp.contextual_widget_name() == 'fft'
    insp.set_mode('order')
    assert insp.contextual_widget_name() == 'order'


# ---- Task 2.3: PersistentTop ----

def test_persistent_top_xaxis_mode_toggle(qapp):
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    assert pt.xaxis_mode() == 'time'
    pt.set_xaxis_mode('channel')
    assert pt.xaxis_mode() == 'channel'
    assert pt._combo_xaxis_ch.isEnabled()


def test_persistent_top_xaxis_channel_change_updates_auto_label(qapp):
    from mf4_analyzer.ui.inspector_sections import PersistentTop

    pt = PersistentTop()
    pt.set_xaxis_candidates([
        ("file speed", ("fid", "speed")),
        ("file angle", ("fid", "angle")),
    ])
    pt.set_xaxis_mode("channel")

    pt._combo_xaxis_ch.setCurrentIndex(1)

    assert pt.xaxis_label() == "angle"


def test_persistent_top_time_mode_clears_auto_channel_label(qapp):
    from mf4_analyzer.ui.inspector_sections import PersistentTop

    pt = PersistentTop()
    pt.set_xaxis_candidates([
        ("file speed", ("fid", "speed")),
        ("file angle", ("fid", "angle")),
    ])
    pt.set_xaxis_mode("channel")
    pt._combo_xaxis_ch.setCurrentIndex(1)
    assert pt.xaxis_label() == "angle"

    pt.set_xaxis_mode("time")

    assert pt.xaxis_label() == ""


def test_persistent_top_apply_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    with qtbot.waitSignal(pt.xaxis_apply_requested, timeout=200):
        pt.btn_apply_xaxis.click()


# ---- Task 2.4: TimeContextual ----

def test_time_contextual_plot_button_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import TimeContextual
    tc = TimeContextual()
    with qtbot.waitSignal(tc.plot_time_requested, timeout=200):
        tc.btn_plot.click()


def test_inspector_primary_buttons_share_section_width(qapp, qtbot):
    """Inspector primary buttons should share the same section button width."""
    from pathlib import Path

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )

        inspector = Inspector()
        qtbot.addWidget(inspector)
        inspector.resize(288, 900)
        inspector.set_mode("time")
        inspector.show()
        qtbot.waitExposed(inspector)
        qapp.processEvents()

        def rect_in_inspector(widget):
            top_left = widget.mapTo(inspector, widget.rect().topLeft())
            return top_left.x(), top_left.x() + widget.width(), widget.width()

        expected = rect_in_inspector(inspector.top.btn_apply_xaxis)
        assert rect_in_inspector(inspector.time_ctx.btn_plot) == expected

        for mode, ctx_name, button_name in (
            ("fft", "fft_ctx", "btn_fft"),
            ("fft_time", "fft_time_ctx", "btn_compute"),
            ("order", "order_ctx", "btn_ot"),
        ):
            inspector.set_mode(mode)
            qapp.processEvents()
            button = getattr(getattr(inspector, ctx_name), button_name)
            assert rect_in_inspector(button) == expected
    finally:
        qapp.setStyleSheet(old_sheet)


# ---- Task 2.5: FFTContextual ----

def test_fft_contextual_defaults(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    p = fc.get_params()
    assert p['window'] in ('hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop')
    assert 'nfft' in p
    assert 0 <= p['overlap'] <= 0.9
    assert isinstance(p['autoscale'], bool)


def test_fft_contextual_fft_button_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    with qtbot.waitSignal(fc.fft_requested, timeout=200):
        fc.btn_fft.click()


def test_fft_contextual_uses_xy_axis_settings_group(qapp):
    from PyQt5.QtWidgets import QFrame, QGroupBox
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    fc = FFTContextual()
    titles = {gb.title() for gb in fc.findChildren(QGroupBox)}

    assert "坐标轴设置" in titles
    assert "选项" not in titles
    for attr in (
        "chk_x_auto", "spin_x_min", "spin_x_max",
        "chk_y_auto", "spin_y_min", "spin_y_max",
    ):
        assert hasattr(fc, attr)
    assert fc.chk_autoscale is fc.chk_x_auto
    assert fc.chk_x_auto.isChecked()
    assert fc.chk_y_auto.isChecked()


def test_fft_contextual_xy_axis_params_round_trip(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    fc = FFTContextual()
    fc.chk_x_auto.setChecked(False)
    fc.spin_x_min.setValue(12.5)
    fc.spin_x_max.setValue(345.0)
    fc.chk_y_auto.setChecked(False)
    fc.spin_y_min.setValue(-20.0)
    fc.spin_y_max.setValue(3.0)

    params = fc.current_params()

    assert params["autoscale"] is False
    assert params["x_auto"] is False
    assert params["x_min"] == 12.5
    assert params["x_max"] == 345.0
    assert params["y_auto"] is False
    assert params["y_min"] == -20.0
    assert params["y_max"] == 3.0

    fc.apply_params({
        "autoscale": True,
        "x_min": 5.0,
        "x_max": 50.0,
        "y_auto": False,
        "y_min": -1.0,
        "y_max": 1.0,
    })

    assert fc.chk_x_auto.isChecked() is True
    assert fc.spin_x_min.value() == 5.0
    assert fc.spin_x_max.value() == 50.0
    assert fc.chk_y_auto.isChecked() is False
    assert fc.spin_y_min.value() == -1.0
    assert fc.spin_y_max.value() == 1.0


def test_fft_contextual_overlap_fraction_round_trip(qapp):
    """V10: get_params() emits overlap as a FRACTION (0.5); apply_params must
    accept a fraction (and percent) so a view/preset restore round-trips
    instead of int(0.5)==0 drifting the overlap toward 0%."""
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    fc = FFTContextual()
    # Fraction in -> fraction out (the regression: was int(0.5) -> 0%).
    fc.apply_params({"overlap": 0.5})
    assert fc.spin_overlap.value() == 50
    assert fc.get_params()["overlap"] == 0.5

    # A get/apply round-trip is stable for several fractions.
    for frac, pct in ((0.0, 0), (0.25, 25), (0.75, 75), (0.9, 90)):
        fc.apply_params({"overlap": frac})
        assert fc.spin_overlap.value() == pct
        assert fc.get_params()["overlap"] == frac

    # Backwards/percent path: a value > 1 is treated as already-percent.
    fc.apply_params({"overlap": 60})
    assert fc.spin_overlap.value() == 60
    assert fc.get_params()["overlap"] == 0.6

    # Non-numeric is tolerated (no crash, value unchanged).
    fc.spin_overlap.setValue(40)
    fc.apply_params({"overlap": None})
    assert fc.spin_overlap.value() == 40


# ---- Task 2.6: OrderContextual ----

def test_order_contextual_params(qapp):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    p = oc.get_params()
    for k in ('max_order', 'order_res', 'time_res', 'nfft'):
        assert k in p


def test_order_contextual_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    with qtbot.waitSignal(oc.order_time_requested, timeout=200):
        oc.btn_ot.click()


def test_analysis_compute_button_labels_are_consistent(qapp):
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
    )

    assert FFTContextual().btn_fft.text() == "计算 FFT"
    assert FFTTimeContextual().btn_compute.text() == "计算时频图"
    assert OrderContextual().btn_ot.text() == "计算阶次图"


def test_order_contextual_presets_precede_compute_and_no_cancel(qapp):
    from PyQt5.QtWidgets import QFrame, QGroupBox
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    oc = OrderContextual()

    # 2026-06-13 split: presets + compute action now share the params_card,
    # so order is asserted within that card's layout (not the root).
    params = oc.findChild(QFrame, "orderParamsCard")
    assert params is not None
    plan = params.layout()
    assert hasattr(oc, "_order_section")
    assert plan.indexOf(oc._order_section) < plan.indexOf(oc.btn_ot)
    assert oc.preset_bar.parentWidget() is not oc
    assert not any(gb.title() == "预设配置" for gb in oc.findChildren(QGroupBox))
    assert not hasattr(oc, "btn_cancel")
    assert not hasattr(oc, "cancel_requested")


def test_collapsible_param_section_defaults_collapsed_persists_and_keeps_persistent_visible(
    qtbot, tmp_path,
):
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QLabel, QToolButton
    from mf4_analyzer.ui.inspector_sections import _CollapsibleParamSection

    settings = QSettings(str(tmp_path / "inspector.ini"), QSettings.IniFormat)
    key = "tests/params_expanded"
    settings.remove(key)

    section = _CollapsibleParamSection("谱参数", key, settings=settings)
    persistent = QLabel("preset bar")
    body = QLabel("body controls")
    section.add_persistent(persistent)
    section.set_body(body)
    section.set_summary("2048 · hanning · 50%")

    qtbot.addWidget(section)
    section.resize(320, 140)
    section.show()
    qtbot.waitExposed(section)

    collapser = section.findChild(QToolButton, "inspectorCollapser")
    assert collapser is not None
    assert section.findChild(QLabel, "inspectorParamSummary").text() == (
        "2048 · hanning · 50%"
    )
    assert section.summary_text() == "2048 · hanning · 50%"
    assert section.is_expanded() is False
    assert persistent.isVisible()
    assert not body.isVisible()

    section.set_expanded(True)
    assert section.is_expanded() is True
    assert body.isVisible()
    settings.sync()

    restored = _CollapsibleParamSection("谱参数", key, settings=settings)
    restored_persistent = QLabel("restored preset")
    restored_body = QLabel("restored body")
    restored.add_persistent(restored_persistent)
    restored.set_body(restored_body)
    qtbot.addWidget(restored)
    restored.resize(320, 140)
    restored.show()
    qtbot.waitExposed(restored)

    assert restored.is_expanded() is True
    assert restored_persistent.isVisible()
    assert restored_body.isVisible()

    restored.set_expanded(False)
    assert restored.is_expanded() is False
    assert restored_persistent.isVisible()
    assert not restored_body.isVisible()


def test_collapsible_param_section_background_hosts_have_qss_contract(qapp):
    from pathlib import Path
    from PyQt5.QtWidgets import QFrame, QWidget
    from mf4_analyzer.ui.inspector_sections import _CollapsibleParamSection
    import mf4_analyzer.ui_kit as ui_kit

    section = _CollapsibleParamSection("谱参数", "tests/params_style_contract")

    hosts = [
        (section, "inspectorParamSection"),
        (section.findChild(QWidget, "inspectorParamHeader"), "inspectorParamHeader"),
        (
            section.findChild(QWidget, "inspectorParamPersistentHost"),
            "inspectorParamPersistentHost",
        ),
        (section.findChild(QFrame, "inspectorParamBody"), "inspectorParamBody"),
    ]
    for widget, object_name in hosts:
        assert widget is not None
        assert widget.objectName() == object_name

    qss = (Path(ui_kit.__file__).resolve().parent / "style.qss").read_text(
        encoding="utf-8"
    )
    for selector in (
        "Inspector QWidget#inspectorParamSection",
        "Inspector QWidget#inspectorParamHeader",
        "Inspector QWidget#inspectorParamPersistentHost",
        "Inspector QWidget#inspectorPresetBar",
        "Inspector QFrame#inspectorParamBody",
    ):
        assert selector in qss
    assert "background-color: transparent;" in qss[
        qss.index("Inspector QWidget#inspectorParamSection"):
        qss.index("Inspector QToolButton#inspectorCollapser")
    ]


def _param_section_summary(ctx, kind):
    if kind == "fft_time":
        return ctx._tf_summary_text()
    if kind == "fft":
        return ctx._fft_summary_text()
    return ctx._order_summary_text()


def _set_first_summary_field(ctx, kind):
    if kind == "fft_time":
        ctx.combo_nfft.setCurrentText("2048")
    elif kind == "fft":
        ctx.combo_nfft.setCurrentText("4096")
    else:
        ctx.spin_order_res.setValue(0.25)


def _mutate_non_summary_param(ctx, kind):
    if kind == "fft_time":
        ctx.chk_remove_mean.toggle()
    elif kind == "fft":
        ctx.combo_avg_mode.setCurrentIndex(1)
    else:
        ctx.spin_time_res.setValue(0.2)


def _preset_payload(ctx, kind):
    if kind == "fft_time":
        return {
            "nfft": "2048",
            "window": "flattop",
            "overlap": 75,
            "remove_mean": False,
        }
    if kind == "fft":
        return {
            "nfft": "4096",
            "window": "flattop",
            "overlap": 75,
            "avg_mode": ctx.combo_avg_mode.itemText(1),
        }
    return {
        "max_order": 30,
        "order_res": 0.25,
        "time_res": 0.2,
        "nfft": "4096",
        "samples_per_rev": 512,
    }


def _save_settings(settings, keys):
    return {
        key: (settings.contains(key), settings.value(key))
        for key in keys
    }


def _restore_settings(settings, saved):
    for key, (exists, value) in saved.items():
        if exists:
            settings.setValue(key, value)
        else:
            settings.remove(key)
    settings.sync()


@pytest.mark.parametrize(
    "kind, cls_name, section_attr, helper_name, title, settings_key",
    [
        (
            "fft_time",
            "FFTTimeContextual",
            "_tf_section",
            "is_tf_expanded",
            "时频参数",
            "inspector/fft_time/params_expanded",
        ),
        (
            "fft",
            "FFTContextual",
            "_fft_section",
            "is_fft_params_expanded",
            "谱参数",
            "inspector/fft/params_expanded",
        ),
        (
            "order",
            "OrderContextual",
            "_order_section",
            "is_order_params_expanded",
            "谱参数",
            "inspector/order/params_expanded",
        ),
    ],
)
def test_contextual_param_sections_are_merged_collapsed_and_summarized(
    qapp, qtbot, kind, cls_name, section_attr, helper_name, title, settings_key,
):
    from PyQt5.QtWidgets import QGroupBox, QToolButton
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
        _preset_settings,
    )

    classes = {
        "FFTTimeContextual": FFTTimeContextual,
        "FFTContextual": FFTContextual,
        "OrderContextual": OrderContextual,
    }
    settings = _preset_settings()
    saved = _save_settings(settings, [settings_key])
    settings.remove(settings_key)
    settings.sync()
    try:
        ctx = classes[cls_name]()
        qtbot.addWidget(ctx)
        ctx.resize(360, 760)
        ctx.show()
        qtbot.waitExposed(ctx)

        section = getattr(ctx, section_attr)
        collapser = section.findChild(QToolButton, "inspectorCollapser")
        assert collapser is not None
        assert collapser.text() == title
        assert section.is_expanded() is False
        assert getattr(ctx, helper_name)() is False
        assert ctx.preset_bar.objectName() == "inspectorPresetBar"
        assert ctx.preset_bar.isVisible()
        assert not ctx.combo_nfft.isVisible()
        assert section.summary_text() == _param_section_summary(ctx, kind)
        assert not any(
            gb.title() in {title, "预设", "预设配置"}
            for gb in ctx.findChildren(QGroupBox)
        )

        _set_first_summary_field(ctx, kind)
        assert section.summary_text() == _param_section_summary(ctx, kind)

        section.set_expanded(True)
        assert getattr(ctx, helper_name)() is True
        assert ctx.combo_nfft.isVisible()
    finally:
        _restore_settings(settings, saved)


@pytest.mark.parametrize(
    "kind, cls_name, settings_key",
    [
        ("fft_time", "FFTTimeContextual", "inspector/fft_time/params_expanded"),
        ("fft", "FFTContextual", "inspector/fft/params_expanded"),
        ("order", "OrderContextual", "inspector/order/params_expanded"),
    ],
)
def test_contextual_param_sections_preserve_and_clear_preset_highlight(
    qapp, qtbot, kind, cls_name, settings_key,
):
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
        _preset_settings,
    )

    classes = {
        "FFTTimeContextual": FFTTimeContextual,
        "FFTContextual": FFTContextual,
        "OrderContextual": OrderContextual,
    }
    settings = _preset_settings()
    keys = [settings_key] + [f"{kind}/preset_override/{slot}" for slot in (1, 2, 3)]
    saved = _save_settings(settings, keys)
    for key in keys:
        settings.remove(key)
    settings.sync()
    try:
        ctx = classes[cls_name]()
        qtbot.addWidget(ctx)

        ctx.preset_bar.set_recommended(1)
        _mutate_non_summary_param(ctx, kind)
        assert all(
            ctx.preset_bar._load_btns[slot].property("recommended") == "false"
            for slot in (1, 2, 3)
        )

        ctx.preset_bar.set_recommended(1)
        ctx._apply_preset(_preset_payload(ctx, kind))
        assert ctx.preset_bar._load_btns[1].property("recommended") == "true"
        assert ctx.preset_bar._load_btns[2].property("recommended") == "false"
        section_attr = {
            "fft_time": "_tf_section",
            "fft": "_fft_section",
            "order": "_order_section",
        }[kind]
        assert getattr(ctx, section_attr).summary_text() == _param_section_summary(ctx, kind)

        ctx.preset_bar.set_recommended(None)
        ctx.preset_bar._load(2)
        assert ctx.preset_bar._load_btns[2].property("applied") == "true"
        assert ctx.preset_bar._load_btns[2].property("recommended") == "false"
    finally:
        _restore_settings(settings, saved)


def test_fft_time_contextual_keeps_only_compute_action(qapp):
    from mf4_analyzer.ui.inspector import Inspector
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    assert ctx.btn_compute.text() == "计算时频图"
    for name in (
        "btn_force",
        "btn_export_full",
        "btn_export_main",
        "force_recompute_requested",
        "export_full_requested",
        "export_main_requested",
    ):
        assert not hasattr(ctx, name)

    insp = Inspector()
    for name in (
        "fft_time_force_requested",
        "fft_time_export_full_requested",
        "fft_time_export_main_requested",
    ):
        assert not hasattr(insp, name)


def test_inspector_no_longer_exposes_mode_signals(qapp):
    """Spec §9: after 2026-04-24 cleanup, Inspector no longer relays
    plot_mode_changed / cursor_mode_changed — those are on ChartStack now."""
    insp = Inspector()
    assert not hasattr(insp, 'plot_mode_changed')
    assert not hasattr(insp, 'cursor_mode_changed')


def test_persistent_top_no_longer_renders_tick_density_group(qapp):
    """刻度密度入口已迁移到图表 toolbar；Inspector 不再显示旧组。"""
    from PyQt5.QtWidgets import QFrame, QGroupBox
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()

    titles = {gb.title() for gb in pt.findChildren(QGroupBox)}
    assert "坐标刻度密度" not in titles
    assert "刻度密度" not in pt.btn_collapser.text()

    # Back-compat: existing state/project plumbing can still read the
    # tick-count values, but the legacy controls are no longer visible.
    parent_gb = pt.spin_xt.parentWidget()
    while parent_gb is not None and not isinstance(parent_gb, QGroupBox):
        parent_gb = parent_gb.parentWidget()
    assert parent_gb is None
    assert pt.spin_xt.isHidden() is True
    assert pt.spin_yt.isHidden() is True
    assert pt.tick_density() == (10, 10)


def test_inspector_exposes_fft_time_context(qtbot):
    from mf4_analyzer.ui.inspector import Inspector

    inspector = Inspector()
    qtbot.addWidget(inspector)
    inspector.set_mode('fft_time')

    assert inspector.current_mode() == 'fft_time'
    assert hasattr(inspector, 'fft_time_ctx')


# ---- Task 4: FFTTimeContextual real controls ----

def test_fft_time_context_returns_params(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.set_signal_candidates([("file:ch", ("f1", "ch"))])

    ctx.combo_nfft.setCurrentText('2048')
    ctx.combo_win.setCurrentText('hanning')
    ctx.spin_overlap.setValue(75)
    # Wave 4: combo_amp_mode replaced by combo_amp_unit (dB↔Linear) on
    # the Z axis row; B polish maps chk_freq_auto / spin_freq_min/max to
    # the Y-frequency row because FFT-vs-Time renders X=time, Y=frequency;
    # combo_dynamic replaced by spin_z_floor.
    ctx.combo_amp_unit.setCurrentText('dB')
    ctx.chk_freq_auto.setChecked(False)
    ctx.spin_freq_min.setValue(50.0)
    ctx.spin_freq_max.setValue(2400.0)
    ctx.spin_z_floor.setValue(-80.0)
    ctx.spin_z_ceiling.setValue(0.0)
    ctx.chk_z_auto.setChecked(False)

    params = ctx.get_params()

    assert params['nfft'] == 2048
    assert params['window'] == 'hanning'
    assert params['overlap'] == 0.75
    assert params['amplitude_mode'] == 'amplitude_db'
    assert params['freq_auto'] is False
    assert params['freq_min'] == 50.0
    assert params['freq_max'] == 2400.0
    # Legacy ``dynamic`` is now synthesised from spin_z_floor.
    assert params['dynamic'] == '80 dB'
    # Keys the FFT-vs-Time inspector get_params() must expose. Note
    # db_reference is here as a DISPLAY value (passed to plot_result), even
    # though it is NOT part of the compute cache key
    # (_fft_time_analysis_cache_key).
    for key in (
        'signal', 'fs', 'nfft', 'window', 'overlap', 'remove_mean',
        'amplitude_mode', 'db_reference', 'freq_auto', 'freq_min',
        'freq_max', 'dynamic', 'cmap',
    ):
        assert key in params


def test_fft_time_compute_button_tracks_signal_candidates(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert ctx.btn_compute.isEnabled() is False

    ctx.set_signal_candidates([("file:ch", ("f1", "ch"))])
    assert ctx.btn_compute.isEnabled() is True

    ctx.set_signal_candidates([])
    assert ctx.btn_compute.isEnabled() is False


def test_fft_time_signal_candidates_preserve_selection(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.set_signal_candidates([
        ("file:a", ("f1", "a")),
        ("file:b", ("f1", "b")),
    ])
    ctx.combo_sig.setCurrentIndex(1)
    assert ctx.current_signal() == ("f1", "b")

    # Re-supply candidates (e.g. opening another file). The previously
    # selected ("f1", "b") is still available and must remain selected.
    ctx.set_signal_candidates([
        ("file:a", ("f1", "a")),
        ("file:b", ("f1", "b")),
        ("file:c", ("f2", "c")),
    ])
    assert ctx.current_signal() == ("f1", "b")


def test_fft_time_context_builtin_presets(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    # 扭矩类: flattop / auto 2.5 s / 75% overlap / dB amplitude / Auto dynamic.
    ctx.apply_builtin_preset('torque')
    params = ctx.get_params()

    assert params['window'] == 'flattop'
    assert params['nfft'] is None
    assert params['nfft_mode'] == 'auto'
    assert params['t_win_s'] == 2.5
    assert params['overlap'] == 0.75
    assert params['amplitude_mode'] == 'amplitude_db'

    # 振动类(均衡): hanning / auto 1.5 s / 50% / dB / auto color,
    # with a 40 dB manual fallback.
    ctx.apply_builtin_preset('vibration')
    p_vib = ctx.get_params()
    assert p_vib['window'] == 'hanning'
    assert p_vib['nfft'] is None
    assert p_vib['nfft_mode'] == 'auto'
    assert p_vib['t_win_s'] == 1.5
    assert p_vib['overlap'] == 0.50
    assert p_vib['dynamic'] == 'Auto'
    assert p_vib['z_auto'] is True
    assert p_vib['z_floor'] == -40.0

    # 启停类(时间优先): hanning / auto 0.6 s / 75% / dB / auto color,
    # with a tighter 30 dB manual fallback.
    ctx.apply_builtin_preset('transient')
    p_tr = ctx.get_params()
    assert p_tr['window'] == 'hanning'
    assert p_tr['nfft'] is None
    assert p_tr['nfft_mode'] == 'auto'
    assert p_tr['t_win_s'] == 0.6
    assert p_tr['overlap'] == 0.75
    assert p_tr['dynamic'] == 'Auto'
    assert p_tr['z_auto'] is True
    assert p_tr['z_floor'] == -30.0


# ---- 紧凑化【1】同行并排：X+Y / 开始+结束 / 窗函数+NFFT / 频率下限+上限 ----

def _form_for(widget):
    """Walk parents to find the QFormLayout owning this widget."""
    from PyQt5.QtWidgets import QFormLayout
    p = widget.parentWidget()
    while p is not None:
        layout = p.layout()
        if isinstance(layout, QFormLayout):
            return layout
        p = p.parentWidget()
    return None


def _form_row_for(widget):
    """Return ``(form, row, target)`` where ``target`` is the topmost
    parent of ``widget`` that ``form`` indexes directly.

    Handles the row-pairing pattern where two controls live inside an
    inner host widget that the QFormLayout indexes as the row's field.
    """
    fl = _form_for(widget)
    if fl is None:
        return None, -1, None
    target = widget
    # Walk up until getWidgetPosition resolves a real row.
    while target is not None:
        row, _ = fl.getWidgetPosition(target)
        if row >= 0:
            return fl, row, target
        target = target.parentWidget()
    return fl, -1, None


def test_persistent_top_tick_controls_are_not_in_form_layout(qapp):
    """The hidden compatibility tick widgets must not reserve Inspector rows."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    fl_x, r_x, _ = _form_row_for(pt.spin_xt)
    fl_y, r_y, _ = _form_row_for(pt.spin_yt)
    assert fl_x is None
    assert fl_y is None
    assert r_x == r_y == -1


def test_persistent_top_range_share_one_form_row(qapp):
    """Range start/end must collapse into a single QFormLayout row."""
    from PyQt5.QtWidgets import QFormLayout
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    fl_s, r_s, _ = _form_row_for(pt.spin_start)
    fl_e, r_e, _ = _form_row_for(pt.spin_end)
    assert isinstance(fl_s, QFormLayout)
    assert fl_s is fl_e
    assert r_s == r_e >= 0


def test_fft_contextual_spectrum_params_three_rows(qapp):
    """FFT 谱参数: revert to three independent rows (R3 change A).

    R1 collapsed 窗函数 + NFFT into one inline pair, but the user found
    the inline layout cramped and asymmetric. We restore three rows so the
    section visually matches FFTTimeContextual's 时频参数 group: 窗函数 /
    NFFT / 重叠 each on its own row.
    """
    from PyQt5.QtWidgets import QFormLayout
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    fl_w, r_win, _ = _form_row_for(fc.combo_win)
    fl_n, r_nfft, _ = _form_row_for(fc.combo_nfft)
    fl_o, r_ov, _ = _form_row_for(fc.spin_overlap)
    assert isinstance(fl_w, QFormLayout)
    assert fl_w is fl_n is fl_o, "all three controls must live in one form"
    # Three distinct rows.
    rows = {r_win, r_nfft, r_ov}
    assert len(rows) == 3, f"expected three distinct rows, got {rows}"
    assert -1 not in rows


def test_fft_time_freq_min_max_share_one_axis_row(qtbot):
    """B polish: 频率下限/上限 live in the Y-frequency row of the
    坐标轴设置 group as spin_y_min / spin_y_max
    (aliased back to spin_freq_min / spin_freq_max). The old "share one
    form row" contract becomes "share one axis row widget" → both spins
    sit inside the same direct parent QWidget host built by
    ``_build_axis_row``.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert ctx.spin_freq_min is ctx.spin_y_min
    assert ctx.spin_freq_max is ctx.spin_y_max
    assert ctx.spin_freq_min.parentWidget() is ctx.spin_freq_max.parentWidget()


# ---- 紧凑化【2】条件可见 (hide rows entirely when not relevant) ----

def _row_is_hidden(form, field_widget):
    """Treat a row as hidden iff the field's containing row widget is hidden.

    Falls back to checking the field widget itself if no row container is
    present.
    """
    # Walk up to the field's row container (either the widget supplied
    # directly to addRow, or the QWidget wrapping a layout-as-field).
    target = field_widget
    return target.isHidden()


def test_persistent_top_xaxis_channel_row_hidden_when_auto(qapp):
    """When 来源 == 自动(时间), the 通道 row should be hidden, not just disabled."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    pt.show()
    try:
        channel_field_host = pt._combo_xaxis_ch.parentWidget()
        channel_label = pt._xaxis_form.labelForField(channel_field_host)
        assert channel_label is not None
        # Default index is 0 = 自动(时间)
        assert pt.combo_xaxis.currentIndex() == 0
        assert pt._combo_xaxis_ch.isHidden(), \
            "通道 combo should be hidden when 来源 == 自动(时间)"
        assert channel_label.isHidden(), \
            "通道 label should be hidden with the channel combo row"
        # Switch to 指定通道 → row reveals
        pt.combo_xaxis.setCurrentIndex(1)
        assert not pt._combo_xaxis_ch.isHidden()
        assert not channel_label.isHidden()
        # Back to auto → hidden again
        pt.combo_xaxis.setCurrentIndex(0)
        assert pt._combo_xaxis_ch.isHidden()
        assert channel_label.isHidden()
    finally:
        pt.hide()


def test_persistent_top_range_rows_stay_visible_when_unchecked(qapp):
    """The time-range fields stay visible; the checkbox only gates filtering."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    pt.show()
    try:
        # Default state: unchecked means "do not filter", not "hide fields".
        assert not pt.chk_range.isChecked()
        assert not pt.spin_start.isHidden()
        assert not pt.spin_end.isHidden()
        # Toggle on → row visible.
        pt.chk_range.setChecked(True)
        assert not pt.spin_start.isHidden()
        assert not pt.spin_end.isHidden()
        # Toggle off keeps the current values visible for reference.
        pt.chk_range.setChecked(False)
        assert not pt.spin_start.isHidden()
        assert not pt.spin_end.isHidden()
    finally:
        pt.hide()


def test_fft_time_freq_spins_disabled_when_auto(qtbot):
    """Wave 4: when 自动 (chk_x_auto / chk_freq_auto alias) is on (default),
    the freq spins must be DISABLED (not hidden). The new inline 坐标轴设置
    group keeps every row visible at all times so the user can see the
    full X/Y/Z structure; the auto checkbox only toggles the spinbox
    enabled state via _sync_axis_enabled.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.show()
    try:
        assert ctx.chk_freq_auto.isChecked()
        assert not ctx.spin_freq_min.isEnabled()
        assert not ctx.spin_freq_max.isEnabled()
        ctx.chk_freq_auto.setChecked(False)
        assert ctx.spin_freq_min.isEnabled()
        assert ctx.spin_freq_max.isEnabled()
        ctx.chk_freq_auto.setChecked(True)
        assert not ctx.spin_freq_min.isEnabled()
        assert not ctx.spin_freq_max.isEnabled()
    finally:
        ctx.hide()


# ---- 紧凑化【3】行间距收紧 ----

def test_configure_form_compact_spacing(qapp):
    """_configure_form must apply the tightened H=6 V=4 spacing."""
    from PyQt5.QtWidgets import QFormLayout
    from mf4_analyzer.ui.inspector_sections import _configure_form
    fl = QFormLayout()
    _configure_form(fl)
    assert fl.horizontalSpacing() == 6
    assert fl.verticalSpacing() == 4


def test_persistent_top_root_spacing_compact(qapp):
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    assert pt.layout().spacing() == 6


# 2026-06-13 分析信号/谱参数 split: the contextual root now holds just two
# stacked cards, so its spacing is the 8px gutter between them; the compact
# 6px group rhythm moved into the lower params_card.
def test_fft_contextual_root_spacing_compact(qapp):
    from PyQt5.QtWidgets import QFrame
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    assert fc.layout().spacing() == 8
    params = fc.findChild(QFrame, "fftParamsCard")
    assert params is not None and params.layout().spacing() == 6


def test_order_contextual_root_spacing_compact(qapp):
    from PyQt5.QtWidgets import QFrame
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    assert oc.layout().spacing() == 8
    params = oc.findChild(QFrame, "orderParamsCard")
    assert params is not None and params.layout().spacing() == 6


def test_fft_time_contextual_root_spacing_compact(qtbot):
    from PyQt5.QtWidgets import QFrame
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert ctx.layout().spacing() == 8
    params = ctx.findChild(QFrame, "fftTimeParamsCard")
    assert params is not None and params.layout().spacing() == 6


# ---- R3 #3-B: GroupBox title 紧凑+下划线分隔 ----

def test_inspector_groupbox_title_has_underline_and_compact_padding():
    """Inspector QGroupBox::title rule must carry a 1px hairline underline
    and the tightened 12px / 600 weight typography (R3 #3-B).
    """
    from pathlib import Path
    qss_path = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui_kit" / "style.qss"
    qss = qss_path.read_text(encoding="utf-8")
    # Find the Inspector QGroupBox::title block.
    import re
    m = re.search(
        r"Inspector\s+QGroupBox::title\s*\{([^}]*)\}", qss, flags=re.DOTALL,
    )
    assert m, "Inspector QGroupBox::title rule not found"
    block = m.group(1)
    assert "border-bottom" in block, \
        "title block must include a border-bottom hairline (R3 #3-B)"
    assert "font-size: 12px" in block, \
        "title font-size must drop from 13px to 12px (R3 #3-B)"
    assert "font-weight: 600" in block, \
        "title font-weight must drop from 700 to 600 (R3 #3-B)"


def test_combo_popup_style_removes_native_outer_focus_frame():
    """Combo popups draw their rounded selection in QSS; Qt's native
    focus rectangle must be suppressed while the custom rounded list border
    remains visible.
    """
    from pathlib import Path
    import re

    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    popup = re.search(
        r"QComboBox\s+QAbstractItemView\s*\{([^}]*)\}",
        qss,
        flags=re.DOTALL,
    )
    assert popup, "QComboBox popup item-view rule not found"
    popup_block = popup.group(1)
    assert "outline: none" in popup_block or "outline: 0" in popup_block
    assert "border: 1px solid #cbd5e1;" in popup_block
    assert (
        "background-color: transparent" in popup_block
        or "background: transparent" in popup_block
    )

    selected = re.search(
        r"QComboBox\s+QAbstractItemView::item:selected[^{]*\{([^}]*)\}",
        qss,
        flags=re.DOTALL,
    )
    assert selected, "QComboBox selected-item popup rule not found"
    selected_block = selected.group(1)
    assert "border: none" in selected_block
    assert "border-radius" in selected_block


# ---- R3 #6: PersistentTop collapser ----

def test_persistent_top_has_collapser(qapp):
    """PersistentTop must wrap its three groups in a single collapsible
    container that defaults to expanded.
    """
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    # The collapser persists its state in QSettings; clear it so this test
    # does not depend on whatever a previous run / fixture left behind.
    settings = QSettings("MF4Analyzer", "DataAnalyzer")
    settings.remove("inspector/persistent_top/expanded")
    settings.remove("inspector/persistent_top/expanded_v2")
    pt = PersistentTop()
    assert hasattr(pt, "btn_collapser"), \
        "PersistentTop must expose btn_collapser (the toggle handle)"
    assert hasattr(pt, "_collapser_body"), \
        "PersistentTop must expose _collapser_body (the inner container)"
    # Default: expanded, so the time-domain settings are immediately visible.
    assert pt.btn_collapser.isChecked() is True
    assert pt._collapser_body.isHidden() is False
    pt.show()
    try:
        qapp.processEvents()
        assert pt._collapser_body.isVisible() is True
    finally:
        pt.hide()


def test_persistent_top_collapser_toggle_reveals_groups(qapp):
    """Toggling the collapser must reveal the inner three groups while
    keeping every documented attribute reachable (programmatic access works
    even when the body is hidden).
    """
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    settings = QSettings("MF4Analyzer", "DataAnalyzer")
    settings.remove("inspector/persistent_top/expanded")
    settings.remove("inspector/persistent_top/expanded_v2")
    pt = PersistentTop()
    # Programmatic access works regardless of visibility — preserves contract.
    for attr in (
        "spin_xt", "spin_yt", "chk_range", "spin_start", "spin_end",
        "combo_xaxis", "_combo_xaxis_ch", "edit_xlabel", "btn_apply_xaxis",
    ):
        assert getattr(pt, attr) is not None, f"missing attr: {attr}"
    pt.show()
    try:
        qapp.processEvents()
        assert pt._collapser_body.isVisible() is True
        # Toggle collapse.
        pt.btn_collapser.setChecked(False)
        assert pt._collapser_body.isHidden() is True
        # Toggle expand.
        pt.btn_collapser.setChecked(True)
        assert pt._collapser_body.isVisible() is True
        # Group-level controls still visible; migrated tick controls stay out
        # of the Inspector even when the body is expanded.
        assert pt.combo_xaxis.isVisible() is True
        assert pt.spin_start.isVisible() is True
        assert pt.spin_xt.isHidden() is True
        assert pt.spin_yt.isHidden() is True
    finally:
        pt.hide()


def test_inspector_hides_persistent_top_for_analysis_modes(qapp, qtbot):
    """Analysis modes own their time/axis controls inside contextual cards, so
    the global time-domain chart settings block should not take space."""
    from PyQt5.QtWidgets import QGroupBox
    from mf4_analyzer.ui.inspector import Inspector

    inspector = Inspector()
    qtbot.addWidget(inspector)
    inspector.show()
    try:
        qapp.processEvents()
        xaxis_group = next(
            group for group in inspector.top.findChildren(QGroupBox)
            if group.title() == "横坐标"
        )

        inspector.set_mode("time")
        assert xaxis_group.isVisible() is True
        assert "横坐标" in inspector.top.btn_collapser.text()

        inspector.set_mode("fft")
        assert inspector.top.isHidden() is True

        inspector.set_mode("order")
        assert inspector.top.isHidden() is True

        inspector.set_mode("fft_time")
        assert inspector.top.isHidden() is True
    finally:
        inspector.hide()


# ---- R3 #8: PresetBar single-row + right-click save ----

def test_preset_bar_single_row_three_buttons(qapp):
    """PresetBar must render exactly 3 buttons (down from 6) and route
    save through the right-click menu (R3 #8).
    """
    from PyQt5.QtWidgets import QPushButton
    from mf4_analyzer.ui.inspector_sections import PresetBar
    bar = PresetBar('test_kind_single', lambda: {}, lambda d: None)
    btns = bar.findChildren(QPushButton)
    assert len(btns) == 3, \
        f"expected 3 preset buttons, got {len(btns)}: {[b.text() for b in btns]}"
    # No save buttons survive — the contract moves save to the menu.
    assert not hasattr(bar, "_save_btns") or not bar._save_btns


def test_preset_bar_right_click_menu_includes_save(qapp, monkeypatch):
    """Right-click on any slot must surface a "保存当前到本槽位" entry
    (and rename / clear), even on empty slots — empty-slot save is the
    primary interaction now that the standalone save row is gone.
    """
    from PyQt5.QtWidgets import QMenu
    from mf4_analyzer.ui.inspector_sections import PresetBar
    bar = PresetBar('test_kind_menu', lambda: {"x": 1}, lambda d: None)
    captured = {}

    class _StubMenu(QMenu):
        def exec_(self, *a, **kw):
            captured["actions"] = [a.text() for a in self.actions()]
            return None

    monkeypatch.setattr(
        "mf4_analyzer.ui.inspector_sections.QMenu", _StubMenu,
    )
    bar._show_menu(1, bar._load_btns[1].rect().center())
    actions = captured.get("actions", [])
    save_seen = any("保存" in a for a in actions)
    rename_seen = any("重命名" in a for a in actions)
    clear_seen = any("清空" in a for a in actions)
    assert save_seen, f"save action missing from menu: {actions}"
    assert rename_seen, f"rename action missing: {actions}"
    assert clear_seen, f"clear action missing: {actions}"


def test_preset_bar_acknowledged_signal_preserved(qapp, qtbot):
    """The acknowledged(level, msg) signal contract must still fire on
    save (this is what Inspector relays to the toast)."""
    from mf4_analyzer.ui.inspector_sections import PresetBar
    bar = PresetBar('test_kind_ack', lambda: {"x": 1}, lambda d: None)
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.acknowledged, timeout=300):
        bar._save(1)
    bar._delete(1)  # cleanup QSettings


def test_preset_bar_summary_uses_name_value_colours(qapp):
    from mf4_analyzer.ui.inspector_sections import PresetBar

    bar = PresetBar('test_kind_summary', lambda: {}, lambda d: None)
    html = bar._format_summary('配置 1', {
        'window': 'hanning',
        'nfft': '4096',
        'x_auto': False,
    })

    assert html.startswith('<html>')
    assert 'color:#61708a' in html
    assert 'color:#0b73e7' in html
    assert '窗函数' in html
    assert 'hanning' in html
    assert 'X 自动' in html
    assert '否' in html


def test_preset_bar_uses_custom_hover_card_instead_of_qtooltip(qapp, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QFrame, QLabel
    from mf4_analyzer.ui.inspector_sections import PresetBar

    current = lambda: {
        'window': 'hanning',
        'nfft': '4096',
        'overlap': 50,
        'x_auto': False,
        'x_min': 0.0,
        'x_max': 600.0,
        'z_auto': False,
        'z_floor': -80.0,
        'z_ceiling': 0.0,
    }
    bar = PresetBar('test_kind_hover_card', current, lambda d: None)
    qtbot.addWidget(bar)
    bar._write(1, '配置1', current())
    bar._refresh_states()

    assert bar._load_btns[1].toolTip() == ''
    bar._show_hover(1)

    assert bar._hover_card.isVisible()
    assert bar._hover_card.objectName() == 'presetHoverCard'
    assert bar._hover_card.testAttribute(Qt.WA_TranslucentBackground)
    assert int(bar._hover_card.windowFlags()) & int(Qt.NoDropShadowWindowHint)
    panel = bar._hover_card.findChild(QFrame, 'presetHoverPanel')
    assert panel is not None
    assert panel.testAttribute(Qt.WA_StyledBackground)
    assert bar._hover_card.findChild(QLabel, 'presetHoverTitle').text() == '配置1'
    chips = [c.text() for c in bar._hover_card.findChildren(QLabel, 'presetChip')]
    assert any('窗函数' in c and 'hanning' in c for c in chips)
    assert any('NFFT' in c and '4096' in c for c in chips)
    assert any('X' in c and '0 → 600' in c for c in chips)
    bar._hide_hover()
    bar._delete(1)


def test_tooltip_qss_does_not_draw_square_outer_frame(qapp):
    """App-wide tooltips use the glass popup, so QSS must not restyle
    native QToolTip chrome back into a square painted surface.
    """
    import re
    from pathlib import Path

    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui_kit.glass_tooltip import _GlassTooltipPopup

    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    native_tooltip_rules = re.findall(
        r"(?m)(?:^|[,{]\s*)QToolTip\b[^{]*\{",
        qss,
    )

    assert native_tooltip_rules == []

    popup = _GlassTooltipPopup.instance()
    assert popup.testAttribute(Qt.WA_TranslucentBackground)
    flags = popup.windowFlags()
    assert bool(flags & Qt.ToolTip)
    assert bool(flags & Qt.FramelessWindowHint)


# ---- R3 #9: rebuild button moved to group header ----

def test_fft_rebuild_lives_in_header_not_fs_row(qapp):
    """btn_rebuild must NOT be a child of the Fs form row (R3 #9).

    The new layout puts btn_rebuild on the group's header bar (right
    side), not on the Fs spinner row.
    """
    from PyQt5.QtWidgets import QHBoxLayout
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    # btn_rebuild must still exist (signal contract preserved).
    assert hasattr(fc, "btn_rebuild")
    # Walk parents — the immediate parent layout MUST NOT include spin_fs.
    rebuild_parent = fc.btn_rebuild.parentWidget()
    spin_fs_parent = fc.spin_fs.parentWidget()
    # The two should now live in distinct parent widgets, since the Fs row
    # no longer contains the rebuild button.
    assert rebuild_parent is not spin_fs_parent, \
        "btn_rebuild and spin_fs must no longer share a parent widget (R3 #9)"


def test_order_rebuild_lives_in_header_not_fs_row(qapp):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    assert hasattr(oc, "btn_rebuild")
    rebuild_parent = oc.btn_rebuild.parentWidget()
    spin_fs_parent = oc.spin_fs.parentWidget()
    assert rebuild_parent is not spin_fs_parent, \
        "btn_rebuild and spin_fs must no longer share a parent widget (R3 #9)"


def test_fft_time_rebuild_lives_in_header_not_fs_row(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert hasattr(ctx, "btn_rebuild")
    rebuild_parent = ctx.btn_rebuild.parentWidget()
    spin_fs_parent = ctx.spin_fs.parentWidget()
    assert rebuild_parent is not spin_fs_parent, \
        "btn_rebuild and spin_fs must no longer share a parent widget (R3 #9)"


# ---- R3 B: OrderContextual labels stay on a single line ----

def test_order_contextual_labels_have_minimum_width(qapp):
    """In OrderContextual, every QFormLayout label must carry a
    minimumWidth large enough to fit its natural sizeHint width — this
    prevents the form's label column from collapsing the long Chinese
    labels (e.g. "阶次分辨率:") under narrow pane widths (R3 B).
    """
    from PyQt5.QtWidgets import QFormLayout, QLabel
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    forms = oc.findChildren(QFormLayout)
    assert forms, "OrderContextual must contain at least one QFormLayout"
    labels = []
    for fl in forms:
        for r in range(fl.rowCount()):
            item = fl.itemAt(r, QFormLayout.LabelRole)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, QLabel) and w.text().strip():
                labels.append(w)
    assert labels, "no QFormLayout labels found in OrderContextual"
    for lbl in labels:
        natural = lbl.sizeHint().width()
        # The label must declare a minimumWidth at least as wide as its
        # natural sizeHint (otherwise the form column may squeeze it,
        # causing the visible label to elide or — with wordWrap — wrap).
        assert lbl.minimumWidth() >= natural, (
            f"label {lbl.text()!r} minimumWidth={lbl.minimumWidth()}px "
            f"is below sizeHint width {natural}px — column may collapse "
            "and elide / wrap the label"
        )


def test_order_contextual_field_widgets_have_max_width(qapp):
    """OrderContextual fields must cap their max width so the form's
    label column gets the slack it needs for long Chinese labels (R3 B).
    """
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    fields = [
        oc.spin_mo, oc.spin_order_res, oc.spin_time_res,
        oc.combo_nfft, oc.spin_rf,
    ]
    for f in fields:
        # 16777215 is QWIDGETSIZE_MAX (no cap). We need a real cap.
        assert f.maximumWidth() < 16777215, (
            f"field {f.objectName() or type(f).__name__} has no maximumWidth "
            "cap — it will steal horizontal space from the label column "
            "(R3 B fix)"
        )


# ---- R3 C: FFTTime presets become PresetBar with builtin defaults ----

def test_fft_time_presets_use_preset_bar(qtbot):
    """FFTTimeContextual must expose a preset_bar (same class as FFT/Order)
    and must NOT carry the legacy btn_preset_diag / amp / hf attributes
    (R3 C — confirmed no external references via grep).
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual, PresetBar
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert hasattr(ctx, "preset_bar"), \
        "FFTTimeContextual must now own a preset_bar"
    assert isinstance(ctx.preset_bar, PresetBar)
    # Legacy three buttons gone.
    assert not hasattr(ctx, "btn_preset_diag")
    assert not hasattr(ctx, "btn_preset_amp")
    assert not hasattr(ctx, "btn_preset_hf")


def test_fft_time_preset_bar_default_button_names_match_builtins(qtbot):
    """Default button labels for the FFTTime preset bar must read as the
    shared signal-type display names: 频率优先 / 均衡 / 时间优先."""
    from PyQt5.QtWidgets import QPushButton
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    # Use a fresh QSettings org/app per test by wiping any prior overrides
    from PyQt5.QtCore import QSettings
    s = QSettings("MF4Analyzer", "DataAnalyzer")
    for slot in (1, 2, 3):
        s.remove(f"fft_time/preset_override/{slot}")
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    btns = ctx.preset_bar.findChildren(QPushButton)
    texts = [b.text() for b in btns]
    assert "频率优先" in texts
    assert "均衡" in texts
    assert "时间优先" in texts


def test_fft_time_preset_bar_menu_includes_reset_to_default(qtbot, monkeypatch):
    """Builtin-aware PresetBar must surface "重置为默认" in its right-click
    menu (R3 C). FFT/Order PresetBar (no builtin) must NOT show that entry.
    """
    from PyQt5.QtWidgets import QMenu
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual, PresetBar
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    captured = {}

    class _StubMenu(QMenu):
        def exec_(self, *a, **kw):
            captured["actions"] = [a.text() for a in self.actions()]
            return None

    monkeypatch.setattr(
        "mf4_analyzer.ui.inspector_sections.QMenu", _StubMenu,
    )
    ctx.preset_bar._show_menu(1, ctx.preset_bar._load_btns[1].rect().center())
    actions = captured.get("actions", [])
    assert any("重置" in a for a in actions), \
        f"reset-to-default missing from FFTTime preset menu: {actions}"
    # FFT bar (no builtin) must NOT show reset.
    captured.clear()
    plain_bar = PresetBar('fft_no_builtin', lambda: {}, lambda d: None)
    plain_bar._show_menu(1, plain_bar._load_btns[1].rect().center())
    plain_actions = captured.get("actions", [])
    assert not any("重置" in a for a in plain_actions), \
        f"plain bar must not show reset-to-default: {plain_actions}"


def test_fft_time_preset_bar_save_overrides_builtin(qtbot):
    """Saving over a slot persists user values; loading then applies the
    override (not the builtin)."""
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    s = QSettings("MF4Analyzer", "DataAnalyzer")
    for slot in (1, 2, 3):
        s.remove(f"fft_time/preset_override/{slot}")
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    # Set distinctive params, save to slot 1.
    ctx.combo_nfft.setCurrentText('512')
    ctx.combo_win.setCurrentText('blackman')
    ctx.spin_overlap.setValue(33)
    ctx.preset_bar._save(1)
    # Mutate, then load from slot 1 — values should restore.
    ctx.combo_nfft.setCurrentText('8192')
    ctx.combo_win.setCurrentText('hanning')
    ctx.spin_overlap.setValue(80)
    ctx.preset_bar._load(1)
    assert ctx.combo_nfft.currentText() == '512'
    assert ctx.combo_win.currentText() == 'blackman'
    assert ctx.spin_overlap.value() == 33
    # Cleanup so subsequent runs start clean.
    s.remove(f"fft_time/preset_override/1")


def test_fft_time_preset_bar_reset_restores_builtin(qtbot):
    """Reset-to-default removes the override; subsequent load applies the
    original builtin params (R3 C)."""
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    s = QSettings("MF4Analyzer", "DataAnalyzer")
    for slot in (1, 2, 3):
        s.remove(f"fft_time/preset_override/{slot}")
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    # Save an override on slot 1 (the 扭矩类 slot).
    ctx.combo_nfft.setCurrentText('512')
    ctx.preset_bar._save(1)
    # Reset slot 1.
    ctx.preset_bar._reset_to_default(1)
    # Mutate then load slot 1 — should now apply the builtin 扭矩类 preset
    # (auto NFFT, window=flattop, overlap=75).
    ctx.combo_nfft.setCurrentText('8192')
    ctx.combo_win.setCurrentText('blackman')
    ctx.spin_overlap.setValue(10)
    ctx.preset_bar._load(1)
    assert ctx.combo_nfft.currentText() == '自动'
    assert ctx._t_win_s == 2.5
    assert ctx.combo_win.currentText() == 'flattop'
    assert ctx.spin_overlap.value() == 75


def test_fft_time_apply_builtin_preset_still_accepts_legacy_keys(qtbot):
    """Legacy FFT-time preset keys map to the closest new signal-type preset."""
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert callable(getattr(ctx, "apply_builtin_preset", None))

    ctx.apply_builtin_preset('amplitude_accuracy')
    p = ctx.get_params()
    assert p['window'] == 'flattop'
    assert p['nfft'] is None
    assert p['nfft_mode'] == 'auto'
    assert p['t_win_s'] == 2.5

    ctx.apply_builtin_preset('diagnostic')
    p = ctx.get_params()
    assert p['nfft'] is None
    assert p['nfft_mode'] == 'auto'
    assert p['t_win_s'] == 1.5
    assert p['window'] == 'hanning'
    assert p['overlap'] == 0.50

    ctx.apply_builtin_preset('high_frequency')
    p = ctx.get_params()
    assert p['nfft'] is None
    assert p['nfft_mode'] == 'auto'
    assert p['t_win_s'] == 0.6
    assert p['dynamic'] == 'Auto'
    assert p['z_floor'] == -30.0


def test_fft_time_preset_collects_explicit_xyz_axes(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.chk_x_auto.setChecked(False)
    ctx.spin_x_min.setValue(1.0)
    ctx.spin_x_max.setValue(2.5)
    ctx.chk_y_auto.setChecked(False)
    ctx.spin_y_min.setValue(20.0)
    ctx.spin_y_max.setValue(600.0)
    ctx.chk_z_auto.setChecked(False)
    ctx.spin_z_floor.setValue(-70.0)
    ctx.spin_z_ceiling.setValue(-5.0)

    p = ctx._collect_preset()

    for key in (
        'x_auto', 'x_min', 'x_max',
        'y_auto', 'y_min', 'y_max',
        'z_auto', 'z_floor', 'z_ceiling',
    ):
        assert key in p
    assert p['x_auto'] is False
    assert p['x_min'] == 1.0
    assert p['x_max'] == 2.5
    assert p['y_auto'] is False
    assert p['y_min'] == 20.0
    assert p['y_max'] == 600.0
    assert p['z_auto'] is False
    assert p['z_floor'] == -70.0
    assert p['z_ceiling'] == -5.0


def test_order_preset_collects_explicit_xyz_axes(qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    ctx = OrderContextual()
    qtbot.addWidget(ctx)
    ctx.chk_x_auto.setChecked(False)
    ctx.spin_x_min.setValue(0.5)
    ctx.spin_x_max.setValue(3.0)
    ctx.chk_y_auto.setChecked(False)
    ctx.spin_y_min.setValue(1.0)
    ctx.spin_y_max.setValue(8.0)
    ctx.combo_amp_unit.setCurrentText('Linear')
    ctx.chk_z_auto.setChecked(False)
    ctx.spin_z_floor.setValue(-20.0)
    ctx.spin_z_ceiling.setValue(4.0)

    p = ctx._collect_preset()

    for key in (
        'amplitude_mode',
        'x_auto', 'x_min', 'x_max',
        'y_auto', 'y_min', 'y_max',
        'z_auto', 'z_floor', 'z_ceiling',
    ):
        assert key in p
    assert p['amplitude_mode'] == 'Amplitude'
    assert p['x_auto'] is False
    assert p['x_min'] == 0.5
    assert p['x_max'] == 3.0
    assert p['y_auto'] is False
    assert p['y_min'] == 1.0
    assert p['y_max'] == 8.0
    assert p['z_auto'] is False
    assert p['z_floor'] == -20.0
    assert p['z_ceiling'] == 4.0


# ---- 2026-04-26 R3 紧凑化 视觉一致性修正 ----

def test_inspector_scroll_body_caps_max_width(qapp):
    """fix-1 — Inspector content must cap its maxWidth so Expanding
    children stop growing past a sane threshold when the splitter pane
    is dragged wider than the docked width. Without the cap, every
    Expanding QSpinBox / QComboBox stretches to fill the entire pane width.
    """
    from mf4_analyzer.ui.inspector import Inspector
    insp = Inspector()
    cap = insp._scroll_body.maximumWidth()
    # 16777215 == QWIDGETSIZE_MAX, i.e. uncapped.
    assert cap < 16777215, (
        "Inspector._scroll_body has no maximumWidth cap — Expanding "
        "children will grow unbounded when the splitter widens."
    )
    assert cap <= 320, (
        f"Inspector._scroll_body.maximumWidth()={cap}px is too generous; "
        "should be ~272 to keep the form column tight (288px pane)."
    )


def test_persistent_top_range_spinners_have_max_width(qapp):
    """A1 — range spinners share the normal inspector field cap."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    for sp in (pt.spin_start, pt.spin_end):
        assert 200 <= sp.maximumWidth() <= 260, (
            f"{sp.objectName() or type(sp).__name__}.maximumWidth()="
            f"{sp.maximumWidth()}px — should use the A1 field cap."
        )


def test_fft_contextual_fields_use_uniform_max_width(qapp):
    """A1 — FFTContextual fields use the same full field-column cap."""
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    fields = (fc.combo_sig, fc.spin_overlap, fc.spin_fs,
              fc.combo_nfft, fc.combo_win)
    widths = [w.maximumWidth() for w in fields]
    assert max(widths) - min(widths) <= 2, (
        f"FFTContextual fields should share one max width; got {widths}"
    )
    for w in fields:
        assert 200 <= w.maximumWidth() <= 260, (
            f"FFTContextual field {w.objectName() or type(w).__name__}"
            f" maximumWidth={w.maximumWidth()}px should use the A1 cap."
        )


def test_fft_contextual_signal_combo_keeps_room_for_long_names(qapp):
    """fix-3 — combo_sig is the long-text exception: signal names like
    'sample.csv :: lateral_acceleration' are routinely 30+ chars, so
    the combo's maxWidth (if any) must stay generous (>=200px).
    """
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    mw = fc.combo_sig.maximumWidth()
    # 16777215 (uncapped) is fine for the long-text exception, OR a cap >= 200.
    assert mw >= 200, (
        f"FFTContextual.combo_sig maximumWidth={mw}px is too tight for "
        "long signal names (R3 紧凑化)."
    )


def test_order_contextual_short_numeric_fields_capped_tighter(qapp):
    """A1 — OrderContextual fields share the normal inspector field cap."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    for w in (oc.spin_mo, oc.spin_order_res, oc.spin_time_res,
              oc.spin_rf):
        assert 200 <= w.maximumWidth() <= 260, (
            f"OrderContextual field {w.objectName() or type(w).__name__}"
            f" maximumWidth={w.maximumWidth()}px should use the A1 cap."
        )


def test_fft_time_contextual_short_fields_capped(qapp):
    """A1 — FFTTimeContextual fields share the normal field cap.

    Wave 4: combo_amp_mode + combo_dynamic dropped; spin_freq_min/max are
    now hosted in the inline 坐标轴设置 group (capped at 72px by the
    helper, NOT the QFormLayout field cap), so they're excluded here.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    for w in (ctx.spin_overlap, ctx.spin_fs, ctx.combo_nfft, ctx.combo_win,
              ctx.spin_db_ref):
        assert 200 <= w.maximumWidth() <= 260, (
            f"FFTTimeContextual field "
            f"{w.objectName() or type(w).__name__} maximumWidth="
            f"{w.maximumWidth()}px should use the A1 cap."
        )


def test_inspector_body_fills_288_width_under_qss(qapp, qtbot):
    """Styled Inspector body should fill the 288px right pane."""
    from pathlib import Path
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        insp = Inspector()
        qtbot.addWidget(insp)
        insp.resize(288, 850)
        insp.show()
        qtbot.waitExposed(insp)
        qtbot.wait(50)

        assert insp.width() == 288
        assert insp._scroll_body.width() >= 268, (
            f"Inspector body should fill a 288px pane; body="
            f"{insp._scroll_body.width()}, viewport={insp._scroll.viewport().width()}"
        )
    finally:
        qapp.setStyleSheet(old_sheet)


def test_fft_contextual_fields_fill_column_under_qss(qapp, qtbot):
    """A1 layout: FFT fields share the full field-column width."""
    from pathlib import Path
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        insp = Inspector()
        qtbot.addWidget(insp)
        insp.resize(360, 850)
        insp.set_mode('fft')
        insp.show()
        qtbot.waitExposed(insp)
        qtbot.wait(50)

        ctx = insp.fft_ctx
        ctx._fft_section.set_expanded(True)
        qapp.processEvents()
        qtbot.wait(50)
        fields = [
            ctx.combo_sig,
            ctx.spin_fs,
            ctx.combo_win,
            ctx.combo_nfft,
            ctx.spin_overlap,
        ]
        widths = [field.width() for field in fields]
        right_edges = [
            field.mapTo(ctx, field.rect().topLeft()).x() + field.width()
            for field in fields
        ]
        assert max(widths) - min(widths) <= 2, (
            "FFT fields should fill the same column width under A1; "
            f"got {widths}"
        )
        assert max(right_edges) - min(right_edges) <= 2, (
            "FFT fields should share a right edge under A1; "
            f"got {right_edges}"
        )
        assert min(widths) >= 170, (
            f"Field column should remain materially wider than compact 110px; "
            f"got {widths}"
        )
    finally:
        qapp.setStyleSheet(old_sheet)


def test_persistent_top_sections_match_contextual_card_breathing_room(qapp, qtbot):
    """2026-06-22 卡片重组: 横坐标 and 时间范围 now live in two independent white
    cards (timeXaxisCard / timeRangeFilterCard). Each group should use the
    same 10px content inset inside its own card, while the collapser header
    stays full width as the click target."""
    from pathlib import Path
    from PyQt5.QtWidgets import QFrame, QGroupBox
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        insp = Inspector()
        qtbot.addWidget(insp)
        insp.resize(288, 850)
        insp.set_mode('time')
        insp.top.btn_collapser.setChecked(True)
        insp.show()
        qtbot.waitExposed(insp)
        qtbot.wait(50)

        root = insp._scroll_body
        xaxis_card = insp.findChild(QFrame, "timeXaxisCard")
        range_card = insp.findChild(QFrame, "timeRangeFilterCard")
        assert xaxis_card is not None and range_card is not None
        assert xaxis_card is not range_card

        def bounds(widget):
            point = widget.mapTo(root, widget.rect().topLeft())
            return point.x(), point.x() + widget.width()

        for card, title in (
            (xaxis_card, "横坐标"),
            (range_card, "时间范围"),
        ):
            card_inner_left = card.mapTo(
                root, card.contentsRect().topLeft()
            ).x()
            card_inner_right = card_inner_left + card.contentsRect().width()
            group = next(
                g for g in insp.top.findChildren(QGroupBox)
                if g.title() == title
            )
            g_left, g_right = bounds(group)
            assert g_left == card_inner_left + 10
            assert card_inner_right - g_right == 10
    finally:
        qapp.setStyleSheet(old_sheet)


def test_time_domain_settings_render_inside_two_rounded_cards(qapp, qtbot):
    """2026-06-22 卡片重组: 横坐标 is its own card; 时间范围+滤波+绘图 share a
    second card. timeDomainSettingsCard is now a transparent outer host."""
    from pathlib import Path
    from PyQt5.QtWidgets import QFrame
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        insp = Inspector()
        qtbot.addWidget(insp)
        insp.resize(288, 850)
        insp.set_mode("time")
        insp.top.btn_collapser.setChecked(True)
        insp.show()
        qtbot.waitExposed(insp)
        qtbot.wait(50)

        outer = insp.findChild(QFrame, "timeDomainSettingsCard")
        xaxis_card = insp.findChild(QFrame, "timeXaxisCard")
        range_card = insp.findChild(QFrame, "timeRangeFilterCard")
        assert outer is not None and outer.isVisible()
        assert xaxis_card is not None and xaxis_card.isVisible()
        assert range_card is not None and range_card.isVisible()
        assert insp._xaxis_card is xaxis_card
        assert insp._range_filter_card is range_card

        # 绘图 button + filter panel are bottom of the range card (card ②).
        assert range_card.layout().indexOf(insp.time_ctx) >= 0
        assert range_card.layout().indexOf(insp.filter_panel) >= 0
        # 绘图 sits below the filter panel.
        assert (range_card.layout().indexOf(insp.time_ctx)
                > range_card.layout().indexOf(insp.filter_panel))

        body_left = insp._scroll_body.mapTo(
            insp, insp._scroll_body.rect().topLeft()
        ).x()
        outer_left = outer.mapTo(insp, outer.rect().topLeft()).x()
        assert outer_left == body_left
        assert outer.width() == insp._scroll_body.width()
    finally:
        qapp.setStyleSheet(old_sheet)


def test_time_domain_settings_card_qss_matches_contextual_cards():
    """2026-06-22 卡片重组: the white-card treatment moved from the single
    timeDomainSettingsCard to the two inner cards; the outer host is now
    transparent."""
    from pathlib import Path
    import re

    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    outer = re.search(
        r"Inspector\s+QFrame#timeDomainSettingsCard\s*\{([^}]*)\}",
        qss,
        flags=re.DOTALL,
    )
    assert outer, "timeDomainSettingsCard QSS block missing"
    assert "background-color: transparent" in outer.group(1)

    inner = re.search(
        r"Inspector\s+QFrame#timeXaxisCard,\s*\n"
        r"Inspector\s+QFrame#timeRangeFilterCard\s*\{([^}]*)\}",
        qss,
        flags=re.DOTALL,
    )
    assert inner, "timeXaxisCard / timeRangeFilterCard QSS block missing"
    text = inner.group(1)
    assert "background-color: #ffffff" in text
    assert "border: 1px solid #dbe2eb" in text
    assert "border-radius: 6px" in text


def test_analysis_modes_embed_time_range_in_input_card(qapp, qtbot):
    from mf4_analyzer.ui.inspector import Inspector

    inspector = Inspector()
    qtbot.addWidget(inspector)

    def ancestor_object_names(widget):
        names = []
        cur = widget.parentWidget()
        while cur is not None:
            names.append(cur.objectName())
            cur = cur.parentWidget()
        return names

    for mode, card_name, title in (
        ("fft", "fftSignalCard", "分析时间"),
        ("fft_time", "fftTimeSignalCard", "分析时间"),
        ("order", "orderSignalCard", "分析时间"),
    ):
        inspector.set_mode(mode)
        qapp.processEvents()
        group = inspector.top.range_group()
        assert inspector.top.isHidden() is True
        assert group.title() == title
        assert card_name in ancestor_object_names(group)

    inspector.set_mode("time")
    qapp.processEvents()
    assert inspector.top.isHidden() is False
    assert inspector.top.range_group().title() == "时间范围"


def test_signal_card_qframes_have_no_white_bleed(qapp):
    """fix-2 — the three sig_card QFrames inside the tinted contextual
    cards must NOT render with the default white QFrame background.

    Background: the global QSS rule ``QFrame, QGroupBox { background:
    #ffffff; }`` matches every plain QFrame and Qt auto-enables
    WA_StyledBackground during style polishing — so the only reliable
    fix is an explicit QSS override on each sig_card's objectName that
    re-transparentizes the background. This test asserts the override
    rule exists in the project's stylesheet (and is not silently dropped
    in a future refactor).
    """
    import pathlib
    qss_path = pathlib.Path(__file__).resolve().parents[2] / (
        "mf4_analyzer/ui_kit/style.qss"
    )
    qss = qss_path.read_text(encoding="utf-8")
    for object_name in (
        "fftSignalCard",
        "orderSignalCard",
        "fftTimeSignalCard",
    ):
        # Each sig_card must appear inside a selector that explicitly
        # transparentizes its background (or removes border) so the
        # tinted contextual card behind it bleeds through.
        assert f"#{object_name}" in qss, (
            f"style.qss is missing the #{object_name} override rule — "
            "the default QFrame{background:#ffffff} rule will render the "
            "card as a white rectangle over the tinted contextual."
        )


def test_order_contextual_old_tinted_background_removed():
    """Order Inspector should no longer carry the old orange/gray tint."""
    import pathlib
    qss_path = pathlib.Path(__file__).resolve().parents[2] / (
        "mf4_analyzer/ui_kit/style.qss"
    )
    qss = qss_path.read_text(encoding="utf-8")
    assert "#fff5e8" not in qss


def test_analysis_params_panels_share_unified_tint():
    """2026-06-13 分析信号/谱参数 split: the lower parameter panel
    (``params_card``) of all three analysis modes shares one #eef4ff tint so
    the lower Inspector panels read consistently. The contextual hosts
    themselves are now transparent — the two stacked cards carry the tint."""
    import pathlib
    qss_path = pathlib.Path(__file__).resolve().parents[2] / (
        "mf4_analyzer/ui_kit/style.qss"
    )
    qss = qss_path.read_text(encoding="utf-8")
    for object_name in (
        "fftParamsCard",
        "fftTimeParamsCard",
        "orderParamsCard",
    ):
        assert f"#{object_name}" in qss, (
            f"style.qss is missing the #{object_name} tint rule — the lower "
            "parameter panel will fall back to the default white QFrame fill"
        )
    # The unified lower-panel tint shared across all three modes.
    assert "#eef4ff" in qss


def test_checkbox_text_background_is_transparent():
    """Checkbox labels such as the axis-row 自动 text should not paint a
    separate rectangle over the contextual panel background."""
    import pathlib
    import re
    qss_path = pathlib.Path(__file__).resolve().parents[2] / (
        "mf4_analyzer/ui_kit/style.qss"
    )
    qss = qss_path.read_text(encoding="utf-8")
    m = re.search(r"QCheckBox,\s*QRadioButton\s*\{([^}]*)\}", qss, re.DOTALL)
    assert m, "QCheckBox/QRadioButton rule not found"
    block = m.group(1)
    assert "background-color: transparent;" in block


def test_time_range_rows_have_transparent_style_rule():
    """The time-range row hosts follow their parent analysis-time panel."""
    import pathlib
    import re
    qss_path = pathlib.Path(__file__).resolve().parents[2] / (
        "mf4_analyzer/ui_kit/style.qss"
    )
    qss = qss_path.read_text(encoding="utf-8")
    m = re.search(
        r"Inspector\s+QWidget#timeRangeToggleRow,\s*"
        r"Inspector\s+QWidget#inspectorPairField\s*\{([^}]*)\}",
        qss,
        re.DOTALL,
    )
    assert m, "time-range transparent row-host rule not found"
    assert "background-color: transparent;" in m.group(1)


def test_checkbox_indicator_has_visible_checked_state():
    """Checkboxes need an explicit, high-contrast indicator under QSS."""
    import pathlib
    import re
    qss_path = pathlib.Path(__file__).resolve().parents[2] / (
        "mf4_analyzer/ui_kit/style.qss"
    )
    qss = qss_path.read_text(encoding="utf-8")
    base = re.search(r"QCheckBox::indicator\s*\{([^}]*)\}", qss, re.DOTALL)
    checked = re.search(
        r"QCheckBox::indicator:checked\s*\{([^}]*)\}", qss, re.DOTALL,
    )
    assert base, "QCheckBox::indicator base rule not found"
    assert checked, "QCheckBox::indicator:checked rule not found"
    base_block = base.group(1)
    checked_block = checked.group(1)
    assert "width: 16px" in base_block or "width: 18px" in base_block
    assert "border:" in base_block
    assert "#1769e0" in checked_block
    assert "image:" in checked_block


def test_btn_rebuild_outer_size_compact(qapp):
    """fix-4 — btn_rebuild outer chrome must shrink to ~24x24 (icon stays
    16x16). Previously setMaximumWidth(30) + default min-height 26 left
    excess padding around the icon.
    """
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
    )
    for ctx_cls in (FFTContextual, OrderContextual, FFTTimeContextual):
        ctx = ctx_cls()
        btn = ctx.btn_rebuild
        # Width axis: <=24px.
        assert btn.maximumWidth() <= 24, (
            f"{ctx_cls.__name__}.btn_rebuild maxWidth={btn.maximumWidth()} "
            "> 24 (R3 紧凑化 fix-4)."
        )
        # Height axis: <=24px.
        assert btn.maximumHeight() <= 24, (
            f"{ctx_cls.__name__}.btn_rebuild maxHeight={btn.maximumHeight()} "
            "> 24 (R3 紧凑化 fix-4)."
        )


# ---- Signal-type builtin preset display names → 频率优先/均衡/时间优先 ----
#
# PresetBar exposes per-slot text via the internal ``_load_btns[n].text()``
# accessor (no public ``slot_text`` getter), and writes overrides through
# ``_write(slot, name, params)`` (no public ``set_slot_override``). Both
# tests below honor the plan's intent — default labels read 频率优先/均衡/时间优先 and
# reset-to-default still surfaces those names — while using the real API.

def test_fft_time_preset_bar_default_names(qtbot):
    """Default slot labels for the FFTTime preset bar must be the shared
    signal-type display names: 频率优先 / 均衡 / 时间优先."""
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    s = QSettings("MF4Analyzer", "DataAnalyzer")
    for slot in (1, 2, 3):
        s.remove(f"fft_time/preset_override/{slot}")
    w = FFTTimeContextual()
    qtbot.addWidget(w)
    bar = w.preset_bar
    # PresetBar exposes per-slot text via ``_load_btns[n].text()``.
    assert bar._load_btns[1].text() == '频率优先'
    assert bar._load_btns[2].text() == '均衡'
    assert bar._load_btns[3].text() == '时间优先'


def test_fft_time_preset_bar_reset_to_default_keeps_new_names(qtbot):
    """After resetting an overridden slot, the slot text must restore to
    the signal-type builtin name (频率优先) — not the legacy 诊断模式.
    """
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    s = QSettings("MF4Analyzer", "DataAnalyzer")
    for slot in (1, 2, 3):
        s.remove(f"fft_time/preset_override/{slot}")
    w = FFTTimeContextual()
    qtbot.addWidget(w)
    bar = w.preset_bar
    # Override slot 1 with a custom display name, then reset to default.
    # Real API: ``_write(slot, name, params)`` persists a JSON override.
    bar._write(1, 'Custom A', {})
    bar._refresh_states()
    assert bar._load_btns[1].text() == 'Custom A'
    bar._reset_to_default(1)
    assert bar._load_btns[1].text() == '频率优先'


# ---- Requested first-open defaults for FFT-vs-Time spectrogram ----

def test_fft_time_defaults_match_requested_screenshot(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)

    params = ctx.get_params()
    assert params['nfft'] is None
    assert params['nfft_mode'] == 'auto'
    assert params['t_win_s'] == 1.5
    assert params['nfft_preview'] == 2048
    assert params['window'] == 'hanning'
    assert params['overlap'] == 0.80
    assert params['remove_mean'] is True
    assert params['db_reference'] == 1.0
    assert params['x_auto'] is True
    assert params['y_auto'] is True
    assert params['z_auto'] is False
    assert params['z_floor'] == -70.0
    assert params['z_ceiling'] == -20.0
    assert params['cmap'] == 'turbo'
    assert ctx.spin_overlap.value() == 80, (
        f"FFTTimeContextual.spin_overlap default = "
        f"{ctx.spin_overlap.value()}; expected 80."
    )
    # Keep the raised maximum so existing high-overlap presets/user values
    # still round-trip.
    assert ctx.spin_overlap.maximum() == 95, (
        f"FFTTimeContextual.spin_overlap.maximum() = "
        f"{ctx.spin_overlap.maximum()}; expected 95."
    )


# M9 retired the matplotlib SpectrogramCanvas (FFT-vs-Time moved to
# PgHeatmapCanvas with_slice=True). The bilinear-imshow-interpolation test
# asserted a matplotlib-only render attribute
# (canvas._ax_spec.images[0].get_interpolation()) that has no equivalent on
# the pyqtgraph ImageItem, so it was removed rather than stubbed. The pg
# canvas's render is verified in tests/ui/test_pg_heatmap_canvas.py and the
# M6/M8 visual-acceptance gate.


# ---- Wave 2 / SP2: FFT 1D Welch averaging + linear/dB toggle ----

def test_fft_contextual_has_avg_mode_combo(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    assert hasattr(w, 'combo_avg_mode')
    items = [w.combo_avg_mode.itemText(i) for i in range(w.combo_avg_mode.count())]
    assert items == ['单帧', '线性平均', '峰值保持']
    assert w.combo_avg_mode.currentText() == '单帧'


def test_fft_contextual_has_overlap_spin(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    assert hasattr(w, 'spin_avg_overlap')
    assert w.spin_avg_overlap.minimum() == 0
    assert w.spin_avg_overlap.maximum() == 95
    assert w.spin_avg_overlap.value() == 50


def test_fft_contextual_overlap_disabled_in_single_frame_mode(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    # default avg_mode = '单帧'
    assert w.spin_avg_overlap.isEnabled() is False
    w.combo_avg_mode.setCurrentText('线性平均')
    assert w.spin_avg_overlap.isEnabled() is True
    w.combo_avg_mode.setCurrentText('单帧')
    assert w.spin_avg_overlap.isEnabled() is False


def test_fft_contextual_avg_mode_in_current_params(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    w.combo_avg_mode.setCurrentText('线性平均')
    w.spin_avg_overlap.setValue(75)
    p = w.current_params()
    assert p.get('avg_mode') == '线性平均'
    assert p.get('avg_overlap') == 75


def test_fft_contextual_apply_params_restores_avg(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    w.apply_params({'avg_mode': '峰值保持', 'avg_overlap': 88})
    assert w.combo_avg_mode.currentText() == '峰值保持'
    assert w.spin_avg_overlap.value() == 88


def test_fft_preset_collects_extended_analysis_params(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    w.combo_win.setCurrentText('flattop')
    w.combo_nfft.setCurrentText('4096')
    w._t_win_s = 2.5
    w.spin_overlap.setValue(25)
    w.combo_avg_mode.setCurrentText('线性平均')
    w.spin_avg_overlap.setValue(75)
    w.combo_amp_y.setCurrentText('dB')

    p = w._collect_preset()

    assert p['window'] == 'flattop'
    assert p['nfft'] == '4096'
    assert p['t_win_s'] == 2.5
    assert p['overlap'] == 25
    assert p['avg_mode'] == '线性平均'
    assert p['avg_overlap'] == 75
    assert p['amp_y'] == 'dB'
    assert 'psd_y' not in p


def test_fft_preset_applies_extended_analysis_params(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()

    w._apply_preset({
        'window': 'blackman',
        'nfft': '自动',
        'nfft_mode': 'auto',
        't_win_s': 0.6,
        'overlap': 35,
        'avg_mode': '峰值保持',
        'avg_overlap': 88,
        'amp_y': 'dB',
    })

    assert w.combo_win.currentText() == 'blackman'
    assert w.combo_nfft.currentText() == '自动'
    assert w._t_win_s == 0.6
    assert w.spin_overlap.value() == 35
    assert w.combo_avg_mode.currentText() == '峰值保持'
    assert w.spin_avg_overlap.value() == 88
    assert w.combo_amp_y.currentText() == 'dB'


def test_fft_preset_apply_legacy_fixed_nfft_without_t_win(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    w = FFTContextual()
    w._apply_preset({
        'window': 'hanning',
        'nfft': '4096',
        'overlap': 50,
        'avg_mode': '线性平均',
        'avg_overlap': 75,
        'amp_y': 'dB',
    })

    assert w.combo_nfft.currentText() == '4096'
    p = w.current_params()
    assert p['nfft'] == 4096
    assert p['nfft_mode'] == 'fixed'
    assert p['t_win_s'] == 1.5


# ---- Task 2.2: averaging routes through DSP helpers ----

def test_welch_average_lowers_noise_floor():
    """Stationary noisy 10Hz tone → Welch averaging produces lower noise std
    than a single FFT frame (sanity check that the wired-up code path is
    correct).
    """
    import numpy as np
    from mf4_analyzer.signal.fft import FFTAnalyzer, one_sided_amplitude

    rng = np.random.default_rng(42)
    fs = 1000.0
    n = int(10 * fs)  # 10 seconds
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 10 * t) + 0.3 * rng.standard_normal(n)

    # single frame (full nfft window of length 4096)
    seg = sig[:4096]
    f1, a1 = one_sided_amplitude(seg, fs, win='hanning', nfft=4096)

    # welch averaging
    f2, a2, _ = FFTAnalyzer.compute_averaged_fft(
        sig, fs, win='hanning', nfft=4096, overlap=0.5,
    )
    # Outside the 10Hz peak (drop bins near 10Hz), welch noise std should be
    # lower.
    mask = np.abs(f1[: len(a2)] - 10.0) > 2.0
    assert a2[mask].std() < a1[: len(a2)][mask].std() * 0.85, (
        "Welch averaging should reduce out-of-peak std by at least 15%"
    )


def test_compute_peak_hold_fft_returns_per_bin_max():
    """``FFTAnalyzer.compute_peak_hold_fft`` must take the per-frequency max
    across overlapping segments — a transient bursty tone should be
    preserved at its peak amplitude even when most of the signal is quiet.
    """
    import numpy as np
    from mf4_analyzer.signal.fft import FFTAnalyzer

    fs = 1000.0
    nfft = 1024
    n = 8 * nfft
    t = np.arange(n) / fs
    # 50 Hz tone, on only inside the second segment (samples 1024:2048).
    sig = np.zeros(n)
    seg_start, seg_end = nfft, 2 * nfft
    sig[seg_start:seg_end] = np.sin(2 * np.pi * 50 * t[seg_start:seg_end])

    freq, peak = FFTAnalyzer.compute_peak_hold_fft(
        sig, fs, win='hanning', nfft=nfft, overlap=0.5,
    )
    # Peak hold preserves the transient: 50 Hz bin must dominate.
    bin_idx = int(np.argmin(np.abs(freq - 50.0)))
    assert peak[bin_idx] > 0.1, (
        f"Peak-hold should preserve transient 50 Hz tone (got "
        f"{peak[bin_idx]:.4f} at bin {bin_idx}, freq={freq[bin_idx]:.2f} Hz)"
    )
    # Sanity: returned arrays match length.
    assert len(freq) == len(peak)


def test_fft_render_dispatches_on_avg_mode(qtbot, monkeypatch):
    """The FFT render path in main_window must route '线性平均' through
    compute_averaged_fft and '峰值保持' through compute_peak_hold_fft. Single
    frame keeps using compute_fft.
    """
    import numpy as np
    from mf4_analyzer.signal.fft import FFTAnalyzer
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    # Stub out the heavy "selected signal" plumbing.
    fs = 1000.0
    n = 4096
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 10 * t)
    win._get_sig = lambda: (t, sig, fs)
    win._check_uniform_or_prompt = lambda fd, mode: True
    # Empty files dict → _on_inspector_signal_changed early-returns on the
    # ``fid not in self.files`` guard, so populating fft_ctx candidates does
    # not trigger an AttributeError on a stub FileData.
    win.files = {}
    win.inspector.fft_ctx.set_signal_candidates([("dummy", (None, "ch"))])
    win.inspector.fft_ctx.spin_fs.setValue(fs)

    calls = []
    real_avg = FFTAnalyzer.compute_averaged_fft
    real_peak = FFTAnalyzer.compute_peak_hold_fft
    real_fft = FFTAnalyzer.compute_fft

    def spy_avg(*a, **kw):
        calls.append('avg')
        return real_avg(*a, **kw)

    def spy_peak(*a, **kw):
        calls.append('peak')
        return real_peak(*a, **kw)

    def spy_fft(*a, **kw):
        calls.append('fft')
        return real_fft(*a, **kw)

    monkeypatch.setattr(FFTAnalyzer, 'compute_averaged_fft', staticmethod(spy_avg))
    monkeypatch.setattr(FFTAnalyzer, 'compute_peak_hold_fft', staticmethod(spy_peak))
    monkeypatch.setattr(FFTAnalyzer, 'compute_fft', staticmethod(spy_fft))

    # Single frame
    win.inspector.fft_ctx.combo_avg_mode.setCurrentText('单帧')
    win.inspector.fft_ctx.combo_nfft.setCurrentText('1024')
    win.do_fft()
    # Linear average
    win.inspector.fft_ctx.combo_avg_mode.setCurrentText('线性平均')
    win.inspector.fft_ctx.spin_avg_overlap.setValue(50)
    win.do_fft()
    # Peak hold
    win.inspector.fft_ctx.combo_avg_mode.setCurrentText('峰值保持')
    win.do_fft()

    assert 'fft' in calls, f"single-frame must use compute_fft (calls={calls})"
    assert 'avg' in calls, f"线性平均 must call compute_averaged_fft (calls={calls})"
    assert 'peak' in calls, f"峰值保持 must call compute_peak_hold_fft (calls={calls})"


# ---- Task 2.3: per-subplot linear/dB toggle ----

def test_fft_contextual_has_axis_toggles(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    assert hasattr(w, 'combo_amp_y')
    assert w.combo_amp_y.currentText() == 'Linear'
    assert not hasattr(w, 'combo_psd_y') or not w.combo_psd_y.isVisible()


def test_fft_contextual_axis_toggles_in_params(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    w.combo_amp_y.setCurrentText('dB')
    p = w.current_params()
    assert p.get('amp_y') == 'dB'
    assert 'psd_y' not in p
    w.apply_params({'amp_y': 'Linear'})
    assert w.combo_amp_y.currentText() == 'Linear'


def test_fft_contextual_source_summary_replaces_signal_combo_for_checked_sources(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    w.set_source_summary(["file1 Â· speed", "file2 Â· speed"])

    assert "左侧已选 2 个信号" in w.lbl_source_summary.text()
    assert w.combo_sig.isHidden() is True

    w.set_source_summary([])

    assert w.lbl_source_summary.text() == "未选通道，使用单信号"
    assert w.lbl_source_summary.wordWrap() is False
    assert w.combo_sig.isHidden() is False


def test_fft_auto_xlim_keeps_low_frequency_spectrum_tight():
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    freq = np.linspace(0.0, 25.0, 251)
    amp = np.zeros_like(freq)
    amp[np.argmin(np.abs(freq - 1.0))] = 1.0

    xmax = MainWindow._fft_auto_xlim(freq, amp)

    assert xmax >= 2.0
    assert xmax == 5.0
    assert xmax <= freq[-1]


def test_plot_fft_entries_auto_xlim_includes_all_overlay_sources(qtbot):
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    class _Canvas:
        def __init__(self):
            self.plot_kwargs = None
            self.tick_density = None

        def plot_spectra(self, entries, **kwargs):
            self.plot_kwargs = kwargs

        def set_tick_density(self, xt, yt):
            self.tick_density = (xt, yt)

    def amp_through(cutoff):
        amp = np.zeros_like(freq)
        amp[np.argmin(np.abs(freq - cutoff))] = 1.0
        return amp

    win = MainWindow()
    qtbot.addWidget(win)
    freq = np.linspace(0.0, 25.0, 251)
    entries = [
        {"label": "low", "color": "#2563eb", "freq": freq,
         "amp": amp_through(1.0), "time": [], "signal": []},
        {"label": "higher", "color": "#dc2626", "freq": freq,
         "amp": amp_through(3.0), "time": [], "signal": []},
    ]
    canvas = _Canvas()

    win._plot_fft_entries(entries, canvas)

    xmax = canvas.plot_kwargs["xlim"][1]
    assert xmax == 20.0
    assert xmax <= freq[-1]


def test_plot_fft_entries_auto_xlim_uses_raw_amp_in_db_mode(qtbot):
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    class _Canvas:
        def __init__(self):
            self.plot_kwargs = None

        def plot_spectra(self, entries, **kwargs):
            self.plot_kwargs = kwargs

        def set_tick_density(self, xt, yt):
            pass

    win = MainWindow()
    qtbot.addWidget(win)
    win.inspector.fft_ctx.combo_amp_y.setCurrentText("dB")
    freq = np.linspace(0.0, 25.0, 251)
    amp = np.zeros_like(freq)
    amp[np.argmin(np.abs(freq - 1.0))] = 1.0
    amp_db = 20 * np.log10(
        np.clip(amp, 1e-12, None) / max(amp.max(), 1e-12)
    )
    entries = [{
        "label": "low",
        "color": "#2563eb",
        "freq": freq,
        "amp": amp_db,
        "amp_for_xlim": amp,
        "time": [],
        "signal": [],
    }]
    canvas = _Canvas()

    win._plot_fft_entries(entries, canvas)

    xmax = canvas.plot_kwargs["xlim"][1]
    assert xmax == 5.0


def test_fft_render_honors_amplitude_axis_toggle(qtbot):
    """Toggling Amp axis to dB must change the spectrum y-label text — this
    proves the toggle round-trips
    through the render code in main_window.do_fft.

    M11: canvas_fft is a PgLineCanvas; the amp row is ``_plot_amp`` and the
    time preview row is ``_plot_time``. The y-label lives on each plot's left
    ``AxisItem.labelText`` (the pg analogue of mpl ``ax.get_ylabel()``).
    """
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fs = 1000.0
    n = 4096
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 10 * t)
    win._get_sig = lambda: (t, sig, fs)
    win._check_uniform_or_prompt = lambda fd, mode: True
    win.files = {}
    win.inspector.fft_ctx.set_signal_candidates([("dummy", (None, "ch"))])
    win.inspector.fft_ctx.spin_fs.setValue(fs)
    win.inspector.fft_ctx.combo_avg_mode.setCurrentText('单帧')

    canvas = win.canvas_fft

    def amp_ylabel():
        return canvas._plot_amp.getAxis('left').labelText

    def time_xlabel():
        return canvas._plot_time.getAxis('bottom').labelText

    # Default render: amp=Linear, psd=dB.
    win.do_fft()
    assert canvas.has_result()
    assert 'dB' not in amp_ylabel()
    assert time_xlabel() == 'Time (s)'

    # Flip: amp=dB, psd=Linear.
    win.inspector.fft_ctx.combo_amp_y.setCurrentText('dB')
    win.do_fft()
    assert 'dB' in amp_ylabel()


def test_fft_single_signal_fallback_amp_label_uses_a_weighted_token(qtbot):
    """``_do_fft_single`` (the legacy no-navigator-checked-sources fallback,
    plan Task 11 Step 11.2 classification) must route its amp axis label
    through :func:`db_reference.format_amplitude_label` like the per-source
    overlay path (:meth:`MainWindow._fft_apply_amplitude_display`) — a bare
    ``'Amplitude (dB)'`` hard-code loses the A-weighting disclosure required
    by spec A9 ("dBA appears... Linear never says dBA") even on this
    back-compat single-signal path.
    """
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fs = 1000.0
    n = 4096
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 10 * t)
    win._get_sig = lambda: (t, sig, fs)
    win._check_uniform_or_prompt = lambda fd, mode: True
    win.files = {}
    win.inspector.fft_ctx.set_signal_candidates([("dummy", (None, "ch"))])
    win.inspector.fft_ctx.spin_fs.setValue(fs)
    win.inspector.fft_ctx.combo_avg_mode.setCurrentText('单帧')
    win.inspector.fft_ctx.combo_amp_y.setCurrentText('dB')

    canvas = win.canvas_fft

    def amp_ylabel():
        return canvas._plot_amp.getAxis('left').labelText

    # None weighting: dB, never dBA.
    win.inspector.fft_ctx.combo_weighting.setCurrentText('None')
    win.do_fft()
    assert canvas.has_result()
    assert 'dB' in amp_ylabel()
    assert 'dBA' not in amp_ylabel()

    # A weighting: must surface the 'dBA' token, matching the checked-source
    # overlay path's format_amplitude_label output (spec A9 stop-gate).
    win.inspector.fft_ctx.combo_weighting.setCurrentText('A')
    win.do_fft()
    assert 'dBA' in amp_ylabel()


def test_fft_render_honors_manual_xy_axis_ranges(qtbot):
    import pytest
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fs = 1000.0
    n = 4096
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 30 * t)
    win._get_sig = lambda: (t, sig, fs)
    win._check_uniform_or_prompt = lambda fd, mode: True
    win.files = {}
    win.inspector.fft_ctx.set_signal_candidates([("dummy", (None, "ch"))])
    win.inspector.fft_ctx.spin_fs.setValue(fs)
    win.inspector.fft_ctx.combo_avg_mode.setCurrentText('单帧')
    win.inspector.fft_ctx.chk_x_auto.setChecked(False)
    win.inspector.fft_ctx.spin_x_min.setValue(10.0)
    win.inspector.fft_ctx.spin_x_max.setValue(80.0)
    win.inspector.fft_ctx.chk_y_auto.setChecked(False)
    win.inspector.fft_ctx.spin_y_min.setValue(-2.0)
    win.inspector.fft_ctx.spin_y_max.setValue(2.0)

    win.do_fft()

    # M11: read the manual X/Y range off each PgLineCanvas row's ViewBox
    # (pg ``vb.viewRange()`` returns [[x0, x1], [y0, y1]]) — the analogue of
    # the old mpl ``ax.get_xlim()`` / ``ax.get_ylim()``.
    canvas = win.canvas_fft
    assert canvas.has_result()
    (x0, x1), (y0, y1) = canvas._plot_amp.vb.viewRange()
    assert (x0, x1) == pytest.approx((10.0, 80.0))
    assert (y0, y1) == pytest.approx((-2.0, 2.0))

    (tx0, tx1), _ = canvas._plot_time.vb.viewRange()
    assert (tx0, tx1) == pytest.approx((0.0, float(t[-1])), abs=0.02)


def test_fft_time_preview_honors_selected_time_range(qtbot):
    import pytest
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fs = 1000.0
    n = 4096
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 20 * t)
    win._get_sig = lambda: (t, sig, fs)
    win._check_uniform_or_prompt = lambda fd, mode: True
    win.files = {}
    win.inspector.fft_ctx.set_signal_candidates([("dummy", (None, "ch"))])
    win.inspector.fft_ctx.spin_fs.setValue(fs)
    win.inspector.fft_ctx.combo_avg_mode.setCurrentText('单帧')
    win.inspector.top.set_range_values(1.0, 2.0)
    win.inspector.top.chk_range.setChecked(True)

    win.do_fft()

    canvas = win.canvas_fft
    assert canvas.has_result()
    (tx0, tx1), _ = canvas._plot_time.vb.viewRange()
    assert (tx0, tx1) == pytest.approx((1.0, 2.0), abs=0.02)


# ---- Regression: FFT time-window drag must not leak chk_range into time ----
#
# Bug: the SINGLE shared ``chk_range`` QCheckBox is reparented across
# time/fft/fft_time/order modes (inspector._place_range_group_for_mode).
# An FFT time-window region drag routes through set_range_from_span, which
# force-checks the box; because the instance is shared, the checked state
# leaked into Time-Domain when the user switched back. The fix decouples the
# checked flag per mode (PersistentTop.checkout_range_for_mode), invoked on
# every mode switch. These tests pin both halves: the drag still enables the
# range for the FFT compute (within FFT mode) AND the box does NOT arrive
# checked in Time-Domain after a mode switch.


def test_fft_preview_span_does_not_leak_chk_range_into_time(qapp):
    """An FFT time-window drag (set_range_from_span) must enable the range
    while FFT mode is active, but switching back to time must restore the
    time-domain checkbox to its own (unchecked) state."""
    insp = Inspector()
    top = insp.top

    # Start in time mode with the box unchecked (constructor default).
    insp.set_mode('time')
    assert not top.range_enabled()

    # Enter FFT mode and drag a time window -> stages start/end AND checks the
    # box so the FFT compute (which reads range_enabled()) uses the window.
    insp.set_mode('fft')
    top.set_range_from_span(2.0, 4.0)
    assert top.range_enabled()
    assert top.range_values() == (2.0, 4.0)

    # Switch back to time-domain: the shared checkbox must NOT carry the FFT
    # drag's checked state. This is the bug under regression.
    insp.set_mode('time')
    assert not top.range_enabled(), (
        "FFT time-window drag leaked chk_range into Time-Domain mode"
    )
    # On this branch the 开始/结束 row is unconditionally visible; the
    # per-mode checkout must not break that (the spin row stays shown).
    assert not top.spin_start.isHidden()
    assert not top.spin_end.isHidden()

    # Returning to FFT restores FFT's own (checked) intent.
    insp.set_mode('fft')
    assert top.range_enabled()
    assert not top.spin_start.isHidden()


def test_time_domain_chk_range_survives_round_trip_through_fft(qapp):
    """If the user explicitly checks the box in Time-Domain, that intent must
    survive a round-trip through FFT mode (where FFT has its own state)."""
    insp = Inspector()
    top = insp.top

    insp.set_mode('time')
    top.chk_range.setChecked(True)
    top.set_range_values(1.0, 3.0)
    assert top.range_enabled()

    # FFT mode starts from its own (unchecked) state, independent of time.
    insp.set_mode('fft')
    assert not top.range_enabled()

    # Back to time: the user's original checked intent is preserved.
    insp.set_mode('time')
    assert top.range_enabled()
    assert top.range_values() == (1.0, 3.0)


def test_main_window_fft_preview_path_does_not_check_time_box(qapp, qtbot):
    """End-to-end: drive the real _on_fft_preview_range_changed handler in FFT
    mode, then switch the inspector back to time-domain; the time-domain
    checkbox must remain unchecked (no leak through the live signal path)."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    top = win.inspector.top
    # Baseline: time mode, box unchecked.
    win.chart_stack.set_mode('time')
    win.inspector.set_mode('time')
    assert not top.range_enabled()

    # Enter FFT mode on both the chart stack (gating) and the inspector
    # (range-group reparent + per-mode checkout).
    win.chart_stack.set_mode('fft')
    win.inspector.set_mode('fft')
    page = win.chart_stack.page_fft
    handled = win._on_fft_preview_range_changed(page.focused_index(), 2.0, 4.0)
    assert handled is True
    assert top.range_enabled()  # FFT compute window is armed within FFT mode.

    # Switch back to time-domain: the shared checkbox must not be checked.
    win.chart_stack.set_mode('time')
    win.inspector.set_mode('time')
    assert not top.range_enabled(), (
        "live FFT-preview path leaked chk_range into Time-Domain mode"
    )


# ---- 「最大」 (maximize time range) button ----
#
# A flat 「最大」 button sits on the right of the 「使用选定时间范围」 row.
# Clicking it fills 开始/结束 to the full data extent [0, 全程时长] AND ticks
# the range checkbox, then (in MainWindow) applies for the current mode. The
# widget itself only emits ``max_range_requested``; the staging is done via
# ``set_range_from_span`` (which records per-mode checked intent).


def test_max_range_button_fills_full_extent_and_enables(qapp, qtbot):
    """Clicking 「最大」 stages the full [lo, hi] extent into the spinboxes and
    enables the range filter — even from a partial, unchecked selection.

    The widget itself only emits ``max_range_requested``; the owner
    (MainWindow) does the staging via ``set_range_from_span``.
    """
    from types import SimpleNamespace

    import numpy as np

    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    top = win.inspector.top
    win.files = {
        "fid": SimpleNamespace(time_array=np.array([0.0, 100.0], dtype=float))
    }
    win.chart_stack.set_mode('time')
    win.inspector.set_mode('time')

    # Start from a stale/narrow UI limit to prove the real slot reads the data
    # extent and refreshes limits before filling the range.
    top.set_range_limits(0, 50)
    top.set_range_values(10, 20)
    top.chk_range.setChecked(False)
    assert top.range_enabled() is False
    assert top.range_values() == (10.0, 20.0)

    # Drive the button the same way the user would.
    top.btn_range_max.click()

    assert top.range_values() == (0.0, 100.0)
    assert top.spin_end.maximum() == 100.0
    assert top.range_enabled() is True


def test_max_range_button_emits_signal(qapp):
    """The button is a pure signal source: clicking it emits
    ``max_range_requested`` (MainWindow owns the mode-aware apply)."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop

    top = PersistentTop()
    fired = []
    top.max_range_requested.connect(lambda: fired.append(True))
    top.btn_range_max.click()
    assert fired == [True]


def test_max_range_button_lives_on_chk_range_row(qapp):
    """The 「最大」 button shares the host row with chk_range; the checkbox row
    itself stays visible regardless of checked state, and the button carries
    the exact spec'd label + tooltip."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop

    top = PersistentTop()
    assert top.btn_range_max.text() == "最大"
    assert top.btn_range_max.toolTip() == "将时间范围设为整段数据（0 ~ 全程）"
    # chk_range and btn_range_max share the same host parent.
    assert top.btn_range_max.parentWidget() is top.chk_range.parentWidget()
    # The checkbox row stays visible even when unchecked.
    top.chk_range.setChecked(False)
    assert not top.chk_range.isHidden()


def test_time_range_toggle_row_background_tracks_parent_panel(qapp, qtbot):
    """The range toggle row must not repaint the generic QWidget page grey.

    This uses a deliberately high-contrast stylesheet: all generic QWidget
    children are grey, while QGroupBox panels are green. The blank stretch
    between the checkbox label and 「最大」 should sample the panel color.
    """
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QLabel
    from mf4_analyzer.ui.inspector_sections import PersistentTop

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet("""
            QWidget { background-color: #d1d5db; }
            QGroupBox {
                background-color: #e9fbf2;
                border: 0;
                margin-top: 18px;
                padding-top: 18px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 0;
            }
            QWidget#timeRangeToggleRow,
            QWidget#inspectorPairField { background: transparent; }
            QCheckBox, QToolButton { background: transparent; }
        """)

        top = PersistentTop()
        qtbot.addWidget(top)
        top.resize(288, 240)
        top.show()
        qtbot.waitExposed(top)
        qapp.processEvents()

        host = top._chk_range_host
        assert host.objectName() == "timeRangeToggleRow"
        checkbox_right = top.chk_range.mapTo(
            host, QPoint(top.chk_range.width(), 0)
        ).x()
        button_left = top.btn_range_max.mapTo(host, QPoint(0, 0)).x()
        if button_left - checkbox_right > 8:
            sample_x = (checkbox_right + button_left) // 2
        else:
            sample_x = max(4, host.width() - 8)
        point = host.mapTo(top, QPoint(sample_x, host.height() // 2))

        color = top.grab().toImage().pixelColor(point)
        assert color.name().lower() == "#e9fbf2", (
            "time range toggle row should inherit the parent panel "
            f"background, got {color.name()}"
        )

        range_host = top._range_row_host
        assert range_host.objectName() == "inspectorPairField"
        end_label = next(
            label for label in range_host.findChildren(QLabel)
            if "结束" in label.text()
        )
        label_right = end_label.mapTo(
            range_host, QPoint(end_label.width(), 0)
        ).x()
        end_left = top.spin_end.mapTo(range_host, QPoint(0, 0)).x()
        sample_x = max(label_right + 1, min(end_left - 1, (label_right + end_left) // 2))
        point = range_host.mapTo(top, QPoint(sample_x, range_host.height() // 2))

        color = top.grab().toImage().pixelColor(point)
        assert color.name().lower() == "#e9fbf2", (
            "time range start/end pair row should inherit the parent panel "
            f"background, got {color.name()}"
        )
    finally:
        qapp.setStyleSheet(old_sheet)


# ---- Wave 3 (axis-settings + COT migration plan): 坐标轴设置 group ----
#
# OrderContextual replaces the legacy combo_amp_mode + combo_dynamic combos
# with an explicit X/Y/Z range group. The dB ↔ Linear toggle now lives on
# the Z (color scale) row as ``combo_amp_unit``. See Wave 3 of
# docs/superpowers/plans/2026-04-28-axis-settings-and-cot-migration.md.


def test_order_contextual_has_axis_settings_group(qtbot):
    """OrderContextual must contain a QGroupBox titled '坐标轴设置' with
    9 controls: chk_x_auto + spin_x_min + spin_x_max + chk_y_auto +
    spin_y_min + spin_y_max + chk_z_auto + spin_z_floor + spin_z_ceiling
    + combo_amp_unit (the dB/Linear dropdown on the Z row)."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    for name in (
        'chk_x_auto', 'spin_x_min', 'spin_x_max',
        'chk_y_auto', 'spin_y_min', 'spin_y_max',
        'chk_z_auto', 'spin_z_floor', 'spin_z_ceiling',
        'combo_amp_unit',
    ):
        assert hasattr(oc, name), f'missing {name}'

    # Defaults: x/y auto on, z auto off with the requested first-open range.
    assert oc.chk_x_auto.isChecked()
    assert oc.chk_y_auto.isChecked()
    assert not oc.chk_z_auto.isChecked()
    assert oc.spin_z_floor.value() == -50.0
    assert oc.spin_z_ceiling.value() == -10.0
    assert oc.combo_amp_unit.currentText() == 'dB'


def test_order_contextual_defaults_match_requested_screenshot(qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    oc = OrderContextual()
    qtbot.addWidget(oc)
    p = oc.current_params()

    assert p['max_order'] == 20
    assert p['order_res'] == 0.1
    assert p['time_res'] == 0.05
    assert p['nfft'] is None
    assert p['nfft_mode'] == 'auto'
    assert p['nfft_preview'] == 4096
    assert p['samples_per_rev'] == 256
    assert p['x_auto'] is True
    assert p['y_auto'] is True
    assert p['z_auto'] is False
    assert p['z_floor'] == -50.0
    assert p['z_ceiling'] == -10.0


def test_order_contextual_manual_rpm_defaults_and_round_trip(qapp):
    from mf4_analyzer.ui.inspector_sections.contextual_order import OrderContextual

    ctx = OrderContextual()
    assert ctx.rpm_mode() == "channel"
    assert ctx.manual_rpm() == 1000.0
    assert ctx.combo_rpm.isEnabled()
    assert ctx.spin_rf.isEnabled()
    assert not ctx.spin_manual_rpm.isEnabled()

    ctx.set_rpm_mode("manual")
    ctx.spin_manual_rpm.setValue(1350.0)

    params = ctx.current_params()
    assert params["rpm_mode"] == "manual"
    assert params["manual_rpm"] == 1350.0
    assert ctx.current_rpm() is None
    assert not ctx.combo_rpm.isEnabled()
    assert not ctx.spin_rf.isEnabled()
    assert ctx.spin_manual_rpm.isEnabled()

    restored = OrderContextual()
    restored.apply_params(params)
    assert restored.rpm_mode() == "manual"
    assert restored.manual_rpm() == 1350.0
    assert not restored.combo_rpm.isEnabled()
    assert not restored.spin_rf.isEnabled()
    assert restored.spin_manual_rpm.isEnabled()


def test_order_contextual_combo_amp_mode_and_dynamic_removed(qtbot):
    """combo_amp_mode and combo_dynamic widgets are gone (their values
    are now expressed via combo_amp_unit + spin_z_floor/ceiling)."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    assert not hasattr(oc, 'combo_amp_mode')
    assert not hasattr(oc, 'combo_dynamic')


def test_order_contextual_y_max_clamped_by_max_order(qtbot):
    """When the user changes spin_mo (max_order, calc param), spin_y_max
    upper bound must follow so display range cannot exceed the calc range."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    oc.spin_mo.setValue(15)
    assert oc.spin_y_max.maximum() == 15.0
    # If user had y_max > 15, it should snap down
    oc.spin_y_max.setValue(20)
    assert oc.spin_y_max.value() <= 15.0


def test_order_contextual_unit_toggle_forces_z_auto(qtbot):
    """Switching combo_amp_unit dB↔Linear forces chk_z_auto on (per
    the 2026-04-28 plan: avoids ambiguous unit-conversion semantics)."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    # Default: z_auto off, dB unit
    oc.chk_z_auto.setChecked(False)
    assert not oc.chk_z_auto.isChecked()
    oc.combo_amp_unit.setCurrentText('Linear')
    assert oc.chk_z_auto.isChecked()


# ---- 2026-05-01 (codex review P7-L1 / P7-L1' fix): toggling combo_amp_unit
# in either direction must reset spin_z_floor / spin_z_ceiling to the unit's
# defaults (-30..0 for dB, 0..1 for Linear) so the previous unit's numeric
# range cannot bleed into the new unit. See
# docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md §1.

@pytest.mark.parametrize(
    "from_unit,to_unit,start_floor,start_ceiling,expected_floor,expected_ceiling",
    [
        # dB → Linear: stale -30..0 dB values must be cleared to 0..1.
        ('dB', 'Linear', -30.0, 0.0, 0.0, 1.0),
        # Linear → dB: stale 0..1 values must be replaced by -30..0 dB.
        ('Linear', 'dB', 0.5, 0.9, -30.0, 0.0),
    ],
)
def test_order_contextual_unit_toggle_resets_z_range(
    qtbot, from_unit, to_unit,
    start_floor, start_ceiling, expected_floor, expected_ceiling,
):
    """Spec §1.2 invariant for OrderContextual.

    After toggling combo_amp_unit:
      - chk_z_auto must be re-enabled (True)
      - spin_z_floor/spin_z_ceiling must reset to the new unit's default
        (-30..0 for dB, 0..1 for Linear)
      - both spinboxes must be disabled (because z_auto is on, _sync_axis
        flips them off)
    """
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    # Set the starting unit silently so we can plant stale values.
    oc.combo_amp_unit.blockSignals(True)
    oc.combo_amp_unit.setCurrentText(from_unit)
    oc.combo_amp_unit.blockSignals(False)
    oc.chk_z_auto.setChecked(False)
    oc.spin_z_floor.setValue(start_floor)
    oc.spin_z_ceiling.setValue(start_ceiling)
    assert not oc.chk_z_auto.isChecked()
    assert oc.spin_z_floor.value() == start_floor
    assert oc.spin_z_ceiling.value() == start_ceiling

    # Trigger handler via user-level signal.
    oc.combo_amp_unit.setCurrentText(to_unit)

    assert oc.chk_z_auto.isChecked() is True
    assert oc.spin_z_floor.value() == expected_floor
    assert oc.spin_z_ceiling.value() == expected_ceiling
    assert oc.spin_z_floor.isEnabled() is False
    assert oc.spin_z_ceiling.isEnabled() is False


def test_order_contextual_unit_toggle_same_unit_idempotent(qtbot):
    """Spec §1.5: dB→dB still executes the reset (handler does not branch
    on equality). User has stale values; re-selecting the same unit clears
    them to that unit's defaults."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    # Plant stale dB values.
    oc.combo_amp_unit.blockSignals(True)
    oc.combo_amp_unit.setCurrentText('dB')
    oc.combo_amp_unit.blockSignals(False)
    oc.chk_z_auto.setChecked(False)
    oc.spin_z_floor.setValue(-99.0)
    oc.spin_z_ceiling.setValue(-5.0)

    # Re-emit the same unit. setCurrentText('dB') won't fire because the
    # combo is already at dB — drive the handler directly to express the
    # idempotency contract.
    oc._on_amp_unit_changed('dB')

    assert oc.chk_z_auto.isChecked() is True
    assert oc.spin_z_floor.value() == -30.0
    assert oc.spin_z_ceiling.value() == 0.0


def test_order_contextual_apply_preset_z_values_survive_unit_change(qtbot):
    """Spec §5: _apply_preset must not trip _on_amp_unit_changed when it
    sets combo_amp_unit, otherwise the freshly-applied z_floor/z_ceiling
    get clobbered."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    # Force the combo to Linear so the preset's 'Amplitude dB' actually
    # changes the index (otherwise blockSignals is exercised on a no-op
    # set and the test is silent).
    oc.combo_amp_unit.blockSignals(True)
    oc.combo_amp_unit.setCurrentText('Linear')
    oc.combo_amp_unit.blockSignals(False)

    oc._apply_preset({
        'amplitude_mode': 'Amplitude dB',
        'z_auto': False,
        'z_floor': -45.0,
        'z_ceiling': -5.0,
    })

    assert oc.combo_amp_unit.currentText() == 'dB'
    assert oc.chk_z_auto.isChecked() is False
    assert oc.spin_z_floor.value() == -45.0
    assert oc.spin_z_ceiling.value() == -5.0


def test_order_contextual_apply_preset_legacy_dynamic_survives_unit_flip(qtbot):
    """Strong RED: prove that ``_apply_preset`` actually blocks the
    ``_on_amp_unit_changed`` handler when it flips ``combo_amp_unit``.

    Order of operations in production (``OrderContextual._apply_preset``):

      1. Legacy ``dynamic`` is processed FIRST and writes
         ``spin_z_floor=-30, spin_z_ceiling=0, chk_z_auto=False``.
      2. ``amplitude_mode`` is processed SECOND and calls
         ``combo_amp_unit.setCurrentIndex(Linear)`` — this is the call
         that **must** be wrapped in ``blockSignals`` because if the
         handler fires it forces ``chk_z_auto=True`` and rewrites
         ``spin_z_floor=0.0, spin_z_ceiling=1.0`` (Linear defaults).
      3. There are NO explicit ``z_floor`` / ``z_ceiling`` keys in the
         dict, so step 2's damage is **not** masked by a later setValue.

    The companion test
    ``test_order_contextual_apply_preset_z_values_survive_unit_change``
    is structurally weak: it passes explicit ``z_floor`` / ``z_ceiling``
    keys that re-write the values after the unit flip, so even with
    ``blockSignals`` removed from production the test still passes.
    This test removes that masking by relying on the legacy ``dynamic``
    path alone.
    """
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    # Precondition: combo is at 'dB' so the preset's ``Amplitude``
    # (Linear) actually triggers an index change.
    oc.combo_amp_unit.blockSignals(True)
    oc.combo_amp_unit.setCurrentText('dB')
    oc.combo_amp_unit.blockSignals(False)

    oc._apply_preset({
        'amplitude_mode': 'Amplitude',  # Linear — flips dB → Linear
        'dynamic': '30 dB',             # → z_floor=-30, z_ceiling=0
    })

    # Combo really did flip, proving setCurrentIndex was a real change
    # (not a no-op that would silently exercise blockSignals on nothing).
    assert oc.combo_amp_unit.currentText() == 'Linear'
    # If blockSignals failed on the unit flip, _on_amp_unit_changed would
    # have set z_auto=True and overwritten floor/ceiling with the Linear
    # defaults (0.0, 1.0). These three asserts together fail the test.
    assert oc.chk_z_auto.isChecked() is False, (
        "z_auto should remain False; if it flipped to True the unit-change "
        "handler ran when it should have been blocked"
    )
    assert oc.spin_z_floor.value() == -30.0, (
        "spin_z_floor should retain the dynamic-derived -30; if it is 0.0 "
        "the unit-change handler reset it to the Linear default"
    )
    assert oc.spin_z_ceiling.value() == 0.0, (
        "spin_z_ceiling should retain the dynamic-derived 0; if it is 1.0 "
        "the unit-change handler reset it to the Linear default"
    )


def test_order_contextual_apply_preset_does_not_emit_unit_signal(qtbot):
    """Belt-and-suspenders signal-spy form of the survival contract.

    Disconnect the real ``_on_amp_unit_changed`` slot and reconnect a
    counting probe to ``combo_amp_unit.currentTextChanged``. If
    ``_apply_preset`` properly wraps its ``setCurrentIndex`` in
    ``blockSignals``, no emission reaches the probe; if blockSignals is
    removed or the wrap pair is mis-ordered, the probe records the
    transition and the test fails.

    Independent of whether the dict carries explicit z keys, this
    asserts the handler edge is not reached during preset application.

    Note: a ``monkeypatch.setattr(oc, '_on_amp_unit_changed', stub)``
    does NOT work here because Qt captured the bound method object at
    connect time; we must disconnect-and-reconnect to redirect the
    slot.
    """
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    # Start at dB so the preset's Linear flip is a real index change.
    oc.combo_amp_unit.blockSignals(True)
    oc.combo_amp_unit.setCurrentText('dB')
    oc.combo_amp_unit.blockSignals(False)

    # Replace the real slot with a counting probe.
    try:
        oc.combo_amp_unit.currentTextChanged.disconnect(
            oc._on_amp_unit_changed
        )
    except TypeError:
        pass
    calls = []
    oc.combo_amp_unit.currentTextChanged.connect(
        lambda text: calls.append(text)
    )

    oc._apply_preset({'amplitude_mode': 'Amplitude'})  # Linear

    assert oc.combo_amp_unit.currentText() == 'Linear', (
        "precondition: setCurrentIndex must have actually changed the combo"
    )
    assert calls == [], (
        f"currentTextChanged must not emit during _apply_preset's unit flip, "
        f"got {calls}"
    )


def test_order_contextual_current_params_emits_axis_keys(qtbot):
    """current_params must emit the new axis keys."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    p = oc.current_params()
    for key in ('x_auto', 'x_min', 'x_max',
                'y_auto', 'y_min', 'y_max',
                'z_auto', 'z_floor', 'z_ceiling',
                'amplitude_mode'):
        assert key in p, f'missing {key} in current_params'
    assert isinstance(p['z_auto'], bool)
    assert p['amplitude_mode'] in ('Amplitude dB', 'Amplitude')


def test_order_contextual_apply_preset_legacy_dynamic(qtbot):
    """_apply_preset must translate legacy 'dynamic' string to new
    z_auto/z_floor/z_ceiling state."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    # Legacy preset shape
    oc._apply_preset({'amplitude_mode': 'Amplitude dB', 'dynamic': '50 dB'})
    assert not oc.chk_z_auto.isChecked()
    assert oc.spin_z_floor.value() == -50.0
    assert oc.spin_z_ceiling.value() == 0.0

    oc._apply_preset({'amplitude_mode': 'Amplitude dB', 'dynamic': 'Auto'})
    assert oc.chk_z_auto.isChecked()


# ---- Wave 2 (axis-settings + COT migration plan): combo_algorithm removed ----
#
# The frequency-domain algorithm picker has been deleted. ``OrderContextual``
# now always dispatches through the COT analyzer, so ``combo_algorithm`` and
# its companion ``_on_algo_changed`` no longer exist, and ``current_params``
# does not emit the ``algorithm`` key. ``spin_samples_per_rev`` is always
# enabled (no longer gated by an algorithm choice).

def test_order_contextual_has_no_algorithm_picker(qtbot):
    """combo_algorithm and on_algo_changed are removed; spin_samples_per_rev
    is always enabled (no longer gated by algorithm choice)."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    assert not hasattr(oc, 'combo_algorithm')
    assert oc.spin_samples_per_rev.isEnabled()


def test_order_contextual_current_params_omits_algorithm(qtbot):
    """current_params must not emit 'algorithm' key (downstream MainWindow
    no longer branches on it)."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)

    p = oc.current_params()
    assert 'algorithm' not in p
    assert 'samples_per_rev' in p


# ---- Wave 4 (axis-settings + COT migration plan): FFTTimeContextual gains
# the same 坐标轴设置 group; combo_amp_mode + combo_dynamic + the freq
# auto/min/max QFormLayout block are migrated into the X / Z rows of the
# new group. Backward-compat: chk_freq_auto / spin_freq_min / spin_freq_max
# are preserved as attribute aliases so downstream main_window readers
# (Wave 5 will retire them) keep working.

def test_fft_time_contextual_has_axis_settings_group(qtbot):
    """FFTTimeContextual must contain QGroupBox '坐标轴设置' with the same
    9 controls as OrderContextual but X = time, Y = frequency."""
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    for name in (
        'chk_x_auto', 'spin_x_min', 'spin_x_max',
        'chk_y_auto', 'spin_y_min', 'spin_y_max',
        'chk_z_auto', 'spin_z_floor', 'spin_z_ceiling',
        'combo_amp_unit',
    ):
        assert hasattr(fc, name), f'missing {name}'

    assert not hasattr(fc, 'combo_amp_mode')
    assert not hasattr(fc, 'combo_dynamic')
    # chk_freq_auto + spin_freq_min/max are backward-compat names for the
    # actual frequency axis, which is Y in an FFT-vs-Time spectrogram.
    assert fc.chk_freq_auto is fc.chk_y_auto
    assert fc.spin_freq_min is fc.spin_y_min
    assert fc.spin_freq_max is fc.spin_y_max


def test_fft_time_axis_labels_match_spectrogram_axes(qtbot):
    """FFT Time Inspector must describe the plotted spectrogram itself:
    X = time, Y = frequency, Z/color = amplitude."""
    from PyQt5.QtWidgets import QLabel
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    labels = {label.text() for label in fc.findChildren(QLabel)}

    assert "时间 (X):" in labels
    assert "频率 (Y):" in labels
    assert "频率 (X):" not in labels
    assert "幅值 (Y):" not in labels


def test_axis_rows_hide_bounds_when_auto_and_show_when_manual(qtbot):
    """Automatic rows show a compact summary; manual rows show editable
    min/max fields. This keeps FFT Time / Order numbers from piling up."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)
    oc.show()
    try:
        assert oc.chk_x_auto.isChecked()
        assert hasattr(oc, "lbl_x_summary")
        assert oc.lbl_x_summary.isVisible()
        assert oc.spin_x_min.isHidden()
        assert oc.spin_x_max.isHidden()

        oc.chk_x_auto.setChecked(False)
        assert oc.lbl_x_summary.isHidden()
        assert oc.spin_x_min.isVisible()
        assert oc.spin_x_max.isVisible()
        assert oc.spin_x_min.isEnabled()
        assert oc.spin_x_max.isEnabled()
    finally:
        oc.hide()


def test_axis_auto_manual_toggle_keeps_range_area_width(qtbot):
    """Auto/manual toggling swaps content inside a fixed range area so the
    Inspector row does not jump horizontally."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)
    oc.show()
    try:
        qtbot.waitExposed(oc)
        assert hasattr(oc, "axis_x_range_host")
        auto_width = oc.axis_x_range_host.width()
        oc.chk_x_auto.setChecked(False)
        qtbot.wait(20)
        manual_width = oc.axis_x_range_host.width()
        oc.chk_x_auto.setChecked(True)
        qtbot.wait(20)
        auto_width_after = oc.axis_x_range_host.width()

        assert auto_width == manual_width == auto_width_after
    finally:
        oc.hide()


def test_axis_auto_rows_reserve_manual_width_before_first_show(qtbot):
    """Rows that start in auto mode must advertise the manual editor width.

    The Inspector uses size hints during first layout. If an auto row reports
    only its short summary label width before it is shown, the initial X/Y/Z
    row reservation is too narrow until the user toggles auto off once.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual, OrderContextual

    for cls in (FFTTimeContextual, OrderContextual):
        ctx = cls()
        qtbot.addWidget(ctx)
        ctx.chk_z_auto.setChecked(True)

        for key in ("x", "y", "z"):
            parts = ctx._axis_row_parts[key]
            host = parts["range_host"]
            assert host.sizeHint().width() >= host.minimumWidth(), (
                f"{cls.__name__}.{key} auto range host reports "
                f"sizeHint={host.sizeHint().width()}px below reserved "
                f"minimumWidth={host.minimumWidth()}px before first show"
            )


def test_axis_auto_rows_use_manual_height_on_first_display(qapp, qtbot):
    """Default auto rows should start at the same height as manual rows."""
    from pathlib import Path
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )

        for mode, ctx_name in (
            ("fft_time", "fft_time_ctx"),
            ("order", "order_ctx"),
        ):
            inspector = Inspector()
            qtbot.addWidget(inspector)
            inspector.resize(360, 850)
            inspector.set_mode(mode)
            inspector.show()
            qtbot.waitExposed(inspector)
            qapp.processEvents()

            ctx = getattr(inspector, ctx_name)
            heights = {
                key: ctx._axis_row_parts[key]["range_host"].height()
                for key in ("x", "y", "z")
            }
            assert len(set(heights.values())) == 1, (
                f"{mode} default axis row heights should match before any "
                f"auto/manual toggle, got {heights}"
            )
            inspector.hide()
    finally:
        qapp.setStyleSheet(old_sheet)


def test_axis_initial_manual_row_keeps_width_after_auto_round_trip(qtbot):
    """Rows that start in manual mode should be stable on first display.

    This catches the first-entry case where the z/color row looked narrow until
    auto was toggled once.
    """
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    qtbot.addWidget(oc)
    oc.resize(344, 620)
    oc.show()
    try:
        qtbot.waitExposed(oc)
        assert not oc.chk_z_auto.isChecked()
        initial_manual_width = oc.axis_z_range_host.width()
        initial_floor_width = oc.spin_z_floor.width()
        initial_ceiling_width = oc.spin_z_ceiling.width()

        oc.chk_z_auto.setChecked(True)
        qtbot.wait(20)
        auto_width = oc.axis_z_range_host.width()
        oc.chk_z_auto.setChecked(False)
        qtbot.wait(20)
        manual_width_after = oc.axis_z_range_host.width()

        assert initial_manual_width == auto_width == manual_width_after
        assert oc.spin_z_floor.width() == initial_floor_width
        assert oc.spin_z_ceiling.width() == initial_ceiling_width
    finally:
        oc.hide()


def test_axis_manual_rows_share_columns_and_right_edge(qtbot):
    """FFT Time and Order axis rows use one visual grid.

    The X/Y labels, automatic checkboxes, range editors, and the rightmost
    visible frame must line up across X, Y, and color rows.
    """
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual, OrderContextual

    def left(widget, root):
        return widget.mapTo(root, widget.rect().topLeft()).x()

    def right(widget, root):
        return left(widget, root) + widget.width()

    for cls in (FFTTimeContextual, OrderContextual):
        ctx = cls()
        qtbot.addWidget(ctx)
        ctx.resize(370, 760)
        ctx.show()
        try:
            qtbot.waitExposed(ctx)
            for key in ("x", "y", "z"):
                ctx._axis_row_parts[key]["checkbox"].setChecked(False)
            QApplication.processEvents()

            parts = [ctx._axis_row_parts[key] for key in ("x", "y", "z")]
            label_lefts = {left(p["label"], ctx) for p in parts}
            checkbox_lefts = {left(p["checkbox"], ctx) for p in parts}
            range_lefts = {left(p["range_host"], ctx) for p in parts}
            right_edges = {
                right(p["unit"] if p["unit"] is not None else p["spin_max"], ctx)
                for p in parts
            }

            assert len(label_lefts) == 1, f"{cls.__name__} labels: {label_lefts}"
            assert len(checkbox_lefts) == 1, (
                f"{cls.__name__} auto column: {checkbox_lefts}"
            )
            assert len(range_lefts) == 1, (
                f"{cls.__name__} range column: {range_lefts}"
            )
            assert len(right_edges) == 1, (
                f"{cls.__name__} right edges: {right_edges}"
            )
        finally:
            ctx.hide()


def test_axis_rows_fit_inspector_and_align_with_panel_right_edge(qapp, qtbot):
    """Axis rows must not overflow the 360px Inspector pane.

    Their rightmost visible controls should align to the axis group border.
    In FFT Time that also matches the 色图 dropdown's right edge below.
    """
    from pathlib import Path
    from PyQt5.QtWidgets import QGroupBox
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )

        for mode, ctx_name in (
            ("fft_time", "fft_time_ctx"),
            ("order", "order_ctx"),
        ):
            inspector = Inspector()
            qtbot.addWidget(inspector)
            inspector.resize(360, 850)
            inspector.set_mode(mode)
            inspector.show()
            qtbot.waitExposed(inspector)
            qtbot.wait(50)

            ctx = getattr(inspector, ctx_name)
            for key in ("x", "y", "z"):
                ctx._axis_row_parts[key]["checkbox"].setChecked(False)
            qapp.processEvents()

            axis_group = next(
                gb for gb in ctx.findChildren(QGroupBox)
                if gb.title() == "坐标轴设置"
            )
            group_right = (
                axis_group.mapTo(ctx, axis_group.rect().topLeft()).x()
                + axis_group.width()
            )

            right_edges = []
            for key in ("x", "y", "z"):
                parts = ctx._axis_row_parts[key]
                last = parts["unit"] if parts["unit"] is not None else parts["spin_max"]
                right_edges.append(
                    last.mapTo(ctx, last.rect().topLeft()).x() + last.width()
                )

            assert right_edges == [group_right, group_right, group_right], (
                f"{mode} axis rows should align to {group_right}, got {right_edges}"
            )
            inspector.hide()
    finally:
        qapp.setStyleSheet(old_sheet)


def test_axis_settings_grid_background_matches_tinted_panel(qapp, qtbot):
    """The shared axis-settings grid should not paint the grey page surface.

    FFT-vs-Time and Order both use the same helper. After the 2026-06-13
    分析信号/谱参数 split their axis grid sits inside the lower params_card.
    After the 2026-06-19 surface-snow redesign the params card is white
    (#ffffff) — the blank cells behind 自动 / 最小 / 最大 and the auto-summary
    rows should read as part of that white card rather than a separate
    grey/table surface.
    """
    from pathlib import Path
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )

        for mode, ctx_name in (
            ("fft_time", "fft_time_ctx"),
            ("order", "order_ctx"),
        ):
            inspector = Inspector()
            qtbot.addWidget(inspector)
            inspector.resize(288, 900)
            inspector.set_mode(mode)
            inspector.show()
            qtbot.waitExposed(inspector)
            bar = inspector._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            qapp.processEvents()

            ctx = getattr(inspector, ctx_name)
            header = ctx.findChild(QWidget, "axisHeaderRow")
            assert header is not None
            samples = [header.mapTo(inspector, QPoint(8, header.height() // 2))]
            for key in ("x", "y"):
                host = ctx._axis_row_parts[key]["range_host"]
                samples.append(host.mapTo(inspector, QPoint(host.width() - 8, host.height() // 2)))

            image = inspector.grab().toImage()
            for point in samples:
                color = image.pixelColor(point)
                # After the 2026-06-19 surface-snow redesign the params card
                # is white (#ffffff); grid cells must be transparent so they
                # show the same white card background (not a grey/tinted table).
                assert (
                    color.red() >= 250
                    and color.green() >= 250
                    and color.blue() >= 250
                ), (
                    f"{mode} axis grid background should match the white "
                    f"params card #ffffff, got {color.name()} at "
                    f"{point.x()},{point.y()}"
                )
            inspector.hide()
    finally:
        qapp.setStyleSheet(old_sheet)


def test_fft_axis_settings_grid_background_matches_tinted_panel(qapp, qtbot):
    """FFT params card is white after the 2026-06-19 surface-snow redesign;
    the axis grid should not introduce a separate grey/table surface inside
    the white card — transparent grid cells must blend with the card's
    #ffffff background.
    """
    from pathlib import Path
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )

        inspector = Inspector()
        qtbot.addWidget(inspector)
        inspector.resize(288, 900)
        inspector.set_mode("fft")
        inspector.show()
        qtbot.waitExposed(inspector)
        bar = inspector._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        qapp.processEvents()

        ctx = inspector.fft_ctx
        header = ctx.findChild(QWidget, "axisHeaderRow")
        assert header is not None
        samples = [header.mapTo(inspector, QPoint(8, header.height() // 2))]
        for key in ("x", "y"):
            host = ctx._axis_row_parts[key]["range_host"]
            samples.append(host.mapTo(inspector, QPoint(host.width() - 8, host.height() // 2)))

        image = inspector.grab().toImage()
        for point in samples:
            color = image.pixelColor(point)
            # After the 2026-06-19 surface-snow redesign the params card is
            # white (#ffffff); grid cells must be transparent so they show the
            # same white card background.
            assert (
                color.red() >= 250
                and color.green() >= 250
                and color.blue() >= 250
            ), (
                "FFT axis grid background should match the white params card "
                f"#ffffff, got {color.name()} at {point.x()},{point.y()}"
            )
    finally:
        qapp.setStyleSheet(old_sheet)


def test_inspector_numeric_spinboxes_have_no_stepper_buttons(qtbot):
    """Numeric Inspector controls should be plain numeric inputs; combo boxes
    keep their own dropdown arrows via QComboBox styling."""
    from PyQt5.QtWidgets import QAbstractSpinBox
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual, OrderContextual

    for cls in (FFTTimeContextual, OrderContextual):
        ctx = cls()
        qtbot.addWidget(ctx)
        spins = ctx.findChildren(QAbstractSpinBox)
        assert spins, f"{cls.__name__} has no spin boxes"
        assert all(
            spin.buttonSymbols() == QAbstractSpinBox.NoButtons
            for spin in spins
        )


def test_fft_time_contextual_current_params_emits_axis_keys(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    p = fc.current_params() if hasattr(fc, 'current_params') else fc.get_params()
    for key in ('x_auto', 'x_min', 'x_max',
                'y_auto', 'y_min', 'y_max',
                'z_auto', 'z_floor', 'z_ceiling',
                'amplitude_mode'):
        assert key in p
    # Legacy keys preserved for now (Wave 5 callers; safe to keep)
    assert 'freq_auto' in p
    assert 'freq_min' in p
    assert 'freq_max' in p


def test_fft_time_contextual_apply_legacy_dynamic_80db(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)
    fc._apply_preset({'amplitude_mode': 'Amplitude dB', 'dynamic': '80 dB'})
    assert not fc.chk_z_auto.isChecked()
    assert fc.spin_z_floor.value() == -80.0
    assert fc.spin_z_ceiling.value() == 0.0


def test_fft_time_contextual_accepts_deep_db_colorbar_echo(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    fc.apply_params({
        'z_auto': False,
        'z_floor': -330.0,
        'z_ceiling': -315.0,
    })

    assert fc.chk_z_auto.isChecked() is False
    assert fc.spin_z_floor.value() == -330.0
    assert fc.spin_z_ceiling.value() == -315.0


# ---- 2026-05-01 (codex review P7-L1' fix): FFTTimeContextual must satisfy
# the same unit-toggle reset invariant as OrderContextual. Closes the test
# blind spot P7-T1 from the review.

@pytest.mark.parametrize(
    "from_unit,to_unit,start_floor,start_ceiling,expected_floor,expected_ceiling",
    [
        ('dB', 'Linear', -30.0, 0.0, 0.0, 1.0),
        ('Linear', 'dB', 0.5, 0.9, -30.0, 0.0),
    ],
)
def test_fft_time_contextual_unit_toggle_resets_z_range(
    qtbot, from_unit, to_unit,
    start_floor, start_ceiling, expected_floor, expected_ceiling,
):
    """Spec §1.2 invariant for FFTTimeContextual."""
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    fc.combo_amp_unit.blockSignals(True)
    fc.combo_amp_unit.setCurrentText(from_unit)
    fc.combo_amp_unit.blockSignals(False)
    fc.chk_z_auto.setChecked(False)
    fc.spin_z_floor.setValue(start_floor)
    fc.spin_z_ceiling.setValue(start_ceiling)
    assert not fc.chk_z_auto.isChecked()
    assert fc.spin_z_floor.value() == start_floor
    assert fc.spin_z_ceiling.value() == start_ceiling

    fc.combo_amp_unit.setCurrentText(to_unit)

    assert fc.chk_z_auto.isChecked() is True
    assert fc.spin_z_floor.value() == expected_floor
    assert fc.spin_z_ceiling.value() == expected_ceiling
    assert fc.spin_z_floor.isEnabled() is False
    assert fc.spin_z_ceiling.isEnabled() is False


def test_fft_time_contextual_apply_preset_z_values_survive_unit_change(qtbot):
    """Spec §5 regression guard for FFTTimeContextual: _apply_preset must
    not trigger the unit-change handler when it sets combo_amp_unit."""
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    fc.combo_amp_unit.blockSignals(True)
    fc.combo_amp_unit.setCurrentText('Linear')
    fc.combo_amp_unit.blockSignals(False)

    fc._apply_preset({
        'amplitude_mode': 'Amplitude dB',
        'z_auto': False,
        'z_floor': -60.0,
        'z_ceiling': -10.0,
    })

    assert fc.combo_amp_unit.currentText() == 'dB'
    assert fc.chk_z_auto.isChecked() is False
    assert fc.spin_z_floor.value() == -60.0
    assert fc.spin_z_ceiling.value() == -10.0


def test_fft_time_contextual_apply_preset_legacy_dynamic_survives_unit_flip(
    qtbot,
):
    """Strong RED: prove that ``FFTTimeContextual._apply_preset`` blocks
    the ``_on_amp_unit_changed`` handler when it flips ``combo_amp_unit``.

    Order of operations in production:

      1. Legacy ``dynamic`` is processed FIRST and writes
         ``spin_z_floor=-30, spin_z_ceiling=0, chk_z_auto=False``.
      2. ``amplitude_mode`` is processed SECOND and calls
         ``combo_amp_unit.setCurrentIndex(Linear)`` — must be wrapped
         in ``blockSignals`` because if the handler fires it forces
         ``chk_z_auto=True`` and rewrites floor/ceiling to (0.0, 1.0).
      3. No explicit ``z_floor`` / ``z_ceiling`` keys are present, so
         step 2's damage is **not** masked by a later setValue.

    The companion test
    ``test_fft_time_contextual_apply_preset_z_values_survive_unit_change``
    is structurally weak: it passes explicit ``z_floor`` / ``z_ceiling``
    keys that re-write the values after the unit flip, so even with
    ``blockSignals`` removed from production the test still passes.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    # Precondition: combo at 'dB' so 'Amplitude' (Linear) actually flips.
    fc.combo_amp_unit.blockSignals(True)
    fc.combo_amp_unit.setCurrentText('dB')
    fc.combo_amp_unit.blockSignals(False)

    fc._apply_preset({
        'amplitude_mode': 'Amplitude',  # Linear — flips dB → Linear
        'dynamic': '30 dB',             # → z_floor=-30, z_ceiling=0
    })

    assert fc.combo_amp_unit.currentText() == 'Linear'
    assert fc.chk_z_auto.isChecked() is False, (
        "z_auto should remain False; if it flipped to True the unit-change "
        "handler ran when it should have been blocked"
    )
    assert fc.spin_z_floor.value() == -30.0, (
        "spin_z_floor should retain the dynamic-derived -30; if it is 0.0 "
        "the unit-change handler reset it to the Linear default"
    )
    assert fc.spin_z_ceiling.value() == 0.0, (
        "spin_z_ceiling should retain the dynamic-derived 0; if it is 1.0 "
        "the unit-change handler reset it to the Linear default"
    )


def test_fft_time_contextual_apply_preset_does_not_emit_unit_signal(qtbot):
    """Belt-and-suspenders signal-spy form of the survival contract for
    FFTTimeContextual.

    Disconnect the real ``_on_amp_unit_changed`` slot and reconnect a
    counting probe; assert no emission reaches the probe when
    ``_apply_preset`` flips the combo. Mirrors
    ``test_order_contextual_apply_preset_does_not_emit_unit_signal``.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)

    fc.combo_amp_unit.blockSignals(True)
    fc.combo_amp_unit.setCurrentText('dB')
    fc.combo_amp_unit.blockSignals(False)

    try:
        fc.combo_amp_unit.currentTextChanged.disconnect(
            fc._on_amp_unit_changed
        )
    except TypeError:
        pass
    calls = []
    fc.combo_amp_unit.currentTextChanged.connect(
        lambda text: calls.append(text)
    )

    fc._apply_preset({'amplitude_mode': 'Amplitude'})  # Linear

    assert fc.combo_amp_unit.currentText() == 'Linear', (
        "precondition: setCurrentIndex must have actually changed the combo"
    )
    assert calls == [], (
        f"currentTextChanged must not emit during _apply_preset's unit flip, "
        f"got {calls}"
    )


# ----- Wave 2a (2026-04-29): spinbox stepper buttons removed everywhere
# in the Inspector. Users only interact via keyboard / scroll wheel. The
# QSS collapses the four subcontrols to zero AND every constructor pairs
# with ``setButtonSymbols(QAbstractSpinBox.NoButtons)`` so platforms
# whose native style ignores the QSS still hide the gutter.

def test_inspector_spinboxes_have_no_button_symbols(qtbot):
    """Every QSpinBox / QDoubleSpinBox under the Inspector tree must
    report ``buttonSymbols() == NoButtons``.

    This is the widget-side leg of the double protection described in
    the QSS comment block — the QSS collapses the subcontrols to zero
    width AND every construction site sets ``setButtonSymbols`` so the
    stepper cannot leak through Qt's native style on macOS / Fusion.
    """
    from PyQt5.QtWidgets import QAbstractSpinBox, QDoubleSpinBox, QSpinBox
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
    )
    panels = [FFTContextual(), FFTTimeContextual(), OrderContextual()]
    for p in panels:
        qtbot.addWidget(p)
    spins_seen = 0
    for p in panels:
        for spin in p.findChildren((QSpinBox, QDoubleSpinBox)):
            spins_seen += 1
            assert spin.buttonSymbols() == QAbstractSpinBox.NoButtons, (
                f"{type(p).__name__}::{spin.objectName() or '<unnamed>'} "
                f"still has button symbols {spin.buttonSymbols()}"
            )
    # Sanity check: we actually iterated through spinboxes (otherwise the
    # loop above would be a vacuous pass).
    assert spins_seen >= 6, f"expected >= 6 spinboxes, found {spins_seen}"


def test_inspector_spinbox_subcontrols_take_zero_visible_space(qtbot):
    """QStyle must report zero-width up/down button rects for every
    spinbox under the Inspector tree once stylesheet polish has run.
    This catches the case where ``setButtonSymbols`` is set but the QSS
    is reverted to draw a gutter again (or vice versa).
    """
    from PyQt5.QtWidgets import (
        QApplication,
        QDoubleSpinBox,
        QSpinBox,
        QStyle,
        QStyleOptionSpinBox,
    )
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    fc = FFTTimeContextual()
    qtbot.addWidget(fc)
    fc.show()
    QApplication.processEvents()
    spins = fc.findChildren((QSpinBox, QDoubleSpinBox))
    assert spins, "expected FFTTimeContextual to contain spin boxes"
    for spin in spins:
        opt = QStyleOptionSpinBox()
        spin.initStyleOption(opt) if hasattr(spin, 'initStyleOption') else None
        # subControlRect returns the geometry the style would paint for
        # the up/down buttons. With NoButtons + zero-width QSS those
        # rects must collapse to width 0.
        up_rect = spin.style().subControlRect(
            QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxUp, spin
        )
        down_rect = spin.style().subControlRect(
            QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxDown, spin
        )
        assert up_rect.width() == 0, (
            f"{spin.objectName() or type(spin).__name__} up button still "
            f"reserves {up_rect.width()}px"
        )
        assert down_rect.width() == 0, (
            f"{spin.objectName() or type(spin).__name__} down button still "
            f"reserves {down_rect.width()}px"
        )


# ---- V5b: FFTTimeContextual.apply_params round-trip (multiview bridge) ----
#
# V7's per-section bridge calls apply_params_from_state(ctx, state) →
# ctx.apply_params(...). FFTTimeContextual previously had get_params /
# current_params but no apply_params, so the bridge would AttributeError.
# These two tests pin the round-trip contract: apply_params(get_params())
# must be idempotent, and a partial dict must touch only its keys.

def test_fft_time_apply_params_idempotent(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    # Give the signal combo a real candidate so the 'signal' key round-trips
    # through findData (None would be a no-op which still satisfies idempotency,
    # but a concrete candidate exercises the combo restore path).
    ctx.set_signal_candidates([
        ("file:a", ("f1", "a")),
        ("file:b", ("f1", "b")),
    ])
    ctx.combo_sig.setCurrentIndex(1)

    # Drive the controls into a distinctive, non-default state across every
    # widget get_params reads (combos, spins, checkboxes, amp-unit token,
    # all three axis rows). z_auto OFF so spin_z_floor/ceiling participate.
    ctx.combo_nfft.setCurrentText('2048')
    ctx.combo_win.setCurrentText('hamming')
    ctx.spin_overlap.setValue(75)
    ctx.chk_remove_mean.setChecked(False)
    ctx.combo_amp_unit.setCurrentText('dB')
    ctx.spin_db_ref.setValue(2.5)
    ctx.spin_fs.setValue(48000.0)
    ctx.chk_x_auto.setChecked(False)
    ctx.spin_x_min.setValue(1.0)
    ctx.spin_x_max.setValue(9.0)
    ctx.chk_y_auto.setChecked(False)
    ctx.spin_y_min.setValue(50.0)
    ctx.spin_y_max.setValue(2400.0)
    ctx.chk_z_auto.setChecked(False)
    ctx.spin_z_floor.setValue(-80.0)
    ctx.spin_z_ceiling.setValue(-5.0)

    p0 = ctx.get_params()
    # Sanity: the amplitude_mode token we will have to reverse-map.
    assert p0['amplitude_mode'] == 'amplitude_db'

    # Perturb several controls so apply_params has real work to do.
    ctx.combo_nfft.setCurrentText('4096')
    ctx.combo_win.setCurrentText('hanning')
    ctx.spin_overlap.setValue(25)
    ctx.chk_remove_mean.setChecked(True)
    ctx.combo_amp_unit.setCurrentText('Linear')
    ctx.spin_db_ref.setValue(1.0)
    ctx.spin_fs.setValue(1000.0)
    ctx.chk_x_auto.setChecked(True)
    ctx.spin_x_min.setValue(-3.0)
    ctx.chk_y_auto.setChecked(True)
    ctx.chk_z_auto.setChecked(True)
    ctx.spin_z_floor.setValue(-40.0)
    ctx.spin_z_ceiling.setValue(0.0)
    assert ctx.get_params() != p0  # the perturbation actually changed state

    ctx.apply_params(p0)

    # Idempotent round-trip: get_params after apply must equal the snapshot.
    assert ctx.get_params() == p0


def test_fft_time_apply_params_partial(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    before = ctx.get_params()

    # A partial dict carrying only 'nfft' must update nfft and leave every
    # other key untouched (and must not raise on the missing keys).
    ctx.apply_params({'nfft': 4096})

    after = ctx.get_params()
    assert after['nfft'] == 4096
    for key, val in before.items():
        if key in {'nfft', 'nfft_mode', 'nfft_preview', 'nfft_effective'}:
            continue
        assert after[key] == val, f"partial apply mutated unrelated key {key!r}"


def test_fft_time_auto_nfft_params_are_preview_only(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)

    assert ctx.combo_nfft.findText("自动") >= 0
    assert ctx.combo_nfft.currentText() == "自动"

    p = ctx.get_params()
    assert p["nfft"] is None
    assert p["nfft_mode"] == "auto"
    assert p["t_win_s"] == 1.5
    assert p["nfft_preview"] == 2048
    assert "自动(" in ctx._tf_summary_text()


def test_fft_time_auto_nfft_preview_is_data_aware_when_provider_set(qtbot):
    """FFT-vs-Time auto preview must mirror the data-aware compute resolver.

    Without a provider it keeps the naive ``ceil_pow2(Fs * t_win)`` estimate.
    Once the main window supplies the available sample count, the preview routes
    through the same ``resolve_nfft`` (same overlap) the spectrogram compute path
    uses, so a short capture shrinks the displayed NFFT to what actually fits.
    """
    from mf4_analyzer.signal import resolve_nfft
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.spin_fs.setValue(1000)
    ctx._t_win_s = 1.5
    ctx.spin_overlap.setValue(50)

    # No provider → naive estimate, unchanged legacy behaviour.
    assert ctx._nfft_preview() == 2048

    # Provider reports only 3000 samples available.
    ctx.set_auto_nfft_provider(lambda: 3000)
    expected = int(resolve_nfft(1000.0, 3000, 1.5, 0.5))
    assert expected == 128  # guards the hand-computed value
    assert ctx._nfft_preview() == expected
    assert f"{ctx._AUTO_NFFT_LABEL}({expected})" in ctx._tf_summary_text()

    # Plenty of samples → resolver returns the full naive target (no shrink).
    ctx.set_auto_nfft_provider(lambda: 1_000_000)
    assert ctx._nfft_preview() == 2048


def test_fft_auto_nfft_summary_is_data_aware_when_provider_set(qtbot):
    """FFT auto summary gains a data-aware 自动(N), consistent with the others.

    The FFT header historically showed a bare ``自动`` with no number. To unify
    the three tabs it now shows ``自动(N)`` once data is available, mirroring
    ``_resolve_fft_effective_params``: single-frame auto = whole-signal FFT
    length; averaging modes = the shared ``resolve_nfft`` segment length. With no
    data loaded it stays a bare ``自动`` (no misleading number).
    """
    from mf4_analyzer.signal import resolve_nfft
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    ctx.spin_fs.setValue(1000)
    ctx._t_win_s = 1.5
    auto = ctx._AUTO_NFFT_LABEL
    assert ctx.combo_nfft.currentText() == auto

    # No provider → bare "自动" (no parens), unchanged legacy header.
    assert ctx._fft_nfft_preview() is None
    assert f"{auto}(" not in ctx._fft_summary_text()
    assert ctx._fft_summary_text().startswith(f"{auto} ·")

    # Single-frame auto = whole-signal FFT → shows the full sample count.
    ctx.combo_avg_mode.setCurrentText('单帧')
    ctx.set_auto_nfft_provider(lambda: 3552)
    assert ctx._fft_nfft_preview() == 3552
    assert f"{auto}(3552)" in ctx._fft_summary_text()

    # Averaging mode → segment length via the same resolver compute uses.
    ctx.combo_avg_mode.setCurrentText('线性平均')
    ctx.spin_avg_overlap.setValue(50)
    ctx.set_auto_nfft_provider(lambda: 3000)
    expected = int(resolve_nfft(1000.0, 3000, 1.5, 0.5))
    assert expected == 128  # guards the hand-computed value
    assert ctx._fft_nfft_preview() == expected
    assert f"{auto}({expected})" in ctx._fft_summary_text()


def test_order_summary_label_refreshes_on_set_fs(qtbot):
    """set_fs (the data-source-change hook) repaints the collapsed summary.

    The auto-NFFT preview is data-aware only once a signal is selected; set_fs
    is the single point the main window calls on every source/Fs change, so it
    must refresh the label — otherwise the header keeps a stale 自动(N) until the
    user happens to nudge a param.
    """
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    ctx = OrderContextual()
    qtbot.addWidget(ctx)
    ctx.spin_samples_per_rev.setValue(512)
    ctx.spin_order_res.setValue(0.10)
    ctx.set_auto_nfft_provider(lambda: 4.0)  # data-aware → 512
    ctx._order_section.set_summary("STALE")
    ctx.set_fs(50.0)
    assert ctx._order_section.summary_text() == ctx._order_summary_text()
    assert "自动(512)" in ctx._order_section.summary_text()


def test_fft_time_summary_label_refreshes_on_set_fs(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx._t_win_s = 1.5
    ctx.spin_overlap.setValue(50)
    ctx.set_auto_nfft_provider(lambda: 3000)  # data-aware → 128
    ctx._tf_section.set_summary("STALE")
    ctx.set_fs(1000.0)
    assert ctx._tf_section.summary_text() == ctx._tf_summary_text()
    assert "自动(128)" in ctx._tf_section.summary_text()


def test_fft_summary_label_refreshes_on_set_fs(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    ctx.combo_nfft.setCurrentText(ctx._AUTO_NFFT_LABEL)
    ctx.combo_avg_mode.setCurrentText('单帧')
    ctx.set_auto_nfft_provider(lambda: 4096)  # single-frame → full length 4096
    ctx._fft_section.set_summary("STALE")
    ctx.set_fs(1000.0)
    assert ctx._fft_section.summary_text() == ctx._fft_summary_text()
    assert "自动(4096)" in ctx._fft_section.summary_text()


def test_fft_time_fixed_nfft_params_still_return_int(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.combo_nfft.setCurrentText("4096")

    p = ctx.get_params()
    assert p["nfft"] == 4096
    assert isinstance(p["nfft"], int)
    assert p["nfft_mode"] == "fixed"
    assert p["nfft_effective"] == 4096


def test_order_auto_nfft_params_are_preview_only(qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    ctx = OrderContextual()
    qtbot.addWidget(ctx)
    auto = ctx._AUTO_NFFT_LABEL

    assert ctx.combo_nfft.findText(auto) >= 0
    assert ctx.combo_nfft.currentText() == auto

    p = ctx.get_params()
    assert p["nfft"] is None
    assert p["nfft_mode"] == "auto"
    assert p["nfft_preview"] == 4096
    assert f"{auto}(4096)" in ctx._order_summary_text()

    ctx.spin_order_res.setValue(0.05)
    assert ctx.get_params()["nfft_preview"] == 8192
    assert f"{auto}(8192)" in ctx._order_summary_text()

    ctx.spin_order_res.setValue(0.25)
    assert ctx.get_params()["nfft_preview"] == 1024
    assert f"{auto}(1024)" in ctx._order_summary_text()


def test_order_auto_nfft_preview_is_data_aware_when_provider_set(qtbot):
    """Auto-nfft preview must mirror the data-aware compute resolver.

    With no data provider the preview falls back to the naive
    ``ceil_pow2(samples_per_rev / order_res)`` upper bound (Fs/data-blind).
    Once the main window supplies the available revolution count, the preview
    routes through the same ``resolve_order_nfft`` the COT compute path uses, so
    a short / low-rev capture shrinks the displayed (and computed) NFFT instead
    of advertising a meaningless 8192.
    """
    from mf4_analyzer.signal import resolve_order_nfft
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    ctx = OrderContextual()
    qtbot.addWidget(ctx)
    ctx.spin_samples_per_rev.setValue(512)
    ctx.spin_order_res.setValue(0.10)

    # No provider → naive upper bound, unchanged legacy behaviour.
    assert ctx._order_nfft_preview() == 8192

    # Provider reports ~4 revolutions of data (n_angle = 512 * 4 = 2048): the
    # resolver shrinks NFFT to satisfy min_frames / max_window_frac.
    ctx.set_auto_nfft_provider(lambda: 4.0)
    expected = int(resolve_order_nfft(512, 0.10, 2048, overlap=0.75))
    assert expected == 512  # guards the hand-computed value
    assert ctx._order_nfft_preview() == expected
    assert f"{ctx._AUTO_NFFT_LABEL}({expected})" in ctx._order_summary_text()

    # Plenty of revolutions → resolver returns the full naive target (no shrink).
    ctx.set_auto_nfft_provider(lambda: 1000.0)
    assert ctx._order_nfft_preview() == 8192


def test_order_fixed_nfft_params_and_legacy_preset_still_return_int(qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    ctx = OrderContextual()
    qtbot.addWidget(ctx)

    ctx.apply_params({"nfft": 4096})
    p = ctx.get_params()
    assert ctx.combo_nfft.currentText() == "4096"
    assert p["nfft"] == 4096
    assert p["nfft_mode"] == "fixed"
    assert p["nfft_effective"] == 4096

    ctx._apply_preset({"nfft": "2048"})
    p = ctx.current_params()
    assert ctx.combo_nfft.currentText() == "2048"
    assert p["nfft"] == 2048
    assert p["nfft_mode"] == "fixed"


# ---- Signal-type built-in presets + per-unit 推荐 highlight ----

def test_recommend_preset_for_unit_exact_match(qapp):
    """Unit -> preset key uses EXACT alias matching with vibration fallback."""
    from mf4_analyzer.ui.inspector_sections import recommend_preset_for_unit

    # Torque-family aliases.
    assert recommend_preset_for_unit('Nm') == 'torque'
    assert recommend_preset_for_unit('kPa') == 'torque'
    assert recommend_preset_for_unit('°') == 'torque'  # degree sign
    assert recommend_preset_for_unit('deg') == 'torque'
    assert recommend_preset_for_unit('%') == 'torque'
    # Vibration-family aliases (incl. superscript-folding equivalence).
    assert recommend_preset_for_unit('g') == 'vibration'
    assert recommend_preset_for_unit('m/s²') == 'vibration'
    assert recommend_preset_for_unit('m/s^2') == 'vibration'
    assert recommend_preset_for_unit('m/s2') == 'vibration'
    assert recommend_preset_for_unit('mm/s') == 'vibration'
    # Fallback (unrecognized / empty -> vibration).
    assert recommend_preset_for_unit('rpm') == 'vibration'
    assert recommend_preset_for_unit('') == 'vibration'
    assert recommend_preset_for_unit(None) == 'vibration'


def test_recommend_preset_for_unit_no_substring_false_positive(qapp):
    """Exact matching must not let aliases bleed into longer unit strings."""
    from mf4_analyzer.ui.inspector_sections import (
        recommend_preset_for_unit, _normalize_unit,
        _TORQUE_UNITS, _VIBRATION_UNITS,
    )

    # 'kg' is unknown -> fallback (vibration), but must NOT be an alias.
    assert recommend_preset_for_unit('kg') == 'vibration'
    assert _normalize_unit('kg') not in _VIBRATION_UNITS
    assert _normalize_unit('kg') not in _TORQUE_UNITS
    # 'kPa' is explicitly torque and must not be reclassified by a 'pa' hit.
    assert recommend_preset_for_unit('kPa') == 'torque'
    # Longer strings containing torque aliases must not match by substring.
    assert recommend_preset_for_unit('kPa/s') == 'vibration'
    assert recommend_preset_for_unit('foobar') == 'vibration'


def test_preset_bar_set_recommended_toggles_property(qapp):
    """Recommendation is a badge hint; it must not mark the slot as applied."""
    from mf4_analyzer.ui.inspector_sections import PresetBar

    bar = PresetBar('test_kind_recommend', lambda: {}, lambda d: None)
    bar.set_recommended(2)
    assert bar._load_btns[1].property('recommended') == 'false'
    assert bar._load_btns[2].property('recommended') == 'true'
    assert bar._load_btns[3].property('recommended') == 'false'
    assert bar._load_btns[2].property('applied') == 'false'
    assert not bar._load_btns[2].text().startswith('★ ')
    assert bar._recommend_badges[2].text() == '荐'
    assert bar._recommend_badges[2].width() == 14
    assert bar._recommend_badges[2].height() == 14
    assert not bar._recommend_badges[2].isHidden()
    assert bar._recommend_badges[1].isHidden()

    bar.set_recommended(3)
    assert bar._load_btns[2].property('recommended') == 'false'
    assert bar._load_btns[3].property('recommended') == 'true'
    assert bar._recommend_badges[2].isHidden()
    assert not bar._recommend_badges[3].isHidden()

    bar.set_recommended(None)
    for n in (1, 2, 3):
        assert bar._load_btns[n].property('recommended') == 'false'
        assert not bar._load_btns[n].text().startswith('★ ')
        assert bar._recommend_badges[n].isHidden()


def test_builtin_preset_second_left_click_restores_default_params(qapp):
    from mf4_analyzer.ui.inspector_sections import PresetBar

    applied = []
    bar = PresetBar(
        'test_kind_builtin_toggle',
        lambda: {'mode': 'current'},
        lambda d: applied.append(dict(d)),
        builtin_defaults={
            1: {'display_name': '频率优先', 'params': {'mode': 'frequency'}},
        },
        default_params={'mode': 'default'},
    )

    bar._on_left_click(1)
    assert applied[-1] == {'mode': 'frequency'}
    assert bar._load_btns[1].property('applied') == 'true'
    assert bar._load_btns[1].property('recommended') == 'false'

    bar._on_left_click(1)
    assert applied[-1] == {'mode': 'default'}
    assert bar._load_btns[1].property('applied') == 'false'
    assert bar._load_btns[1].property('recommended') == 'false'


def test_recommended_only_builtin_click_still_loads_preset(qapp):
    from mf4_analyzer.ui.inspector_sections import PresetBar

    applied = []
    bar = PresetBar(
        'test_kind_builtin_recommend_only',
        lambda: {'mode': 'current'},
        lambda d: applied.append(dict(d)),
        builtin_defaults={
            1: {'display_name': '频率优先', 'params': {'mode': 'frequency'}},
        },
        default_params={'mode': 'default'},
    )

    bar.set_recommended(1)
    bar._on_left_click(1)

    assert applied[-1] == {'mode': 'frequency'}
    assert bar._load_btns[1].property('recommended') == 'true'
    assert bar._load_btns[1].property('applied') == 'true'


def test_recommendation_change_clears_builtin_toggle_selection(qapp):
    from mf4_analyzer.ui.inspector_sections import PresetBar

    applied = []
    bar = PresetBar(
        'test_kind_builtin_recommendation_change',
        lambda: {'mode': 'current'},
        lambda d: applied.append(dict(d)),
        builtin_defaults={
            1: {'display_name': '频率优先', 'params': {'mode': 'frequency'}},
            2: {'display_name': '均衡', 'params': {'mode': 'balanced'}},
        },
        default_params={'mode': 'default'},
    )

    bar._on_left_click(1)
    bar.set_recommended(2)
    bar._on_left_click(1)

    assert applied[-1] == {'mode': 'frequency'}
    assert bar._load_btns[1].property('applied') == 'true'
    assert bar._load_btns[1].property('recommended') == 'false'
    assert bar._load_btns[2].property('recommended') == 'true'


def _combo_text_hits(combo, value):
    return combo.findText(str(value)) >= 0


def test_fft_builtin_presets_apply_through_combos(qapp):
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual, BUILTIN_PRESET_KEYS,
    )
    fc = FFTContextual()
    expected = {
        'torque': dict(
            window='flattop', nfft='自动', t_win_s=2.5, overlap=75,
            amp_y='dB', avg_mode='线性平均', avg_overlap=75,
        ),
        'vibration': dict(
            window='hanning', nfft='自动', t_win_s=1.5, overlap=50,
            amp_y='dB', avg_mode='线性平均', avg_overlap=50,
        ),
        'transient': dict(
            window='hanning', nfft='自动', t_win_s=0.6, overlap=75,
            amp_y='dB', avg_mode='峰值保持', avg_overlap=75,
        ),
    }
    assert fc._SIGNAL_BUILTIN_PRESETS == expected
    for key in BUILTIN_PRESET_KEYS:
        p = fc._SIGNAL_BUILTIN_PRESETS[key]
        assert 'remove_mean' not in p
        assert _combo_text_hits(fc.combo_win, p['window']), (key, p['window'])
        assert _combo_text_hits(fc.combo_nfft, p['nfft']), (key, p['nfft'])
        assert _combo_text_hits(fc.combo_amp_y, p['amp_y']), (key, p['amp_y'])
        assert _combo_text_hits(fc.combo_avg_mode, p['avg_mode']), (
            key, p['avg_mode'])

    fc._apply_preset(fc._SIGNAL_BUILTIN_PRESETS['torque'])
    assert fc.combo_nfft.currentText() == '自动'
    assert fc.combo_amp_y.currentText() == 'dB'
    assert fc._t_win_s == 2.5
    params = fc.current_params()
    assert params['nfft'] is None
    assert params['nfft_mode'] == 'auto'
    assert params['t_win_s'] == 2.5


def test_fft_builtin_preset_second_click_restores_defaults(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    from mf4_analyzer.ui.inspector_sections._helpers import _preset_settings

    settings = _preset_settings()
    for slot in (1, 2, 3):
        settings.remove(f"fft/preset_override/{slot}")
    fc = FFTContextual()

    fc.preset_bar._on_left_click(1)
    assert fc.combo_win.currentText() == 'flattop'
    assert fc.spin_overlap.value() == 75
    assert fc.combo_avg_mode.currentText() == '线性平均'
    assert fc.preset_bar._load_btns[1].property('applied') == 'true'

    fc.preset_bar._on_left_click(1)
    assert fc.combo_win.currentText() == 'hanning'
    assert fc.spin_overlap.value() == 50
    assert fc.combo_avg_mode.currentText() == '单帧'
    assert fc.preset_bar._load_btns[1].property('applied') == 'false'


def test_order_builtin_presets_apply_through_combos(qapp):
    from mf4_analyzer.ui.inspector_sections import (
        OrderContextual, BUILTIN_PRESET_KEYS,
    )
    oc = OrderContextual()
    auto = oc._AUTO_NFFT_LABEL
    expected = {
        'torque': dict(
            max_order=20, order_res=0.05, time_res=0.10, nfft=auto,
            samples_per_rev=256, amplitude_mode='Amplitude dB',
        ),
        'vibration': dict(
            max_order=50, order_res=0.10, time_res=0.05, nfft=auto,
            samples_per_rev=512, amplitude_mode='Amplitude dB',
        ),
        'transient': dict(
            max_order=30, order_res=0.25, time_res=0.02, nfft=auto,
            samples_per_rev=256, amplitude_mode='Amplitude dB',
        ),
    }
    assert oc._SIGNAL_BUILTIN_PRESETS == expected
    for key in BUILTIN_PRESET_KEYS:
        p = oc._SIGNAL_BUILTIN_PRESETS[key]
        assert 'window' not in p
        assert oc.spin_mo.minimum() <= p['max_order'] <= oc.spin_mo.maximum()
        assert _combo_text_hits(oc.combo_nfft, p['nfft']), (key, p['nfft'])
        target = 'dB' if 'dB' in p['amplitude_mode'] else 'Linear'
        assert _combo_text_hits(oc.combo_amp_unit, target), (key, target)

    oc._apply_preset(oc._SIGNAL_BUILTIN_PRESETS['torque'])
    params = oc.current_params()
    assert 'dB' in params['amplitude_mode']
    assert params['nfft'] is None
    assert params['nfft_mode'] == 'auto'
    assert params['nfft_preview'] == 8192
    assert f"{auto}(8192)" in oc._order_summary_text()


def test_order_builtin_preset_second_click_restores_defaults(qapp):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    from mf4_analyzer.ui.inspector_sections._helpers import _preset_settings

    settings = _preset_settings()
    for slot in (1, 2, 3):
        settings.remove(f"order/preset_override/{slot}")
    oc = OrderContextual()

    oc.preset_bar._on_left_click(1)
    assert oc.spin_order_res.value() == 0.05
    assert oc.spin_time_res.value() == 0.10
    assert oc.preset_bar._load_btns[1].property('applied') == 'true'

    oc.preset_bar._on_left_click(1)
    assert oc.spin_order_res.value() == 0.10
    assert oc.spin_time_res.value() == 0.05
    assert oc.preset_bar._load_btns[1].property('applied') == 'false'


def test_fft_time_builtin_presets_apply_through_combos(qtbot):
    from mf4_analyzer.ui.inspector_sections import (
        FFTTimeContextual, BUILTIN_PRESET_KEYS,
    )
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    expected = {
        'torque': dict(
            window='flattop', t_win_s=2.5, overlap=75,
            amplitude_mode='Amplitude dB', freq_auto=True,
            dynamic='Auto', cmap='viridis',
        ),
        'vibration': dict(
            window='hanning', t_win_s=1.5, overlap=50,
            amplitude_mode='Amplitude dB', freq_auto=True,
            dynamic='Auto', cmap='turbo',
        ),
        'transient': dict(
            window='hanning', t_win_s=0.6, overlap=75,
            amplitude_mode='Amplitude dB', freq_auto=True,
            dynamic='Auto', cmap='turbo',
        ),
    }
    assert ctx._BUILTIN_PRESETS == expected
    for key in BUILTIN_PRESET_KEYS:
        p = ctx._BUILTIN_PRESETS[key]
        assert _combo_text_hits(ctx.combo_win, p['window']), (key, p['window'])
        assert _combo_text_hits(ctx.combo_nfft, "自动")
        full = ctx._builtin_preset_full_params(key)
        assert full['nfft'] == "自动"
        assert full['nfft_mode'] == "auto"
        assert full['t_win_s'] == p['t_win_s']
    assert ctx._builtin_preset_full_params('torque')['z_auto'] is True
    assert ctx._builtin_preset_full_params('vibration')['z_auto'] is True
    assert ctx._builtin_preset_full_params('transient')['z_auto'] is True
    assert ctx._builtin_preset_full_params('torque')['z_floor'] == -40.0
    assert ctx._builtin_preset_full_params('vibration')['z_floor'] == -40.0
    assert ctx._builtin_preset_full_params('transient')['z_floor'] == -30.0

    ctx.apply_builtin_preset('torque')
    assert ctx.combo_nfft.currentText() == "自动"
    assert ctx._t_win_s == 2.5
    assert ctx.combo_amp_unit.currentText() == "dB"
    assert "自动(" in ctx._tf_summary_text()


def test_fft_time_builtin_preset_second_click_restores_defaults(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    from mf4_analyzer.ui.inspector_sections._helpers import _preset_settings

    settings = _preset_settings()
    for slot in (1, 2, 3):
        settings.remove(f"fft_time/preset_override/{slot}")
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)

    ctx.preset_bar._on_left_click(1)
    assert ctx.combo_win.currentText() == 'flattop'
    assert ctx.spin_overlap.value() == 75
    assert ctx.chk_z_auto.isChecked() is True
    assert ctx.preset_bar._load_btns[1].property('applied') == 'true'

    ctx.preset_bar._on_left_click(1)
    assert ctx.combo_win.currentText() == 'hanning'
    assert ctx.spin_overlap.value() == 80
    assert ctx.chk_z_auto.isChecked() is False
    assert ctx.spin_z_floor.value() == -70.0
    assert ctx.spin_z_ceiling.value() == -20.0
    assert ctx.preset_bar._load_btns[1].property('applied') == 'false'


def test_order_builtin_presets_respect_order_nyquist(qapp):
    """Order Nyquist: each preset keeps samples_per_rev >= 2 * max_order."""
    from mf4_analyzer.ui.inspector_sections import (
        OrderContextual, BUILTIN_PRESET_KEYS,
    )
    oc = OrderContextual()
    for key in BUILTIN_PRESET_KEYS:
        p = oc._SIGNAL_BUILTIN_PRESETS[key]
        assert p['samples_per_rev'] >= 2 * p['max_order'], (
            f"{key}: samples_per_rev={p['samples_per_rev']} violates "
            f"order-Nyquist for max_order={p['max_order']}"
        )


def test_set_recommended_for_unit_highlights_correct_slot(qapp, qtbot):
    """set_recommended_for_unit maps unit -> slot (torque=1/vibration=2/transient=3)."""
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual, FFTTimeContextual, OrderContextual,
    )
    fc = FFTContextual()
    qtbot.addWidget(fc)
    fc.set_recommended_for_unit('Nm')  # torque -> slot 1
    assert fc.preset_bar._load_btns[1].property('recommended') == 'true'
    fc.set_recommended_for_unit('g')  # vibration -> slot 2
    assert fc.preset_bar._load_btns[2].property('recommended') == 'true'
    fc.set_recommended_for_unit('rpm')  # fallback vibration -> slot 2
    assert fc.preset_bar._load_btns[2].property('recommended') == 'true'
    fc.set_recommended_for_unit('')  # empty unit also falls back to vibration
    assert fc.preset_bar._load_btns[2].property('recommended') == 'true'
    fc.set_recommended_for_unit(None)  # clear
    for n in (1, 2, 3):
        assert fc.preset_bar._load_btns[n].property('recommended') == 'false'

    oc = OrderContextual()
    qtbot.addWidget(oc)
    oc.set_recommended_for_unit('°')  # torque -> slot 1
    assert oc.preset_bar._load_btns[1].property('recommended') == 'true'
    oc.set_recommended_for_unit('m/s²')  # vibration -> slot 2
    assert oc.preset_bar._load_btns[2].property('recommended') == 'true'

    tc = FFTTimeContextual()
    qtbot.addWidget(tc)
    tc.set_recommended_for_unit('Nm')  # torque -> slot 1
    assert tc.preset_bar._load_btns[1].property('recommended') == 'true'
    tc.set_recommended_for_unit('unknown-unit')  # fallback vibration -> slot 2
    assert tc.preset_bar._load_btns[2].property('recommended') == 'true'


# ---- Task 2: Built-in preset hover card shows blurb, not '已保存参数快照' ----

def test_preset_hover_card_builtin_blurb(qtbot):
    """Built-in preset hover card sub-label shows blurb, not '已保存参数快照'."""
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    from PyQt5.QtWidgets import QLabel
    from PyQt5.QtCore import QSettings
    s = QSettings("MF4Analyzer", "DataAnalyzer")
    for slot in (1, 2, 3):
        s.remove(f"fft_time/preset_override/{slot}")
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    # Trigger hover for slot 1 (频率优先/torque builtin)
    bar._show_hover(1)
    sub_labels = bar._hover_card.findChildren(QLabel)
    sub_texts = [l.text() for l in sub_labels]
    # Should contain blurb keyword '适合' and NOT '已保存参数快照'
    assert any("适合" in t for t in sub_texts), f"No '适合' in: {sub_texts}"
    assert not any("已保存参数快照" in t for t in sub_texts), f"Old sub found: {sub_texts}"
    # Non-builtin user-saved: sub should still show '已保存参数快照'
    bar._write(1, '我的预设', {})
    bar._show_hover(1)
    sub_labels2 = bar._hover_card.findChildren(QLabel)
    sub_texts2 = [l.text() for l in sub_labels2]
    assert any("已保存参数快照" in t for t in sub_texts2), f"Missing old sub: {sub_texts2}"
    s.remove("fft_time/preset_override/1")


# ---- Task 3: FFTTimeContextual spectral-param tooltip coverage ----

def test_fft_time_param_tooltips(qtbot):
    """FFTTimeContextual spectral-param widgets must have non-empty tooltips."""
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    checks = [
        (ctx.combo_win, "泄漏"),
        (ctx.combo_nfft, "频率"),
        (ctx.spin_overlap, "重叠"),
        (ctx.chk_remove_mean, "直流"),
        (ctx.spin_db_ref, "dB"),
        (ctx.combo_amp_unit, "动态"),
        (ctx.spin_z_floor, "映射"),
    ]
    for widget, keyword in checks:
        tip = widget.toolTip()
        assert tip and keyword in tip, (
            f"{widget.objectName() or type(widget).__name__} toolTip missing '{keyword}': {tip!r}"
        )


# ---- Task 4: FFTContextual spectral-param tooltip coverage ----

def test_fft_param_tooltips(qtbot):
    """FFTContextual spectral-param widgets must have non-empty tooltips."""
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    checks = [
        (ctx.combo_win, "泄漏"),
        (ctx.combo_nfft, "频率"),
        (ctx.spin_overlap, "重叠"),
        (ctx.combo_amp_y, "动态"),
    ]
    for widget, keyword in checks:
        tip = widget.toolTip()
        assert tip and keyword in tip, (
            f"{type(widget).__name__} toolTip missing '{keyword}': {tip!r}"
        )
    # Pre-existing tooltips must NOT be cleared
    assert ctx.combo_avg_mode.toolTip(), "combo_avg_mode tooltip cleared"


# ---- Task 5: OrderContextual spectral-param tooltip coverage ----

def test_order_param_tooltips(qtbot):
    """OrderContextual spectral-param widgets must have non-empty tooltips."""
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    ctx = OrderContextual()
    qtbot.addWidget(ctx)
    checks = [
        (ctx.spin_rf, "电机 rpm"),
        (ctx.spin_mo, "阶次"),
        (ctx.spin_order_res, "细度"),
        (ctx.spin_time_res, "时间"),
        (ctx.combo_nfft, "阶次"),
    ]
    for widget, keyword in checks:
        tip = widget.toolTip()
        assert tip and keyword in tip, (
            f"{type(widget).__name__} toolTip missing '{keyword}': {tip!r}"
        )
    # spin_samples_per_rev must still have its original tooltip
    assert ctx.spin_samples_per_rev.toolTip(), "spin_samples_per_rev tooltip cleared"


# ---- dB reference placement tests (Task 3) ----

def _form_label_sequences(widget):
    from PyQt5.QtWidgets import QFormLayout, QLabel

    sequences = []
    for form in widget.findChildren(QFormLayout):
        labels = []
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.LabelRole)
            if item is None:
                continue
            label_widget = item.widget()
            if isinstance(label_widget, QLabel):
                labels.append(label_widget.text())
        if labels:
            sequences.append(labels)
    return sequences


def _assert_db_reference_precedes_axis_header(widget):
    from PyQt5.QtWidgets import QGroupBox, QWidget

    axis_group = widget.findChild(QGroupBox, "axisSettingsGroup")
    assert axis_group is not None
    reference_row = axis_group.findChild(QWidget, "dbReferenceAxisRow")
    header = axis_group.findChild(QWidget, "axisHeaderRow")
    assert reference_row is not None
    assert header is not None
    layout = axis_group.layout()
    assert layout.indexOf(reference_row) == 0
    assert layout.indexOf(header) == 1


def test_db_reference_precedes_axis_header_in_all_analysis_contexts(qtbot):
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
    )

    for cls in (FFTContextual, FFTTimeContextual, OrderContextual):
        ctx = cls()
        qtbot.addWidget(ctx)
        _assert_db_reference_precedes_axis_header(ctx)
        assert hasattr(ctx, "spin_db_ref")
        assert "dB" in ctx.spin_db_ref.toolTip()


def test_fft_time_no_standalone_amplitude_group(qtbot):
    from PyQt5.QtWidgets import QGroupBox
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    titles = [g.title() for g in ctx.findChildren(QGroupBox)]
    assert "幅值" not in titles


# ---- 2026-07-12 dB-reference-defaults Task 4: shared compound control ----
#
# Spec: docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md
# §5.3, §10, §13 (S1/S2). Plan Step 4.1's literal 8 test names.

def _analysis_context_classes():
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
    )

    return (FFTContextual, FFTTimeContextual, OrderContextual)


def test_all_analysis_contexts_use_shared_db_reference_compound_control(qtbot):
    from mf4_analyzer.ui.widgets.db_reference import (
        DbReferenceControl,
        ScientificReferenceSpinBox,
    )

    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)

        assert isinstance(ctx.db_reference_control, DbReferenceControl), (
            f"{cls.__name__}.db_reference_control is not a DbReferenceControl"
        )
        assert isinstance(ctx.spin_db_ref, ScientificReferenceSpinBox)
        # Task 4 alias contract: ctx.spin_db_ref MUST be the compound's own
        # editor, not a second stand-alone widget.
        assert ctx.spin_db_ref is ctx.db_reference_control.editor

        control = ctx.db_reference_control
        assert control.objectName() == "dbReferenceControl"
        assert control.editor.objectName() == "dbReferenceEditor"
        assert control.manage_button.objectName() == "dbReferenceManageButton"
        assert control.badge.objectName() == "dbReferenceModeBadge"
        assert control.source_label.objectName() == "dbReferenceSourceLabel"


def test_db_reference_compound_row_precedes_axis_header_and_fits_within_320px(qtbot):
    from PyQt5.QtWidgets import QLabel, QWidget
    from mf4_analyzer.ui.inspector_sections._helpers import _SHORT_FIELD_MAX_WIDTH

    # Every constructed ctx is kept alive (in ``_keep_alive``) for the whole
    # test: qtbot.addWidget only stores a WEAKREF for end-of-test cleanup, so
    # reassigning the loop-local ``ctx`` name would let Python GC the
    # previous widget (and its PresetBar's per-button installEventFilter
    # hover machinery) mid-test, racing in-flight Enter/Leave/Resize events
    # against teardown and crashing the Qt event loop with an unrelated
    # AttributeError on PresetBar._load_btns.
    _keep_alive = []
    for cls in _analysis_context_classes():
        for pane_width in (288, 320):
            ctx = cls()
            _keep_alive.append(ctx)
            qtbot.addWidget(ctx)
            params_section = next(
                (
                    getattr(ctx, attr)
                    for attr in ("_fft_section", "_tf_section", "_order_section")
                    if hasattr(ctx, attr)
                ),
                None,
            )
            assert params_section is not None
            params_section.set_expanded(True)
            ctx.resize(pane_width, 900)
            ctx.show()
            qtbot.waitExposed(ctx)
            qtbot.wait(20)

            _assert_db_reference_precedes_axis_header(ctx)

            control = ctx.db_reference_control
            assert control.maximumWidth() <= _SHORT_FIELD_MAX_WIDTH, (
                f"{cls.__name__} db_reference_control maximumWidth="
                f"{control.maximumWidth()}px at pane={pane_width}px "
                "should stay within the A1 field cap (no Inspector widening)."
            )
            top_left = control.mapTo(ctx, control.rect().topLeft())
            right_edge = top_left.x() + control.width()
            assert right_edge <= pane_width, (
                f"{cls.__name__} db_reference_control right edge "
                f"{right_edge}px overflows the {pane_width}px pane"
            )

            # The dB reference is now part of the axis group, but it must
            # retain the standard Inspector field convention: its compound
            # control uses the same trailing datum as the field above, rather
            # than starting immediately after the shorter axis label column.
            axis_row = ctx.findChild(QWidget, "dbReferenceAxisRow")
            assert axis_row is not None
            control_right = control.mapTo(ctx, control.rect().topRight()).x()
            row_right = axis_row.mapTo(ctx, axis_row.rect().topRight()).x()
            assert abs(control_right - row_right) <= 1, (
                f"{cls.__name__} dB reference right edge {control_right}px "
                f"does not align with its axis row right edge {row_right}px "
                f"at pane={pane_width}px"
            )
            weighting_right = ctx.combo_weighting.mapTo(
                ctx, ctx.combo_weighting.rect().topRight(),
            ).x()
            # The two QGroupBox bodies have a 2px frame-boundary difference;
            # control/weighting edges within that tolerance are visually one
            # right-aligned datum.
            assert abs(control_right - weighting_right) <= 2, (
                f"{cls.__name__} dB reference right edge {control_right}px "
                f"does not align with the weighting field right edge "
                f"{weighting_right}px at pane={pane_width}px"
            )
            assert control.editor.width() > control.editor.minimumSizeHint().width(), (
                f"{cls.__name__} dB reference editor did not expand to fill "
                f"its axis-row field at pane={pane_width}px"
            )

            axis_label = next(
                label
                for label in axis_row.findChildren(QLabel)
                if label.text() == "dB 参考:"
            )
            label_center = axis_label.mapTo(
                ctx, axis_label.rect().center(),
            ).y()
            editor_center = control.editor.mapTo(
                ctx, control.editor.rect().center(),
            ).y()
            assert abs(label_center - editor_center) <= 1, (
                f"{cls.__name__} dB reference label center {label_center}px "
                f"does not align with editor center {editor_center}px "
                f"at pane={pane_width}px"
            )

            control.refresh_geometry()
            btn = control.manage_button
            assert btn.width() == btn.height() > 0, (
                f"{cls.__name__} manage button not square at pane={pane_width}px "
                "(a wrap/overflow would starve it of its editor-matched height)."
            )
            assert control.rect().contains(control.badge.geometry()), (
                f"{cls.__name__} badge clipped at pane={pane_width}px"
            )
            ctx.hide()


def test_all_context_params_emit_mode_and_effective_value(qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)

        for getter_name in ("get_params", "current_params"):
            params = getattr(ctx, getter_name)()
            assert params["db_reference_mode"] == "auto", (
                f"{cls.__name__}.{getter_name}() default db_reference_mode"
            )
            assert params["db_reference"] == pytest.approx(1.0)

        # A genuine user commit (Enter) flips Auto -> Manual; both accessors
        # must reflect the new mode AND the committed value.
        editor = ctx.db_reference_control.editor
        editor.lineEdit().selectAll()
        QTest.keyClicks(editor.lineEdit(), "2.5e-6")
        QTest.keyClick(editor, Qt.Key_Return)

        assert ctx.db_reference_control.mode() == "manual"
        for getter_name in ("get_params", "current_params"):
            params = getattr(ctx, getter_name)()
            assert params["db_reference_mode"] == "manual", (
                f"{cls.__name__}.{getter_name}() did not pick up the manual commit"
            )
            assert params["db_reference"] == pytest.approx(2.5e-6, rel=1e-6)


def test_apply_params_missing_reference_keys_preserves_mode_value_and_weighting(qtbot):
    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)
        ctx.db_reference_control.set_mode("manual")
        ctx.spin_db_ref.setValue(3.3e-5)
        ctx._apply_weighting_value("A")

        before = ctx.get_params()
        assert before["weighting"] == "A"
        assert before["db_reference_mode"] == "manual"
        assert before["db_reference"] == pytest.approx(3.3e-5)

        # A partial dict that carries none of weighting/db_reference/
        # db_reference_mode must leave all three untouched.
        ctx.apply_params({})

        after = ctx.get_params()
        assert after["weighting"] == "A"
        assert after["db_reference_mode"] == "manual"
        assert after["db_reference"] == pytest.approx(3.3e-5)


def test_partial_db_reference_value_does_not_force_mode(qtbot):
    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)
        assert ctx.db_reference_control.mode() == "auto"

        # db_reference alone (no mode key) sets ONLY the value (spec S1).
        ctx.apply_params({"db_reference": 4.2e-7})
        assert ctx.db_reference_control.mode() == "auto", (
            f"{cls.__name__}.apply_params forced Manual off a bare db_reference key"
        )
        assert ctx.spin_db_ref.value() == pytest.approx(4.2e-7)

        # db_reference_mode alone switches mode without touching the value.
        ctx.apply_params({"db_reference_mode": "manual"})
        assert ctx.db_reference_control.mode() == "manual"
        assert ctx.spin_db_ref.value() == pytest.approx(4.2e-7)


def test_new_preset_round_trip_preserves_mode_and_value(qtbot):
    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)
        ctx.db_reference_control.set_mode("manual")
        ctx.spin_db_ref.setValue(9.9e-8)

        preset = ctx._collect_preset()
        assert preset["db_reference_mode"] == "manual"
        assert preset["db_reference"] == pytest.approx(9.9e-8)

        # Perturb, then restore via the real preset-load path (PresetBar's
        # own call shape: _apply_preset wraps _apply_preset_values).
        ctx.db_reference_control.set_mode("auto")
        ctx.spin_db_ref.setValue(1.0)

        ctx._apply_preset(preset)

        assert ctx.db_reference_control.mode() == "manual"
        assert ctx.spin_db_ref.value() == pytest.approx(9.9e-8)


def test_legacy_preset_value_without_mode_migrates_to_manual(qtbot):
    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)
        ctx.db_reference_control.set_mode("auto")

        legacy_preset = dict(ctx._collect_preset())
        legacy_preset.pop("db_reference_mode", None)
        legacy_preset["db_reference"] = 7.0

        ctx._apply_preset(legacy_preset)

        assert ctx.db_reference_control.mode() == "manual", (
            f"{cls.__name__} legacy value-without-mode preset did not migrate "
            "to Manual"
        )
        assert ctx.spin_db_ref.value() == pytest.approx(7.0)


def test_legacy_preset_without_reference_leaves_current_state_unchanged(qtbot):
    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)
        ctx.db_reference_control.set_mode("manual")
        ctx.spin_db_ref.setValue(6.5e-6)

        legacy_preset = dict(ctx._collect_preset())
        legacy_preset.pop("db_reference_mode", None)
        legacy_preset.pop("db_reference", None)

        ctx._apply_preset(legacy_preset)

        assert ctx.db_reference_control.mode() == "manual", (
            f"{cls.__name__} preset missing db_reference entirely changed mode"
        )
        assert ctx.spin_db_ref.value() == pytest.approx(6.5e-6)


# ----------------------------------------------------------------------
# Task 8 Step 8.1 (6th literal test name): a preset predating BOTH the
# weighting combo AND the dB-reference compound control (a truly ancient
# preset, not just missing the new mode key) must leave both pieces of
# LIVE state untouched -- neither guard should force the other to reset
# just because it fired first (spec §13 S1/S2).
# ----------------------------------------------------------------------
def test_old_preset_missing_weighting_and_reference_keys_preserves_live_state(qtbot):
    for cls in _analysis_context_classes():
        ctx = cls()
        qtbot.addWidget(ctx)
        ctx._apply_weighting_value("A")
        ctx.db_reference_control.set_mode("manual")
        ctx.spin_db_ref.setValue(4.4e-6)

        ancient_preset = dict(ctx._collect_preset())
        ancient_preset.pop("weighting", None)
        ancient_preset.pop("db_reference_mode", None)
        ancient_preset.pop("db_reference", None)

        ctx._apply_preset(ancient_preset)

        params = ctx.get_params()
        assert params["weighting"] == "A", (
            f"{cls.__name__} preset missing 'weighting' reset it"
        )
        assert params["db_reference_mode"] == "manual", (
            f"{cls.__name__} preset missing reference keys changed mode"
        )
        assert params["db_reference"] == pytest.approx(4.4e-6)


@pytest.mark.parametrize("preset", ("torque", "vibration", "transient"))
@pytest.mark.parametrize("mode,value", (("auto", 1.0), ("manual", 2.5e-6)))
def test_fft_time_builtin_preset_preserves_db_reference_state(
    qtbot, preset, mode, value,
):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.db_reference_control.set_mode(mode)
    ctx.spin_db_ref.setValue(value)
    changes = []
    ctx.spin_db_ref.valueChanged.connect(changes.append)

    ctx.apply_builtin_preset(preset)

    assert ctx.db_reference_control.mode() == mode
    assert ctx.spin_db_ref.value() == pytest.approx(value)
    assert changes == []
