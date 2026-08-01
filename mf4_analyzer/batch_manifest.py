"""Versioned, atomic run manifests for GUI-free batch execution."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import uuid

import numpy as np

from .app_meta import APP_VERSION
from .batch_output import atomic_write


SCHEMA_VERSION = 1
TERMINAL_TASK_STATUSES = (
    "done", "failed", "cancelled", "skipped", "resumed",
)
RENDER_GROUP_STATUSES = (
    "pending", "running", "done", "partial", "failed", "blocked",
    "cancelled", "degraded", "skipped",
)


class ManifestRecipeMismatch(ValueError):
    """A retry manifest belongs to a different normalized compute recipe."""


class ManifestValidationError(ValueError):
    """A manifest field is missing, malformed, or internally inconsistent."""

    def __init__(self, field: str, message: str) -> None:
        self.field = str(field)
        super().__init__(f"manifest.{self.field}: {message}")


@dataclass(frozen=True)
class GroupMemberResumeFact:
    task_id: str
    source: Mapping[str, Any]


@dataclass(frozen=True)
class RetryScope:
    task_keys: frozenset[tuple[object, str, str]]
    group_ids: frozenset[str]

    def __bool__(self) -> bool:
        return bool(self.task_keys or self.group_ids)

    def __contains__(self, task_key) -> bool:
        return task_key in self.task_keys

    def __iter__(self):
        return iter(self.task_keys)

    def __len__(self) -> int:
        return len(self.task_keys)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _json_safe(value):
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            label = "nan"
        elif value > 0:
            label = "+inf"
        else:
            label = "-inf"
        return {"__nonfinite_float__": label}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def sha256_file(path, *, cancel_token=None, chunk_size: int = 1024 * 1024):
    """Stream a file checksum; return ``None`` if cancellation is requested."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            if cancel_token is not None and cancel_token.is_set():
                return None
            chunk = stream.read(chunk_size)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def source_file_facts(path, *, source_identity: str) -> dict:
    """Capture source identity plus available filesystem change detectors."""

    facts = {
        "identity": str(source_identity),
        "path": None,
        "size": None,
        "mtime_ns": None,
    }
    if path in (None, ""):
        return facts
    source_path = Path(path).expanduser().resolve(strict=False)
    facts["path"] = str(source_path)
    try:
        stat = source_path.stat()
    except OSError:
        return facts
    facts["size"] = int(stat.st_size)
    facts["mtime_ns"] = int(stat.st_mtime_ns)
    return facts


def artifact_facts(
    path,
    *,
    kind: str,
    artifact_format: str,
    width: int | None = None,
    height: int | None = None,
    dpi: int | None = None,
    cancel_token=None,
) -> dict:
    """Return size/checksum facts for one successfully published artifact."""

    artifact_path = Path(path).expanduser().resolve(strict=False)
    stat = artifact_path.stat()
    checksum = sha256_file(artifact_path, cancel_token=cancel_token)
    facts = {
        "kind": str(kind),
        "path": str(artifact_path),
        "format": str(artifact_format).strip().lower().lstrip("."),
        "size": int(stat.st_size),
        "sha256": checksum,
        "checksum_status": "complete" if checksum is not None else "cancelled",
    }
    if width is not None:
        facts["width"] = int(width)
    if height is not None:
        facts["height"] = int(height)
    if dpi is not None:
        facts["dpi"] = int(dpi)
    return facts


def derive_summary(entries) -> dict[str, int]:
    counts = {status: 0 for status in TERMINAL_TASK_STATUSES}
    total = 0
    for entry in entries:
        status = str((entry or {}).get("status", ""))
        if status not in counts:
            continue
        counts[status] += 1
        total += 1
    counts["total"] = total
    return counts


def _write_json_atomic(path: Path, payload: Mapping, *, overwrite: bool) -> Path:
    encoded = json.dumps(
        _json_safe(payload),
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    )
    return atomic_write(
        path,
        lambda temp: temp.write_text(encoded, encoding="utf-8"),
        overwrite=overwrite,
    )


