"""Owner projection must not become a new request, including locked panes."""
from types import SimpleNamespace

import pytest

from mf4_analyzer.db_reference import DbReferenceResolution
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState
from mf4_analyzer.ui.heatmap_color_coordinator import HeatmapColorCoordinator
from mf4_analyzer.ui.main_window.analysis_comparison import AnalysisComparisonDisplay


class Canvas:
    def __init__(self):
        self._matrix_disp = [[1.0]]
        self._matrix_amp_valid = [[True]]
        self.levels = None
        self.reset_baseline = None

    def objectName(self):
        return "heatmap-test"

    def has_result(self):
        return self._matrix_disp is not None

    def project_color_levels(self, auto, lo, hi, *, reset_baseline=False):
        self.levels = (auto, lo, hi)
        if reset_baseline:
            self.reset_baseline = (lo, hi)
        return True


class Ctx:
    def __init__(self):
        self.projection = None

    def project_color_levels(self, auto, lo, hi, *, requested=None):
        self.projection = (auto, lo, hi)
        self.requested = requested


def setup():
    state = AnalysisViewState(name="View", tab_color="#fff", params={"z_auto": False, "z_floor": -80., "z_ceiling": 0.},
                              panes=[PaneState(sources=[("f1", "sig")]), PaneState(sources=[("f2", "sig")])])
    canvases = [Canvas(), Canvas()]
    page = SimpleNamespace(pane_count=lambda: 2, pane_canvas=lambda index: canvases[index], focused_index=lambda: 0,
                           is_levels_locked=lambda: state.compare["levels_locked"])
    manager = SimpleNamespace(views=[state], active=0, get=lambda index: state)
    ctx = Ctx()
    context = SimpleNamespace(_analysis_managers={"fft_time": manager},
                              _chart_stack=SimpleNamespace(current_mode=lambda: "fft_time"),
                              section_ctx=lambda section: ctx, page=lambda section: page,
                              comparison=AnalysisComparisonDisplay(),
                              _analysis_state_for_id=lambda section, view_id: state if state.view_id == view_id else None)
    return HeatmapColorCoordinator(context=context), state, canvases, ctx


def resolution(value):
    return DbReferenceResolution(value=value, unit="N", quantity="force", source="manual", warning="")


def paint(owner, canvas, reference, source):
    policy = owner.prepare("fft_time", canvas, {}, resolution(reference), source, "amplitude_db")
    owner.complete("fft_time", canvas, policy)
    return policy


def test_repeat_projection_preserves_request_and_reference_anchor():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    paint(owner, canvases[0], 1, ("f1", "sig"))
    for _ in range(20):
        paint(owner, canvases[0], 10, ("f1", "sig"))
    assert ctx.projection == (False, -100, -20)
    assert state.params["z_floor"] == -80
    assert state.panes[0].heatmap_color_basis["reference"] == 1


def test_locked_union_does_not_poison_natural_ranges_on_unlock():
    owner, state, canvases, ctx = setup()
    state.panes[1].chart_appearances = {"heatmap": {"z_auto": False, "z_min": -20, "z_max": 20}}
    with owner.transaction("fft_time"):
        paint(owner, canvases[1], 10, ("f2", "sig"))
        assert ctx.projection is None
        paint(owner, canvases[0], 1, ("f1", "sig"))
    assert canvases[0].levels == canvases[1].levels == (False, -80, 20)
    state.compare["levels_locked"] = False
    owner.settle("fft_time")
    assert canvases[0].levels == (False, -80, 0)
    assert canvases[1].levels == (False, -20, 20)
    assert state.params["z_ceiling"] == 0


def test_nonfocus_completion_cannot_project_inspector():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    paint(owner, canvases[1], 1, ("f2", "sig"))
    assert ctx.projection is None


def test_failed_transaction_does_not_commit_first_pane_basis():
    owner, state, canvases, ctx = setup()
    with pytest.raises(ValueError):
        with owner.transaction("fft_time"):
            paint(owner, canvases[0], 1, ("f1", "sig"))
            raise ValueError("second pane cannot paint")
    assert state.panes[0].heatmap_color_basis is None
    assert ctx.projection is None


