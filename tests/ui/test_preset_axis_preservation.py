"""User preset switches protect manual ranges without changing restore semantics."""
import pytest
from mf4_analyzer.ui.inspector_sections import FFTContextual, FFTTimeContextual, OrderContextual


@pytest.mark.parametrize('factory', [FFTContextual, FFTTimeContextual, OrderContextual])
@pytest.mark.parametrize('choice', ['keep', 'preset', 'cancel'])
def test_user_switch_is_one_shot(qtbot, monkeypatch, factory, choice):
    ctx = factory()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    ctx.chk_x_auto.setChecked(False)
    ctx.spin_x_min.setValue(1)
    ctx.spin_x_max.setValue(5)
    before = ctx._collect_preset()
    calls = []
    def choose(*args, **kwargs):
        calls.append(args)
        return choice
    monkeypatch.setattr(bar, '_confirm_axis_preservation', choose)
    bar._load(1)
    assert len(calls) == 1
    after = ctx._collect_preset()
    if choice == 'cancel':
        assert after == before
        assert bar._selected_slot is None
        assert bar.baseline() is None
    elif choice == 'keep':
        assert (after['x_auto'], after['x_min'], after['x_max']) == (False, 1, 5)
        assert bar._selected_slot == 1
        assert bar.baseline()["slot"] == 1
        assert not bar._live_diff.params_differ
        # The stored preset remains unchanged; a later choice can replace it.
        monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'preset')
        bar._load(2)
        assert ctx.chk_x_auto.isChecked()
    else:
        assert ctx.chk_x_auto.isChecked()


def test_defaults_cancel_and_programmatic_restore(qtbot, monkeypatch):
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    ctx.chk_z_auto.setChecked(False)
    ctx.spin_z_floor.setValue(-70)
    before = ctx._collect_preset()
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'cancel')
    bar._restore_default_params(1)
    assert ctx._collect_preset() == before
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: pytest.fail('restore must not prompt'))
    ctx._apply_preset({'z_auto': True})
    assert ctx.chk_z_auto.isChecked()


@pytest.mark.parametrize('factory,unit_key,unit,axis', [
    (FFTContextual, 'amp_y', 'Linear', 'y'),
    (FFTTimeContextual, 'amplitude_mode', 'Amplitude', 'z'),
    (OrderContextual, 'amplitude_mode', 'Amplitude', 'z'),
])
def test_unit_change_keeps_only_compatible_ranges(qtbot, monkeypatch, factory, unit_key, unit, axis):
    ctx = factory()
    qtbot.addWidget(ctx)
    ctx._apply_preset({unit_key: 'dB' if unit_key == 'amp_y' else 'Amplitude dB'})
    getattr(ctx, 'chk_' + axis + '_auto').setChecked(False)
    ctx.chk_x_auto.setChecked(False)
    ctx.spin_x_max.setValue(5)
    bar = ctx.preset_bar
    incoming = dict(ctx._collect_preset(), **{unit_key: unit, 'x_auto': True})
    bar._write(4, '单位变化', incoming)
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'keep')
    bar._load(4)
    assert not ctx.chk_x_auto.isChecked()
    assert getattr(ctx, 'chk_' + axis + '_auto').isChecked()
    assert bar._read(4)[1] == incoming


def test_no_conflict_does_not_prompt(qtbot, monkeypatch):
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: pytest.fail('no conflict'))
    bar._load(1)
    ctx.chk_x_auto.setChecked(False)
    params = ctx._collect_preset()
    bar._write(4, '相同范围', params)
    bar._load(4)


@pytest.mark.parametrize('button,expected', [('保留手动范围', 'keep'), ('使用预设范围', 'preset'), ('取消', 'cancel')])
def test_real_confirmation_buttons(qtbot, qapp, button, expected):
    from PyQt5.QtCore import QTimer
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    def respond():
        box = qapp.activeModalWidget()
        next(item for item in box.buttons() if item.text() == button).click()
    QTimer.singleShot(0, respond)
    assert ctx.preset_bar._confirm_axis_preservation(['频率 X', '幅值 Y'], ['幅值 Y']) == expected


def test_legacy_ranges_and_default_keep(qtbot, monkeypatch):
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.chk_y_auto.setChecked(False)
    ctx.spin_y_max.setValue(25)
    ctx.chk_z_auto.setChecked(False)
    ctx.spin_z_floor.setValue(-60)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'keep')
    bar._write(4, '旧配置', {'freq_auto': True, 'dynamic': 'Auto'})
    bar._load(4)
    assert not ctx.chk_y_auto.isChecked()
    assert ctx.spin_y_max.value() == 25
    assert not ctx.chk_z_auto.isChecked()
    assert ctx.spin_z_floor.value() == -60
    bar._restore_default_params(1)
    assert not ctx.chk_y_auto.isChecked()
    assert ctx.spin_y_max.value() == 25
    assert ctx.spin_z_floor.value() == -60
    assert bar.baseline() is None


def test_cancel_keeps_recommendation_and_does_not_compute(qtbot, monkeypatch):
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    ctx.chk_x_auto.setChecked(False)
    ctx.spin_x_min.setValue(1)
    ctx.spin_x_max.setValue(5)
    bar.set_recommended(1, unit='Nm')
    emitted = []
    ctx.fft_requested.connect(lambda: emitted.append(True))
    before = ctx._collect_preset()
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *a, **k: 'cancel')
    bar._load(2)
    assert ctx._collect_preset() == before
    assert bar.baseline() is None
    assert bar._load_btns[1].property('recommended') == 'true'
    assert emitted == []


def test_colorbar_echo_keeps_baseline_and_shows_axis_dot(qtbot, monkeypatch):
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *a, **k: 'preset')
    bar._on_left_click(2)
    assert bar._selected_slot == 2
    ctx.apply_params({'z_auto': False, 'z_floor': -55.0, 'z_ceiling': -5.0})
    assert bar._selected_slot == 2
    assert bar._live_diff.axes_differ
    assert not bar._axis_dots[2].isHidden()
    assert bar._load_btns[4].property('applied') != 'true'


def test_restore_panel_defaults_clears_baseline(qtbot, monkeypatch):
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *a, **k: 'preset')
    bar._on_left_click(1)
    assert bar.baseline()['slot'] == 1
    bar._restore_default_params()
    assert bar.baseline() is None
    assert bar._selected_slot is None


def test_reset_slot_does_not_change_current_params(qtbot, monkeypatch):
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *a, **k: 'preset')
    bar._on_left_click(1)
    bar._save(1)
    ctx.spin_overlap.setValue(11)
    before = ctx._collect_preset()
    snapshot = bar.baseline()['params']
    bar._reset_to_default(1)
    assert ctx._collect_preset() == before
    assert bar.baseline()['slot'] == 1
    assert bar.baseline()['params'] == snapshot


def test_keep_disabled_when_only_incompatible_axis(qtbot, qapp):
    from PyQt5.QtCore import QTimer
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    captured = {}

    def respond():
        box = qapp.activeModalWidget()
        keep = next(item for item in box.buttons() if item.text() == '保留手动范围')
        captured['enabled'] = keep.isEnabled()
        captured['default'] = box.defaultButton().text()
        next(item for item in box.buttons() if item.text() == '使用预设范围').click()

    QTimer.singleShot(0, respond)
    result = ctx.preset_bar._confirm_axis_preservation(
        ['幅值 Y'], ['幅值 Y'], keep_enabled=False,
    )
    assert result == 'preset'
    assert captured['enabled'] is False
    assert captured['default'] == '使用预设范围'
