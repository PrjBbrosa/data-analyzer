"""JSON serialization for TraceLab project sessions (.tlproj).

Reference-only: stores file *paths* (+ per-file fs/time_source overrides) and
the full View list — never parsed data. Mirrors ``batch_preset_io.py``'s
versioned save/load shape. Pure (no Qt, no MainWindow) so it round-trips
through tests without a running app.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from .time_xaxis import CustomXAxisSpec, EXACT_SOURCE, PER_SOURCE_NAME

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, 2}


class UnsupportedProjectVersion(ValueError):
    """Raised when reading a .tlproj whose schema_version is unknown."""


@dataclass
class ProjectPathRef:
    path_abs: str
    path_rel: str | None


@dataclass
class ProjectFileRef:
    fid: str
    path_abs: str
    path_rel: str | None
    fs: float
    time_source: str
    dbc_refs: list = field(default_factory=list)  # list[ProjectPathRef]


@dataclass
class ProjectDocument:
    active_file: str | None
    current_mode: str
    files: list = field(default_factory=list)        # list[ProjectFileRef]
    views: list = field(default_factory=list)         # list[dict] (ViewState.to_dict)
    view_manager: dict = field(default_factory=dict)  # {"active": int, "split_pairs": {}}
    # {"fft"|"fft_time"|"order": {"active": int, "views": [AnalysisViewState.to_dict()]}}
    analysis_views: dict = field(default_factory=dict)
    filter: dict | None = None


def save_project_to_json(doc: ProjectDocument, path) -> None:
    path = Path(path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "active_file": doc.active_file,
        "current_mode": doc.current_mode,
        "files": [
            {
                "fid": r.fid,
                "path_abs": r.path_abs,
                "path_rel": r.path_rel,
                "fs": float(r.fs),
                "time_source": r.time_source,
                "dbc_refs": [
                    {
                        "path_abs": d.path_abs,
                        "path_rel": d.path_rel,
                    }
                    for d in getattr(r, "dbc_refs", [])
                ],
            }
            for r in doc.files
        ],
        "views": doc.views,
        "view_manager": doc.view_manager,
        "analysis_views": doc.analysis_views,
        "filter": doc.filter,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_project_from_json(path) -> ProjectDocument:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid project JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("project JSON must be a JSON object")

    version = raw.get("schema_version")
    if version is None:
        version = 1
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedProjectVersion(
            f"project schema_version={version} not supported "
            f"(this app reads v{SCHEMA_VERSION})"
        )

    files = [
        ProjectFileRef(
            fid=str(f["fid"]),
            path_abs=str(f["path_abs"]),
            path_rel=f.get("path_rel"),
            fs=float(f.get("fs", 1000.0)),
            time_source=str(f.get("time_source", "generated")),
            dbc_refs=[
                ProjectPathRef(
                    path_abs=str(d["path_abs"]),
                    path_rel=d.get("path_rel"),
                )
                for d in f.get("dbc_refs", [])
            ],
        )
        for f in raw.get("files", [])
    ]
    return ProjectDocument(
        active_file=raw.get("active_file"),
        current_mode=str(raw.get("current_mode", "time")),
        files=files,
        views=list(raw.get("views", [])),
        view_manager=dict(raw.get("view_manager", {})),
        analysis_views=dict(raw.get("analysis_views", {})),
        filter=raw.get("filter") if version >= 2 else None,
    )


def make_relative(path_abs: str, project_path) -> str | None:
    """Path of ``path_abs`` relative to the .tlproj dir; None across drives."""
    try:
        return os.path.relpath(path_abs, Path(project_path).parent)
    except ValueError:
        return None


def make_path_ref(path_abs: str, project_path) -> ProjectPathRef:
    return ProjectPathRef(
        path_abs=str(Path(path_abs).resolve()),
        path_rel=make_relative(str(Path(path_abs).resolve()), project_path),
    )


def resolve_path_ref(ref: ProjectPathRef, project_path) -> "Path | None":
    project_dir = Path(project_path).parent
    if ref.path_rel:
        cand = (project_dir / ref.path_rel).resolve()
        if cand.exists():
            return cand
    cand = Path(ref.path_abs)
    if cand.exists():
        return cand
    return None


def resolve_file_path(ref: ProjectFileRef, project_path) -> "Path | None":
    """Locate a referenced file: path_rel (relative to the .tlproj) first,
    then path_abs. Returns None when neither exists."""
    project_dir = Path(project_path).parent
    if ref.path_rel:
        cand = (project_dir / ref.path_rel).resolve()
        if cand.exists():
            return cand
    cand = Path(ref.path_abs)
    if cand.exists():
        return cand
    return None


def resolve_dbc_paths(ref: ProjectFileRef, project_path) -> list[str]:
    paths = []
    refs = list(getattr(ref, "dbc_refs", []) or [])
    if not refs:
        return []
    for dbc_ref in refs:
        resolved = resolve_path_ref(dbc_ref, project_path)
        if resolved is None:
            return []
        paths.append(str(resolved))
    return paths


def _encode_channel_key(fid: str, channel: str) -> str:
    # Matches ui.view_state._encode_channel_key exactly.
    return json.dumps([fid, channel], ensure_ascii=False, separators=(",", ":"))


def remap_view_fids(views: list, fid_map: dict) -> list:
    """Rewrite the fid of every channel reference in a list of
    ``ViewState.to_dict()`` payloads, dropping references whose fid is absent
    from ``fid_map`` (the file went missing on load)."""
    out = []
    for view in views:
        v = dict(view)

        if "attached_file_ids" in view:
            v["attached_file_ids"] = [
                fid_map[fid]
                for fid in view.get("attached_file_ids", [])
                if fid in fid_map
            ]
        else:
            v["attached_file_ids"] = list(fid_map.values())

        v["checked"] = [
            [fid_map[fid], ch]
            for fid, ch in (tuple(x) for x in view.get("checked", []))
            if fid in fid_map
        ]
        v["hidden_channels"] = [
            [fid_map[fid], ch]
            for fid, ch in (tuple(x) for x in view.get("hidden_channels", []))
            if fid in fid_map
        ]

        new_colors = {}
        for key, color in (view.get("colors") or {}).items():
            fid, ch = json.loads(key)
            if fid in fid_map:
                new_colors[_encode_channel_key(fid_map[fid], ch)] = color
        v["colors"] = new_colors

        op = view.get("overlay_primary")
        v["overlay_primary"] = (
            [fid_map[op[0]], op[1]] if op and op[0] in fid_map else None
        )

        axis = dict(view.get("axis_opts") or {})
        signature = axis.get("frf_source_signature")
        if isinstance(signature, dict):
            input_source = signature.get("input")
            output_source = signature.get("output")
            if (
                isinstance(input_source, (list, tuple))
                and len(input_source) == 2
                and isinstance(output_source, (list, tuple))
                and len(output_source) == 2
                and input_source[0] in fid_map
                and output_source[0] in fid_map
            ):
                mapped_signature = dict(signature)
                mapped_signature["input"] = [
                    fid_map[input_source[0]], input_source[1]
                ]
                mapped_signature["output"] = [
                    fid_map[output_source[0]], output_source[1]
                ]
                axis["frf_source_signature"] = mapped_signature
            else:
                axis.pop("frf_source_signature", None)
        if "x_axis" in axis:
            spec = CustomXAxisSpec.from_axis_opts(axis["x_axis"])
            if spec.resolver == PER_SOURCE_NAME:
                mapped_spec = spec
            elif spec.resolver == EXACT_SOURCE and spec.source_fid in fid_map:
                mapped_spec = replace(spec, source_fid=fid_map[spec.source_fid])
            else:
                mapped_spec = CustomXAxisSpec(label=spec.label)
            axis["x_axis"] = mapped_spec.to_axis_opts()
        if axis or "axis_opts" in view:
            v["axis_opts"] = axis

        out.append(v)
    return out


def remap_analysis_view_fids(analysis_views: dict, fid_map: dict) -> dict:
    """Rewrite fids inside analysis_views payloads; drop refs whose fid
    is absent from ``fid_map`` (same contract as remap_view_fids)."""
    out = {}
    for section, block in (analysis_views or {}).items():
        views = []
        for view in block.get("views", []):
            v = dict(view)
            panes = []
            for pane in view.get("panes", []):
                pn = dict(pane)
                pn["sources"] = [
                    [fid_map[fid], ch]
                    for fid, ch in (tuple(s) for s in pane.get("sources", []))
                    if fid in fid_map
                ]
                rpm = pane.get("rpm_source")
                pn["rpm_source"] = (
                    [fid_map[rpm[0]], rpm[1]]
                    if rpm and rpm[0] in fid_map else None
                )
                for role in ("input_source", "output_source"):
                    source = pane.get(role)
                    pn[role] = (
                        [fid_map[source[0]], source[1]]
                        if source and source[0] in fid_map else None
                    )
                panes.append(pn)
            v["panes"] = panes
            views.append(v)
        out[section] = {"active": int(block.get("active", 0)), "views": views}
    return out
