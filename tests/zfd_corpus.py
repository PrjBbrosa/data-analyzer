"""Optional real-sample corpus supply for ZFD owner tests.

Reads ``TRACELAB_ZFD_CORPUS_ROOT`` and ``TRACELAB_REQUIRE_ZFD_CORPUS`` here,
not in the repo-root conftest. This module must not import the product
parser or ``tools/matlab_ports``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CORPUS_ROOT_ENV = "TRACELAB_ZFD_CORPUS_ROOT"
REQUIRE_CORPUS_ENV = "TRACELAB_REQUIRE_ZFD_CORPUS"
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "zfd" / "corpus_manifest.json"
)
_REQUIRED_SAMPLE_KEYS = (
    "id",
    "relative_path",
    "sha256",
    "profile",
    "source_count",
    "sample_count",
    "t0",
    "dt",
    "channels",
    "units",
    "value_evidence",
)


class CorpusSupplyError(Exception):
    """Corpus is missing or does not match the checked-in manifest."""

    def __init__(self, message, *, optional=False):
        super().__init__(message)
        self.optional = bool(optional)


def is_require_zfd_corpus(environ=None):
    env = os.environ if environ is None else environ
    return str(env.get(REQUIRE_CORPUS_ENV, "")).strip() == "1"


def zfd_corpus_root(environ=None):
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


def read_zfd_corpus_manifest(path=None):
    manifest_path = Path(DEFAULT_MANIFEST_PATH if path is None else path)
    if not manifest_path.is_file():
        raise CorpusSupplyError(
            f"ZFD corpus manifest missing: {manifest_path}",
            optional=False,
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusSupplyError(
            f"ZFD corpus manifest is not valid JSON: {manifest_path} ({exc})",
            optional=False,
        ) from exc
    samples = payload.get("samples")
    if not isinstance(payload, dict) or not isinstance(samples, list):
        raise CorpusSupplyError(
            f"ZFD corpus manifest has no samples list: {manifest_path}",
            optional=False,
        )
    if len(samples) != 6:
        raise CorpusSupplyError(
            f"ZFD corpus manifest must list exactly 6 samples, got {len(samples)}",
            optional=False,
        )
    seen = []
    for item in samples:
        if not isinstance(item, dict):
            raise CorpusSupplyError(
                "ZFD corpus manifest sample is not an object",
                optional=False,
            )
        missing = [key for key in _REQUIRED_SAMPLE_KEYS if key not in item]
        if missing:
            raise CorpusSupplyError(
                f"ZFD corpus manifest sample missing {missing}",
                optional=False,
            )
        sample_id = item["id"]
        if sample_id in seen:
            raise CorpusSupplyError(
                f"ZFD corpus manifest has duplicate id {sample_id!r}",
                optional=False,
            )
        seen.append(sample_id)
        digest = str(item["sha256"]).strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise CorpusSupplyError(
                f"ZFD corpus manifest sha256 is not 64 hex chars: {sample_id}",
                optional=False,
            )
        rel = Path(item["relative_path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise CorpusSupplyError(
                f"ZFD corpus manifest relative_path is not a safe relative path: {sample_id}",
                optional=False,
            )
    payload["_manifest_path"] = str(manifest_path)
    return payload


def resolve_zfd_corpus_samples(*, environ=None, manifest_path=None):
    """Return ``[(entry, path), ...]`` or raise ``CorpusSupplyError``.

    Missing optional corpus (no root, not required) sets ``optional=True``.
    A checked-in manifest problem, required mode, or a configured root that
    does not match the manifest is never optional.
    """
    required = is_require_zfd_corpus(environ)
    root = zfd_corpus_root(environ)
    manifest = read_zfd_corpus_manifest(manifest_path)
    if root is None:
        raise CorpusSupplyError(
            f"ZFD corpus unavailable: set {CORPUS_ROOT_ENV} to the directory "
            "that contains the six registered sample relative paths.",
            optional=not required,
        )
    if not root.is_dir():
        raise CorpusSupplyError(
            f"ZFD corpus root is not a directory: {root}",
            optional=False,
        )

    resolved = []
    problems = []
    for entry in manifest["samples"]:
        path = root / entry["relative_path"]
        if not path.is_file():
            problems.append(f"missing {entry['id']} ({entry['relative_path']})")
            continue
        digest = sha256_file(path)
        expected = str(entry["sha256"]).strip().lower()
        if digest != expected:
            problems.append(
                f"hash mismatch {entry['id']}: expected {expected}, got {digest}"
            )
            continue
        resolved.append((entry, path))
    if problems:
        raise CorpusSupplyError(
            "ZFD corpus supply failed: " + "; ".join(problems),
            optional=False,
        )
    return resolved