class BatchManifestRecorder:
    """Append task facts to an atomic partial journal and terminal manifest."""

    def __init__(
        self,
        output_dir,
        *,
        preset_name: str,
        normalized_recipe: Mapping,
        recipe_fingerprint: str,
        requested_outputs: Mapping,
        app_version: str = APP_VERSION,
        run_id: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + "_"
            + uuid.uuid4().hex[:8]
        )
        self.final_path = self.output_dir / f"batch-manifest__{self.run_id}.json"
        self.partial_path = (
            self.output_dir / f"batch-manifest__{self.run_id}.partial.json"
        )
        if self.final_path.exists() or self.partial_path.exists():
            raise FileExistsError(f"batch manifest run_id already exists: {self.run_id}")
        self._created_at = utc_now()
        self._preset_name = str(preset_name)
        self._normalized_recipe = _json_safe(normalized_recipe)
        self._recipe_fingerprint = str(recipe_fingerprint)
        self._requested_outputs = _json_safe(requested_outputs)
        self._app_version = str(app_version)
        self._entries: dict[str, dict] = {}
        self._render_groups: dict[str, dict] = {}
        self._started = False
        self._finished = False

    @property
    def entries(self) -> tuple[dict, ...]:
        return tuple(self._entries.values())

    @property
    def render_groups(self) -> tuple[dict, ...]:
        return tuple(self._render_groups.values())

    def _payload(
        self,
        *,
        run_status: str,
        blocked_reasons=(),
        finished_at: str | None = None,
    ) -> dict:
        entries = list(self._entries.values())
        payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_at": self._created_at,
            "finished_at": finished_at,
            "app_version": self._app_version,
            "preset_name": self._preset_name,
            "normalized_recipe": self._normalized_recipe,
            "recipe_fingerprint": self._recipe_fingerprint,
            "requested_output_settings": self._requested_outputs,
            "summary": derive_summary(entries),
            "run_status": str(run_status),
            "blocked_reasons": [str(reason) for reason in blocked_reasons],
            "entries": entries,
        }
        if self._render_groups:
            payload["render_groups"] = list(self._render_groups.values())
        return payload

    def start(self) -> Path:
        if self._finished:
            raise RuntimeError("batch manifest is already terminal")
        self._started = True
        return _write_json_atomic(
            self.partial_path,
            self._payload(run_status="running"),
            overwrite=self.partial_path.exists(),
        )

    def upsert_task(self, entry: Mapping) -> Path:
        if self._finished:
            raise RuntimeError("batch manifest is already terminal")
        if not self._started:
            self.start()
        safe_entry = _json_safe(entry)
        task_id = safe_entry.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("manifest task entry requires a non-empty task_id")
        self._entries[task_id] = safe_entry
        return _write_json_atomic(
            self.partial_path,
            self._payload(run_status="running"),
            overwrite=True,
        )

    record = upsert_task

    def upsert_render_group(self, group: Mapping) -> Path:
        if self._finished:
            raise RuntimeError("batch manifest is already terminal")
        if not self._started:
            self.start()
        safe_group = _json_safe(group)
        group_id = safe_group.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("manifest render group requires a non-empty group_id")
        self._render_groups[group_id] = safe_group
        return _write_json_atomic(
            self.partial_path,
            self._payload(run_status="running"),
            overwrite=True,
        )

    def finish(self, *, run_status: str, blocked_reasons=()) -> Path:
        if self._finished:
            return self.final_path
        if not self._started:
            self.start()
        payload = self._payload(
            run_status=run_status,
            blocked_reasons=blocked_reasons,
            finished_at=utc_now(),
        )
        _write_json_atomic(self.final_path, payload, overwrite=False)
        self.partial_path.unlink(missing_ok=True)
        self._finished = True
        return self.final_path


