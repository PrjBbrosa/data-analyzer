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
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from ..db_reference import migrate_legacy_reference_params

ChannelKey = tuple[str, str]
MAX_PANES = 2  # spec §2: v1 caps split at 2; the model is list-shaped for later N
# dB reference defaults (Task 8, spec §13 S3) introduced nested schema 2;
# FRF role state adds schema 3, including separate requested/effective ranges;
# schema 4 added the pane-local FRF cursor flag; schema 5 replaces it with the
# shared frequency-domain off/single/dual cursor mode for FFT and FRF panes;
# schema 6 removes the obsolete FRF Time-View link from persisted output;
# schema 7 adds per-analysis-View ``attached_file_ids`` (Stage 1 source isolation).
# The additions are field-presence tolerant -- from_dict() keys the
# migration off "params has db_reference and no db_reference_mode", NOT this
# number, so schema-2 through schema-6 projects all apply the
# saved snapshot value manual-style instead of erroring or dropping it.
_SCHEMA = 7


def _coerce_key(value: Any) -> ChannelKey:
    fid, ch = value
    return (str(fid), str(ch))


def _cursor_mode_from_data(data: dict[str, Any]) -> str:
    """Read schema-5 mode, migrating the short-lived schema-4 FRF flag."""
    mode = str(data.get("cursor_mode") or "")
    if mode in {"off", "single", "dual"}:
        return mode
    return "single" if data.get("frf_cursor_enabled") else "off"


