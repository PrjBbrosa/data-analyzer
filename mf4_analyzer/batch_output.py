"""Stable batch output identity and same-directory atomic writes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid

import pandas as pd

from .batch_recipe import recipe_fingerprint


_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')
_REPEATED_SEPARATOR = re.compile(r"[\s_]+")

#: XLSX permits 1,048,576 rows including the column header. ``batch.py``
#: imports this by name into its own module namespace (rather than reading
#: this module's copy at call time) so
#: ``monkeypatch.setattr(mf4_analyzer.batch, "_XLSX_MAX_DATA_ROWS", ...)``
#: keeps working -- ``BatchRunner._write_dataframe`` / ``_write_workbook``
#: read that patched module global explicitly at call time and pass it in
#: (see the compatibility aliases at the bottom of ``batch.py``).
_XLSX_MAX_DATA_ROWS = 1_048_575

#: CSV cannot hold the two sheets a slice workbook needs, and
#: ``reserve_output_paths`` publishes exactly one file per extension, so
#: splitting into several csv files would break the write-set's atomicity.
#: Degrading to the historical long table costs nothing a csv reader had
#: before and keeps the run green (design D22).
_SLICE_CSV_FALLBACK_WARNING = (
    'slice.csv_fallback: 切片工作簿需要 xlsx 格式，当前数据格式为 CSV，'
    '本次数据文件仍为完整长表'
)

#: Group identity used when a source carries no label suffix or group metadata.
#: It is part of the hashed identity and must never change; it is only omitted
#: from human-readable filename stems.
DEFAULT_GROUP_IDENTITY = "default"


def unicode_slug(value, fallback: str = "default") -> str:
    """Keep readable Unicode while replacing filesystem-unsafe characters."""

    text = _UNSAFE_FILENAME.sub("_", str(value or ""))
    text = _REPEATED_SEPARATOR.sub("_", text).strip(" ._")
    return text or fallback


@dataclass(frozen=True)
class TaskOutputIdentity:
    task_id: str
    source_identity: str
    group_identity: str
    channel_identity: str
    stem: str


@dataclass(frozen=True)
class GroupOutputIdentity:
    group_id: str
    stem: str
    members: tuple[tuple[str, str, str], ...]


class OutputPublishRace(FileExistsError):
    """A non-cooperating writer published a final path after reservation."""


class OutputRollbackIncomplete(RuntimeError):
    """Rollback stopped rather than deleting or replacing an unknown owner."""


@dataclass(frozen=True)
class _FileOwnership:
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class ReservationTokenInfo:
    """Snapshot required for an explicit compare-before-release operation."""

    path: Path
    metadata: dict
    ownership: _FileOwnership | None


@dataclass
class OutputReservation:
    """One coordinated task basename held across every requested artifact."""

    paths: dict[str, Path]
    stem: str
    conflict_policy: str
    status: str = "reserved"
    warning: str = ""
    token_path: Path | None = None
    token_ownership: _FileOwnership | None = None
    before_publish: Callable[[], object] | None = None
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.token_path is not None and self.token_path.exists():
            if _is_owned_path(self.token_path, self.token_ownership):
                self.token_path.unlink()
            else:
                detail = "reservation token ownership changed; left untouched"
                self.warning = f"{self.warning}; {detail}" if self.warning else detail

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


def _source_identity(source, file_id) -> str:
    raw_path = getattr(source, "filepath", None)
    if raw_path not in (None, ""):
        return str(Path(raw_path).expanduser().resolve(strict=False))
    return f"file_id:{file_id!r}"


def _group_identity(source) -> str:
    suffix = str(getattr(source, "label_suffix", "") or "").strip()
    if suffix:
        return suffix
    metadata = getattr(source, "source_metadata", None)
    if isinstance(metadata, Mapping):
        for key in ("group_identity", "group_name", "group"):
            value = metadata.get(key)
            if value not in (None, ""):
                return str(value)
    return DEFAULT_GROUP_IDENTITY


def _group_stem_segments(group_identity) -> tuple[str, ...]:
    """Return the readable group segment, or nothing when it carries no info.

    Plain sources fall back to :data:`DEFAULT_GROUP_IDENTITY`, which every
    filename in the run would repeat without telling the reader anything.  The
    hashed identity keeps the fallback; only the stem drops it.
    """

    slug = unicode_slug(
        str(group_identity or "").strip(), DEFAULT_GROUP_IDENTITY,
    )
    if slug == DEFAULT_GROUP_IDENTITY:
        return ()
    return (slug,)


def build_task_output_identity(
    source,
    *,
    file_id,
    channel: str,
    method: str,
    params,
) -> TaskOutputIdentity:
    """Build the stable task hash and its readable filename stem."""

    source_identity = _source_identity(source, file_id)
    group_identity = _group_identity(source)
    channel_identity = str(channel)
    task_id = recipe_fingerprint(
        params,
        method,
        source_identity=source_identity,
        group_identity=group_identity,
        channel_identity=channel_identity,
    )
    source_stem = unicode_slug(Path(source_identity).stem, "source")
    stem = "__".join((
        source_stem,
        *_group_stem_segments(group_identity),
        unicode_slug(channel_identity, "channel"),
        unicode_slug(method, "method"),
        task_id[:8],
    ))
    return TaskOutputIdentity(
        task_id=task_id,
        source_identity=source_identity,
        group_identity=group_identity,
        channel_identity=channel_identity,
        stem=stem,
    )


def build_group_output_identity(
    members: Sequence[tuple[str, str, str]],
    *,
    method: str,
    params: Mapping[str, Any],
    group_by: str,
) -> GroupOutputIdentity:
    """Build an order-independent identity for one rendered member set."""

    normalized_members = tuple(sorted(
        (str(source), str(group), str(channel))
        for source, group, channel in members
    ))
    if not normalized_members:
        raise ValueError("render group requires at least one member")
    group_by = str(group_by or "").strip().lower()
    if group_by not in {"none", "source", "channel"}:
        raise ValueError(f"unsupported render grouping: {group_by!r}")
    group_id = recipe_fingerprint(
        params,
        method,
        group_identity={
            "group_by": group_by,
            "members": normalized_members,
        },
    )
    if group_by == "source":
        source_identity, group_identity, _channel = normalized_members[0]
        readable = (
            unicode_slug(Path(source_identity).stem, "source"),
            *_group_stem_segments(group_identity),
        )
    elif group_by == "channel":
        readable = (unicode_slug(normalized_members[0][2], "channel"),)
    else:
        readable = ("group",)
    # The grouping mode is constant for a whole run, so it is left out of the
    # stem; the group hash still separates differently grouped artifacts.
    stem = "__".join((
        *readable,
        unicode_slug(method, "method"),
        group_id[:8],
    ))
    return GroupOutputIdentity(
        group_id=group_id,
        stem=stem,
        members=normalized_members,
    )


def choose_output_paths(
    directory,
    stem: str,
    extensions: Iterable[str],
    *,
    collision_policy: str = "auto_number",
) -> dict[str, Path]:
    """Choose one coherent stem while preserving the Phase-1 mapping API.

    Execution code should use :func:`reserve_output_paths` and retain the
    returned token through publication.  This helper deliberately releases
    its short-lived reservation before returning and is therefore suitable
    for previews and compatibility callers, not race-safe publication.
    """

    reservation = reserve_output_paths(
        directory,
        stem,
        extensions,
        conflict_policy=collision_policy,
    )
    try:
        return dict(reservation.paths)
    finally:
        reservation.release()


def _normalized_extensions(extensions: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(str(ext).lower().lstrip(".") for ext in extensions)
    if not normalized or any(not ext for ext in normalized):
        raise ValueError("at least one non-empty output extension is required")
    if len(set(normalized)) != len(normalized):
        raise ValueError("output extensions must be unique within one task")
    return normalized


def _candidate_paths(directory: Path, stem: str, extensions) -> dict[str, Path]:
    return {
        ext: directory / f"{stem}.{ext}"
        for ext in extensions
    }


def _acquire_reservation_token(directory: Path, stem: str) -> Path | None:
    token_path = directory / f".{stem}.batch-reserve"
    try:
        descriptor = os.open(
            token_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        return None
    metadata = {
        "schema_version": 1,
        "owner_id": uuid.uuid4().hex,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "created_at": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "stem": stem,
    }
    try:
        os.write(
            descriptor,
            json.dumps(metadata, sort_keys=True).encode("utf-8"),
        )
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        token_path.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    return token_path


def inspect_output_reservation(token_path) -> ReservationTokenInfo | None:
    """Read a reservation token without guessing whether its owner is alive."""

    path = Path(token_path)
    if not (
        path.name.startswith(".")
        and path.name.endswith(".batch-reserve")
    ):
        raise ValueError("reservation token path must end with .batch-reserve")
    if not path.exists():
        return None
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
        metadata = decoded if isinstance(decoded, dict) else {
            "unreadable": "token metadata is not an object",
        }
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        metadata = {"unreadable": str(exc)}
    return ReservationTokenInfo(
        path=path,
        metadata=metadata,
        ownership=_capture_ownership(path),
    )


def release_output_reservation(info: ReservationTokenInfo) -> None:
    """Explicitly release the exact token snapshot returned by inspection."""

    if not isinstance(info, ReservationTokenInfo):
        raise TypeError("release requires ReservationTokenInfo from inspection")
    if not _is_owned_path(info.path, info.ownership):
        raise RuntimeError("reservation token changed since inspection")
    info.path.unlink()


def _reservation_conflict_detail(token_path: Path) -> str:
    info = inspect_output_reservation(token_path)
    metadata = info.metadata if info is not None else {}
    owner = metadata.get("owner_id", "unknown")
    host = metadata.get("host", "unknown")
    pid = metadata.get("pid", "unknown")
    created_at = metadata.get("created_at", "unknown")
    return (
        f"reservation token may be active or stale; owner={owner} "
        f"host={host} pid={pid} "
        f"created_at={created_at}; explicit inspect/release required"
    )


def reserve_output_paths(
    directory,
    stem: str,
    extensions: Iterable[str],
    *,
    conflict_policy: str = "auto_number",
) -> OutputReservation:
    """Atomically reserve one basename for a task's complete artifact set."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    normalized = _normalized_extensions(extensions)
    policy = str(conflict_policy or "").strip().lower()
    if policy not in {"error", "skip", "overwrite", "auto_number"}:
        raise ValueError(f"unsupported conflict_policy: {conflict_policy}")

    counter = 1
    while True:
        candidate_stem = stem if counter == 1 else f"{stem}__{counter}"
        paths = _candidate_paths(directory, candidate_stem, normalized)
        existing = tuple(path for path in paths.values() if path.exists())

        if policy == "auto_number" and existing:
            counter += 1
            continue
        if policy == "error" and existing:
            raise FileExistsError(
                f"batch output already exists: {candidate_stem}"
            )
        if policy == "skip" and existing:
            return OutputReservation(
                paths=paths,
                stem=candidate_stem,
                conflict_policy=policy,
                status="skipped",
                warning=(
                    "existing artifact skipped without matching manifest "
                    "provenance"
                ),
            )

        token = _acquire_reservation_token(directory, candidate_stem)
        if token is None:
            token_path = directory / f".{candidate_stem}.batch-reserve"
            conflict_detail = _reservation_conflict_detail(token_path)
            if policy == "auto_number":
                counter += 1
                continue
            if policy == "skip":
                return OutputReservation(
                    paths=paths,
                    stem=candidate_stem,
                    conflict_policy=policy,
                    status="skipped",
                    warning=(
                        "artifact reservation skipped without matching "
                        f"manifest provenance; {conflict_detail}"
                    ),
                )
            raise FileExistsError(
                f"batch output basename is reserved: {candidate_stem}; "
                f"{conflict_detail}"
            )

        token_ownership = _capture_ownership(token)

        # Close the exists-before-lock race.  Overwrite is the sole policy
        # allowed to retain pre-existing finals after acquiring the token.
        appeared = tuple(path for path in paths.values() if path.exists())
        if appeared and policy != "overwrite":
            if _is_owned_path(token, token_ownership):
                token.unlink()
            if policy == "auto_number":
                counter += 1
                continue
            if policy == "skip":
                return OutputReservation(
                    paths=paths,
                    stem=candidate_stem,
                    conflict_policy=policy,
                    status="skipped",
                    warning=(
                        "existing artifact skipped without matching manifest "
                        "provenance"
                    ),
                )
            raise FileExistsError(
                f"batch output already exists: {candidate_stem}"
            )

        return OutputReservation(
            paths=paths,
            stem=candidate_stem,
            conflict_policy=policy,
            token_path=token,
            token_ownership=token_ownership,
        )


