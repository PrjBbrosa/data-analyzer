"""Applied analysis authorization is independent of cached arrays and drafts."""
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState


def test_binding_is_session_only_and_request_is_detached():
    from mf4_analyzer.ui.analysis_result_state import bind_result, snapshot_request

    pane = PaneState(sources=[("f0", "speed")], time_range=(0.1, 0.9))
    state = AnalysisViewState("A", "#123456", params={"window": "hanning"}, panes=[pane])
    request = snapshot_request(state, pane)
    state.params["window"] = "blackman"
    pane.sources.append(("f1", "speed"))
    assert request.params["window"] == "hanning"
    assert request.sources == (("f0", "speed"),)
    assert bind_result(pane, request, ("key",))
    restored = PaneState.from_dict(pane.to_dict())
    assert restored.result_binding is None
    assert restored.request_revision == 0


def test_edit_and_revert_cannot_authorize_old_completion():
    from mf4_analyzer.ui.analysis_result_state import bind_result, mark_pending, snapshot_request

    pane = PaneState()
    state = AnalysisViewState("A", "#123456", params={"window": "hanning"}, panes=[pane])
    applied = snapshot_request(state, pane)
    assert bind_result(pane, applied, ("old",))
    submitted = snapshot_request(state, pane)
    mark_pending(pane)
    mark_pending(pane)
    assert not bind_result(pane, submitted, ("late",))
    assert pane.result_binding.keys == ("old",)
    assert pane.result_binding.stale
    assert bind_result(pane, snapshot_request(state, pane), ("new",))
    assert not pane.result_binding.stale


def test_empty_or_failed_result_keeps_previous_binding():
    from mf4_analyzer.ui.analysis_result_state import bind_result, snapshot_request

    pane = PaneState()
    state = AnalysisViewState("A", "#123456", panes=[pane])
    request = snapshot_request(state, pane)
    assert bind_result(pane, request, ("old",))
    assert not bind_result(pane, request, ())
    assert pane.result_binding.keys == ("old",)


def test_snapshot_nested_intent_is_immutable_and_duplicate_drops_authorization():
    import pytest
    from mf4_analyzer.ui.analysis_result_state import bind_result, snapshot_request
    from mf4_analyzer.ui.view_state import ViewManager

    manager = ViewManager(state_factory=AnalysisViewState)
    state = manager.get(0)
    state.params = {"nested": {"levels": [1, 2]}}
    pane = state.panes[0]
    request = snapshot_request(state, pane)
    bind_result(pane, request, ("applied",))
    state.params["nested"]["levels"].append(3)
    assert request.params["nested"]["levels"] == (1, 2)
    with pytest.raises(TypeError):
        request.params["nested"]["levels"] = ()
    copied = manager.get(manager.duplicate(0))
    assert copied.panes[0].result_binding is None
    assert copied.panes[0].request_revision == 0
    assert copied.params["nested"]["levels"] == [1, 2, 3]