def normalize_analysis_attachments(values: Iterable[Any] | None) -> list[str]:
    """Deduplicate fids while preserving first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        fid = str(value)
        if not fid or fid in seen:
            continue
        seen.add(fid)
        out.append(fid)
    return out


def analysis_view_source_fids(
    state_or_payload: "AnalysisViewState | Mapping[str, Any] | None",
) -> list[str]:
    """First-seen union of pane role fids (sources / rpm / input / output)."""
    if state_or_payload is None:
        return []
    if isinstance(state_or_payload, AnalysisViewState):
        panes: Sequence[Any] = state_or_payload.panes
        role_fids: list[str] = []
        for pane in panes:
            for key in pane.sources:
                role_fids.append(str(key[0]))
            if pane.rpm_source is not None:
                role_fids.append(str(pane.rpm_source[0]))
            if pane.input_source is not None:
                role_fids.append(str(pane.input_source[0]))
            if pane.output_source is not None:
                role_fids.append(str(pane.output_source[0]))
        return normalize_analysis_attachments(role_fids)

    role_fids = []
    for pane in (state_or_payload.get("panes") or []):
        if not isinstance(pane, Mapping):
            continue
        for source in pane.get("sources") or []:
            if isinstance(source, (list, tuple)) and source:
                role_fids.append(str(source[0]))
        for role in ("rpm_source", "input_source", "output_source"):
            source = pane.get(role)
            if isinstance(source, (list, tuple)) and source:
                role_fids.append(str(source[0]))
    return normalize_analysis_attachments(role_fids)


@dataclass
class PaneState:
    sources: list[ChannelKey] = field(default_factory=list)
    rpm_source: ChannelKey | None = None     # Order only
    input_source: ChannelKey | None = None   # FRF only
    output_source: ChannelKey | None = None  # FRF only
    time_range: tuple[float, float] | None = None
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None
    ylims: dict[str, tuple[float, float]] = field(default_factory=dict)
    source_time_view_id: str | None = None
    # FRF only: actual first/last selected sample. ``time_range`` remains the
    # user's manual/current-Time-View snapshot and must not be overwritten by
    # sample-grid rounding during candidate construction.
    effective_time_range: tuple[float, float] | None = None
    # FFT and FRF only.  ``frf_cursor_enabled`` was the schema-4 predecessor;
    # old project payloads migrate its true value to the single-cursor mode.
    cursor_mode: str = "off"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [list(k) for k in self.sources],
            "rpm_source": list(self.rpm_source) if self.rpm_source else None,
            "input_source": (
                list(self.input_source) if self.input_source else None
            ),
            "output_source": (
                list(self.output_source) if self.output_source else None
            ),
            "time_range": list(self.time_range) if self.time_range else None,
            "xlim": list(self.xlim) if self.xlim else None,
            "ylim": list(self.ylim) if self.ylim else None,
            "ylims": {key: list(value) for key, value in self.ylims.items()},
            "effective_time_range": (
                list(self.effective_time_range)
                if self.effective_time_range else None
            ),
            "cursor_mode": self.cursor_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaneState":
        def pair(v):
            return (float(v[0]), float(v[1])) if v else None
        return cls(
            sources=[_coerce_key(k) for k in data.get("sources", [])],
            rpm_source=(_coerce_key(data["rpm_source"])
                        if data.get("rpm_source") else None),
            input_source=(_coerce_key(data["input_source"])
                          if data.get("input_source") else None),
            output_source=(_coerce_key(data["output_source"])
                           if data.get("output_source") else None),
            time_range=pair(data.get("time_range")),
            xlim=pair(data.get("xlim")),
            ylim=pair(data.get("ylim")),
            ylims={
                str(key): pair(value)
                for key, value in (data.get("ylims") or {}).items()
                if pair(value) is not None
            },
            source_time_view_id=(
                str(data["source_time_view_id"])
                if data.get("source_time_view_id") else None
            ),
            effective_time_range=pair(data.get("effective_time_range")),
            cursor_mode=_cursor_mode_from_data(data),
        )


@dataclass
class AnalysisViewState:
    name: str
    tab_color: str
    panes: list[PaneState] = field(default_factory=lambda: [PaneState()])
    params: dict[str, Any] = field(default_factory=dict)
    compare: dict[str, bool] = field(
        default_factory=lambda: {"x_linked": True, "levels_locked": True})
    # Appended so the pre-FRF positional constructor stays compatible.
    view_id: str = field(default_factory=lambda: str(uuid4()))
    # Stage 1 source isolation: per-analysis-View file membership. Kept after
    # ``view_id`` so older positional callers remain valid.
    attached_file_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "name": self.name,
            "tab_color": self.tab_color,
            "view_id": self.view_id,
            "attached_file_ids": list(self.attached_file_ids),
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
        # dB reference defaults (Task 8, spec §13 S3/S5): a legacy blob with
        # db_reference but no db_reference_mode migrates to Manual -- the
        # bare number WAS the old authoritative display reference. Keyed off
        # field presence (migrate_legacy_reference_params), never off the
        # "schema" field itself (see _SCHEMA note above); a view with no
        # db_reference at all keeps the key absent so the live control's
        # current Auto/Manual state drives it instead of an injected default.
        params = migrate_legacy_reference_params(dict(data.get("params", {})))
        # Schema-5-and-earlier FRF views hid range origin and Time-View
        # identity beside the shared range inputs.  Read that historical
        # state once, then reduce it to the universal explicit pane range
        # contract.  A missing old range_mode meant "full"; schema 6 no
        # longer writes it, so do not erase a newly persisted explicit range.
        is_legacy_payload = int(data.get("schema") or 0) < 6
        is_frf = any(
            pane.input_source is not None and pane.output_source is not None
            for pane in panes
        )
        if "range_mode" in params or (is_legacy_payload and is_frf):
            legacy_range_mode = str(params.pop("range_mode", "full") or "full")
            if legacy_range_mode not in {"manual", "current_time"}:
                for pane in panes:
                    pane.time_range = None
            for pane in panes:
                pane.source_time_view_id = None
        if "attached_file_ids" in data:
            attached = normalize_analysis_attachments(data.get("attached_file_ids"))
        else:
            attached = analysis_view_source_fids(
                {"panes": [p.to_dict() for p in panes]}
            )
        return cls(
            name=data["name"],
            tab_color=data["tab_color"],
            view_id=str(data.get("view_id") or uuid4()),
            panes=panes[:MAX_PANES],
            params=params,
            compare=compare,
            attached_file_ids=attached,
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
        attached = {str(fid) for fid in self.attached_file_ids}
        for i, p in enumerate(self.panes):
            if not allow_overlay and len(p.sources) > 1:
                errs.append(
                    f"pane {i}: overlay ({len(p.sources)} sources) "
                    "not allowed for heatmap sections")
            for key in p.sources:
                if str(key[0]) not in attached:
                    errs.append(
                        f"pane {i}: source fid {key[0]!r} not in "
                        "attached_file_ids"
                    )
            for role_name, role in (
                ("rpm_source", p.rpm_source),
                ("input_source", p.input_source),
                ("output_source", p.output_source),
            ):
                if role is not None and str(role[0]) not in attached:
                    errs.append(
                        f"pane {i}: {role_name} fid {role[0]!r} "
                        "not in attached_file_ids"
                    )
        return errs


def analysis_view_has_sources(section: str, state: AnalysisViewState) -> bool:
    """Whether a restored analysis view has enough source intent to compute."""

    if str(section) == "frf":
        return any(
            pane.input_source is not None and pane.output_source is not None
            for pane in state.panes
        )
    return any(pane.sources for pane in state.panes)
