"""Tests for the Inspector skeleton (Phase 1) and section widgets (Phase 2)."""
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


def test_inspector_no_longer_exposes_mode_signals(qapp):
    """Spec §9: after 2026-04-24 cleanup, Inspector no longer relays
    plot_mode_changed / cursor_mode_changed — those are on ChartStack now."""
    insp = Inspector()
    assert not hasattr(insp, 'plot_mode_changed')
    assert not hasattr(insp, 'cursor_mode_changed')


def test_persistent_top_tick_group_not_checkable(qapp):
    """刻度 GroupBox must be always-open per spec §3.3 (2026-04-24 cleanup)."""
    from PyQt5.QtWidgets import QGroupBox
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    # Walk up from spin_xt to its QGroupBox ancestor.
    parent_gb = pt.spin_xt.parentWidget()
    while parent_gb is not None and not isinstance(parent_gb, QGroupBox):
        parent_gb = parent_gb.parentWidget()
    assert parent_gb is not None, "spin_xt has no QGroupBox ancestor"
    assert not parent_gb.isCheckable()
    # Key contract: tick density reflects current spin values (not zero).
    assert pt.tick_density() == (10, 6)


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
    # the Z axis row; chk_freq_auto / spin_freq_min/max alias the X row;
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
    # The 13 keys that MainWindow._fft_time_cache_key consumes.
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
    ctx.apply_builtin_preset('amplitude_accuracy')
    params = ctx.get_params()

    assert params['window'] == 'flattop'
    assert params['nfft'] == 4096
    assert params['amplitude_mode'] == 'amplitude'

    # Sanity-check the other two presets land on their distinguishing
    # parameters per design §7.
    ctx.apply_builtin_preset('diagnostic')
    p_diag = ctx.get_params()
    assert p_diag['window'] == 'hanning'
    assert p_diag['nfft'] == 2048
    assert p_diag['overlap'] == 0.75
    assert p_diag['dynamic'] == '80 dB'

    ctx.apply_builtin_preset('high_frequency')
    p_hf = ctx.get_params()
    assert p_hf['nfft'] == 4096
    assert p_hf['overlap'] == 0.50
    assert p_hf['dynamic'] == '60 dB'


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


def test_persistent_top_tick_xy_share_one_form_row(qapp):
    """Tick group must collapse "X" and "Y" into a single QFormLayout row."""
    from PyQt5.QtWidgets import QFormLayout
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    fl_x, r_x, _ = _form_row_for(pt.spin_xt)
    fl_y, r_y, _ = _form_row_for(pt.spin_yt)
    assert isinstance(fl_x, QFormLayout)
    assert fl_x is fl_y, "spin_xt and spin_yt must live in the same QFormLayout"
    assert r_x == r_y >= 0


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
    """Wave 4: 频率下限/上限 are no longer in a QFormLayout — they live
    in the X row of the new 坐标轴设置 group as spin_x_min / spin_x_max
    (aliased back to spin_freq_min / spin_freq_max). The old "share one
    form row" contract becomes "share one axis row widget" → both spins
    sit inside the same direct parent QWidget host built by
    ``_build_axis_row``.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert ctx.spin_freq_min is ctx.spin_x_min
    assert ctx.spin_freq_max is ctx.spin_x_max
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
        # Default index is 0 = 自动(时间)
        assert pt.combo_xaxis.currentIndex() == 0
        assert pt._combo_xaxis_ch.isHidden(), \
            "通道 combo should be hidden when 来源 == 自动(时间)"
        # Switch to 指定通道 → row reveals
        pt.combo_xaxis.setCurrentIndex(1)
        assert not pt._combo_xaxis_ch.isHidden()
        # Back to auto → hidden again
        pt.combo_xaxis.setCurrentIndex(0)
        assert pt._combo_xaxis_ch.isHidden()
    finally:
        pt.hide()


def test_persistent_top_range_rows_hidden_when_unchecked(qapp):
    """When chk_range is unchecked, both 开始 and 结束 rows hide."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    pt.show()
    try:
        # Default state: chk_range unchecked → range row hidden.
        assert not pt.chk_range.isChecked()
        assert pt.spin_start.isHidden()
        assert pt.spin_end.isHidden()
        # Toggle on → row visible.
        pt.chk_range.setChecked(True)
        assert not pt.spin_start.isHidden()
        assert not pt.spin_end.isHidden()
        # Toggle off → hidden again.
        pt.chk_range.setChecked(False)
        assert pt.spin_start.isHidden()
        assert pt.spin_end.isHidden()
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


