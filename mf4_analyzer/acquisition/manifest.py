from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


VALID_PATH_KINDS = ("local", "lfs", "external")
_VALID_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, kw_only=True)
class Mf4DatasetEntry:
    id: str
    path: str
    sets: tuple[str, ...]
    path_kind: str = "local"
    vehicle: str = ""
    platform: str = ""
    scenario: str = ""
    issue_tags: tuple[str, ...] = ()
    expected_channels: tuple[str, ...] = ()
    sha256: str | None = None
    required: bool = True


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tuple(raw, field_name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{field_name} must be a list")
    return tuple(str(item) for item in raw)


def _entry(raw: dict) -> Mf4DatasetEntry:
    entry_id = str(raw.get("id", "")).strip()
    if not entry_id:
        raise ValueError("entry id is required")
    if not _VALID_ID.match(entry_id):
        raise ValueError(
            f"entry id {entry_id!r} contains invalid characters "
            f"(allowed: alphanumeric, dash, underscore)"
        )
    path = str(raw.get("path", "")).strip()
    if not path:
        raise ValueError(f"{entry_id}: path is required")
    sets = _tuple(raw.get("sets"), f"{entry_id}.sets")
    if not sets:
        raise ValueError(f"{entry_id}: at least one set is required")
    path_kind = str(raw.get("path_kind", "local"))
    if path_kind not in VALID_PATH_KINDS:
        raise ValueError(
            f"{entry_id}: path_kind {path_kind!r} not in {VALID_PATH_KINDS}"
        )
    sha256_raw = raw.get("sha256")
    sha256 = str(sha256_raw) if sha256_raw else None
    required = bool(raw.get("required", True))
    if required and path_kind in ("local", "lfs") and not sha256:
        raise ValueError(
            f"{entry_id}: sha256 is required for required={required} "
            f"path_kind={path_kind!r} entries"
        )
    return Mf4DatasetEntry(
        id=entry_id,
        path=path,
        path_kind=path_kind,
        sets=sets,
        vehicle=str(raw.get("vehicle", "") or ""),
        platform=str(raw.get("platform", "") or ""),
        scenario=str(raw.get("scenario", "") or ""),
        issue_tags=_tuple(raw.get("issue_tags", []), f"{entry_id}.issue_tags"),
        expected_channels=_tuple(
            raw.get("expected_channels", []), f"{entry_id}.expected_channels"
        ),
        sha256=sha256,
        required=required,
    )


def load_manifest(path: str | Path) -> list[Mf4DatasetEntry]:
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"manifest must be a JSON object, got {type(raw).__name__}")
    if raw.get("version") != 1:
        raise ValueError(f"unsupported manifest version: {raw.get('version')!r}")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    return [_entry(item) for item in entries]


def select_entries(
    entries: Iterable[Mf4DatasetEntry], dataset: str
) -> list[Mf4DatasetEntry]:
    return [entry for entry in entries if dataset in entry.sets]


def resolve_entry_path(
    entry: Mf4DatasetEntry, *, manifest_path: str | Path
) -> Path:
    p = Path(entry.path)
    if p.is_absolute():
        return p.resolve()
    return (Path(manifest_path).resolve().parent / p).resolve()