def load_batch_manifest(path_or_manifest) -> dict:
    if isinstance(path_or_manifest, Mapping):
        raw = dict(path_or_manifest)
    else:
        path = Path(path_or_manifest)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestValidationError("json", str(exc)) from exc
    if not isinstance(raw, dict):
        raise ManifestValidationError("$", "must be a JSON object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ManifestValidationError(
            "schema_version",
            f"value {raw.get('schema_version')!r} is not supported",
        )
    required_top_fields = (
        "run_id",
        "created_at",
        "finished_at",
        "app_version",
        "preset_name",
        "normalized_recipe",
        "recipe_fingerprint",
        "requested_output_settings",
        "summary",
        "run_status",
        "blocked_reasons",
        "entries",
    )
    for field in required_top_fields:
        if field not in raw:
            raise ManifestValidationError(field, "required field is missing")

    for field in ("run_id", "created_at", "app_version", "preset_name"):
        if not isinstance(raw[field], str) or not raw[field]:
            raise ManifestValidationError(field, "must be a non-empty string")
    if not isinstance(raw["recipe_fingerprint"], str) or not raw["recipe_fingerprint"]:
        raise ManifestValidationError(
            "recipe_fingerprint", "must be a non-empty string",
        )
    for field in ("normalized_recipe", "requested_output_settings", "summary"):
        if not isinstance(raw[field], Mapping):
            raise ManifestValidationError(field, "must be an object")
    if not isinstance(raw["blocked_reasons"], list) or not all(
        isinstance(reason, str) for reason in raw["blocked_reasons"]
    ):
        raise ManifestValidationError(
            "blocked_reasons", "must be an array of strings",
        )

    run_status = raw["run_status"]
    if run_status not in {"running", "done", "partial", "blocked", "cancelled"}:
        raise ManifestValidationError(
            "run_status", "must be running, done, partial, blocked, or cancelled",
        )
    if run_status == "running":
        if raw["finished_at"] is not None:
            raise ManifestValidationError(
                "finished_at", "must be null while run_status is running",
            )
    elif not isinstance(raw["finished_at"], str) or not raw["finished_at"]:
        raise ManifestValidationError(
            "finished_at", "must be a terminal timestamp",
        )

    entries = raw["entries"]
    if not isinstance(entries, list):
        raise ManifestValidationError("entries", "must be an array")
    required_entry_fields = (
        "task_id",
        "source_id",
        "source",
        "channel",
        "channel_unit",
        "method",
        "requested_params",
        "effective_facts",
        "status",
        "message",
        "warnings",
        "started_at",
        "finished_at",
        "artifacts",
    )
    for index, entry in enumerate(entries):
        prefix = f"entries.{index}"
        if not isinstance(entry, Mapping):
            raise ManifestValidationError(prefix, "must be an object")
        for field in required_entry_fields:
            if field not in entry:
                raise ManifestValidationError(
                    f"{prefix}.{field}", "required field is missing",
                )
        if entry["status"] not in TERMINAL_TASK_STATUSES:
            raise ManifestValidationError(
                f"{prefix}.status",
                "must be done, failed, cancelled, skipped, or resumed",
            )
        for field in ("source", "requested_params", "effective_facts", "artifacts"):
            if not isinstance(entry[field], Mapping):
                raise ManifestValidationError(
                    f"{prefix}.{field}", "must be an object",
                )
        for field in ("requested_outputs", "effective_outputs"):
            if field in entry and not isinstance(entry[field], Mapping):
                raise ManifestValidationError(
                    f"{prefix}.{field}", "must be an object",
                )
        if "degraded_reason" in entry and not isinstance(
            entry["degraded_reason"], str
        ):
            raise ManifestValidationError(
                f"{prefix}.degraded_reason", "must be a string",
            )
        if not isinstance(entry["task_id"], str) or not entry["task_id"]:
            raise ManifestValidationError(
                f"{prefix}.task_id", "must be a non-empty string",
            )
        if not isinstance(entry["source"].get("identity"), str) or not entry[
            "source"
        ].get("identity"):
            raise ManifestValidationError(
                f"{prefix}.source.identity", "must be a non-empty string",
            )
        for artifact_name, artifact in entry["artifacts"].items():
            if not isinstance(artifact, Mapping):
                raise ManifestValidationError(
                    f"{prefix}.artifacts.{artifact_name}",
                    "must be an object",
                )
        if not isinstance(entry["warnings"], list) or not all(
            isinstance(warning, str) for warning in entry["warnings"]
        ):
            raise ManifestValidationError(
                f"{prefix}.warnings", "must be an array of strings",
            )

    render_groups = raw.get("render_groups", [])
    if not isinstance(render_groups, list):
        raise ManifestValidationError("render_groups", "must be an array")
    seen_group_ids: set[str] = set()
    required_group_fields = (
        "group_id",
        "stem",
        "group_by",
        "layout",
        "members",
        "requested_outputs",
        "effective_outputs",
        "degraded_reason",
        "status",
        "message",
        "warnings",
        "artifact",
    )
    for index, group in enumerate(render_groups):
        prefix = f"render_groups.{index}"
        if not isinstance(group, Mapping):
            raise ManifestValidationError(prefix, "must be an object")
        for field in required_group_fields:
            if field not in group:
                raise ManifestValidationError(
                    f"{prefix}.{field}", "required field is missing",
                )
        group_id = group["group_id"]
        if not isinstance(group_id, str) or not group_id:
            raise ManifestValidationError(
                f"{prefix}.group_id", "must be a non-empty string",
            )
        if group_id in seen_group_ids:
            raise ManifestValidationError(
                f"{prefix}.group_id", "must be unique",
            )
        seen_group_ids.add(group_id)
        if not isinstance(group["stem"], str) or not group["stem"]:
            raise ManifestValidationError(
                f"{prefix}.stem", "must be a non-empty string",
            )
        if group["group_by"] not in {"source", "channel"}:
            raise ManifestValidationError(
                f"{prefix}.group_by", "must be source or channel",
            )
        if group["layout"] not in {"overlay", "subplot"}:
            raise ManifestValidationError(
                f"{prefix}.layout", "must be overlay or subplot",
            )
        if group["status"] not in RENDER_GROUP_STATUSES:
            raise ManifestValidationError(
                f"{prefix}.status", "is not a supported render group status",
            )
        for field in ("degraded_reason", "message"):
            if not isinstance(group[field], str):
                raise ManifestValidationError(
                    f"{prefix}.{field}", "must be a string",
                )
        for field in ("requested_outputs", "effective_outputs"):
            if not isinstance(group[field], Mapping):
                raise ManifestValidationError(
                    f"{prefix}.{field}", "must be an object",
                )
        if not isinstance(group["warnings"], list) or not all(
            isinstance(warning, str) for warning in group["warnings"]
        ):
            raise ManifestValidationError(
                f"{prefix}.warnings", "must be an array of strings",
            )
        if group["artifact"] is not None and not isinstance(
            group["artifact"], Mapping
        ):
            raise ManifestValidationError(
                f"{prefix}.artifact", "must be an object or null",
            )
        members = group["members"]
        if not isinstance(members, list) or not members:
            raise ManifestValidationError(
                f"{prefix}.members", "must be a non-empty array",
            )
        for member_index, member in enumerate(members):
            member_prefix = f"{prefix}.members.{member_index}"
            if not isinstance(member, Mapping):
                raise ManifestValidationError(member_prefix, "must be an object")
            task_id = member.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise ManifestValidationError(
                    f"{member_prefix}.task_id", "must be a non-empty string",
                )
            source = member.get("source")
            if not isinstance(source, Mapping):
                raise ManifestValidationError(
                    f"{member_prefix}.source", "must be an object",
                )
            for source_field in ("identity", "size", "mtime_ns"):
                if source_field not in source:
                    raise ManifestValidationError(
                        f"{member_prefix}.source.{source_field}",
                        "required field is missing",
                    )
            if not isinstance(source["identity"], str) or not source["identity"]:
                raise ManifestValidationError(
                    f"{member_prefix}.source.identity",
                    "must be a non-empty string",
                )
            for source_field in ("size", "mtime_ns"):
                value = source[source_field]
                if value is not None and (
                    not isinstance(value, int) or isinstance(value, bool)
                ):
                    raise ManifestValidationError(
                        f"{member_prefix}.source.{source_field}",
                        "must be an integer or null",
                    )

    expected_summary = derive_summary(entries)
    if dict(raw["summary"]) != expected_summary:
        raise ManifestValidationError(
            "summary",
            f"does not match entries; expected {expected_summary!r}",
        )
    return raw


