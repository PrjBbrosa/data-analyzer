"""Analysis-section view state: Section → View → Pane → Source.

Per-section ``ViewManager(state_factory=AnalysisViewState)`` instances
manage these. Unlike the time-domain ``ViewState``, split lives INSIDE
the view as ``panes`` (spec §3) — the time-domain ``_split_pairs``
pairing is not used for analysis sections.

Serialization mirrors view_state.py conventions (JSON-safe dicts,
``(fid, ch)`` keys as 2-lists) so project_io can persist both shapes
with one code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ChannelKey = tuple[str, str]
MAX_PANES = 2  # spec §2: v1 caps split at 2; the model is list-shaped for later N


def _coerce_key(value: Any) -> ChannelKey:
    fid, ch = value
    return (str(fid), str(ch))


@dataclass
class PaneState:
    sources: list[ChannelKey] = field(default_factory=list)
    rpm_source: ChannelKey | None = None     # Order only
    time_range: tuple[float, float] | None = None
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [list(k) for k in self.sources],
            "rpm_source": list(self.rpm_source) if self.rpm_source else None,
            "time_range": list(self.time_range) if self.time_range else None,
            "xlim": list(self.xlim) if self.xlim else None,
            "ylim": list(self.ylim) if self.ylim else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaneState":
        def pair(v):
            return (float(v[0]), float(v[1])) if v else None
        return cls(
            sources=[_coerce_key(k) for k in data.get("sources", [])],
            rpm_source=(_coerce_key(data["rpm_source"])
                        if data.get("rpm_source") else None),
            time_range=pair(data.get("time_range")),
            xlim=pair(data.get("xlim")),
            ylim=pair(data.get("ylim")),
        )


@dataclass
class AnalysisViewState:
    name: str
    tab_color: str
    panes: list[PaneState] = field(default_factory=lambda: [PaneState()])
    params: dict[str, Any] = field(default_factory=dict)
    compare: dict[str, bool] = field(
        default_factory=lambda: {"x_linked": True, "levels_locked": True})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "name": self.name,
            "tab_color": self.tab_color,
            "panes": [p.to_dict() for p in self.panes],
            "params": dict(self.params),
            "compare": dict(self.compare),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisViewState":
        panes = [PaneState.from_dict(p) for p in data.get("panes", [])]
        if not panes:
            panes = [PaneState()]
        compare = {"x_linked": True, "levels_locked": True}
        compare.update(data.get("compare", {}))
        return cls(
            name=data["name"],
            tab_color=data["tab_color"],
            panes=panes[:MAX_PANES],
            params=dict(data.get("params", {})),
            compare=compare,
        )

    # -- structure ops -------------------------------------------------
    def add_pane(self) -> bool:
        if len(self.panes) >= MAX_PANES:
            return False
        self.panes.append(PaneState())
        return True

    def remove_second_pane(self) -> None:
        del self.panes[1:]

    def validate(self, *, allow_overlay: bool) -> list[str]:
        """Heatmap sections pass allow_overlay=False (1 source per pane)."""
        errs = []
        for i, p in enumerate(self.panes):
            if not allow_overlay and len(p.sources) > 1:
                errs.append(
                    f"pane {i}: overlay ({len(p.sources)} sources) "
                    "not allowed for heatmap sections")
        return errs
