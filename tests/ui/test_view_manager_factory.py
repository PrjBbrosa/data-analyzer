"""ViewManager works with a custom state_factory (analysis views)."""
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
from mf4_analyzer.ui.view_state import ViewManager, ViewState


def test_default_factory_unchanged(qapp):
    m = ViewManager()
    assert isinstance(m.views[0], ViewState)


def test_analysis_factory(qapp):
    m = ViewManager(state_factory=AnalysisViewState)
    assert isinstance(m.views[0], AnalysisViewState)
    idx = m.new_view()
    assert isinstance(m.views[idx], AnalysisViewState)


def test_duplicate_uses_factory_type(qapp):
    m = ViewManager(state_factory=AnalysisViewState)
    m.views[0].params = {"nfft": 2048}
    original_id = m.views[0].view_id
    idx = m.duplicate(0)
    assert isinstance(m.views[idx], AnalysisViewState)
    assert m.views[idx].params == {"nfft": 2048}
    assert m.views[idx].name.endswith("副本")
    assert m.views[idx].view_id != original_id


def test_analysis_view_reorder_preserves_stable_ids(qapp):
    m = ViewManager(state_factory=AnalysisViewState)
    m.new_view()
    m.new_view()
    m.views[0].name, m.views[1].name, m.views[2].name = "A", "B", "C"
    ids_by_name = {view.name: view.view_id for view in m.views}

    m.reorder(0, 2)

    assert {view.name: view.view_id for view in m.views} == ids_by_name
