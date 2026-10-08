"""Heatmap inspector projections are silent and preserve unedited precision."""
import pytest

from mf4_analyzer.ui.inspector_sections.contextual_fft_time import FFTTimeContextual
from mf4_analyzer.ui.inspector_sections.contextual_order import OrderContextual


@pytest.fixture(params=[FFTTimeContextual, OrderContextual])
def controls(request, qtbot):
    widget = request.param()
    qtbot.addWidget(widget)
    return widget


def test_projection_is_silent_and_single_boundary_edit_keeps_exact_peer(controls):
    emitted = []
    controls.display_params_changed.connect(emitted.append)
    lo, hi = -712.123456789, 812.987654321
    controls.project_color_levels(False, lo, hi)
    assert not emitted
    assert controls.consume_color_policy_edit() is None
    assert controls.spin_z_floor.value() == pytest.approx(round(lo, 2))
    assert controls.spin_z_ceiling.value() == pytest.approx(round(hi, 2))
    controls.spin_z_floor.setValue(-700.25)
    assert controls.consume_color_policy_edit() == {
        'z_auto': False, 'z_floor': -700.25, 'z_ceiling': hi,
    }
    assert controls.consume_color_policy_edit() is None


def test_automatic_to_manual_uses_exact_projected_window(controls):
    lo, hi = -65.123456789, 0.876543219
    controls.project_color_levels(True, lo, hi)
    controls.chk_z_auto.setChecked(False)
    assert controls.consume_color_policy_edit() == {
        'z_auto': False, 'z_floor': lo, 'z_ceiling': hi,
    }


def test_non_z_edit_and_restore_do_not_commit_projection(controls):
    controls.project_color_levels(False, -70.123456789, 3.987654321)
    controls.spin_x_min.setValue(0.25)
    assert controls.consume_color_policy_edit() is None
    controls.spin_z_floor.setValue(-50)
    controls.apply_params({'z_auto': False, 'z_floor': -40, 'z_ceiling': 0})
    assert controls.consume_color_policy_edit() is None
    controls.spin_z_floor.setValue(-30)
    assert controls.consume_color_policy_edit()['z_ceiling'] == 0


def test_preset_without_z_keeps_projection_and_export_precision(controls):
    lo, hi = -80.123456789, 0.987654321
    controls.project_color_levels(False, lo, hi)
    controls._apply_preset({'window': 'Hanning'})
    assert controls.consume_color_policy_edit() is None
    assert controls.color_policy_projection()['z_floor'] == lo
    assert controls._collect_preset()['z_ceiling'] == hi
    assert controls.current_params()['z_floor'] == lo


def test_preset_with_z_is_explicit_and_invalidates_old_projection(controls):
    controls.project_color_levels(False, -80.123456789, 0.987654321)
    controls._apply_preset({'z_auto': False, 'z_floor': -40.123456789, 'z_ceiling': 2})
    assert controls.color_policy_projection() is None
    assert controls.consume_color_policy_edit() == {
        'z_auto': False, 'z_floor': -40.123456789, 'z_ceiling': 2,
    }


def test_real_preset_load_keep_range_does_not_reanchor_projection(controls, monkeypatch):
    controls.project_color_levels(False, -80.123456789, 0.987654321)
    bar = controls.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'keep')
    bar._write(4, 'Z patch', {'z_auto': False, 'z_floor': -40, 'z_ceiling': 10})
    bar._load(4)
    assert controls.consume_color_policy_edit() is None
    assert controls.color_policy_projection()['z_floor'] == -80.123456789


def test_real_non_z_preset_load_does_not_claim_inherited_color_fields(controls, monkeypatch):
    controls.project_color_levels(False, -80.123456789, 0.987654321)
    bar = controls.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'preset')
    bar._write(4, 'X patch', {'x_auto': False, 'x_min': 0.1, 'x_max': 0.4})
    bar._load(4)
    assert controls.consume_color_policy_edit() is None
    assert controls.color_policy_projection()['z_floor'] == -80.123456789


def test_amplitude_unit_change_publishes_one_complete_window(controls):
    controls.project_color_levels(False, -80.123456789, 0.987654321)
    emitted = []
    controls.display_params_changed.connect(emitted.append)
    controls.combo_amp_unit.setCurrentText('Linear')
    assert len(emitted) == 1
    assert emitted[0]['z_auto'] is True
    assert emitted[0]['z_floor'] < emitted[0]['z_ceiling']
    assert controls.color_policy_projection() is None
    assert controls.consume_color_policy_edit() is None


def test_invalid_boundary_draft_is_not_captured_when_leaving_view(controls):
    from mf4_analyzer.ui.analysis_view_bridge import capture_params_to_state
    from mf4_analyzer.ui.analysis_view_state import AnalysisViewState

    requested = {'z_auto': False, 'z_floor': -80.123456789, 'z_ceiling': 0.0}
    state = AnalysisViewState('View', '#123456', params=dict(requested))
    controls.apply_params(requested)
    controls.spin_z_floor.setValue(10)
    # Model the owner rejecting this explicit invalid edit before capture.
    assert controls.consume_color_policy_edit()['z_floor'] == 10
    capture_params_to_state(controls, state)
    assert {key: state.params[key] for key in requested} == requested


def test_reference_projection_does_not_mark_baseline_dirty_but_save_exports_visible(controls, monkeypatch):
    requested = {'z_auto': False, 'z_floor': -80.123456789, 'z_ceiling': 0.987654321}
    controls.apply_params(requested)
    bar = controls.preset_bar
    bar._save(4)
    assert not bar._live_diff.axes_differ
    controls.project_color_levels(
        False, requested['z_floor'] - 20, requested['z_ceiling'] - 20,
        requested=requested,
    )
    bar.sync_match()
    assert not bar._live_diff.axes_differ
    bar._save(4)
    saved = bar._read(4)[1]
    assert saved['z_floor'] == requested['z_floor'] - 20
    assert saved['z_ceiling'] == requested['z_ceiling'] - 20
    assert not bar._live_diff.axes_differ
    controls.project_color_levels(
        False, requested['z_floor'] - 40, requested['z_ceiling'] - 40,
        requested=requested,
    )
    assert not bar._live_diff.axes_differ
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'preset')
    bar._load(4)
    assert controls.consume_color_policy_edit()['z_floor'] == saved['z_floor']
    assert not bar._live_diff.axes_differ


def test_non_z_preset_baseline_compares_inherited_requests(controls, monkeypatch):
    requested = {'z_auto': False, 'z_floor': -80.123456789, 'z_ceiling': 0.987654321}
    controls.apply_params(requested)
    controls.project_color_levels(False, -100.123456789, -19.012345679, requested=requested)
    bar = controls.preset_bar
    monkeypatch.setattr(bar, '_confirm_axis_preservation', lambda *args, **kwargs: 'preset')
    bar._write(4, 'Only X', {'x_auto': False, 'x_min': 0.1, 'x_max': 0.4})
    bar._load(4)
    assert not bar._live_diff.axes_differ
    assert bar.baseline()['params']['z_floor'] == requested['z_floor']
    assert controls.consume_color_policy_edit() is None