def _source_stat_matches(previous: Mapping, current: Mapping) -> bool:
    for key in ("size", "mtime_ns"):
        prior_value = previous.get(key)
        if prior_value is None:
            continue
        if current.get(key) != prior_value:
            return False
    return True


def _artifact_matches(
    facts: Mapping,
    expected_format: str,
    *,
    cancel_token=None,
) -> bool:
    if str(facts.get("format", "")).lower() != str(expected_format).lower():
        return False
    if facts.get("checksum_status") != "complete":
        return False
    path_value = facts.get("path")
    checksum = facts.get("sha256")
    expected_size = facts.get("size")
    if not path_value or not checksum or expected_size is None:
        return False
    path = Path(path_value)
    try:
        if path.stat().st_size != int(expected_size):
            return False
        actual_checksum = sha256_file(path, cancel_token=cancel_token)
        return actual_checksum is not None and actual_checksum == str(checksum)
    except (OSError, TypeError, ValueError):
        return False


def find_resumable_entry(
    manifest,
    *,
    recipe_fingerprint: str,
    task_id: str,
    source_id,
    source_identity: str,
    source_stat: Mapping,
    required_artifacts: Mapping[str, str],
    cancel_token=None,
):
    """Return a checksum-proven done entry, otherwise fail closed with None."""

    raw = load_batch_manifest(manifest)
    if raw.get("recipe_fingerprint") != recipe_fingerprint:
        return None
    for entry in raw.get("entries", []):
        if cancel_token is not None and cancel_token.is_set():
            return None
        if entry.get("status") not in {"done", "resumed"}:
            continue
        if entry.get("degraded_reason"):
            continue
        if entry.get("task_id") != task_id:
            continue
        if entry.get("source_id") != source_id:
            continue
        source = entry.get("source") or {}
        if source.get("identity") != source_identity:
            continue
        if not _source_stat_matches(source, source_stat):
            continue
        artifacts = entry.get("artifacts") or {}
        if not all(
            kind in artifacts and _artifact_matches(
                artifacts[kind], fmt, cancel_token=cancel_token,
            )
            for kind, fmt in required_artifacts.items()
        ):
            continue
        return entry
    return None


