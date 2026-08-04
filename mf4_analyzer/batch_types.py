"""Batch data contracts: presets, item results, run results, events.

Pure dataclasses (plus two control-flow exceptions) shared by ``batch.py``
and its satellite modules. No runner state, no Qt, no heavy imports --
this module exists so the data shapes can be depended on without pulling
in ``BatchRunner`` itself.

``batch.py`` re-exports every name here for backward compatibility; new
code should prefer importing directly from this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping

from .batch_validation import resolve_output_image_dimensions

if TYPE_CHECKING:
    from .batch_series_spool import SpooledSeriesRef


@dataclass(frozen=True)
class BatchOutput:
    export_data: bool = True
    export_image: bool = True
    data_format: str = 'csv'
    image_format: str = 'png'
    image_size: str = '1920x1080'
    image_width: int = 1920
    image_height: int = 1080
    image_dpi: int = 144
    image_background: str = 'white'
    image_line_width: float = 1.5
    conflict_policy: str = 'auto_number'
    write_manifest: bool = True
    resume_policy: str = 'none'
    requested_image_format: str | None = None
    migration_warnings: tuple[str, ...] = ()

    def resolved_image_dimensions(self) -> tuple[int, int]:
        return resolve_output_image_dimensions(self)


@dataclass(frozen=True)
class BatchOutputPreview:
    task_count: int
    artifact_count: int
    conflict_count: int
    image_format: str
    image_width: int
    image_height: int
    image_dpi: int
    conflict_policy: str
    estimated: bool = True
    group_count: int = 0
    data_artifact_count: int = 0
    image_artifact_count: int = 0
    data_conflict_count: int = 0
    image_conflict_count: int = 0
    representative_group: "BatchRepresentativeGroup | None" = None


@dataclass(frozen=True)
class BatchRepresentativeGroup:
    """One deterministic, no-load render-group description for UI preview."""

    group_id: str
    display_name: str
    group_by: str
    member_count: int
    required_source_count: int
    planned_stem: str
    ordinal: int
    total_groups: int
    # False only when the caller supplied a source→channel map and *no*
    # planned group turned out to hold the selected channels.  Defaults to
    # True so callers that plan without the map keep the old contract.
    channel_available: bool = True


@dataclass(frozen=True)
class BatchPreviewResult:
    """The private, image-only result returned by :meth:`preview_group`."""

    image_path: str | None
    group_id: str
    display_name: str
    loaded_source_count: int
    warnings: tuple[str, ...] = ()
    status: str = "blocked"
    message: str = ""


@dataclass
class AnalysisPreset:
    name: str
    method: str
    source: str
    params: dict = field(default_factory=dict)
    outputs: BatchOutput = field(default_factory=BatchOutput)
    signal: tuple | None = None
    rpm_signal: tuple | None = None
    signal_pattern: str = ''
    rpm_channel: str = ''
    # NEW (configuration; free_config only)
    target_signals: tuple = ()
    # NEW (run-time selection; free_config only; injected via dataclasses.replace)
    target_pairs: tuple = ()
    source_ids: tuple = ()
    source_paths: tuple = ()
    target_policy: str = 'common'
    file_ids: tuple = ()
    file_paths: tuple = ()

    @classmethod
    def from_current_single(cls, name, method, signal, params=None,
                            outputs=None, rpm_channel='', rpm_signal=None,
                            target_signals=None, file_ids=None, file_paths=None):
        if target_signals:
            raise ValueError(
                "target_signals is a free_config-only field; "
                "use AnalysisPreset.free_config instead"
            )
        if file_ids or file_paths:
            raise ValueError(
                "file_ids / file_paths are run-time selection fields; "
                "inject via dataclasses.replace, not from_current_single"
            )
        return cls(
            name=str(name or 'current analysis'),
            method=str(method),
            source='current_single',
            signal=tuple(signal) if signal is not None else None,
            rpm_signal=tuple(rpm_signal) if rpm_signal is not None else None,
            rpm_channel=str(rpm_channel or ''),
            params=dict(params or {}),
            outputs=outputs or BatchOutput(),
        )

    @classmethod
    def free_config(cls, name, method, signal_pattern='', rpm_channel='',
                    params=None, outputs=None, target_signals=None,
                    target_policy='common',
                    file_ids=None, file_paths=None):
        if file_ids:
            raise ValueError(
                "file_ids is a run-time selection field; "
                "inject via dataclasses.replace after free_config()"
            )
        if file_paths:
            raise ValueError(
                "file_paths is a run-time selection field; "
                "inject via dataclasses.replace after free_config()"
            )
        return cls(
            name=str(name or 'custom batch'),
            method=str(method),
            source='free_config',
            signal_pattern=str(signal_pattern or ''),
            rpm_channel=str(rpm_channel or ''),
            target_signals=tuple(target_signals or ()),
            target_policy=str(target_policy or 'common'),
            params=dict(params or {}),
            outputs=outputs or BatchOutput(),
        )


@dataclass
class BatchItemResult:
    method: str
    file_id: object
    file_name: str
    signal: str
    status: str
    data_path: str | None = None
    image_path: str | None = None
    message: str = ''
    # dB-reference-defaults Task 9 (spec §15 C4): output metadata kept for
    # tests -- never exported into the linear CSV/DataFrame columns.
    colorbar_label: str | None = None
    db_reference_value: float | None = None
    db_reference_source: str | None = None
    task_id: str = ''
    source_identity: str = ''
    group_identity: str = ''
    effective_params: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    requested_outputs: dict = field(default_factory=dict)
    effective_outputs: dict = field(default_factory=dict)
    degraded_reason: str = ''
    artifact_facts: dict = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class EffectiveOutputPlan:
    requested: Mapping[str, str]
    effective: Mapping[str, str]
    render_backend_types: tuple[type, type] | None
    degraded_reason: str
    migration_warnings: tuple[str, ...] = ()


@dataclass
class TaskComputeResult:
    item: BatchItemResult
    series_refs: tuple[SpooledSeriesRef, ...] = ()
    render_error: str = ''
    render_status: str = ''


@dataclass
class RenderGroupResult:
    group_id: str
    status: str
    image_path: str | None = None
    message: str = ''
    warnings: list[str] = field(default_factory=list)
    artifact: dict[str, Any] | None = None
    effective_facts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GroupRecoveryDecision:
    data_write_task_ids: frozenset[str]
    payload_task_ids: frozenset[str]
    image_write_required: bool
    reusable_group: Mapping[str, Any] | None


@dataclass
class BatchRunResult:
    status: str
    items: list[BatchItemResult] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    summary: dict = field(default_factory=dict)
    run_id: str | None = None
    degraded_count: int = 0
    warnings: list[str] = field(default_factory=list)
    render_groups: list[RenderGroupResult] = field(default_factory=list)


@dataclass
class BatchProgressEvent:
    kind: Literal[
        'task_started', 'task_done', 'task_failed',
        'task_cancelled', 'task_skipped', 'task_resumed', 'run_finished',
    ]
    task_index: int | None = None
    total: int | None = None
    file_name: str | None = None
    signal: str | None = None
    method: str | None = None
    error: str | None = None        # task_failed only
    final_status: str | None = None  # run_finished only
    task_id: str | None = None
    message: str | None = None
    data_path: str | None = None
    image_path: str | None = None


@dataclass
class _LoadFailure:
    """Sentinel returned by ``BatchRunner._resolve_files`` when a disk path
    cannot be loaded. ``_expand_tasks`` still yields tasks for it; ``run``
    converts each to a ``task_failed`` event with the cached error.
    """
    path: str
    error: str


@dataclass(frozen=True)
class _ResolvedSource:
    """One logical source resident under a physical-file cache entry."""

    source_id: object
    physical_path: str
    group_id: str
    file_data: object
    display_name: str


class _BatchCancelled(RuntimeError):
    pass


class _ImageBackendUnavailable(RuntimeError):
    """The task cannot proceed because it requested only rendered output."""