def test_inspector_edit_clears_only_focused_override_and_reanchors_defaults():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    state.panes[0].chart_appearances = {"heatmap": {"title": "keep", "z_auto": False, "z_min": -20, "z_max": 20}}
    with owner.transaction("fft_time"):
        paint(owner, canvases[0], 10, ("f1", "sig"))
        paint(owner, canvases[1], 1, ("f2", "sig"))
    assert owner.commit("fft_time", canvases[0], {"z_auto": False, "z_floor": -55.12345, "z_ceiling": 5.12345})
    assert state.params["z_floor"] == -55.12345
    assert state.panes[0].chart_appearances == {"heatmap": {"title": "keep"}}
    assert state.panes[0].heatmap_color_basis["reference"] == 10
    assert state.panes[1].heatmap_color_basis["reference"] == 1


def test_empty_result_cannot_anchor_request():
    owner, state, canvases, ctx = setup()
    canvases[0]._matrix_amp_valid = [[False]]
    paint(owner, canvases[0], 1, ("f1", "sig"))
    assert state.panes[0].heatmap_color_basis is None
    assert ctx.projection is None


def test_deferred_reveal_observes_final_union():
    owner, state, canvases, ctx = setup()
    observed = []
    state.panes[1].chart_appearances = {"heatmap": {"z_auto": False, "z_min": -20, "z_max": 20}}
    with owner.transaction("fft_time"):
        paint(owner, canvases[0], 1, ("f1", "sig"))
        owner.defer_after_settle("fft_time", lambda: observed.append(canvases[0].levels))
        paint(owner, canvases[1], 1, ("f2", "sig"))
        assert not observed
    assert observed == [(False, -80, 20)]


def test_bridge_keeps_exact_request_while_capturing_non_z_edits():
    from mf4_analyzer.ui.analysis_view_bridge import requested_params_from_context
    raw = dict(z_auto=False, z_floor=-80.123456789, z_ceiling=0.123456789)
    state = SimpleNamespace(params=dict(raw, x_min=0))
    ctx = SimpleNamespace(current_params=lambda: dict(z_auto=False, z_floor=-100.12, z_ceiling=-19.88, x_min=5),
                          color_policy_projection=lambda: dict(z_floor=-100.123456789))
    assert requested_params_from_context(ctx, state) == dict(raw, x_min=5)
    legacy = SimpleNamespace(get_params=lambda: {"x_min": 3})
    assert requested_params_from_context(legacy, state) == {"x_min": 3}


def test_chart_restore_keeps_opening_anchor_and_preserves_non_z_edits():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    paint(owner, canvases[0], 1, ("f1", "sig"))
    paint(owner, canvases[0], 10, ("f1", "sig"))
    snapshot = owner.snapshot("fft_time", canvases[0])
    owner.commit("fft_time", canvases[0], dict(z_auto=False, z_floor=-20, z_ceiling=20), origin="chart_options")
    state.params["x_min"] = 5
    state.panes[0].chart_appearances["heatmap"]["title"] = "keep"
    assert owner.restore("fft_time", canvases[0], snapshot)
    assert canvases[0].levels == (False, -100, -20)
    assert state.params["x_min"] == 5
    assert state.panes[0].chart_appearances == {"heatmap": {"title": "keep"}}
    assert state.panes[0].heatmap_color_basis["reference"] == 1
    state.panes[0].sources = [("replacement", "sig")]
    assert not owner.restore("fft_time", canvases[0], snapshot)


def test_manual_to_auto_rederives_data_window():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    canvases[0]._automatic_color_window = lambda: (-45., -5.)
    paint(owner, canvases[0], 1, ("f1", "sig"))
    assert owner.commit("fft_time", canvases[0], {"z_auto": True})
    assert canvases[0].levels == (True, -45., -5.)
    assert state.panes[0].heatmap_color_basis is None


def test_locked_inspector_edit_preserves_sibling_override_scope():
    owner, state, canvases, ctx = setup()
    state.panes[1].chart_appearances = {"heatmap": {"z_auto": False, "z_min": -20, "z_max": 20}}
    with owner.transaction("fft_time"):
        paint(owner, canvases[0], 1, ("f1", "sig"))
        paint(owner, canvases[1], 1, ("f2", "sig"))
    owner.commit("fft_time", canvases[0], dict(z_auto=False, z_floor=-50, z_ceiling=10))
    assert state.panes[1].chart_appearances["heatmap"]["z_min"] == -50
    assert canvases[0].levels == canvases[1].levels == (False, -50, 10)


