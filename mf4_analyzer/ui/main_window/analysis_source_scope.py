"""Pure helpers for analysis View file/source scope (Stage 1 isolation).

No Qt / MainWindow / cache / dialog side effects. Callers own projection
and confirmation UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from ..analysis_view_state import (
    AnalysisViewState,
    analysis_view_source_fids,
    normalize_analysis_attachments,
)
from ..time_xaxis import EXACT_SOURCE, CustomXAxisSpec


@dataclass(frozen=True)
class SourceUse:
    domain: str  # time | fft | fft_time | frf | order
    view_id: str
    view_name: str
    pane_idx: int | None
    role: str  # attachment | checked | signal | rpm | input | output | overlay_primary | x_axis
    fid: str
    channel: str | None = None


@dataclass
class DetachImpact:
    removed_fids: list[str] = field(default_factory=list)
    cleared_roles: list[tuple[int, str, str | None]] = field(default_factory=list)
    # (pane_idx, role, channel-or-None)


def analysis_scope_fids(
    state: AnalysisViewState | None,
    files: Mapping[str, Any] | Iterable[str] | None,
) -> list[str]:
    """Still-loaded fids from an analysis View's attachment list."""
    if state is None:
        if files is None:
            return []
        if isinstance(files, Mapping):
            return list(files)
        return [str(fid) for fid in files]
    loaded = set(files) if not isinstance(files, Mapping) else set(files)
    return [
        str(fid) for fid in state.attached_file_ids if str(fid) in loaded
    ]


def _append_time_persisted_uses(
    uses: list[SourceUse],
    state: Any,
    *,
    target: str,
    view_id: str,
    view_name: str,
) -> None:
    """Index Time View persisted refs that are not attachment/checked."""
    overlay = getattr(state, "overlay_primary", None)
    if overlay is not None and str(overlay[0]) == target:
        uses.append(SourceUse(
            domain="time",
            view_id=view_id,
            view_name=view_name,
            pane_idx=None,
            role="overlay_primary",
            fid=target,
            channel=str(overlay[1]),
        ))

    axis_opts = getattr(state, "axis_opts", None) or {}
    if not isinstance(axis_opts, Mapping):
        return
    spec = CustomXAxisSpec.from_axis_opts(axis_opts.get("x_axis"))
    if (
        spec.resolver == EXACT_SOURCE
        and spec.source_fid is not None
        and str(spec.source_fid) == target
    ):
        uses.append(SourceUse(
            domain="time",
            view_id=view_id,
            view_name=view_name,
            pane_idx=None,
            role="x_axis",
            fid=target,
            channel=str(spec.channel) if spec.channel else None,
        ))

    signature = axis_opts.get("frf_source_signature")
    if not isinstance(signature, dict):
        return
    for role_name in ("input", "output"):
        endpoint = signature.get(role_name)
        if (
            isinstance(endpoint, (list, tuple))
            and len(endpoint) == 2
            and str(endpoint[0]) == target
        ):
            uses.append(SourceUse(
                domain="time",
                view_id=view_id,
                view_name=view_name,
                pane_idx=None,
                role=role_name,
                fid=target,
                channel=str(endpoint[1]),
            ))


