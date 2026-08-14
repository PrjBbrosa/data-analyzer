"""Pure policy helpers for bounded BLF/DBC candidate discovery.

The UI owns prompting and the loader owns full frame decoding.  This module
keeps path-set identity, structural scoring, and final ordering independent of
both so the expensive probe policy can be tested without Qt or CAN fixtures.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import os
from typing import Iterable, Mapping, Sequence


AUTO_PROBE_LIMIT = 3


@dataclass(frozen=True)
class StructuralScore:
    """Low-cost overlap between a BLF ID histogram and a DBC ID set."""

    frame_coverage: float = 0.0
    id_coverage: float = 0.0
    matched_id_count: int = 0


def _real_path(path) -> str:
    return os.path.realpath(os.path.abspath(os.fspath(path)))


def normalize_dbc_paths(paths: Iterable[object]) -> tuple[str, ...]:
    """Return real absolute paths in display order, removing aliases."""

    normalized = []
    seen = set()
    for path in paths or ():
        if not path:
            continue
        real_path = _real_path(path)
        identity_path = os.path.normcase(real_path)
        if identity_path in seen:
            continue
        seen.add(identity_path)
        normalized.append(real_path)
    return tuple(normalized)


def dbc_candidate_identity(paths: Iterable[object]) -> tuple[str, ...]:
    """Canonical unordered identity for one DBC set."""

    return tuple(sorted(os.path.normcase(path) for path in normalize_dbc_paths(paths)))


def deduplicate_dbc_sets(
    path_sets: Iterable[Iterable[object]],
) -> list[tuple[str, ...]]:
    """Dedupe equivalent sets while retaining the first set's display order."""

    deduplicated = []
    seen = set()
    for paths in path_sets or ():
        display_paths = normalize_dbc_paths(paths)
        identity = dbc_candidate_identity(display_paths)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(display_paths)
    return deduplicated


def frame_id_histogram(frames: Iterable[Sequence[object]]) -> Counter:
    """Build the one-pass ID histogram used by structural prefiltering."""

    return Counter(int(frame[1]) for frame in frames)


def load_dbc_frame_ids(paths: Iterable[object]) -> frozenset[int]:
    """Parse only message definitions; no BLF frames are decoded here."""

    try:
        import cantools
    except ImportError as exc:
        raise ImportError(
            "cantools 未安装，无法预筛 DBC。请先 pip install cantools"
        ) from exc

    database = cantools.database.Database()
    for path in normalize_dbc_paths(paths):
        database.add_dbc_file(path)
    return frozenset(int(message.frame_id) for message in database.messages)


def structural_prefilter_score(
    blf_id_counts: Mapping[int, int], dbc_frame_ids: Iterable[int],
) -> StructuralScore:
    """Score overlap using unique IDs and their observed BLF frame weights."""

    counts = {
        int(frame_id): max(0, int(count))
        for frame_id, count in blf_id_counts.items()
    }
    dbc_ids = {int(frame_id) for frame_id in dbc_frame_ids}
    total_frames = sum(counts.values())
    total_ids = len(counts)
    matched_ids = set(counts).intersection(dbc_ids)
    matched_frames = sum(counts[frame_id] for frame_id in matched_ids)
    return StructuralScore(
        frame_coverage=(matched_frames / total_frames) if total_frames else 0.0,
        id_coverage=(len(matched_ids) / total_ids) if total_ids else 0.0,
        matched_id_count=len(matched_ids),
    )


def prefilter_candidates(candidates, blf_id_counts: Mapping[int, int]):
    """Attach structural scores and rank candidates for automatic probing."""

    scored = []
    for candidate in candidates:
        item = dict(candidate)
        item["structural_score"] = structural_prefilter_score(
            blf_id_counts,
            item.get("dbc_frame_ids", ()),
        )
        scored.append(item)
    return sorted(
        scored,
        key=lambda candidate: (
            candidate["structural_score"].frame_coverage,
            candidate["structural_score"].id_coverage,
            candidate["structural_score"].matched_id_count,
            int(candidate.get("recent_rank", 0)),
        ),
        reverse=True,
    )


#: Ordered best-to-worst.  ``incomplete`` sits between ``unverified`` and
#: ``mismatch``: the probe ran but was cut short (cancel / truncated /
#: corrupt tail), so it proved less than a full probe yet more than nothing.
#: Only ``mismatch`` is real negative evidence, and only it is unselectable.
CANDIDATE_STATUSES = ("strong", "weak", "unverified", "incomplete", "mismatch")


def candidate_status(candidate) -> str:
    """Return a truthful state; absent probe results are not mismatches."""

    probe = candidate.get("probe")
    if probe is None:
        return "mismatch" if candidate.get("probe_attempted") else "unverified"
    strength = str(getattr(probe, "strength", "none") or "none")
    if strength == "strong":
        return "strong"
    if strength == "weak":
        return "weak"
    # A probe that never finished cannot have proved a mismatch.  Anything it
    # did manage to decode is already reflected in ``strength`` above.
    if not bool(getattr(probe, "sampling_complete", True)):
        return "incomplete"
    return "mismatch"


def rank_candidates(candidates):
    """Rank by exact coverage and sample ratio, then structure/path/name."""

    status_rank = {
        status: len(CANDIDATE_STATUSES) - index
        for index, status in enumerate(CANDIDATE_STATUSES)
    }

    def exact_coverage(probe):
        if probe is None:
            return 0.0
        total = int(getattr(probe, "total_frame_count", 0) or 0)
        matched = getattr(probe, "matched_frame_count", None)
        if matched is None or total <= 0:
            return 0.0
        return float(matched) / float(total)

    def sample_ratio(probe):
        if probe is None:
            return 0.0
        value = getattr(probe, "sample_decode_success_ratio", None)
        if value is None:
            value = getattr(probe, "estimated_decoded_frame_ratio", None)
        return float(value or 0.0)

    def filename_key(candidate):
        paths = candidate.get("paths") or ()
        return tuple(
            os.path.normcase(os.path.basename(os.fspath(path)))
            for path in paths
        )

    def key(candidate):
        probe = candidate.get("probe")
        score = candidate.get("structural_score") or StructuralScore()
        signal_count = len(getattr(probe, "signal_names", ()) or ())
        return (
            -status_rank[candidate_status(candidate)],
            -exact_coverage(probe),
            -sample_ratio(probe),
            -signal_count,
            -score.frame_coverage,
            -score.id_coverage,
            -score.matched_id_count,
            -int(candidate.get("recent_rank", 0)),
            filename_key(candidate),
        )

    return sorted(candidates, key=key)
