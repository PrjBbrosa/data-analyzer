"""Optional real-file sample supply for IO owner tests (T08 / HEAD HDF / MAT / WWT).

Reads ``TRACELAB_REALFILE_ROOT`` and ``TRACELAB_REQUIRE_REALFILE`` here, not
in the repo-root conftest. Per-sample path overrides are explicit inputs.
This module must not import product loaders.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CORPUS_ROOT_ENV = "TRACELAB_REALFILE_ROOT"
REQUIRE_CORPUS_ENV = "TRACELAB_REQUIRE_REALFILE"
EXPLORE_WWT_ENV = "TRACELAB_WWT_CORPUS_EXPLORE"
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "io_corpus" / "corpus_manifest.json"
)
_REQUIRED_SAMPLE_KEYS = (
    "id",
    "relative_path",
    "format",
    "scene",
    "path_env",
)
_HEX = set("0123456789abcdef")


class CorpusSupplyError(Exception):
    """Corpus is missing or does not match the checked-in manifest."""

    def __init__(self, message, *, optional=False):
        super().__init__(message)
        self.optional = bool(optional)


def is_require_realfile(environ=None):
    env = os.environ if environ is None else environ
    return str(env.get(REQUIRE_CORPUS_ENV, "")).strip() == "1"


def is_explore_wwt_glob(environ=None):
    env = os.environ if environ is None else environ
    return str(env.get(EXPLORE_WWT_ENV, "")).strip() == "1"


def realfile_root(environ=None):
    env = os.environ if environ is None else environ
    raw = str(env.get(CORPUS_ROOT_ENV, "")).strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value):
    digest = str(value or "").strip().lower()
    return len(digest) == 64 and all(ch in _HEX for ch in digest)


def read_realfile_manifest(path=None):
    manifest_path = Path(DEFAULT_MANIFEST_PATH if path is None else path)
    if not manifest_path.is_file():
        raise CorpusSupplyError(
            f"real-file corpus manifest missing: {manifest_path}",
            optional=False,
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusSupplyError(
            f"real-file corpus manifest is not valid JSON: {manifest_path} ({exc})",
            optional=False,
        ) from exc
    samples = payload.get("samples")
    if not isinstance(payload, dict) or not isinstance(samples, list) or not samples:
        raise CorpusSupplyError(
            f"real-file corpus manifest has no samples list: {manifest_path}",
            optional=False,
        )
    seen = []
    for item in samples:
        if not isinstance(item, dict):
            raise CorpusSupplyError(
                "real-file corpus manifest sample is not an object",
                optional=False,
            )
        missing = [key for key in _REQUIRED_SAMPLE_KEYS if key not in item]
        if missing:
            raise CorpusSupplyError(
                f"real-file corpus manifest sample missing {missing}",
                optional=False,
            )
        sample_id = item["id"]
        if sample_id in seen:
            raise CorpusSupplyError(
                f"real-file corpus manifest has duplicate id {sample_id!r}",
                optional=False,
            )
        seen.append(sample_id)
        rel = Path(item["relative_path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise CorpusSupplyError(
                f"real-file corpus manifest relative_path is not a safe relative path: {sample_id}",
                optional=False,
            )
        digest = str(item.get("sha256") or "").strip().lower()
        status = str(item.get("sha256_status") or "").strip().lower()
        if digest:
            if not _valid_sha256(digest):
                raise CorpusSupplyError(
                    f"real-file corpus manifest sha256 is not 64 hex chars: {sample_id}",
                    optional=False,
                )
        elif status != "unknown":
            raise CorpusSupplyError(
                f"real-file corpus manifest sample {sample_id} has no sha256 "
                "(set sha256_status=unknown only when the file was absent)",
                optional=False,
            )
    payload["_manifest_path"] = str(manifest_path)
    return payload


def _optional_unavailable(message, *, required):
    return CorpusSupplyError(message, optional=not required)


def resolve_realfile_sample(sample_id, *, environ=None, manifest_path=None):
    """Return ``(entry, path)`` for one registered sample.

    Missing optional corpus (no root / no per-sample path, not required)
    sets ``optional=True``. A checked-in manifest problem, required mode,
    an explicit bad path, or a hash mismatch is never optional.
    """
    required = is_require_realfile(environ)
    env = os.environ if environ is None else environ
    manifest = read_realfile_manifest(manifest_path)
    entry = next((item for item in manifest["samples"] if item["id"] == sample_id), None)
    if entry is None:
        raise CorpusSupplyError(
            f"real-file corpus has no sample id {sample_id!r}",
            optional=False,
        )

    override = str(env.get(str(entry["path_env"]), "")).strip()
    root = realfile_root(env)
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise CorpusSupplyError(
                f"real-file sample {sample_id} path is not a file: {path} "
                f"(from {entry['path_env']})",
                optional=False,
            )
    elif root is not None:
        if not root.is_dir():
            raise CorpusSupplyError(
                f"real-file corpus root is not a directory: {root}",
                optional=False,
            )
        path = root / entry["relative_path"]
        if not path.is_file():
            raise _optional_unavailable(
                f"UNAUDITED real-file sample {sample_id}: missing {path} "
                f"under {CORPUS_ROOT_ENV}",
                required=required,
            )
    else:
        raise _optional_unavailable(
            f"UNAUDITED real-file sample {sample_id}: set {entry['path_env']} "
            f"or {CORPUS_ROOT_ENV} to the directory that contains "
            f"{entry['relative_path']}.",
            required=required,
        )

    digest = str(entry.get("sha256") or "").strip().lower()
    if _valid_sha256(digest):
        actual = sha256_file(path)
        if actual != digest:
            raise CorpusSupplyError(
                f"hash mismatch {sample_id}: expected {digest}, got {actual}",
                optional=False,
            )
    return entry, path


def resolve_realfile_samples(format_name, *, environ=None, manifest_path=None):
    """Return ``[(entry, path), ...]`` for one format. Missing optional samples skip.

    A configured explicit path or hash mismatch still fails. Required mode
    fails if any registered sample of that format is unavailable.
    """
    required = is_require_realfile(environ)
    manifest = read_realfile_manifest(manifest_path)
    wanted = [item for item in manifest["samples"] if item["format"] == format_name]
    if not wanted:
        raise CorpusSupplyError(
            f"real-file corpus has no samples with format {format_name!r}",
            optional=False,
        )
    resolved = []
    optional_missing = []
    for entry in wanted:
        try:
            resolved.append(
                resolve_realfile_sample(
                    entry["id"], environ=environ, manifest_path=manifest_path,
                )
            )
        except CorpusSupplyError as exc:
            if exc.optional:
                optional_missing.append(str(exc))
                continue
            raise
    if resolved:
        return resolved
    raise _optional_unavailable(
        f"UNAUDITED {format_name} real-file samples: " + "; ".join(optional_missing),
        required=required,
    )


def extra_wwt_glob_paths(*, environ=None, manifest_path=None):
    """Return ``.wwt`` files under the corpus root that are not registered.

    Default gate must not call this. Opt-in via ``TRACELAB_WWT_CORPUS_EXPLORE=1``.
    """
    if not is_explore_wwt_glob(environ):
        return []
    required = is_require_realfile(environ)
    root = realfile_root(environ)
    if root is None:
        raise _optional_unavailable(
            f"WWT extra glob requested but {CORPUS_ROOT_ENV} is unset",
            required=required,
        )
    if not root.is_dir():
        raise CorpusSupplyError(
            f"real-file corpus root is not a directory: {root}",
            optional=False,
        )
    manifest = read_realfile_manifest(manifest_path)
    registered = {
        str((root / item["relative_path"]).resolve())
        for item in manifest["samples"]
        if item["format"] == "wwt"
    }
    extras = []
    for path in sorted(root.rglob("*.wwt")):
        if not path.is_file():
            continue
        if str(path.resolve()) in registered:
            continue
        extras.append(path)
    return extras