def collect_source_uses(
    fid: str,
    *,
    time_views: Sequence[Any] = (),
    analysis_managers: Mapping[str, Any] | None = None,
) -> list[SourceUse]:
    """Index every Time / Analysis reference to ``fid`` without mutating."""
    target = str(fid)
    uses: list[SourceUse] = []
    for state in time_views or ():
        view_id = str(getattr(state, "view_id", "") or "")
        view_name = str(getattr(state, "name", "") or "")
        attached = [
            str(item) for item in getattr(state, "attached_file_ids", []) or []
        ]
        if target in attached:
            uses.append(SourceUse(
                domain="time",
                view_id=view_id,
                view_name=view_name,
                pane_idx=None,
                role="attachment",
                fid=target,
            ))
        for key in getattr(state, "checked", []) or []:
            if str(key[0]) == target:
                uses.append(SourceUse(
                    domain="time",
                    view_id=view_id,
                    view_name=view_name,
                    pane_idx=None,
                    role="checked",
                    fid=target,
                    channel=str(key[1]),
                ))
        _append_time_persisted_uses(
            uses,
            state,
            target=target,
            view_id=view_id,
            view_name=view_name,
        )

    for section, manager in (analysis_managers or {}).items():
        views = getattr(manager, "views", None) or ()
        for state in views:
            view_id = str(getattr(state, "view_id", "") or "")
            view_name = str(getattr(state, "name", "") or "")
            attached = [
                str(item)
                for item in getattr(state, "attached_file_ids", []) or []
            ]
            if target in attached:
                uses.append(SourceUse(
                    domain=str(section),
                    view_id=view_id,
                    view_name=view_name,
                    pane_idx=None,
                    role="attachment",
                    fid=target,
                ))
            for pane_idx, pane in enumerate(getattr(state, "panes", []) or []):
                for key in getattr(pane, "sources", []) or []:
                    if str(key[0]) == target:
                        uses.append(SourceUse(
                            domain=str(section),
                            view_id=view_id,
                            view_name=view_name,
                            pane_idx=pane_idx,
                            role="signal",
                            fid=target,
                            channel=str(key[1]),
                        ))
                rpm = getattr(pane, "rpm_source", None)
                if rpm is not None and str(rpm[0]) == target:
                    uses.append(SourceUse(
                        domain=str(section),
                        view_id=view_id,
                        view_name=view_name,
                        pane_idx=pane_idx,
                        role="rpm",
                        fid=target,
                        channel=str(rpm[1]),
                    ))
                for role_name in ("input_source", "output_source"):
                    role = getattr(pane, role_name, None)
                    if role is not None and str(role[0]) == target:
                        short = "input" if role_name.startswith("input") else "output"
                        uses.append(SourceUse(
                            domain=str(section),
                            view_id=view_id,
                            view_name=view_name,
                            pane_idx=pane_idx,
                            role=short,
                            fid=target,
                            channel=str(role[1]),
                        ))
    return uses


def collect_channel_uses(
    fid: str,
    channels: Iterable[str],
    *,
    time_views: Sequence[Any] = (),
    analysis_managers: Mapping[str, Any] | None = None,
) -> list[SourceUse]:
    """Like ``collect_source_uses`` but limited to specific channel names."""
    wanted = {(str(fid), str(ch)) for ch in channels or ()}
    if not wanted:
        return []
    uses = []
    for use in collect_source_uses(
        fid, time_views=time_views, analysis_managers=analysis_managers,
    ):
        if use.role in {"attachment"}:
            continue
        if use.channel is None:
            continue
        if (use.fid, use.channel) in wanted:
            uses.append(use)
    return uses

def detach_analysis_files(
    state: AnalysisViewState,
    removed_fids: Iterable[str],
) -> DetachImpact:
    """Remove fids from one analysis View's attachment + dependent roles."""
    removed = {str(fid) for fid in removed_fids if str(fid)}
    impact = DetachImpact(removed_fids=sorted(removed))
    if not removed:
        return impact

    before = list(state.attached_file_ids)
    state.attached_file_ids = [
        fid for fid in before if str(fid) not in removed
    ]

    for pane_idx, pane in enumerate(state.panes):
        kept_sources = []
        for key in pane.sources:
            if str(key[0]) in removed:
                impact.cleared_roles.append((pane_idx, "signal", str(key[1])))
            else:
                kept_sources.append(key)
        pane.sources = kept_sources

        if pane.rpm_source is not None and str(pane.rpm_source[0]) in removed:
            impact.cleared_roles.append(
                (pane_idx, "rpm", str(pane.rpm_source[1]))
            )
            pane.rpm_source = None

        input_hit = (
            pane.input_source is not None
            and str(pane.input_source[0]) in removed
        )
        output_hit = (
            pane.output_source is not None
            and str(pane.output_source[0]) in removed
        )
        if input_hit or output_hit:
            if pane.input_source is not None:
                impact.cleared_roles.append(
                    (pane_idx, "input", str(pane.input_source[1]))
                )
            if pane.output_source is not None:
                impact.cleared_roles.append(
                    (pane_idx, "output", str(pane.output_source[1]))
                )
            pane.input_source = None
            pane.output_source = None

    return impact


def filter_analysis_view_for_removed_fids(
    state: AnalysisViewState,
    removed: Iterable[str],
) -> DetachImpact:
    """Alias used by project/global cleanup paths."""
    return detach_analysis_files(state, removed)


def derive_attachments_from_remapped_payload(view_payload: Mapping[str, Any]) -> list[str]:
    """Schema ≤6 migration helper after pane roles have already been remapped."""
    if "attached_file_ids" in view_payload:
        return normalize_analysis_attachments(
            view_payload.get("attached_file_ids")
        )
    return analysis_view_source_fids(view_payload)