def _publish_no_replace(temp: Path, target: Path) -> None:
    """Publish *temp* atomically while refusing to replace *target*."""

    try:
        os.link(temp, target)
    except FileExistsError as exc:
        raise OutputPublishRace(
            f"batch output appeared during write: {target}"
        ) from exc
    temp.unlink()


def _stage_path(target: Path) -> Path:
    handle = tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.stem}.batch-stage.",
        suffix=target.suffix,
        delete=False,
    )
    path = Path(handle.name)
    handle.close()
    path.unlink(missing_ok=True)
    return path


def _capture_ownership(path: Path) -> _FileOwnership | None:
    """Capture a conservative identity for rollback ownership checks.

    Some filesystems expose no stable inode/file index (reported as zero).
    In that case rollback deliberately refuses to remove a published final.
    """

    try:
        stat = path.stat()
    except OSError:
        return None
    inode = int(getattr(stat, "st_ino", 0) or 0)
    if inode <= 0:
        return None
    return _FileOwnership(
        device=int(getattr(stat, "st_dev", 0) or 0),
        inode=inode,
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
    )


def _is_owned_path(path: Path, expected: _FileOwnership | None) -> bool:
    if expected is None:
        return False
    return _capture_ownership(path) == expected


def atomic_write_set(
    reservation: OutputReservation,
    writers: Mapping[str, Callable[[Path], object]],
) -> dict[str, Path]:
    """Stage every task artifact, then publish the coordinated set.

    Writer/render failures occur before any final path changes.  For
    ``overwrite`` this preserves every old final until all new artifacts are
    complete.  Non-overwrite publication uses hard-link no-replace semantics
    and rolls back any newly published sibling if a late outsider wins a race.
    """

    if reservation.status != "reserved":
        reservation.release()
        raise RuntimeError("cannot publish a skipped output reservation")
    if set(writers) != set(reservation.paths):
        reservation.release()
        raise ValueError("writers must match every reserved output extension")

    staged = {
        ext: _stage_path(path)
        for ext, path in reservation.paths.items()
    }
    backups: dict[str, Path] = {}
    published: list[str] = []
    staged_ownership: dict[str, _FileOwnership | None] = {}
    preserved_backups: set[Path] = set()
    try:
        for ext, writer in writers.items():
            writer(staged[ext])
            if not staged[ext].exists():
                raise IOError(
                    f"batch writer did not create staged output: {staged[ext]}"
                )
            staged_ownership[ext] = _capture_ownership(staged[ext])

        if reservation.before_publish is not None:
            reservation.before_publish()

        if reservation.conflict_policy == "overwrite":
            for ext, target in reservation.paths.items():
                if not target.exists():
                    continue
                backup = _stage_path(target)
                try:
                    os.link(target, backup)
                except OSError:
                    shutil.copy2(target, backup)
                backups[ext] = backup

        for ext, target in reservation.paths.items():
            if reservation.conflict_policy == "overwrite":
                os.replace(staged[ext], target)
            else:
                _publish_no_replace(staged[ext], target)
            published.append(ext)
    except BaseException as publish_error:
        rollback_problems: list[str] = []
        for ext in reversed(published):
            target = reservation.paths[ext]
            backup = backups.get(ext)
            if not target.exists():
                if backup is not None and backup.exists():
                    try:
                        os.link(backup, target)
                        backup.unlink()
                    except OSError as exc:
                        preserved_backups.add(backup)
                        rollback_problems.append(
                            f"could not restore missing {target}: {exc}; "
                            f"backup preserved at {backup}"
                        )
                continue
            if not _is_owned_path(target, staged_ownership.get(ext)):
                if backup is not None and backup.exists():
                    preserved_backups.add(backup)
                rollback_problems.append(
                    f"unknown owner at {target}; left untouched"
                    + (
                        f"; backup preserved at {backup}"
                        if backup is not None and backup.exists() else ""
                    )
                )
                continue
            try:
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                else:
                    target.unlink()
            except OSError as exc:
                if backup is not None and backup.exists():
                    preserved_backups.add(backup)
                rollback_problems.append(
                    f"rollback failed for {target}: {exc}"
                    + (
                        f"; backup preserved at {backup}"
                        if backup is not None and backup.exists() else ""
                    )
                )
        if rollback_problems:
            raise OutputRollbackIncomplete(
                "batch artifact rollback incomplete: "
                + "; ".join(rollback_problems)
            ) from publish_error
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
        for path in backups.values():
            if path not in preserved_backups:
                path.unlink(missing_ok=True)
        reservation.release()
    return dict(reservation.paths)


