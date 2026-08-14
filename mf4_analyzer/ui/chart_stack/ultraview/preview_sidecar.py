"""Validated optional storage for UltraView preview pixels.

The project document owns the Board/ref semantics.  This module stores only
non-authoritative preview images and metadata in a versioned ZIP sidecar; a
missing or rejected sidecar is deliberately a safe ``missing`` degradation.
It never imports a window, analysis code, or result cache.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
import uuid
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from PyQt5.QtCore import QBuffer, QIODevice, QThread
from PyQt5.QtGui import QImage, QImageReader
from PyQt5.QtWidgets import QApplication

from ...ultraview_state import PreviewMeta, UltraViewRef, parse_ref_payload
from .preview_store import (
    MAX_PREVIEW_RAW_EDGE,
    MAX_PREVIEW_PIXELS,
    PreviewRecord,
    PreviewStore,
)

SIDECAR_FORMAT = 1
SIDECAR_SUFFIX = ".uvpz"
SIDECAR_DIRECTORY_SUFFIX = ".ultraview"
MANIFEST_NAME = "manifest.json"
IMAGE_DIRECTORY = "images"
MAX_SIDECAR_ENTRIES = 512
MAX_SIDECAR_IMAGE_BYTES = 16 * 1024 * 1024
MAX_SIDECAR_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SIDECAR_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_SIDECAR_MANIFEST_BYTES = 1024 * 1024
MAX_SIDECAR_COMPRESSION_RATIO = 100
_MIN_VALID_EDGE = 8
_HEX_DIGEST_LENGTH = 64


@dataclass(frozen=True)
class SidecarWarning:
    """A non-fatal sidecar issue, suitable for coordinator toast/log routing."""

    code: str
    detail: str = ""
    ref: UltraViewRef | None = None
    path: str | None = None


@dataclass(frozen=True)
class SidecarSaveResult:
    ok: bool
    descriptor: dict[str, Any] | None
    saved_refs: tuple[UltraViewRef, ...]
    warnings: tuple[SidecarWarning, ...] = ()


@dataclass(frozen=True)
class SidecarLoadResult:
    ok: bool
    loaded_refs: tuple[UltraViewRef, ...]
    rejected_refs: tuple[UltraViewRef, ...]
    warnings: tuple[SidecarWarning, ...] = ()


@dataclass(frozen=True)
class SidecarImagePayload:
    """Validated PNG bytes for one membership ref; decode happens later."""

    ref: UltraViewRef
    image_bytes: bytes
    captured_digest: str | None
    meta: PreviewMeta
    width: int
    height: int


@dataclass(frozen=True)
class SidecarOpenResult:
    ok: bool
    images: tuple[SidecarImagePayload, ...]
    rejected_refs: tuple[UltraViewRef, ...]
    warnings: tuple[SidecarWarning, ...] = ()


class _SidecarRejected(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_ref_hash(ref: UltraViewRef) -> str:
    """Stable file-safe identity, independent of names, paths, and Board slots."""
    value = f"{ref.section}\0{ref.view_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def sidecar_directory(project_path: str | Path) -> Path:
    """Return the only allowed sibling directory for a project sidecar."""
    return Path(f"{Path(project_path)}{SIDECAR_DIRECTORY_SUFFIX}")


def _unlink_stale_sidecar_archives(sidecar_dir: Path, keep: Path | None) -> None:
    """Drop previous ``.uvpz`` generations after a successful replace.

    Temp files, symlinks, and the just-written archive stay put.  Unlink
    failures are ignored so a leftover orphan cannot fail the save.
    """
    keep_name = keep.name if keep is not None else None
    try:
        children = list(sidecar_dir.iterdir())
    except OSError:
        return
    for path in children:
        if path.name == keep_name or path.suffix != SIDECAR_SUFFIX:
            continue
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            continue
        try:
            path.unlink()
        except OSError:
            continue


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _warning(
    code: str,
    detail: str = "",
    *,
    ref: UltraViewRef | None = None,
    path: Path | None = None,
) -> SidecarWarning:
    return SidecarWarning(
        code=code,
        detail=detail,
        ref=ref,
        path=None if path is None else str(path),
    )


def _require_gui_thread() -> None:
    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        raise RuntimeError(
            "UltraView sidecar image operations must run on the GUI thread"
        )


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != _HEX_DIGEST_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _safe_generation(value: str | None) -> str:
    generation = value or uuid.uuid4().hex
    if (
        not isinstance(generation, str)
        or not 8 <= len(generation) <= 128
        or any(not (char.isascii() and (char.isalnum() or char in "_-")) for char in generation)
    ):
        raise ValueError("generation must be 8–128 ASCII letters, digits, '_' or '-'")
    return generation


def _iter_board_refs(board: Mapping[str, Any]) -> Iterable[UltraViewRef]:
    collections: list[object] = [board.get("placements"), board.get("unplaced")]
    # P2 free-grid keeps its placement identity below ``free_grid`` rather
    # than adding a template-only slot_id.  Read it directly so the sidecar
    # remains ref-based across schema 2 → 3 without a codec format change.
    free_grid = board.get("free_grid")
    if isinstance(free_grid, Mapping):
        collections.append(free_grid.get("placements"))
    for raw in collections:
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            ref = parse_ref_payload(item)
            if ref is not None:
                yield ref


def workspace_membership(workspace_payload: Mapping[str, Any] | None) -> tuple[UltraViewRef, ...]:
    """Extract the ordered unique membership from schema-1 or schema-2 payloads.

    This tolerant read helper intentionally never legalizes or mutates project
    state.  The coordinator remains responsible for authoritative migration.
    """
    if not isinstance(workspace_payload, Mapping):
        return ()
    root = workspace_payload.get("workspace", workspace_payload)
    if not isinstance(root, Mapping):
        return ()
    boards_raw = root.get("boards")
    if not isinstance(boards_raw, list):
        board = root.get("board")
        boards_raw = [board] if isinstance(board, Mapping) else []
    result: list[UltraViewRef] = []
    seen: set[UltraViewRef] = set()
    for board in boards_raw:
        if not isinstance(board, Mapping):
            continue
        for ref in _iter_board_refs(board):
            if ref not in seen:
                seen.add(ref)
                result.append(ref)
    return tuple(result)


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    if not buffer.open(QIODevice.WriteOnly) or not image.save(buffer, "PNG"):
        raise OSError("QImage PNG encoding failed")
    return bytes(buffer.data())


def _record_entry(record: PreviewRecord) -> tuple[dict[str, Any], bytes]:
    image = record.image
    if not PreviewStore.image_valid(image):
        raise _SidecarRejected("image_invalid")
    assert image is not None
    width = image.width()
    height = image.height()
    if not _valid_dimensions(width, height):
        raise _SidecarRejected("image_dimensions_invalid")
    png = _encode_png(image)
    if not 0 < len(png) <= MAX_SIDECAR_IMAGE_BYTES:
        raise _SidecarRejected("image_bytes_invalid")
    ref = record.ref
    return (
        {
            "ref": ref.to_dict(),
            "image": _image_name(ref),
            "captured_digest": record.captured_digest,
            "meta": {
                "captured_at": record.captured_at,
                "axis_kind": record.axis_kind,
                "x_unit": record.x_unit,
                "x_range": None if record.x_range is None else list(record.x_range),
                "y_unit": record.y_unit,
                "title": record.title,
                "source_summary": record.source_summary,
                "tab_color": record.tab_color,
            },
            "width": width,
            "height": height,
            "bytes": len(png),
            "sha256": hashlib.sha256(png).hexdigest(),
        },
        png,
    )


def _image_name(ref: UltraViewRef) -> str:
    return f"{IMAGE_DIRECTORY}/{canonical_ref_hash(ref)}.png"


def _valid_dimensions(width: object, height: object) -> bool:
    if isinstance(width, bool) or isinstance(height, bool):
        return False
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    return (
        _MIN_VALID_EDGE <= width <= MAX_PREVIEW_RAW_EDGE
        and _MIN_VALID_EDGE <= height <= MAX_PREVIEW_RAW_EDGE
        and width * height <= MAX_PREVIEW_PIXELS
    )


def save_preview_sidecar(
    project_path: str | Path,
    workspace_payload: Mapping[str, Any] | None,
    store: PreviewStore,
    *,
    generation: str | None = None,
) -> SidecarSaveResult:
    """Atomically save valid, uniquely referenced previews for one project.

    The returned descriptor is JSON-ready and relative to the project directory.
    On any write/encode failure no descriptor is returned and an existing
    generation remains untouched.  The caller may then save project semantics
    without a new ``preview_sidecar`` descriptor.
    """
    _require_gui_thread()
    try:
        generation = _safe_generation(generation)
    except ValueError as exc:
        return SidecarSaveResult(
            ok=False,
            descriptor=None,
            saved_refs=(),
            warnings=(_warning("sidecar_generation_invalid", str(exc)),),
        )
    project = Path(project_path)
    refs = workspace_membership(workspace_payload)
    entries: list[dict[str, Any]] = []
    images: dict[str, bytes] = {}
    saved_refs: list[UltraViewRef] = []
    for ref in refs:
        record = store.get(ref)
        if record is None or not PreviewStore.image_valid(record.image):
            continue
        try:
            entry, png = _record_entry(record)
        except _SidecarRejected:
            continue
        except (OSError, RuntimeError) as exc:
            return SidecarSaveResult(
                ok=False,
                descriptor=None,
                saved_refs=(),
                warnings=(_warning("sidecar_write_failed", str(exc)),),
            )
        entries.append(entry)
        images[entry["image"]] = png
        saved_refs.append(ref)

    sidecar_dir = sidecar_directory(project)
    if not entries:
        if sidecar_dir.is_dir() and not sidecar_dir.is_symlink():
            _unlink_stale_sidecar_archives(sidecar_dir, keep=None)
            try:
                sidecar_dir.rmdir()
            except OSError:
                pass
        return SidecarSaveResult(ok=True, descriptor=None, saved_refs=())

    destination = sidecar_dir / f"{generation}{SIDECAR_SUFFIX}"
    temp_path: Path | None = None
    try:
        if sidecar_dir.is_symlink():
            raise OSError("sidecar directory must not be a symlink")
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "format": SIDECAR_FORMAT,
            "generation": generation,
            "entries": entries,
        }
        manifest_bytes = _canonical_json_bytes(manifest)
        if len(manifest_bytes) > MAX_SIDECAR_MANIFEST_BYTES:
            raise OSError("manifest exceeds sidecar limit")
        descriptor = {
            "format": SIDECAR_FORMAT,
            "path": destination.relative_to(project.parent).as_posix(),
            "generation": generation,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{generation}.",
            suffix=".tmp",
            dir=str(sidecar_dir),
        )
        os.close(fd)
        temp_path = Path(temp_name)
        with zipfile.ZipFile(
            temp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(MANIFEST_NAME, manifest_bytes)
            for name, png in images.items():
                archive.writestr(name, png)
        with temp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        if temp_path.stat().st_size > MAX_SIDECAR_ARCHIVE_BYTES:
            raise OSError("archive exceeds sidecar limit")
        os.replace(temp_path, destination)
        temp_path = None
        _unlink_stale_sidecar_archives(sidecar_dir, keep=destination)
        return SidecarSaveResult(
            ok=True,
            descriptor=descriptor,
            saved_refs=tuple(saved_refs),
        )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        return SidecarSaveResult(
            ok=False,
            descriptor=None,
            saved_refs=(),
            warnings=(_warning("sidecar_write_failed", str(exc), path=destination),),
        )
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _archive_path_from_descriptor(
    project: Path, descriptor: Mapping[str, Any] | None
) -> tuple[Path | None, str | None, SidecarWarning | None]:
    if not isinstance(descriptor, Mapping):
        return None, None, _warning("sidecar_descriptor_invalid")
    if descriptor.get("format") != SIDECAR_FORMAT:
        return None, None, _warning("sidecar_format_unsupported")
    generation = descriptor.get("generation")
    try:
        generation = _safe_generation(generation)
    except ValueError:
        return None, None, _warning("sidecar_generation_invalid")
    raw_path = descriptor.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None, None, _warning("sidecar_path_invalid")
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return None, None, _warning("sidecar_path_invalid", raw_path)
    # Keep the lexical sibling path intact until the explicit symlink checks
    # below.  Calling ``resolve`` here would silently follow a malicious
    # ``.ultraview`` directory or archive symlink out of the project folder.
    base = project.parent.resolve()
    allowed_dir = base / sidecar_directory(project).name
    candidate = base / Path(*pure.parts)
    expected = allowed_dir / f"{generation}{SIDECAR_SUFFIX}"
    if candidate != expected or candidate.parent != allowed_dir:
        return None, None, _warning("sidecar_path_invalid", raw_path)
    return candidate, generation, None


def _validate_zip_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not 1 <= len(infos) <= MAX_SIDECAR_ENTRIES + 1:
        raise _SidecarRejected("zip_entry_count_invalid")
    seen: set[str] = set()
    members: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for info in infos:
        name = info.filename
        pure = PurePosixPath(name)
        if (
            not name
            or pure.is_absolute()
            or ".." in pure.parts
            or name.endswith("/")
            or name in seen
        ):
            raise _SidecarRejected("zip_member_invalid", name)
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            raise _SidecarRejected("zip_symlink_rejected", name)
        compressed = info.compress_size
        uncompressed = info.file_size
        if uncompressed < 0 or compressed < 0:
            raise _SidecarRejected("zip_member_invalid", name)
        if uncompressed and (
            compressed == 0
            or uncompressed > compressed * MAX_SIDECAR_COMPRESSION_RATIO
        ):
            raise _SidecarRejected("zip_ratio_exceeded", name)
        total_size += uncompressed
        if total_size > MAX_SIDECAR_TOTAL_BYTES + MAX_SIDECAR_MANIFEST_BYTES:
            raise _SidecarRejected("zip_total_exceeded")
        seen.add(name)
        members[name] = info
    if MANIFEST_NAME not in members:
        raise _SidecarRejected("manifest_missing")
    if members[MANIFEST_NAME].file_size > MAX_SIDECAR_MANIFEST_BYTES:
        raise _SidecarRejected("manifest_too_large")
    return members


def _safe_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4096:
        raise _SidecarRejected("manifest_entry_invalid", field)
    return value


def _safe_optional_float(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _SidecarRejected("manifest_entry_invalid", field)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise _SidecarRejected("manifest_entry_invalid", field) from exc
    if not math.isfinite(result):
        raise _SidecarRejected("manifest_entry_invalid", field)
    return result


def _parse_meta(ref: UltraViewRef, raw: object) -> PreviewMeta:
    if not isinstance(raw, Mapping):
        raise _SidecarRejected("manifest_entry_invalid", "meta")
    x_range_raw = raw.get("x_range")
    x_range: tuple[float, float] | None = None
    if x_range_raw is not None:
        if not isinstance(x_range_raw, (list, tuple)) or len(x_range_raw) != 2:
            raise _SidecarRejected("manifest_entry_invalid", "x_range")
        left = _safe_optional_float(x_range_raw[0], "x_range")
        right = _safe_optional_float(x_range_raw[1], "x_range")
        assert left is not None and right is not None
        x_range = (left, right)
    return PreviewMeta(
        ref=ref,
        captured_at=_safe_optional_float(raw.get("captured_at"), "captured_at"),
        axis_kind=_safe_string(raw.get("axis_kind"), "axis_kind"),
        x_unit=_safe_string(raw.get("x_unit"), "x_unit"),
        x_range=x_range,
        y_unit=_safe_string(raw.get("y_unit"), "y_unit"),
        title=_safe_string(raw.get("title"), "title") or "",
        source_summary=_safe_string(raw.get("source_summary"), "source_summary") or "",
        tab_color=_safe_string(raw.get("tab_color"), "tab_color") or "",
    )


@dataclass(frozen=True)
class _ManifestEntry:
    ref: UltraViewRef
    image: str
    captured_digest: str | None
    meta: PreviewMeta
    width: int
    height: int
    byte_count: int
    sha256: str


def _parse_manifest(
    manifest_bytes: bytes,
    *,
    descriptor: Mapping[str, Any],
    members: Mapping[str, zipfile.ZipInfo],
) -> tuple[_ManifestEntry, ...]:
    try:
        raw = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _SidecarRejected("manifest_invalid", str(exc)) from exc
    if not isinstance(raw, Mapping) or raw.get("format") != SIDECAR_FORMAT:
        raise _SidecarRejected("manifest_format_unsupported")
    if raw.get("generation") != descriptor.get("generation"):
        raise _SidecarRejected("manifest_generation_mismatch")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list) or len(entries_raw) > MAX_SIDECAR_ENTRIES:
        raise _SidecarRejected("manifest_entries_invalid")
    expected_names = {MANIFEST_NAME}
    result: list[_ManifestEntry] = []
    seen_refs: set[UltraViewRef] = set()
    for raw_entry in entries_raw:
        if not isinstance(raw_entry, Mapping):
            raise _SidecarRejected("manifest_entry_invalid")
        ref = parse_ref_payload(raw_entry.get("ref"))
        if ref is None or ref in seen_refs:
            raise _SidecarRejected("manifest_entry_invalid", "ref")
        image = raw_entry.get("image")
        if image != _image_name(ref) or image not in members:
            raise _SidecarRejected("manifest_entry_invalid", "image")
        expected_names.add(image)
        width = raw_entry.get("width")
        height = raw_entry.get("height")
        if not _valid_dimensions(width, height):
            raise _SidecarRejected("manifest_entry_invalid", "dimensions")
        byte_count = raw_entry.get("bytes")
        if (
            isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or not 0 < byte_count <= MAX_SIDECAR_IMAGE_BYTES
        ):
            raise _SidecarRejected("manifest_entry_invalid", "bytes")
        sha256 = raw_entry.get("sha256")
        if not _is_sha256(sha256):
            raise _SidecarRejected("manifest_entry_invalid", "sha256")
        digest = raw_entry.get("captured_digest")
        if digest is not None and not isinstance(digest, str):
            raise _SidecarRejected("manifest_entry_invalid", "captured_digest")
        result.append(
            _ManifestEntry(
                ref=ref,
                image=image,
                captured_digest=digest,
                meta=_parse_meta(ref, raw_entry.get("meta")),
                width=width,
                height=height,
                byte_count=byte_count,
                sha256=sha256,
            )
        )
        seen_refs.add(ref)
    if set(members) != expected_names:
        raise _SidecarRejected("zip_unknown_member")
    return tuple(result)


def _png_reader(image_bytes: bytes) -> tuple[QBuffer, QImageReader]:
    buffer = QBuffer()
    buffer.setData(image_bytes)
    if not buffer.open(QIODevice.ReadOnly):
        raise _SidecarRejected("image_decode_failed")
    return buffer, QImageReader(buffer, b"png")


def _validate_png_size(image_bytes: bytes, *, width: int, height: int) -> None:
    _buffer, reader = _png_reader(image_bytes)
    size = reader.size()
    if not size.isValid() or size.width() != width or size.height() != height:
        raise _SidecarRejected("image_dimensions_mismatch")
    if not _valid_dimensions(size.width(), size.height()):
        raise _SidecarRejected("image_dimensions_invalid")


def _decode_png(image_bytes: bytes, *, width: int, height: int) -> QImage:
    buffer, reader = _png_reader(image_bytes)
    size = reader.size()
    if not size.isValid() or size.width() != width or size.height() != height:
        raise _SidecarRejected("image_dimensions_mismatch")
    if not _valid_dimensions(size.width(), size.height()):
        raise _SidecarRejected("image_dimensions_invalid")
    image = reader.read()
    if not PreviewStore.image_valid(image):
        raise _SidecarRejected("image_decode_failed")
    return image


def publish_sidecar_image(store: PreviewStore, payload: SidecarImagePayload) -> None:
    """Decode one validated PNG onto the GUI thread and publish it."""
    image = _decode_png(payload.image_bytes, width=payload.width, height=payload.height)
    if not store.publish(
        payload.ref,
        image,
        digest=payload.captured_digest,
        meta=payload.meta,
    ):
        raise _SidecarRejected("image_publish_rejected")


def open_preview_sidecar(
    project_path: str | Path,
    workspace_payload: Mapping[str, Any] | None,
    descriptor: Mapping[str, Any] | None,
) -> SidecarOpenResult:
    """Validate the archive and collect PNG bytes without decoding QImages."""
    _require_gui_thread()
    project = Path(project_path)
    archive_path, _generation, descriptor_warning = _archive_path_from_descriptor(
        project, descriptor
    )
    if descriptor_warning is not None:
        return SidecarOpenResult(False, (), (), (descriptor_warning,))
    assert archive_path is not None
    if archive_path.parent.is_symlink() or archive_path.is_symlink() or not archive_path.is_file():
        return SidecarOpenResult(
            False,
            (),
            (),
            (_warning("sidecar_missing", path=archive_path),),
        )
    try:
        if archive_path.stat().st_size > MAX_SIDECAR_ARCHIVE_BYTES:
            raise _SidecarRejected("sidecar_archive_too_large")
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = _validate_zip_members(archive)
            manifest_bytes = archive.read(MANIFEST_NAME)
            expected_hash = descriptor.get("manifest_sha256") if isinstance(descriptor, Mapping) else None
            if not _is_sha256(expected_hash) or hashlib.sha256(manifest_bytes).hexdigest() != expected_hash:
                raise _SidecarRejected("manifest_hash_mismatch")
            entries = _parse_manifest(
                manifest_bytes,
                descriptor=descriptor,
                members=members,
            )
            wanted = set(workspace_membership(workspace_payload))
            images: list[SidecarImagePayload] = []
            rejected: list[UltraViewRef] = []
            warnings: list[SidecarWarning] = []
            for entry in entries:
                if entry.ref not in wanted:
                    continue
                try:
                    image_bytes = archive.read(entry.image)
                    if hashlib.sha256(image_bytes).hexdigest() != entry.sha256:
                        raise _SidecarRejected("image_hash_mismatch")
                    if len(image_bytes) != entry.byte_count:
                        raise _SidecarRejected("image_bytes_mismatch")
                    _validate_png_size(image_bytes, width=entry.width, height=entry.height)
                    images.append(
                        SidecarImagePayload(
                            ref=entry.ref,
                            image_bytes=image_bytes,
                            captured_digest=entry.captured_digest,
                            meta=entry.meta,
                            width=entry.width,
                            height=entry.height,
                        )
                    )
                except (OSError, RuntimeError, _SidecarRejected) as exc:
                    code = exc.code if isinstance(exc, _SidecarRejected) else "image_decode_failed"
                    detail = exc.detail if isinstance(exc, _SidecarRejected) else str(exc)
                    rejected.append(entry.ref)
                    warnings.append(
                        _warning(code, detail, ref=entry.ref, path=archive_path)
                    )
                    continue
            return SidecarOpenResult(
                True,
                tuple(images),
                tuple(rejected),
                tuple(warnings),
            )
    except (OSError, zipfile.BadZipFile, _SidecarRejected) as exc:
        code = exc.code if isinstance(exc, _SidecarRejected) else "sidecar_invalid"
        detail = exc.detail if isinstance(exc, _SidecarRejected) else str(exc)
        return SidecarOpenResult(
            False,
            (),
            (),
            (_warning(code, detail, path=archive_path),),
        )


def restore_preview_sidecar(
    project_path: str | Path,
    workspace_payload: Mapping[str, Any] | None,
    store: PreviewStore,
    descriptor: Mapping[str, Any] | None,
) -> SidecarLoadResult:
    """Validate and restore sidecar images belonging to the current workspace.

    A malformed archive/descriptor returns ``ok=False`` with a warning and
    leaves the store untouched.  A bad PNG is isolated to its one ref while
    valid sibling entries continue to restore.
    """
    opened = open_preview_sidecar(project_path, workspace_payload, descriptor)
    if not opened.ok:
        return SidecarLoadResult(False, (), opened.rejected_refs, opened.warnings)
    loaded: list[UltraViewRef] = []
    rejected = list(opened.rejected_refs)
    warnings = list(opened.warnings)
    for payload in opened.images:
        try:
            publish_sidecar_image(store, payload)
        except (OSError, RuntimeError, _SidecarRejected) as exc:
            code = exc.code if isinstance(exc, _SidecarRejected) else "image_decode_failed"
            detail = exc.detail if isinstance(exc, _SidecarRejected) else str(exc)
            rejected.append(payload.ref)
            warnings.append(_warning(code, detail, ref=payload.ref))
            continue
        loaded.append(payload.ref)
    return SidecarLoadResult(True, tuple(loaded), tuple(rejected), tuple(warnings))


__all__ = [
    "IMAGE_DIRECTORY",
    "MANIFEST_NAME",
    "MAX_SIDECAR_ARCHIVE_BYTES",
    "MAX_SIDECAR_COMPRESSION_RATIO",
    "MAX_SIDECAR_ENTRIES",
    "MAX_SIDECAR_IMAGE_BYTES",
    "MAX_SIDECAR_MANIFEST_BYTES",
    "MAX_SIDECAR_TOTAL_BYTES",
    "SIDECAR_FORMAT",
    "SIDECAR_SUFFIX",
    "SidecarImagePayload",
    "SidecarLoadResult",
    "SidecarOpenResult",
    "SidecarSaveResult",
    "SidecarWarning",
    "canonical_ref_hash",
    "open_preview_sidecar",
    "publish_sidecar_image",
    "restore_preview_sidecar",
    "save_preview_sidecar",
    "sidecar_directory",
    "workspace_membership",
]