def test_fft_contextual_root_spacing_compact(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    assert fc.layout().spacing() == 6


def test_order_contextual_root_spacing_compact(qapp):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    assert oc.layout().spacing() == 6


def test_fft_time_contextual_root_spacing_compact(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert ctx.layout().spacing() == 6


# ---- R3 #3-B: GroupBox title 紧凑+下划线分隔 ----

def test_inspector_groupbox_title_has_underline_and_compact_padding():
    """Inspector QGroupBox::title rule must carry a 1px hairline underline
    and the tightened 12px / 600 weight typography (R3 #3-B).
    """
    from pathlib import Path
    qss_path = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui" / "style.qss"
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


# ---- R3 #6: PersistentTop collapser ----

def test_persistent_top_has_collapser(qapp):
    """PersistentTop must wrap its three groups in a single collapsible
    container that defaults to collapsed (R3 #6).
    """
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    # The collapser persists its state in QSettings; clear it so this test
    # does not depend on whatever a previous run / fixture left behind.
    QSettings("MF4Analyzer", "DataAnalyzer").remove(
        "inspector/persistent_top/expanded",
    )
    pt = PersistentTop()
    assert hasattr(pt, "btn_collapser"), \
        "PersistentTop must expose btn_collapser (the toggle handle)"
    assert hasattr(pt, "_collapser_body"), \
        "PersistentTop must expose _collapser_body (the inner container)"
    # Default: collapsed.
    assert pt.btn_collapser.isChecked() is False
    assert pt._collapser_body.isVisibleTo(pt) is False or \
        pt._collapser_body.isHidden()


def test_persistent_top_collapser_toggle_reveals_groups(qapp):
    """Toggling the collapser must reveal the inner three groups while
    keeping every documented attribute reachable (programmatic access works
    even when the body is hidden).
    """
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    QSettings("MF4Analyzer", "DataAnalyzer").remove(
        "inspector/persistent_top/expanded",
    )
    pt = PersistentTop()
    # Programmatic access works regardless of visibility — preserves contract.
    for attr in (
        "spin_xt", "spin_yt", "chk_range", "spin_start", "spin_end",
        "combo_xaxis", "_combo_xaxis_ch", "edit_xlabel", "btn_apply_xaxis",
    ):
        assert getattr(pt, attr) is not None, f"missing attr: {attr}"
    # Toggle expand.
    pt.btn_collapser.setChecked(True)
    pt.show()
    try:
        assert pt._collapser_body.isVisible() is True
        # Group-level controls now visible.
        assert pt.combo_xaxis.isVisible() is True
        assert pt.spin_xt.isVisible() is True
        # Toggle collapse.
        pt.btn_collapser.setChecked(False)
        assert pt._collapser_body.isHidden() is True
    finally:
        pt.hide()


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
    builtin display names: 配置1 / 配置2 / 配置3 (Wave 2 #2.13)."""
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
    assert "配置1" in texts
    assert "配置2" in texts
    assert "配置3" in texts


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
    # Save an override on slot 1 (the diagnostic slot).
    ctx.combo_nfft.setCurrentText('512')
    ctx.preset_bar._save(1)
    # Reset slot 1.
    ctx.preset_bar._reset_to_default(1)
    # Mutate then load slot 1 — should now apply the builtin diagnostic
    # preset (nfft=2048, window=hanning, overlap=75).
    ctx.combo_nfft.setCurrentText('8192')
    ctx.combo_win.setCurrentText('blackman')
    ctx.spin_overlap.setValue(10)
    ctx.preset_bar._load(1)
    assert ctx.combo_nfft.currentText() == '2048'
    assert ctx.combo_win.currentText() == 'hanning'
    assert ctx.spin_overlap.value() == 75


def test_fft_time_apply_builtin_preset_still_callable(qtbot):
    """The apply_builtin_preset(name) method must remain callable as it
    is referenced by tests (and possibly by external regression paths).
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert callable(getattr(ctx, "apply_builtin_preset", None))
    ctx.apply_builtin_preset('diagnostic')
    p = ctx.get_params()
    assert p['nfft'] == 2048
    assert p['window'] == 'hanning'


# ---- 2026-04-26 R3 紧凑化 视觉一致性修正 ----

def test_inspector_scroll_body_caps_max_width(qapp):
    """fix-1 — Inspector content must cap its maxWidth so Expanding
    children stop growing past a sane threshold when the splitter pane
    is dragged wider than ~360px. Without the cap, every Expanding
    QSpinBox / QComboBox stretches to fill the entire pane width.
    """
    from mf4_analyzer.ui.inspector import Inspector
    insp = Inspector()
    cap = insp._scroll_body.maximumWidth()
    # 16777215 == QWIDGETSIZE_MAX, i.e. uncapped.
    assert cap < 16777215, (
        "Inspector._scroll_body has no maximumWidth cap — Expanding "
        "children will grow unbounded when the splitter widens."
    )
    assert cap <= 400, (
        f"Inspector._scroll_body.maximumWidth()={cap}px is too generous; "
        "should be ~360 to keep the form column tight."
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
              ctx.spin_db_ref, ctx.combo_cmap):
        assert 200 <= w.maximumWidth() <= 260, (
            f"FFTTimeContextual field "
            f"{w.objectName() or type(w).__name__} maximumWidth="
            f"{w.maximumWidth()}px should use the A1 cap."
        )


def test_inspector_body_fills_360_width_under_qss(qapp, qtbot):
    """Styled Inspector body should fill the 360px right pane."""
    from pathlib import Path
    from mf4_analyzer.ui.inspector import Inspector

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui/style.qss").read_text(encoding="utf-8")
        )
        insp = Inspector()
        qtbot.addWidget(insp)
        insp.resize(360, 850)
        insp.show()
        qtbot.waitExposed(insp)
        qtbot.wait(50)

        assert insp.width() == 360
        assert insp._scroll_body.width() >= 340, (
            f"Inspector body should fill a 360px pane; body="
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
            Path("mf4_analyzer/ui/style.qss").read_text(encoding="utf-8")
        )
        insp = Inspector()
        qtbot.addWidget(insp)
        insp.resize(360, 850)
        insp.set_mode('fft')
        insp.show()
        qtbot.waitExposed(insp)
        qtbot.wait(50)

        ctx = insp.fft_ctx
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
        assert min(widths) >= 190, (
            f"Field column should be materially wider than compact 110px; "
            f"got {widths}"
        )
    finally:
        qapp.setStyleSheet(old_sheet)


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
        "mf4_analyzer/ui/style.qss"
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


# ---- Wave 2 Task 2.13: builtin preset display names → 配置1/2/3 ----
#
# PresetBar exposes per-slot text via the internal ``_load_btns[n].text()``
# accessor (no public ``slot_text`` getter), and writes overrides through
# ``_write(slot, name, params)`` (no public ``set_slot_override``). Both
# tests below honor the plan's intent — default labels read 配置1/2/3 and
# reset-to-default still surfaces those names — while using the real API.

def test_fft_time_preset_bar_default_names(qtbot):
    """Default slot labels for the FFTTime preset bar must be the new
    builtin display names: 配置1 / 配置2 / 配置3 (Wave 2 #2.13)."""
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    s = QSettings("MF4Analyzer", "DataAnalyzer")
    for slot in (1, 2, 3):
        s.remove(f"fft_time/preset_override/{slot}")
    w = FFTTimeContextual()
    qtbot.addWidget(w)
    bar = w.preset_bar
    # PresetBar exposes per-slot text via ``_load_btns[n].text()``.
    assert bar._load_btns[1].text() == '配置1'
    assert bar._load_btns[2].text() == '配置2'
    assert bar._load_btns[3].text() == '配置3'


def test_fft_time_preset_bar_reset_to_default_keeps_new_names(qtbot):
    """After resetting an overridden slot, the slot text must restore to
    the new builtin name (配置1) — not the legacy 诊断模式 (Wave 2 #2.13).
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
    assert bar._load_btns[1].text() == '配置1'


# ---- HEAD-style smoothness defaults for FFT-vs-Time spectrogram ----
#
# Two coupled changes raise spectrogram visual smoothness without a DSP
# rewrite:
#   1. FFTTimeContextual.spin_overlap default 75% → 88% (closest integer
#      to the 87.5% target on a QSpinBox-percent control), max 90% → 95%.
#      Doubling the frame count keeps memory inside the existing chunk
#      budget (see signal-processing/2026-04-26-batched-fft-transient-…).
#   2. SpectrogramCanvas.plot_result imshow uses interpolation='bilinear'
#      instead of 'nearest' — pure display-side smoothing, no DSP impact.

def test_fft_time_overlap_default_and_max_target_smooth_spectrogram(qtbot):
    """The FFT-vs-Time overlap spinbox must default to 88% (the integer
    realisation of the 87.5% smoothness target) and allow up to 95%.
    """
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    # Default value — 88% is the closest QSpinBox integer to the 87.5%
    # smoothness target documented in the FFT-vs-Time integration plan.
    assert ctx.spin_overlap.value() == 88, (
        f"FFTTimeContextual.spin_overlap default = "
        f"{ctx.spin_overlap.value()}; expected 88 (87.5% target)."
    )
    # Maximum — must be raised to 95 so users can pick the COLA-safe
    # high-overlap region for visually smooth spectrograms.
    assert ctx.spin_overlap.maximum() == 95, (
        f"FFTTimeContextual.spin_overlap.maximum() = "
        f"{ctx.spin_overlap.maximum()}; expected 95."
    )


def test_spectrogram_canvas_uses_bilinear_interpolation(qtbot):
    """SpectrogramCanvas.plot_result must build the imshow with
    interpolation='bilinear' so the FFT-vs-Time render is visually
    smooth without any DSP-side change.
    """
    import numpy as np
    from mf4_analyzer.signal.spectrogram import (
        SpectrogramParams, SpectrogramResult,
    )
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.0, 0.1, 0.2]),
        frequencies=np.array([0.0, 50.0, 100.0]),
        amplitude=np.ones((3, 3), dtype=np.float32),
        params=SpectrogramParams(fs=200.0, nfft=8),
        channel_name='demo',
    )
    canvas.plot_result(result, amplitude_mode='amplitude')
    im = canvas._ax_spec.images[0]
    assert im.get_interpolation() == 'bilinear', (
        f"SpectrogramCanvas imshow interpolation = "
        f"{im.get_interpolation()!r}; expected 'bilinear'."
    )


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
    assert hasattr(w, 'combo_psd_y')
    assert w.combo_amp_y.currentText() == 'Linear'
    assert w.combo_psd_y.currentText() == 'dB'


def test_fft_contextual_axis_toggles_in_params(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    w = FFTContextual()
    w.combo_amp_y.setCurrentText('dB')
    w.combo_psd_y.setCurrentText('Linear')
    p = w.current_params()
    assert p.get('amp_y') == 'dB'
    assert p.get('psd_y') == 'Linear'
    w.apply_params({'amp_y': 'Linear', 'psd_y': 'dB'})
    assert w.combo_amp_y.currentText() == 'Linear'
    assert w.combo_psd_y.currentText() == 'dB'


def test_fft_render_honors_axis_toggles(qtbot):
    """Toggling Amp axis to dB / PSD axis to Linear must change the y-label
    text on the rendered subplots — this proves the toggles round-trip
    through the render code in main_window.do_fft.
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

    # Default render: amp=Linear, psd=dB.
    win.do_fft()
    axes = win.canvas_fft.fig.axes
    assert len(axes) >= 2
    assert 'dB' not in axes[0].get_ylabel()
    assert 'dB' in axes[1].get_ylabel()

    # Flip: amp=dB, psd=Linear.
    win.inspector.fft_ctx.combo_amp_y.setCurrentText('dB')
    win.inspector.fft_ctx.combo_psd_y.setCurrentText('Linear')
    win.do_fft()
    axes = win.canvas_fft.fig.axes
    assert 'dB' in axes[0].get_ylabel()
    assert 'dB' not in axes[1].get_ylabel()


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

    # Defaults: x/y auto on, z auto off (mirrors old default 30 dB)
    assert oc.chk_x_auto.isChecked()
    assert oc.chk_y_auto.isChecked()
    assert not oc.chk_z_auto.isChecked()
    assert oc.spin_z_floor.value() == -30.0
    assert oc.spin_z_ceiling.value() == 0.0
    assert oc.combo_amp_unit.currentText() == 'dB'


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
    9 controls as OrderContextual but X = freq, Y = amplitude."""
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
    # chk_freq_auto + spin_freq_min/max moved into the axis group
    # but kept as attribute names for backward-compat with downstream readers
    # — they now alias to chk_x_auto / spin_x_min / spin_x_max.
    assert fc.chk_freq_auto is fc.chk_x_auto
    assert fc.spin_freq_min is fc.spin_x_min
    assert fc.spin_freq_max is fc.spin_x_max


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
