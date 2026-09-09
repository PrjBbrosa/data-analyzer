"""Geometry contracts for preset baseline difference dots."""
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.inspector_sections.preset_state import build_preset_baseline
from mf4_analyzer.ui.inspector_sections.presets import (
    PresetBar,
    _DIFF_DOT_GAP,
    _DIFF_DOT_PX,
)


def test_baseline_slot_shows_purple_then_amber_dots(qtbot):
    live = {
        'window': 'hanning',
        'overlap': 40,
        'x_auto': False,
        'x_min': 1.0,
        'x_max': 5.0,
    }
    bar = PresetBar(
        'fft',
        lambda: dict(live),
        lambda _params: None,
        builtin_defaults={
            1: {'display_name': '频率', 'params': {'window': 'flattop'}},
            2: {'display_name': '均衡', 'params': {'window': 'hanning'}},
        },
        custom_slots={4: '自定义'},
    )
    qtbot.addWidget(bar)
    bar.resize(360, 32)
    bar.show()
    QApplication.processEvents()

    bar.set_baseline(build_preset_baseline(
        'fft', 2, '均衡',
        {'window': 'hanning', 'overlap': 50, 'x_auto': True},
    ))
    QApplication.processEvents()

    param = bar._param_dots[2]
    axis = bar._axis_dots[2]
    assert param.isVisible()
    assert axis.isVisible()
    assert param.width() == _DIFF_DOT_PX
    assert axis.width() == _DIFF_DOT_PX
    assert axis.x() - (param.x() + param.width()) == _DIFF_DOT_GAP
    assert bar._param_dots[1].isHidden()
    assert bar._axis_dots[1].isHidden()
    assert '分析参数有差异' in bar._load_btns[2].accessibleDescription()
    assert '坐标有差异' in bar._load_btns[2].accessibleDescription()


def test_matching_baseline_hides_dots(qtbot):
    current = {'window': 'hanning', 'overlap': 50, 'x_auto': True}
    bar = PresetBar(
        'fft',
        lambda: dict(current),
        lambda _params: None,
        builtin_defaults={
            2: {'display_name': '均衡', 'params': {'window': 'hanning'}},
        },
        custom_slots={4: '自定义'},
    )
    qtbot.addWidget(bar)
    bar.set_baseline(build_preset_baseline('fft', 2, '均衡', current))
    assert bar._param_dots[2].isHidden()
    assert bar._axis_dots[2].isHidden()
