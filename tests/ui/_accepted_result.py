"""Seed a successful explicit analysis request, not merely a shared cache hit."""
from mf4_analyzer.ui.analysis_result_state import bind_result, snapshot_request


def accept_cached_result(state, keys, pane_idx=0):
    pane = state.panes[pane_idx]
    request = snapshot_request(state, pane)
    assert bind_result(pane, request, keys)
    return request
