"""GUI-free metadata planning for Batch FRF input/output pairs.

This module owns only the no-load stage: already-bound logical source/group
identity, metadata channel inventory, portable pair rules, and estimated
missing-channel facts. It does not inspect real time arrays, infer sampling
rates, validate segment counts, reserve outputs, load samples, or compute FRF.
Those authoritative steps belong to the runner's later data preflight.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .batch_types import FrfPairRule


def _channel_name(value: object, *, field: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError(f"{field} must be a non-empty channel name")
    return name


@dataclass(frozen=True)
class ResolvedFrfTask:
    """One directional SISO task resolved against logical-source metadata."""

    source_id: object
    group_identity: str
    input_channel: str
    output_channel: str

    def __post_init__(self) -> None:
        if self.source_id is None or (
            isinstance(self.source_id, str) and not self.source_id.strip()
        ):
            raise ValueError("source_id must be bound before FRF pair planning")
        group_identity = str(self.group_identity or "").strip()
        if not group_identity:
            raise ValueError(
                "group_identity must be bound before FRF pair planning"
            )
        input_channel = _channel_name(
            self.input_channel, field="input_channel",
        )
        output_channel = _channel_name(
            self.output_channel, field="output_channel",
        )
        if input_channel == output_channel:
            raise ValueError("an FRF input channel cannot be paired with itself")
        object.__setattr__(self, "group_identity", group_identity)
        object.__setattr__(self, "input_channel", input_channel)
        object.__setattr__(self, "output_channel", output_channel)


@dataclass(frozen=True)
class SkippedFrfTask(ResolvedFrfTask):
    """One policy-allowed pair candidate skipped by metadata inventory."""

    missing_channels: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        missing = tuple(
            _channel_name(channel, field="missing_channels")
            for channel in tuple(self.missing_channels or ())
        )
        if not missing:
            raise ValueError("skipped FRF task requires missing_channels")
        if len(set(missing)) != len(missing):
            raise ValueError("missing_channels must be unique")
        allowed = {self.input_channel, self.output_channel}
        if any(channel not in allowed for channel in missing):
            raise ValueError("missing_channels must belong to the FRF pair")
        object.__setattr__(self, "missing_channels", missing)


@dataclass(frozen=True)
class FrfPairIssue:
    severity: Literal["error", "warning"]
    field: str
    code: str
    message: str
    source_id: object
    group_identity: str
    input_channel: str
    output_channel: str


@dataclass(frozen=True)
class FrfExecutionPlan:
    """Immutable metadata plan with ordered candidates as canonical truth.

    ``tasks`` and ``skipped_tasks`` remain additive compatibility projections;
    new orchestration must consume ``ordered_candidates`` so metadata skips do
    not move behind later runnable candidates.
    """

    tasks: tuple[ResolvedFrfTask, ...] = ()
    issues: tuple[FrfPairIssue, ...] = ()
    estimated: bool = False
    skipped_tasks: tuple[SkippedFrfTask, ...] = ()
    ordered_candidates: tuple[ResolvedFrfTask | SkippedFrfTask, ...] = ()

    def __post_init__(self) -> None:
        tasks = tuple(self.tasks or ())
        skipped_tasks = tuple(self.skipped_tasks or ())
        ordered_candidates = tuple(self.ordered_candidates or ())
        if ordered_candidates:
            if any(
                not isinstance(candidate, ResolvedFrfTask)
                for candidate in ordered_candidates
            ):
                raise TypeError(
                    "ordered_candidates must contain resolved FRF tasks"
                )
            projected_tasks = tuple(
                candidate for candidate in ordered_candidates
                if not isinstance(candidate, SkippedFrfTask)
            )
            projected_skips = tuple(
                candidate for candidate in ordered_candidates
                if isinstance(candidate, SkippedFrfTask)
            )
            if tasks and tasks != projected_tasks:
                raise ValueError(
                    "tasks must match the ordered_candidates compatibility view"
                )
            if skipped_tasks and skipped_tasks != projected_skips:
                raise ValueError(
                    "skipped_tasks must match the ordered_candidates compatibility view"
                )
            tasks = projected_tasks
            skipped_tasks = projected_skips
        else:
            if any(isinstance(task, SkippedFrfTask) for task in tasks):
                raise ValueError("tasks must not contain skipped FRF candidates")
            ordered_candidates = (*tasks, *skipped_tasks)
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "issues", tuple(self.issues or ()))
        object.__setattr__(self, "skipped_tasks", skipped_tasks)
        object.__setattr__(self, "ordered_candidates", ordered_candidates)

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


def _coerce_rule(value: object) -> FrfPairRule:
    if isinstance(value, FrfPairRule):
        return value
    if isinstance(value, Mapping):
        return FrfPairRule(
            value.get("input_channel", ""),
            tuple(value.get("output_channels") or ()),
        )
    raise TypeError("FRF pair rules must be FrfPairRule values or mappings")


def _inventory_facts(value: object) -> tuple[object, str, frozenset[str] | None]:
    if isinstance(value, Mapping):
        source_id = value.get("source_id")
        group_identity = value.get("group_identity", value.get("group_id", ""))
        raw_channels = value.get("channel_names")
    else:
        source_id = getattr(value, "source_id", None)
        group_identity = getattr(
            value, "group_identity", getattr(value, "group_id", ""),
        )
        raw_channels = getattr(value, "channel_names", None)
    if source_id is None or (
        isinstance(source_id, str) and not source_id.strip()
    ):
        raise ValueError("source_id must be bound before FRF pair planning")
    group_identity = str(group_identity or "").strip()
    if not group_identity:
        raise ValueError("group_identity must be bound before FRF pair planning")
    channels = None if raw_channels is None else frozenset(
        _channel_name(item, field="channel_names") for item in raw_channels
    )
    return source_id, group_identity, channels


def resolve_frf_tasks(
    pair_rules: Iterable[FrfPairRule | Mapping[str, object]],
    source_inventories: Iterable[object],
    *,
    target_policy: str = "common",
) -> FrfExecutionPlan:
    """Expand portable rules using metadata inventories without sample loads.

    Ordering is stable and user-driven: pair-rule, output, then selected logical
    source. Unknown inventories produce deterministic unresolved tasks plus
    estimated warnings; they are not treated as evidence that channels exist.
    """

    policy = str(target_policy or "").strip().lower()
    if policy not in {"common", "available_per_source"}:
        raise ValueError(
            "target_policy must be common or available_per_source for FRF"
        )

    rules = tuple(_coerce_rule(rule) for rule in pair_rules)
    sources = tuple(_inventory_facts(source) for source in source_inventories)
    if not rules:
        return FrfExecutionPlan((), (FrfPairIssue(
            "error", "frf_pair_rules", "required",
            "at least one FRF input/output pair rule is required",
            None, "", "", "",
        ),))
    if not sources:
        return FrfExecutionPlan((), (FrfPairIssue(
            "error", "source_ids", "required",
            "at least one logical source is required for FRF planning",
            None, "", "", "",
        ),))
    source_keys = [(source_id, group) for source_id, group, _channels in sources]
    if len(set(source_keys)) != len(source_keys):
        raise ValueError("logical source/group inventories must be unique")

    ordered_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for rule in rules:
        for output_channel in rule.output_channels:
            pair = (rule.input_channel, output_channel)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                ordered_pairs.append(pair)

    ordered_candidates: list[ResolvedFrfTask | SkippedFrfTask] = []
    issues: list[FrfPairIssue] = []
    estimated = False
    missing_severity: Literal["error", "warning"] = (
        "error" if policy == "common" else "warning"
    )
    for input_channel, output_channel in ordered_pairs:
        for source_id, group_identity, channels in sources:
            if channels is None:
                estimated = True
                task = ResolvedFrfTask(
                    source_id, group_identity, input_channel, output_channel,
                )
                ordered_candidates.append(task)
                issues.append(FrfPairIssue(
                    "warning", "frf_pair_rules", "channel_inventory_unknown",
                    "channel inventory is unresolved; data preflight must verify both channels",
                    source_id, group_identity, input_channel, output_channel,
                ))
                continue

            input_missing = input_channel not in channels
            output_missing = output_channel not in channels
            if not input_missing and not output_missing:
                task = ResolvedFrfTask(
                    source_id, group_identity, input_channel, output_channel,
                )
                ordered_candidates.append(task)
                continue
            if policy == "available_per_source":
                skipped_task = SkippedFrfTask(
                    source_id,
                    group_identity,
                    input_channel,
                    output_channel,
                    tuple(
                        channel for channel, missing in (
                            (input_channel, input_missing),
                            (output_channel, output_missing),
                        )
                        if missing
                    ),
                )
                ordered_candidates.append(skipped_task)
            if input_missing:
                issues.append(FrfPairIssue(
                    missing_severity, "input_channel", "missing_input_channel",
                    f"logical source does not contain FRF input {input_channel!r}",
                    source_id, group_identity, input_channel, output_channel,
                ))
            if output_missing:
                issues.append(FrfPairIssue(
                    missing_severity, "output_channels", "missing_output_channel",
                    f"logical source does not contain FRF output {output_channel!r}",
                    source_id, group_identity, input_channel, output_channel,
                ))

    return FrfExecutionPlan(
        issues=tuple(issues),
        estimated=estimated,
        ordered_candidates=tuple(ordered_candidates),
    )


__all__ = [
    "FrfExecutionPlan",
    "FrfPairIssue",
    "ResolvedFrfTask",
    "SkippedFrfTask",
    "resolve_frf_tasks",
]