def test_committed_preset_targets_focused_comparison_peer():
    from mf4_analyzer.ui.main_window.analysis_context import AnalysisContext
    from mf4_analyzer.ui.main_window.analysis_comparison import AnalysisViewTarget
    owner, host, canvases, ctx = setup()
    peer = AnalysisViewState(name="Peer", tab_color="#fff", params=dict(host.params),
                             panes=[PaneState(sources=[("f2", "sig")])])
    context = owner._context
    context.heatmap_color = owner
    context._analysis_managers["fft_time"].views.append(peer)
    context._analysis_state_for_id = lambda section, view_id: next(
        (state for state in (host, peer) if state.view_id == view_id), None)
    context.page("fft_time").focused_canvas = lambda: canvases[0]
    comp = context.comparison
    comp.begin("fft_time", host.view_id, peer.view_id)
    comp.bind_canvas(canvases[0], AnalysisViewTarget("fft_time", host.view_id, 0))
    comp.bind_canvas(canvases[1], AnalysisViewTarget("fft_time", peer.view_id, 0))
    comp.focus("fft_time", peer.view_id, 0)
    paint(owner, canvases[0], 1, ("f1", "sig"))
    paint(owner, canvases[1], 1, ("f2", "sig"))
    preset = dict(z_auto=False, z_floor=-30., z_ceiling=10.)
    ctx.consume_color_policy_edit = lambda: preset
    ctx.current_params = lambda: preset
    AnalysisContext.sync_committed_preset(context, "fft_time", peer)
    assert host.params["z_floor"] == -80.
    assert peer.params["z_floor"] == -30.
    assert canvases[1].levels == (False, -30., 10.)


@pytest.mark.parametrize("auto", [False, True])
def test_focused_no_result_edit_projects_without_creating_basis(auto):
    owner, state, canvases, ctx = setup()
    canvases[0]._matrix_disp = None
    assert owner.commit("fft_time", canvases[0], dict(z_auto=auto, z_floor=-50., z_ceiling=5.))
    assert state.params["z_auto"] is auto
    assert ctx.projection == (auto, -50., 5.)
    assert state.panes[0].heatmap_color_basis is None
    assert canvases[0].levels is None


def test_standalone_render_settles_once_before_reveal():
    owner, state, canvases, ctx = setup()
    observed = []
    original = owner.settle
    def counted(section):
        observed.append(section)
        return original(section)
    owner.settle = counted
    paint(owner, canvases[0], 1, ("f1", "sig"))
    owner.defer_after_settle("fft_time", lambda: observed.append("reveal"))
    assert observed == ["fft_time", "reveal"]


def test_late_completion_does_not_consume_new_request_or_picture():
    owner, state, canvases, ctx = setup()
    old = owner.prepare("fft_time", canvases[0], {}, resolution(1), ("f1", "sig"), "amplitude_db")
    new = owner.prepare("fft_time", canvases[0], {}, resolution(10), ("f1", "sig"), "amplitude_db")
    assert not owner.complete("fft_time", canvases[0], old)
    assert owner.complete("fft_time", canvases[0], new)
    assert not owner.complete("fft_time", canvases[0], old)
    owner.settle("fft_time")
    assert canvases[0].levels == (False, -80., 0.)
    assert state.panes[0].heatmap_color_basis["reference"] == 10
    assert canvases[0] in owner._records


def test_comparison_retains_each_views_local_lock_group():
    from mf4_analyzer.ui.main_window.analysis_comparison import AnalysisViewTarget
    owner, host, canvases, ctx = setup()
    peer = AnalysisViewState(name="Peer", tab_color="#fff", params=dict(host.params),
                             panes=[PaneState(sources=[("f3", "sig")])])
    canvases.append(Canvas())
    context = owner._context
    context._analysis_managers["fft_time"].views.append(peer)
    context._analysis_state_for_id = lambda section, view_id: next(
        (state for state in (host, peer) if state.view_id == view_id), None)
    comp = context.comparison
    comp.begin("fft_time", host.view_id, peer.view_id)
    for canvas, state, index in ((canvases[0], host, 0), (canvases[1], host, 1), (canvases[2], peer, 0)):
        comp.bind_canvas(canvas, AnalysisViewTarget("fft_time", state.view_id, index))
    host.panes[1].chart_appearances = {"heatmap": {"z_auto": False, "z_min": -20, "z_max": 20}}
    with owner.transaction("fft_time"):
        for index, canvas in enumerate(canvases):
            paint(owner, canvas, 1, (f"f{index + 1}", "sig"))
    assert canvases[0].levels == canvases[1].levels == (False, -80., 20.)
    assert canvases[2].levels == (False, -80., 0.)
    owner.commit("fft_time", canvases[0], dict(z_auto=False, z_floor=-50., z_ceiling=10.))
    assert canvases[0].levels == canvases[1].levels == (False, -50., 10.)
    assert peer.params["z_floor"] == -80.
    assert canvases[2].levels == (False, -80., 0.)


