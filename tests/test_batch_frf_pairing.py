from __future__ import annotations

from dataclasses import dataclass

import pytest

from mf4_analyzer.batch_frf import (
    FrfExecutionPlan,
    ResolvedFrfTask,
    SkippedFrfTask,
    resolve_frf_tasks,
)
from mf4_analyzer.batch_types import FrfPairRule


@dataclass(frozen=True)
class _Inventory:
    source_id: object
    group_id: str
    channel_names: tuple[str, ...] | None


def _rules():
    return (
        FrfPairRule("cmd_b", ("out_2", "out_1")),
        FrfPairRule("cmd_a", ("out_3",)),
    )


def test_resolver_expands_rule_then_output_then_source_order():
    sources = (
        _Inventory("source-2", "group-b", ("cmd_a", "cmd_b", "out_1", "out_2", "out_3")),
        _Inventory("source-1", "group-a", ("cmd_a", "cmd_b", "out_1", "out_2", "out_3")),
    )

    plan = resolve_frf_tasks(_rules(), sources, target_policy="common")

    assert isinstance(plan, FrfExecutionPlan)
    assert plan.issues == ()
    assert plan.estimated is False
    assert plan.tasks == (
        ResolvedFrfTask("source-2", "group-b", "cmd_b", "out_2"),
        ResolvedFrfTask("source-1", "group-a", "cmd_b", "out_2"),
        ResolvedFrfTask("source-2", "group-b", "cmd_b", "out_1"),
        ResolvedFrfTask("source-1", "group-a", "cmd_b", "out_1"),
        ResolvedFrfTask("source-2", "group-b", "cmd_a", "out_3"),
        ResolvedFrfTask("source-1", "group-a", "cmd_a", "out_3"),
    )


def test_duplicate_pair_across_rules_is_resolved_once_at_first_position():
    rules = (
        FrfPairRule("cmd", ("out", "angle")),
        FrfPairRule("cmd", ("out",)),
    )
    plan = resolve_frf_tasks(
        rules,
        (_Inventory("source", "group", ("cmd", "out", "angle")),),
        target_policy="common",
    )

    assert [(task.input_channel, task.output_channel) for task in plan.tasks] == [
        ("cmd", "out"), ("cmd", "angle"),
    ]


def test_common_policy_reports_each_missing_logical_source_pair_as_blocking():
    plan = resolve_frf_tasks(
        (FrfPairRule("cmd", ("out",)),),
        (
            _Inventory("complete", "group-1", ("cmd", "out")),
            _Inventory("missing-output", "group-2", ("cmd",)),
            _Inventory("missing-input", "group-3", ("out",)),
        ),
        target_policy="common",
    )

    assert plan.tasks == (
        ResolvedFrfTask("complete", "group-1", "cmd", "out"),
    )
    assert [issue.severity for issue in plan.issues] == ["error", "error"]
    assert [issue.field for issue in plan.issues] == [
        "output_channels", "input_channel",
    ]
    assert plan.has_blocking_issues is True


def test_available_per_source_skips_incomplete_pairs_with_warning_facts():
    plan = resolve_frf_tasks(
        (FrfPairRule("cmd", ("out",)),),
        (
            _Inventory("complete", "group-1", ("cmd", "out")),
            _Inventory("incomplete", "group-2", ("cmd",)),
        ),
        target_policy="available_per_source",
    )

    assert len(plan.tasks) == 1
    assert len(plan.issues) == 1
    assert plan.issues[0].severity == "warning"
    assert plan.issues[0].source_id == "incomplete"
    assert plan.has_blocking_issues is False
    assert plan.skipped_tasks == (
        SkippedFrfTask(
            "incomplete", "group-2", "cmd", "out", ("out",),
        ),
    )
    with pytest.raises((AttributeError, TypeError)):
        plan.skipped_tasks[0].source_id = "mutated"


def test_ordered_candidates_preserve_pair_output_source_order_across_skips():
    plan = resolve_frf_tasks(
        (FrfPairRule("cmd", ("out-1", "out-2")),),
        (
            _Inventory("partial", "group-1", ("cmd", "out-2")),
            _Inventory("complete", "group-2", ("cmd", "out-1", "out-2")),
        ),
        target_policy="available_per_source",
    )

    assert plan.ordered_candidates == (
        SkippedFrfTask("partial", "group-1", "cmd", "out-1", ("out-1",)),
        ResolvedFrfTask("complete", "group-2", "cmd", "out-1"),
        ResolvedFrfTask("partial", "group-1", "cmd", "out-2"),
        ResolvedFrfTask("complete", "group-2", "cmd", "out-2"),
    )
    assert plan.tasks == tuple(
        candidate for candidate in plan.ordered_candidates
        if not isinstance(candidate, SkippedFrfTask)
    )
    assert plan.skipped_tasks == tuple(
        candidate for candidate in plan.ordered_candidates
        if isinstance(candidate, SkippedFrfTask)
    )


def test_unknown_inventory_stays_deterministic_and_estimated_without_loading():
    class Descriptor:
        source_id = "unresolved-source"
        group_id = "unresolved-group"
        channel_names = None

        def load_sources(self):  # pragma: no cover - tripwire
            pytest.fail("pure FRF pair resolver must never load source samples")

    first = resolve_frf_tasks(
        (FrfPairRule("cmd", ("out",)),),
        (Descriptor(),),
        target_policy="common",
    )
    second = resolve_frf_tasks(
        (FrfPairRule("cmd", ("out",)),),
        (Descriptor(),),
        target_policy="common",
    )

    assert first == second
    assert first.estimated is True
    assert first.tasks == (
        ResolvedFrfTask("unresolved-source", "unresolved-group", "cmd", "out"),
    )
    assert first.issues[0].code == "channel_inventory_unknown"
    assert first.issues[0].severity == "warning"


def test_split_physical_file_is_resolved_by_logical_source_identity():
    plan = resolve_frf_tasks(
        (FrfPairRule("cmd", ("out",)),),
        (
            _Inventory("physical::fast", "fast", ("cmd", "out")),
            _Inventory("physical::slow", "slow", ("cmd",)),
        ),
        target_policy="available_per_source",
    )

    assert plan.tasks[0].source_id == "physical::fast"
    assert plan.tasks[0].group_identity == "fast"
    assert plan.issues[0].source_id == "physical::slow"


def test_resolver_rejects_unbound_identity_and_unknown_policy():
    with pytest.raises(ValueError, match="source_id"):
        resolve_frf_tasks(
            (FrfPairRule("cmd", ("out",)),),
            (_Inventory("", "group", ("cmd", "out")),),
            target_policy="common",
        )
    with pytest.raises(ValueError, match="target_policy"):
        resolve_frf_tasks(
            (FrfPairRule("cmd", ("out",)),),
            (_Inventory("source", "group", ("cmd", "out")),),
            target_policy="exact_pairs",
        )


def test_resolver_reports_empty_portable_rules_and_source_scope():
    no_rules = resolve_frf_tasks(
        (), (_Inventory("source", "group", ("cmd", "out")),),
        target_policy="common",
    )
    no_sources = resolve_frf_tasks(
        (FrfPairRule("cmd", ("out",)),), (), target_policy="common",
    )

    assert no_rules.has_blocking_issues is True
    assert no_rules.issues[0].field == "frf_pair_rules"
    assert no_sources.has_blocking_issues is True
    assert no_sources.issues[0].field == "source_ids"