def find_resumable_group(
    manifest: Mapping[str, Any],
    *,
    recipe_fingerprint: str,
    group_id: str,
    members: Sequence[GroupMemberResumeFact],
    image_format: str,
    cancel_token=None,
) -> Mapping[str, Any] | None:
    """Return a checksum-proven complete render group, otherwise ``None``."""

    raw = load_batch_manifest(manifest)
    if raw.get("recipe_fingerprint") != recipe_fingerprint:
        return None
    expected_format = str(image_format).strip().lower().lstrip(".")
    for group in raw.get("render_groups", []):
        if cancel_token is not None and cancel_token.is_set():
            return None
        if group.get("group_id") != group_id:
            continue
        if group.get("status") != "done" or group.get("degraded_reason"):
            return None
        recorded_members = group.get("members") or []
        if len(recorded_members) != len(members):
            return None
        for recorded, current in zip(recorded_members, members):
            if cancel_token is not None and cancel_token.is_set():
                return None
            if recorded.get("task_id") != current.task_id:
                return None
            previous_source = recorded.get("source") or {}
            if any(
                key not in previous_source
                for key in ("identity", "size", "mtime_ns")
            ):
                return None
            if any(
                previous_source.get(key) != current.source.get(key)
                for key in ("identity", "size", "mtime_ns")
            ):
                return None
        requested = group.get("requested_outputs") or {}
        effective = group.get("effective_outputs") or {}
        if str(requested.get("image", "")).lower().lstrip(".") != expected_format:
            return None
        if str(effective.get("image", "")).lower().lstrip(".") != expected_format:
            return None
        artifact = group.get("artifact")
        if not isinstance(artifact, Mapping) or artifact.get("kind") != "image":
            return None
        if not _artifact_matches(
            artifact, expected_format, cancel_token=cancel_token,
        ):
            return None
        if cancel_token is not None and cancel_token.is_set():
            return None
        return group
    return None


def retry_failed_scope(
    manifest, *, recipe_fingerprint: str
) -> RetryScope:
    raw = load_batch_manifest(manifest)
    if raw.get("recipe_fingerprint") != recipe_fingerprint:
        raise ManifestRecipeMismatch(
            "retry manifest recipe fingerprint does not match current recipe"
        )
    failed_entries = [
        entry for entry in raw.get("entries", [])
        if entry.get("status") in {"failed", "cancelled"}
    ]
    task_keys = frozenset(
        (entry.get("source_id"), entry.get("channel"), entry.get("method"))
        for entry in failed_entries
    )
    failed_task_ids = {entry.get("task_id") for entry in failed_entries}
    retry_group_statuses = {"failed", "partial", "blocked", "cancelled"}
    group_ids = frozenset(
        group["group_id"]
        for group in raw.get("render_groups", [])
        if group.get("status") in retry_group_statuses
        or any(
            member.get("task_id") in failed_task_ids
            for member in group.get("members", [])
        )
    )
    return RetryScope(task_keys=task_keys, group_ids=group_ids)


__all__ = [
    "BatchManifestRecorder",
    "GroupMemberResumeFact",
    "ManifestRecipeMismatch",
    "ManifestValidationError",
    "RENDER_GROUP_STATUSES",
    "RetryScope",
    "SCHEMA_VERSION",
    "TERMINAL_TASK_STATUSES",
    "artifact_facts",
    "derive_summary",
    "find_resumable_entry",
    "find_resumable_group",
    "load_batch_manifest",
    "retry_failed_scope",
    "sha256_file",
    "source_file_facts",
    "utc_now",
]