def test_safe_picture_query_is_read_only_and_requires_same_source_owner():
    owner, state, canvases, ctx = setup()
    paint(owner, canvases[0], 1, ("f1", "sig"))
    before = state.to_dict()
    assert owner.has_current_picture("fft_time", canvases[0], ("f1", "sig"))
    assert not owner.has_current_picture("fft_time", canvases[0], ("other", "sig"))
    assert not owner.has_current_picture("order", canvases[0], ("f1", "sig"))
    assert state.to_dict() == before
    state.panes[0].sources = [("other", "sig")]
    assert not owner.has_current_picture("fft_time", canvases[0])
    state.panes[0].sources = [("f1", "sig")]
    state.view_id = "another-view"
    assert not owner.has_current_picture("fft_time", canvases[0])
    assert state.panes[0].heatmap_color_basis == before["panes"][0]["heatmap_color_basis"]


def test_pane_override_projection_passes_view_request_to_preset_baseline():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    state.panes[0].chart_appearances = {"heatmap": {"z_auto": False, "z_min": -20, "z_max": 20}}
    paint(owner, canvases[0], 1, ("f1", "sig"))
    assert ctx.projection == (False, -20, 20)
    assert ctx.requested["z_floor"] == -80
    assert ctx.requested["z_ceiling"] == 0


def test_dialog_apply_after_owner_switch_cannot_edit_new_view():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    paint(owner, canvases[0], 1, ("f1", "sig"))
    with owner.edit_session("fft_time", canvases[0]):
        state.view_id = "new-view"
        state.params.update(z_floor=-60., z_ceiling=10.)
        paint(owner, canvases[0], 1, ("f1", "sig"))
        canvases[0].levels = (False, -5., 5.)  # Dialog applies its preview before emitting.
        assert not owner.commit("fft_time", canvases[0], dict(z_auto=False, z_floor=-5., z_ceiling=5.), origin="chart_options")
        assert state.params["z_floor"] == -60.
        assert not state.panes[0].chart_appearances
        assert canvases[0].levels == (False, -60., 10.)
    assert owner.commit("fft_time", canvases[0], dict(z_auto=False, z_floor=-5., z_ceiling=5.), origin="chart_options")


def test_dialog_apply_after_source_switch_cannot_edit_replacement_source():
    owner, state, canvases, ctx = setup()
    state.compare["levels_locked"] = False
    paint(owner, canvases[0], 1, ("f1", "sig"))
    with owner.edit_session("fft_time", canvases[0]):
        state.panes[0].sources = [("new-source", "sig")]
        paint(owner, canvases[0], 10, ("new-source", "sig"))
        before = state.to_dict()
        assert not owner.commit("fft_time", canvases[0], dict(z_auto=False, z_floor=-5., z_ceiling=5.), origin="chart_options")
        assert state.to_dict() == before


def test_render_group_reset_baseline_is_final_union_and_edits_do_not_replace_it():
    owner, state, canvases, ctx = setup()
    state.panes[1].chart_appearances = {"heatmap": {"z_auto": False, "z_min": -20, "z_max": 20}}
    with owner.transaction("fft_time"):
        paint(owner, canvases[0], 1, ("f1", "sig"))
        paint(owner, canvases[1], 1, ("f2", "sig"))
    assert canvases[0].reset_baseline == canvases[1].reset_baseline == (-80., 20.)
    owner.commit("fft_time", canvases[0], dict(z_auto=False, z_floor=-50., z_ceiling=10.))
    owner.settle("fft_time")
    assert canvases[0].levels == canvases[1].levels == (False, -50., 10.)
    assert canvases[0].reset_baseline == canvases[1].reset_baseline == (-80., 20.)
