"""Reject diagnostic JSON targets that would overwrite frozen inputs."""
from __future__ import annotations

import os
from pathlib import Path


class UnsafeEvidencePath(ValueError):
    """The evidence target could overwrite an input or protected artifact."""


def canonical_path(path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def same_path(left: Path, right: Path) -> bool:
    if os.path.normcase(str(left)) == os.path.normcase(str(right)):
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def path_is_within(path: Path, root: Path) -> bool:
    path = canonical_path(path)
    root = canonical_path(root)
    try:
        return path == root or path.is_relative_to(root)
    except ValueError:
        return False


def reject_aliased_evidence(
    evidence: Path,
    protected_files: tuple[Path, ...] = (),
    *,
    contained_in: tuple[Path, ...] = (),
    message: str,
) -> None:
    evidence = canonical_path(evidence)
    if any(same_path(evidence, canonical_path(path)) for path in protected_files):
        raise UnsafeEvidencePath(message)
    if any(path_is_within(evidence, root) for root in contained_in):
        raise UnsafeEvidencePath(message)