def atomic_write(
    path,
    writer: Callable[[Path], object],
    *,
    overwrite: bool = False,
) -> Path:
    """Run *writer* on a sibling temp file, then atomically publish it."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(f"batch output already exists: {target}")
    handle = tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.stem}.",
        suffix=target.suffix,
        delete=False,
    )
    temp = Path(handle.name)
    handle.close()
    try:
        writer(temp)
        if not temp.exists():
            raise IOError(f"batch writer did not create temporary output: {temp}")
        if overwrite:
            os.replace(temp, target)
        else:
            _publish_no_replace(temp, target)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def write_dataframe(df, path, *, max_data_rows: int = _XLSX_MAX_DATA_ROWS):
    path = Path(path)
    fmt = path.suffix.lower()
    if fmt not in {'.csv', '.xlsx'}:
        path = path.with_suffix('.csv')

    def write(temp_path):
        if path.suffix.lower() == '.xlsx':
            # XLSX permits 1,048,576 rows including the column header.
            # Split only at the physical format boundary so a large
            # batch never silently truncates its final samples.
            with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
                starts = range(0, len(df), max_data_rows) or (0,)
                for sheet_index, start in enumerate(
                    starts, start=1,
                ):
                    df.iloc[start:start + max_data_rows].to_excel(
                        writer,
                        sheet_name=f"数据{sheet_index}",
                        index=False,
                    )
        else:
            df.to_csv(temp_path, index=False)

    return atomic_write(path, write)


def write_workbook(
    sheets: "dict[str, pd.DataFrame]",
    path,
    *,
    max_data_rows: int = _XLSX_MAX_DATA_ROWS,
):
    """Publish several named sheets as one xlsx, atomically.

    The sibling of :func:`write_dataframe` for the slice export: same
    ``atomic_write`` publication, but the caller names every sheet instead
    of getting one ``数据N`` series. Unlike the long table a slice sheet is
    a few hundred rows, so there is nothing to split -- exceeding the xlsx
    row ceiling here would mean the caller handed over the wrong frame, and
    silently dropping rows is worse than saying so.
    """
    path = Path(path)
    if path.suffix.lower() != '.xlsx':
        path = path.with_suffix('.xlsx')
    for name, frame in sheets.items():
        if len(frame) > max_data_rows:
            raise ValueError(
                f"worksheet {name!r} has {len(frame)} rows, above the "
                f"xlsx limit of {max_data_rows}"
            )

    def write(temp_path):
        with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=name, index=False)

    return atomic_write(path, write)


def write_image(
    payload,
    path,
    params=None,
    *,
    options=None,
    context=None,
    warnings_out: list[str] | None = None,
):
    from .batch_render import BatchRenderOptions, render_batch_image

    target = Path(path)
    render_options = options or BatchRenderOptions(
        format=target.suffix.lower().lstrip('.') or 'png',
    )
    return atomic_write(
        target,
        lambda temp: render_batch_image(
            payload,
            temp,
            params=params,
            options=render_options,
            context=context,
            warnings_out=warnings_out,
        ),
    )


__all__ = [
    "DEFAULT_GROUP_IDENTITY",
    "OutputPublishRace",
    "OutputRollbackIncomplete",
    "OutputReservation",
    "ReservationTokenInfo",
    "GroupOutputIdentity",
    "TaskOutputIdentity",
    "atomic_write",
    "atomic_write_set",
    "build_task_output_identity",
    "build_group_output_identity",
    "choose_output_paths",
    "inspect_output_reservation",
    "release_output_reservation",
    "reserve_output_paths",
    "unicode_slug",
    "write_dataframe",
    "write_workbook",
    "write_image",
]
