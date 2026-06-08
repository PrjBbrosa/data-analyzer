"""JSON serialization for TraceLab project sessions (.tlproj).

Reference-only: stores file *paths* (+ per-file fs/time_source overrides) and
the full View list — never parsed data. Mirrors ``batch_preset_io.py``'s
versioned save/load shape. Pure (no Qt, no MainWindow) so it round-trips
through tests without a running app.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


class UnsupportedProjectVersion(ValueError):
    """Raised when reading a .tlproj whose schema_version is unknown."""


@dataclass
class ProjectFileRef:
    fid: str
    path_abs: str
    path_rel: str | None
    fs: float
    time_source: str


@dataclass
class ProjectDocument:
    active_file: str | None
    current_mode: str
    files: list = field(default_factory=list)        # list[ProjectFileRef]
    views: list = field(default_factory=list)         # list[dict] (ViewState.to_dict)
    view_manager: dict = field(default_factory=dict)  # {"active": int, "split_pairs": {}}


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
            }
            for r in doc.files
        ],
        "views": doc.views,
        "view_manager": doc.view_manager,
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
    if version != SCHEMA_VERSION:
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
        )
        for f in raw.get("files", [])
    ]
    return ProjectDocument(
        active_file=raw.get("active_file"),
        current_mode=str(raw.get("current_mode", "time")),
        files=files,
        views=list(raw.get("views", [])),
        view_manager=dict(raw.get("view_manager", {})),
    )


def make_relative(path_abs: str, project_path) -> str | None:
    """Path of ``path_abs`` relative to the .tlproj dir; None across drives."""
    try:
        return os.path.relpath(path_abs, Path(project_path).parent)
    except ValueError:
        return None
