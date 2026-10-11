"""Qt-free, session-local authorization for explicitly applied analysis results."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class AnalysisRequestSnapshot:
    params: Mapping[str, Any]
    sources: tuple[tuple[str, str], ...]
    time_range: tuple[float, float] | None
    rpm_source: tuple[str, str] | None
    input_source: tuple[str, str] | None
    output_source: tuple[str, str] | None
    revision: int


@dataclass(frozen=True)
class AnalysisResultBinding:
    request: AnalysisRequestSnapshot
    keys: tuple[Any, ...]
    stale: bool = False


def snapshot_request(state, pane) -> AnalysisRequestSnapshot:
    """Detach user intent from the mutable Inspector/View before submission."""
    def source(value):
        return tuple(value) if value is not None else None

    def freeze(value):
        if isinstance(value, Mapping):
            return MappingProxyType({key: freeze(item) for key, item in value.items()})
        if isinstance(value, (tuple, list)):
            return tuple(freeze(item) for item in value)
        if isinstance(value, (set, frozenset)):
            return frozenset(freeze(item) for item in value)
        return deepcopy(value)

    return AnalysisRequestSnapshot(
        params=freeze(state.params),
        sources=tuple(tuple(item) for item in pane.sources),
        time_range=tuple(pane.time_range) if pane.time_range is not None else None,
        rpm_source=source(pane.rpm_source),
        input_source=source(pane.input_source),
        output_source=source(pane.output_source),
        revision=pane.request_revision,
    )


def mark_pending(pane) -> None:
    """Every compute-intent edit invalidates older in-flight requests."""
    pane.request_revision += 1
    if pane.result_binding is not None:
        pane.result_binding = replace(pane.result_binding, stale=True)


def bind_result(pane, request: AnalysisRequestSnapshot, keys) -> bool:
    """Apply a successful explicit request; failure/staleness retains old data."""
    keys = tuple(keys)
    if not keys or request.revision != pane.request_revision:
        return False
    pane.result_binding = AnalysisResultBinding(request=request, keys=keys)
    return True
