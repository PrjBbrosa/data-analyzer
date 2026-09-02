"""JSON serialization for TraceLab project sessions (.tlproj).

Reference-only: stores file *paths* (+ per-file fs/time_source overrides) and
the full View list — never parsed data. Mirrors ``batch_preset_io.py``'s
versioned save/load shape. Pure (no Qt, no MainWindow) so it round-trips
through tests without a running app.

Canonical dirty digest (Task 5A) hashes :func:`project_document_to_payload`,
the same object :func:`save_project_to_json` writes. Do not maintain a
parallel "approximate" serializer for close/replace review.

Field inventory
---------------
Stable top-level keys (exactly :data:`PROJECT_PAYLOAD_KEYS`):

* ``schema_version`` — codec version (currently 3); not user content.
* ``active_file`` — navigator active fid.
* ``current_mode`` — persisted chart mode (``time`` / analysis sections;
  UltraView is not a source workspace and falls back to ``time`` on load).
* ``files`` — ``ProjectFileRef`` rows: ``fid``, ``path_abs``, ``path_rel``,
  ``fs``, ``time_source``, ``dbc_refs[{path_abs, path_rel}]``,
  ``channel_order`` (navigator order is semantic).
* ``views`` — TimeDomain ``ViewState.to_dict()`` rows (name, tab_color,
  view_id, attached_file_ids, checked, hidden_channels, colors, plot_mode,
  cursor_mode, xlim, ylims, overlay_primary, axis_opts, remarks,
  cursor_placement, curve_bindings, hidden_curve_binding_ids). Retired WWT
  display keys ``x_viewport_intent`` / ``native_ticks`` are stripped.
* ``view_manager`` — ``{active, split_pairs}``.
* ``analysis_views`` — per section ``{active, views: AnalysisViewState.to_dict()}``
  (schema, name, tab_color, view_id, attached_file_ids, panes, params,
  compare). Pane rows persist sources / rpm / FRF io / time_range / xlim /
  ylim / ylims / effective_time_range / cursor_mode / remarks /
  cursor_placement. ``PaneState.source_time_view_id`` is **not** written.
* ``filter`` — Inspector filter panel: ``enabled``, ``spec`` (FilterSpec),
  ``show_original``, ``show_filtered``. Absent in schema v1.
* ``ultraview`` — ``workspace_to_payload`` Board/workspace blob (schema,
  workspace.{active_board_id, show_card_actions, boards}, optional
  ``preview_sidecar`` descriptor). Preview **pixels** live in a sidecar
  file, not this JSON.

Runtime-only (never in the payload; must not mark dirty): selection, focus,
hover, popup, render/envelope cache, analysis numeric results, job progress,
toast, QWidget/QImage objects, restore/open guards, UltraView presentation
digest / captured preview buffers. User preferences (QSettings) are also
outside ``.tlproj``.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
import tempfile

from .time_xaxis import CustomXAxisSpec, EXACT_SOURCE, PER_SOURCE_NAME
from .view_overlay_state import remap_remarks

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}
_SOURCE_MODES = frozenset({"time", "fft", "fft_time", "frf", "order"})

# Top-level keys of the object ``save_project_to_json`` writes. List order
# here is documentation; digest canonicalization sorts dict keys.
PROJECT_PAYLOAD_KEYS = (
    "schema_version",
    "active_file",
    "current_mode",
    "files",
    "views",
    "view_manager",
    "analysis_views",
    "filter",
    "ultraview",
)

# Keys that are session/runtime and must never appear in the canonical
# payload (top-level or nested). ``filter`` is a stable top-level project
# field; it is intentionally absent from this set.
PROJECT_RUNTIME_ONLY_KEYS = frozenset({
    "selection",
    "selected",
    "focus",
    "hover",
    "popup",
    "render_cache",
    "envelope_cache",
    "job_progress",
    "toast",
    "preview_pixels",
    "qwidget",
    "qimage",
    "image",
    "presentation",
    "captured_digest",
    "runtime",
    "lru",
    "restore_pending",
    "opening_project",
    "restoring_project",
    "snapshot",
    "left_snapshot",
    "inspector_snapshot",
})


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
    channel_order: list[str] = field(default_factory=list)


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
    ultraview: dict | None = None


def project_document_to_payload(doc: ProjectDocument) -> dict:
    """Qt-free JSON object written by :func:`save_project_to_json`.

    This is the canonical persistable snapshot. Dirty digest and close/replace
    review must hash this object, not a second hand-built mapping.
    """
    return {
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
                "channel_order": [
                    str(name) for name in (getattr(r, "channel_order", None) or [])
                    if str(name).strip()
                ],
            }
            for r in doc.files
        ],
        "views": [_retire_view_display_fields(view) for view in doc.views],
        "view_manager": doc.view_manager,
        "analysis_views": doc.analysis_views,
        "filter": doc.filter,
        "ultraview": doc.ultraview,
    }


def canonical_project_digest(source) -> str:
    """SHA-256 of the save-path payload with dict keys sorted.

    List order is semantic (file / View / channel order) and is preserved.
    ``source`` is a :class:`ProjectDocument` or an already-built payload dict.
    """
    if isinstance(source, ProjectDocument):
        payload = project_document_to_payload(source)
    elif isinstance(source, dict):
        payload = source
    else:
        raise TypeError(
            f"canonical digest expects ProjectDocument or dict, "
            f"not {type(source).__name__}"
        )
    blob = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def save_project_to_json(doc: ProjectDocument, path) -> None:
    path = Path(path)
    payload = project_document_to_payload(doc)
    _write_text_atomic(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )


def _write_text_atomic(path: Path, text: str) -> None:
    """Replace one project document only after its complete sibling is durable.

    ``.tlproj`` is the authoritative session state.  UltraView's optional
    preview sidecar can therefore safely be published before this call: an
    interrupted project save leaves an unreferenced sidecar generation, never
    a partially-written JSON document that points to it.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.stem}.",
        suffix=f"{target.suffix}.tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


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
            channel_order=[
                str(name).strip()
                for name in (f.get("channel_order") or [])
                if str(name).strip()
            ],
        )
        for f in raw.get("files", [])
    ]
    mode = str(raw.get("current_mode", "time"))
    if mode not in _SOURCE_MODES:
        mode = "time"
    uv_payload = raw.get("ultraview")
    if uv_payload is not None and not isinstance(uv_payload, dict):
        uv_payload = None
    return ProjectDocument(
        active_file=raw.get("active_file"),
        current_mode=mode,
        files=files,
        views=[
            _retire_view_display_fields(view)
            for view in raw.get("views", [])
        ],
        view_manager=dict(raw.get("view_manager", {})),
        analysis_views=dict(raw.get("analysis_views", {})),
        filter=raw.get("filter") if version >= 2 else None,
        ultraview=uv_payload,
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


def _retire_view_display_fields(view):
    """Drop retired WWT display policy from a serialized Time View payload."""
    if not isinstance(view, dict):
        return view
    result = dict(view)
    result.pop("x_viewport_intent", None)
    axis = result.get("axis_opts")
    if not isinstance(axis, dict):
        return result
    axis = dict(axis)
    axis.pop("native_ticks", None)
    axis.pop("x_viewport_intent", None)
    result["axis_opts"] = axis
    return result


def _remap_channel_axis_groups(value, fid_map: dict) -> dict[str, str]:
    """Remap valid persisted channel-axis memberships, dropping stale fids."""
    if not isinstance(value, dict):
        return {}
    groups: dict[str, str] = {}
    for raw_key, raw_axis_id in value.items():
        if not isinstance(raw_key, str):
            continue
        try:
            key = json.loads(raw_key)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(key, (list, tuple)) or len(key) != 2:
            continue
        old_fid = str(key[0] or "").strip()
        channel = str(key[1] or "").strip()
        axis_id = str(raw_axis_id or "").strip()
        if not old_fid or not channel or not axis_id or old_fid not in fid_map:
            continue
        groups[_encode_channel_key(fid_map[old_fid], channel)] = axis_id
    return groups


def remap_view_fids(views: list, fid_map: dict) -> list:
    """Rewrite the fid of every channel reference in a list of
    ``ViewState.to_dict()`` payloads, dropping references whose fid is absent
    from ``fid_map`` (the file went missing on load)."""
    out = []
    for view in views:
        v = _retire_view_display_fields(view)

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

        # ylims keys are the same composite encoding as colors
        # (``_view_state_channel_key`` / ``json.dumps([fid, name])``). Older
        # projects may omit the field entirely — treat that as empty.
        new_ylims = {}
        for key, ylim in (view.get("ylims") or {}).items():
            try:
                decoded = json.loads(key)
            except (TypeError, ValueError, json.JSONDecodeError):
                # Legacy display-name keys: keep as-is so restore can still
                # match ``legacy_lines.get(name)`` on the canvas.
                new_ylims[key] = ylim
                continue
            if not (isinstance(decoded, (list, tuple)) and len(decoded) == 2):
                new_ylims[key] = ylim
                continue
            fid, ch = decoded
            if fid in fid_map:
                new_ylims[_encode_channel_key(fid_map[fid], ch)] = ylim
        v["ylims"] = new_ylims

        op = view.get("overlay_primary")
        v["overlay_primary"] = (
            [fid_map[op[0]], op[1]] if op and op[0] in fid_map else None
        )

        axis = dict(v.get("axis_opts") or {})
        channel_axis_groups = _remap_channel_axis_groups(
            axis.get("channel_axis_groups"), fid_map,
        )
        if channel_axis_groups:
            axis["channel_axis_groups"] = channel_axis_groups
        else:
            axis.pop("channel_axis_groups", None)
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

        v["remarks"] = remap_remarks(view.get("remarks"), fid_map)
        # cursor_placement has no fid; keep the payload as copied above.

        from .time_curve_bindings import (
            prune_hidden_curve_binding_ids,
            remap_curve_bindings,
        )
        bindings = remap_curve_bindings(
            view.get("curve_bindings") or [], fid_map
        )
        v["curve_bindings"] = [
            binding.to_dict()
            for binding in bindings
        ]
        v["hidden_curve_binding_ids"] = prune_hidden_curve_binding_ids(
            view.get("hidden_curve_binding_ids"), bindings,
        )

        out.append(v)
    return out


def remap_analysis_view_fids(analysis_views: dict, fid_map: dict) -> dict:
    """Rewrite fids inside analysis_views payloads; drop refs whose fid
    is absent from ``fid_map`` (same contract as remap_view_fids).

    Schema 7 ``attached_file_ids`` are remapped in order. Older payloads
    without the field derive attachments from remapped pane roles only —
    never from the full project file set.
    """
    from .analysis_view_state import (
        analysis_view_source_fids,
        normalize_analysis_attachments,
    )

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
                pn["remarks"] = remap_remarks(pane.get("remarks"), fid_map)
                panes.append(pn)
            v["panes"] = panes
            if "attached_file_ids" in view:
                v["attached_file_ids"] = normalize_analysis_attachments(
                    fid_map[fid]
                    for fid in view.get("attached_file_ids", [])
                    if fid in fid_map
                )
            else:
                v["attached_file_ids"] = analysis_view_source_fids(v)
            views.append(v)
        out[section] = {"active": int(block.get("active", 0)), "views": views}
    return out


def collect_dropped_analysis_refs(analysis_views: dict, fid_map: dict) -> list[tuple]:
    """Pane roles whose source fid is absent from ``fid_map`` after restore.

    Returns ``(section, view_id, pane_idx, role)`` tuples. Roles are
    ``signal`` (overlay sources), ``rpm``, ``input``, and ``output``.
    """
    dropped: list[tuple] = []
    for section, block in (analysis_views or {}).items():
        for view in block.get("views", []) or []:
            view_id = str(view.get("view_id") or view.get("name") or "")
            for pane_idx, pane in enumerate(view.get("panes", []) or []):
                for source in pane.get("sources", []) or []:
                    if (
                        isinstance(source, (list, tuple))
                        and len(source) >= 1
                        and source[0] not in fid_map
                    ):
                        dropped.append((section, view_id, pane_idx, "signal"))
                rpm = pane.get("rpm_source")
                if (
                    isinstance(rpm, (list, tuple))
                    and len(rpm) >= 1
                    and rpm[0] not in fid_map
                ):
                    dropped.append((section, view_id, pane_idx, "rpm"))
                for field_name, role in (
                    ("input_source", "input"),
                    ("output_source", "output"),
                ):
                    source = pane.get(field_name)
                    if (
                        isinstance(source, (list, tuple))
                        and len(source) >= 1
                        and source[0] not in fid_map
                    ):
                        dropped.append((section, view_id, pane_idx, role))
    return dropped


def collect_dropped_time_refs(views: list, fid_map: dict) -> list[tuple]:
    """Time-View channel refs whose fid is absent from ``fid_map``.

    Returns ``(view_id_or_name, fid, channel)`` tuples from ``checked``.
    """
    dropped: list[tuple] = []
    for view in views or []:
        view_id = str(view.get("view_id") or view.get("name") or "")
        for item in view.get("checked", []) or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            fid, channel = item[0], item[1]
            if fid not in fid_map:
                dropped.append((view_id, fid, channel))
        from .time_curve_bindings import collect_dropped_binding_refs
        dropped.extend(
            collect_dropped_binding_refs(
                view.get("curve_bindings") or [], fid_map, view_id=view_id
            )
        )
    return dropped
