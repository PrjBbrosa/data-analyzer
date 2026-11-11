"""Match saved project file rows to reloaded logical sources.

One physical file can expand into several logical sources. Project restore
must not pair a saved row with whichever group happens to load in that
slot. This module is the pairing rule. It does not read files, touch Qt,
or guess a sampling rate.

Levels, in order:

1. ``identity`` — the saved ``source_group`` equals one loaded group id.
2. ``evidence`` — among what is left, the saved loader channel names (and,
   only as a tie-break, a file-measured sampling rate) produce exactly one
   one-to-one assignment.
3. ``sole`` — one saved row and one loaded group are all that remain. That
   group is the file, so recipes and the saved sampling rate are applied
   even when the row has no channel list. A changed column then surfaces as
   an ordinary skipped recipe, not as an unconfirmed source.
4. ``unverified`` — more than one row or group is still unassigned and the
   evidence is not unique. Equal counts keep relative position, and nothing
   that changes numbers is applied.
5. ``missing`` — a saved row has no loaded group left. The file is not
   loaded a second time.

An empty channel list is not evidence. ``root`` is the single-source id and
is not a split-source identity, so it never counts as level 1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LEVEL_IDENTITY = "identity"
LEVEL_EVIDENCE = "evidence"
LEVEL_SOLE = "sole"
LEVEL_UNVERIFIED = "unverified"
LEVEL_MISSING = "missing"

UNVERIFIED_SOURCE_REASON = "来源对应关系无法确认"

_RATE_RELATIVE = 1e-4
_NON_EVIDENCE_TIME_SOURCES = frozenset({"manual", "generated"})


@dataclass(frozen=True)
class SourceRefFact:
    """One saved file row, reduced to the facts the pairing rule needs."""

    key: str
    group_id: str
    loader_channels: frozenset[str]
    fs: float | None
    time_source: str


@dataclass(frozen=True)
class SourceCandidateFact:
    """One logical source produced by loading the file once."""

    key: str
    group_id: str
    channels: frozenset[str]
    measured_fs: float | None


@dataclass(frozen=True)
class SourceAssignment:
    """Where one saved row landed, and how sure the pairing is."""

    ref_key: str
    candidate_key: str | None
    level: str


def loader_channel_names(channel_order, channel_edits) -> frozenset[str]:
    """Names the loader produced, reconstructed from a saved row.

    Derived names are subtracted. Names a recipe removed are added back,
    unless that name is itself a derive output.
    """
    derived: set[str] = set()
    removed: set[str] = set()
    for item in channel_edits or ():
        if not isinstance(item, dict):
            continue
        op = item.get("op")
        if op == "derive":
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                derived.add(name.strip())
        elif op == "remove":
            for name in item.get("names") or ():
                text = str(name).strip()
                if text:
                    removed.add(text)
    names: set[str] = set()
    for name in channel_order or ():
        text = str(name).strip()
        if text and text not in derived:
            names.add(text)
    names.update(name for name in removed if name not in derived)
    return frozenset(names)


def match_project_sources(
    refs: tuple[SourceRefFact, ...] | list[SourceRefFact],
    candidates: tuple[SourceCandidateFact, ...] | list[SourceCandidateFact],
) -> tuple[SourceAssignment, ...]:
    """Pair one path's saved rows with the groups a single load produced."""
    assigned: dict[str, tuple[str | None, str]] = {}
    used: set[str] = set()

    by_identity: dict[str, list[SourceCandidateFact]] = {}
    for candidate in candidates:
        identity = _split_identity(candidate.group_id)
        if identity:
            by_identity.setdefault(identity, []).append(candidate)
    for ref in refs:
        identity = _split_identity(ref.group_id)
        if not identity:
            continue
        options = [
            candidate for candidate in by_identity.get(identity, ())
            if candidate.key not in used
        ]
        if len(options) != 1:
            continue
        assigned[ref.key] = (options[0].key, LEVEL_IDENTITY)
        used.add(options[0].key)

    rest_refs = [ref for ref in refs if ref.key not in assigned]
    rest_candidates = [candidate for candidate in candidates if candidate.key not in used]
    evidence = _unique_evidence(rest_refs, rest_candidates)
    if evidence:
        for ref_key, candidate_key in evidence.items():
            assigned[ref_key] = (candidate_key, LEVEL_EVIDENCE)
            used.add(candidate_key)

    left_refs = [ref for ref in refs if ref.key not in assigned]
    left_candidates = [candidate for candidate in candidates if candidate.key not in used]
    if len(left_refs) == 1 and len(left_candidates) == 1:
        assigned[left_refs[0].key] = (left_candidates[0].key, LEVEL_SOLE)
        left_refs = []
        left_candidates = []
    paired = min(len(left_refs), len(left_candidates))
    for ref, candidate in zip(left_refs[:paired], left_candidates[:paired]):
        assigned[ref.key] = (candidate.key, LEVEL_UNVERIFIED)
    for ref in left_refs[paired:]:
        assigned[ref.key] = (None, LEVEL_MISSING)

    return tuple(
        SourceAssignment(ref.key, assigned[ref.key][0], assigned[ref.key][1])
        for ref in refs
    )


def _split_identity(value) -> str:
    text = str(value or "").strip()
    if not text or text == "root":
        return ""
    return text


def _rates_agree(saved, measured) -> bool:
    if saved is None or measured is None:
        return False
    if not math.isfinite(saved) or not math.isfinite(measured):
        return False
    scale = max(abs(saved), abs(measured), 1.0)
    return abs(saved - measured) <= _RATE_RELATIVE * scale


def _evidence_options(ref: SourceRefFact, candidates) -> list[SourceCandidateFact]:
    if not ref.loader_channels:
        return []
    options = [
        candidate for candidate in candidates
        if ref.loader_channels <= candidate.channels
    ]
    if (
        len(options) > 1
        and ref.time_source not in _NON_EVIDENCE_TIME_SOURCES
    ):
        narrowed = [
            candidate for candidate in options
            if _rates_agree(ref.fs, candidate.measured_fs)
        ]
        if narrowed:
            options = narrowed
    return options


def _unique_evidence(refs, candidates) -> dict[str, str] | None:
    """The one covering assignment, or None when it is missing or not unique.

    An empty result means no row had evidence. ``None`` means the rows that
    did have evidence do not line up in exactly one way, so none of them
    may be treated as confirmed.
    """
    edged = [
        (ref, _evidence_options(ref, candidates))
        for ref in refs
    ]
    edged = [(ref, options) for ref, options in edged if options]
    if not edged:
        return {}
    found: list[dict[str, str]] = []

    def walk(index: int, used: set[str], chosen: dict[str, str]) -> None:
        if len(found) > 1:
            return
        if index == len(edged):
            found.append(dict(chosen))
            return
        ref, options = edged[index]
        for candidate in options:
            if candidate.key in used:
                continue
            used.add(candidate.key)
            chosen[ref.key] = candidate.key
            walk(index + 1, used, chosen)
            del chosen[ref.key]
            used.remove(candidate.key)

    walk(0, set(), {})
    if len(found) != 1:
        return None
    return found[0]
