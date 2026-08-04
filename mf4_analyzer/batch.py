"""Batch analysis presets and GUI-free runner.

Two preset entry points are supported:

* ``from_current_single``: capture the currently selected one-off analysis.
* ``free_config``: describe a reusable rule that selects matching signals.

The runner intentionally depends only on ``FileData`` plus pure analysis and
output modules, so a desktop worker can delegate work without GUI objects.

Data contracts (presets, item/run results, progress events) live in
``batch_types``; this module re-exports them for backward compatibility.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence
import re
import threading
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import db_reference
from .batch_output import (
    OutputPublishRace,
    atomic_write,
    atomic_write_set,
    build_task_output_identity,
    reserve_output_paths,
)
from .batch_grouping import RenderGroup, RenderTask, group_render_tasks
from .batch_manifest import (
    BatchManifestRecorder,
    GroupMemberResumeFact,
    ManifestRecipeMismatch,
    RetryScope,
    artifact_facts,
    derive_summary,
    find_resumable_entry,
    find_resumable_group,
    load_batch_manifest,
    retry_failed_scope,
    source_file_facts,
    utc_now,
)
from .batch_preprocess import BatchPreprocessResult, preprocess_batch_signal
from .batch_recipe import normalize_batch_params, recipe_fingerprint
from .renderer_import_policy import is_optional_renderer_import_error
from .batch_types import (
    AnalysisPreset,
    BatchItemResult,
    BatchOutput,
    BatchOutputPreview,
    BatchPreviewResult,
    BatchProgressEvent,
    BatchRepresentativeGroup,
    BatchRunResult,
    EffectiveOutputPlan,
    GroupRecoveryDecision,
    RenderGroupResult,
    TaskComputeResult,
    _BatchCancelled,
    _ImageBackendUnavailable,
    _LoadFailure,
    _ResolvedSource,
)
from .batch_validation import (
    raise_for_issues,
    validate_outputs,
    validate_recipe,
    validate_task,
)
from .io.source_adapters import (
    DEFAULT_SOURCE_ADAPTER_REGISTRY,
    LoadedSource,
    SourceUnavailableError,
    canonical_source_path,
)
from .signal import resolve_nfft, resolve_order_nfft
from .signal.fft import FFTAnalyzer

if TYPE_CHECKING:
    from .batch_render import BatchSeries, BatchTimeFigureSpec
    from .batch_series_spool import BatchSeriesSpool, SpooledSeriesRef


_RENDER_BACKEND_DEGRADED_REASON = (
    '图片/PDF 导出后端不可用，本次仅导出数据文件'
)
_RENDER_BACKEND_IMAGE_ONLY_ERROR = (
    '图片/PDF 导出后端不可用，无法完成图片/PDF 导出'
)
_LEGACY_IMAGE_FORMATS = frozenset({'pdf', 'svg'})


def _legacy_image_format_warning(requested_format: object) -> str:
    requested = str(requested_format or '').strip().upper()
    return f'旧预设图像格式 {requested} 已迁移为 PNG；本次仅输出 PNG。'
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

#: Sheet name and column prefix per *fixed* dimension, keyed by the
#: ``_Spectro2D`` axis name that dimension carries (design §6.2).
_SLICE_AXIS_LABELS = {
    'time_s': ('时间', '时间切片', 't', 's', 2),
    'frequency_hz': ('频率', '频率切片', 'f', 'Hz', 1),
    'order': ('阶次', '阶次切片', '阶次', '', 2),
}


def _slice_axis_labels(axis_name: str):
    """``(dimension, sheet, prefix, unit, decimals)`` for one matrix axis."""
    return _SLICE_AXIS_LABELS.get(
        str(axis_name or '').strip().lower(), ('切片', '切片', axis_name, '', 2)
    )


def _load_slice_render_contract():
    """The renderer's own slice helpers, or ``None`` when it is not installed.

    Acceptance item 11 requires the workbook to reproduce the *drawn* curve
    exactly, so the grid snapping (``plan_heatmap_slice``), the amplitude scale
    decision (``_render_in_db``) and the dB reference lookup all come from the
    renderer rather than from a second implementation here. Two calculation
    paths would be free to drift; one cannot.

    ``batch.py`` itself stays GUI-free: its caller loads this contract only
    after confirming that slicing is enabled. The caller falls back to the
    historical long table when the optional Qt renderer is absent -- in that
    case no curve was drawn, so there is nothing for the table to match.
    """
    try:
        from .batch_render_qt._builder import (
            _linear_amplitude_label,
            _render_in_db,
            _slice_clamp_warning,
        )
        from .batch_render_qt._models import plan_heatmap_slice
        from .batch_render_qt._page import _DEFAULT_METHOD, effective_fact_items
    except ImportError as exc:
        if not is_optional_renderer_import_error(exc):
            raise
        return None
    return SimpleNamespace(
        plan_heatmap_slice=plan_heatmap_slice,
        render_in_db=_render_in_db,
        linear_amplitude_label=_linear_amplitude_label,
        # Same wording the chart emits, so a run that exports both artifacts
        # cannot report the same clamp twice in two different phrasings.
        slice_clamp_warning=_slice_clamp_warning,
        # Same picker the page header uses, so the workbook can never say
        # ``NFFT=512`` under a chart drawn with ``NFFT=1024`` (plan §5.2).
        effective_fact_items=effective_fact_items,
        method_labels=_DEFAULT_METHOD,
    )


#: ``effective_fact_items`` emits ``key=value`` strings sized for a one-line
#: page header. The workbook has a whole column, so each key gets a readable
#: Chinese label -- the *values* still arrive from that one shared function.
_SLICE_FACT_LABELS = {
    'window': '窗',
    'NFFT': 'NFFT',
    'weighting': '计权',
    'averaging': '平均',
    'overlap': '重叠',
    'Fs': '采样率 Fs',
    'members': '成员',
}


def _slice_fact_rows(items) -> list[tuple[str, str]]:
    rows = []
    for item in items:
        text = str(item)
        key, sep, value = text.partition('=')
        if not sep:
            continue
        rows.append((_SLICE_FACT_LABELS.get(key, key), value))
    return rows


def _default_loader(path):
    """Compatibility loader backed by the shared source registry.

    ``BatchRunner`` consumes the registry's full ``LoadedSource`` tuple so it
    can retain multi-group identity.  This legacy helper keeps returning a
    ``FileData`` for single-source direct callers and returns a tuple of
    ``FileData`` objects only when the physical container has multiple groups.
    Unknown extensions fail in the registry instead of falling through to MDF.
    """

    loaded = DEFAULT_SOURCE_ADAPTER_REGISTRY.load_sources(path)
    file_data = tuple(source.file_data for source in loaded)
    return file_data[0] if len(file_data) == 1 else file_data


class BatchRunner:
    SUPPORTED_METHODS = {'time', 'fft', 'order_time', 'fft_time'}

    def __init__(self, files, loader: Callable | None = None, *,
                 source_registry=None, source_context=None,
                 db_reference_catalog=None, prefer_channel_metadata=True):
        self.files = files
        self._loader = loader
        self._source_registry = (
            source_registry or DEFAULT_SOURCE_ADAPTER_REGISTRY
        )
        self._source_context = dict(source_context or {})
        self._disk_cache: dict[str, object] = {}
        self._source_cache: dict[object, _ResolvedSource] = {}
        self._source_channel_cache: dict[object, frozenset[str]] = {}
        self._source_locators: dict[object, str] = {}
        self._source_group_identity_hints: dict[object, str] = {}
        self._descriptor_probe_cache: set[str] = set()
        self._descriptor_source_ids: dict[str, tuple[object, ...]] = {}
        self._descriptor_probe_failures: dict[str, str] = {}
        self._physical_paths: dict[str, str] = {}
        # dB-reference-defaults Task 9 (spec §13 S4 / plan Step 9.2):
        # ``db_reference_catalog`` is an immutable, DUCK-TYPED snapshot
        # exposing ``system_catalog``/``user_catalog`` (see
        # ``mf4_analyzer.ui.db_reference_settings.DbReferenceCatalogSnapshot``)
        # -- this module never imports that settings-backed type, it
        # only reads plain attributes off whatever object the caller passes,
        # so Batch/worker code stays free of desktop settings imports.
        # ``None`` (every pre-Task-9 direct caller/test) resolves against the
        # immutable factory catalog with no user overrides -- unchanged
        # legacy behaviour. ``prefer_channel_metadata`` is a SEPARATE
        # argument (not read off the snapshot) so a caller can pass the
        # service's current preference explicitly alongside its catalog.
        if db_reference_catalog is not None:
            self._db_reference_system_catalog = tuple(
                getattr(db_reference_catalog, 'system_catalog', ()) or ()
            )
            self._db_reference_user_catalog = tuple(
                getattr(db_reference_catalog, 'user_catalog', ()) or ()
            )
        else:
            self._db_reference_system_catalog = db_reference.FACTORY_CATALOG_V1
            self._db_reference_user_catalog = ()
        self._prefer_channel_metadata = bool(prefer_channel_metadata)

    @staticmethod
    def _output_extensions(outputs) -> tuple[str, ...]:
        extensions = []
        if outputs.export_data:
            data_format = str(outputs.data_format).lower().lstrip('.')
            extensions.append(data_format if data_format == 'xlsx' else 'csv')
        if outputs.export_image:
            extensions.append(
                str(getattr(outputs, 'image_format', 'png')).lower().lstrip('.')
            )
        return tuple(extensions)

    @staticmethod
    def _required_artifacts(outputs) -> dict[str, str]:
        required = {}
        if outputs.export_data:
            data_format = str(outputs.data_format).lower().lstrip('.')
            required['data'] = data_format if data_format == 'xlsx' else 'csv'
        if outputs.export_image:
            required['image'] = str(
                getattr(outputs, 'image_format', 'png')
            ).lower().lstrip('.')
        return required

    @classmethod
    def _requested_artifacts(cls, outputs) -> dict[str, str]:
        requested = cls._required_artifacts(outputs)
        if outputs.export_image:
            provenance = getattr(outputs, 'requested_image_format', None)
            if provenance not in (None, ''):
                requested['image'] = str(provenance).lower().lstrip('.')
        return requested

    @staticmethod
    def _probe_image_backend():
        """Import the renderer types before reserving any output paths."""

        from .batch_render import BatchRenderContext, BatchRenderOptions

        return BatchRenderContext, BatchRenderOptions

    @staticmethod
    def _is_allowed_renderer_import_failure(exc: ImportError) -> bool:
        """Return whether a probe failure means the optional renderer is absent.

        The probe may degrade only for a genuinely unavailable renderer stack.
        An import defect inside the application's UI graph is a programming
        error, not a reason to silently drop requested images.
        """
        return is_optional_renderer_import_error(exc)

    def _resolve_effective_outputs(self, outputs) -> EffectiveOutputPlan:
        """Resolve one immutable renderer decision for the complete run."""

        requested = self._requested_artifacts(outputs)
        effective = self._required_artifacts(outputs)
        render_backend_types = None
        degraded_reason = ''
        migration_warnings = list(
            getattr(outputs, 'migration_warnings', ()) or ()
        )
        requested_image = requested.get('image')
        effective_image = effective.get('image')
        if (
            requested_image in _LEGACY_IMAGE_FORMATS
            and effective_image == 'png'
        ):
            migration_warnings.append(
                _legacy_image_format_warning(requested_image)
            )
        migration_warnings = list(dict.fromkeys(
            str(item) for item in migration_warnings if item
        ))
        if 'image' in effective:
            try:
                render_backend_types = self._probe_image_backend()
            except ImportError as exc:
                if not self._is_allowed_renderer_import_failure(exc):
                    raise
                if 'data' not in requested:
                    raise _ImageBackendUnavailable(
                        _RENDER_BACKEND_IMAGE_ONLY_ERROR
                    ) from exc
                effective.pop('image')
                degraded_reason = _RENDER_BACKEND_DEGRADED_REASON
        return EffectiveOutputPlan(
            requested=dict(requested),
            effective=effective,
            render_backend_types=render_backend_types,
            degraded_reason=degraded_reason,
            migration_warnings=tuple(migration_warnings),
        )

    @staticmethod
    def _requested_output_settings(outputs) -> dict:
        try:
            return asdict(outputs)
        except TypeError:
            return {
                field_name: getattr(outputs, field_name)
                for field_name in (
                    'export_data', 'export_image', 'data_format',
                    'image_format', 'image_size', 'image_width',
                    'image_height', 'image_dpi', 'image_background',
                    'image_line_width', 'conflict_policy',
                    'write_manifest', 'resume_policy',
                    'requested_image_format', 'migration_warnings',
                )
                if hasattr(outputs, field_name)
            }

    @staticmethod
    def _lazy_pattern_execution_scope(preset) -> dict[str, Any] | None:
        """Return the complete portable proof for a lazy pattern task scope."""

        source_paths = tuple(getattr(preset, 'source_paths', ()) or ())
        if (
            getattr(preset, 'source', '') == 'current_single'
            or not source_paths
            or tuple(getattr(preset, 'target_pairs', ()) or ())
            or tuple(getattr(preset, 'target_signals', ()) or ())
        ):
            return None
        return {
            'mode': 'lazy_pattern',
            'source_paths': [
                str(Path(path).expanduser().resolve(strict=False))
                for path in source_paths
            ],
            'signal_pattern': str(
                getattr(preset, 'signal_pattern', '') or ''
            ).strip(),
        }

    @staticmethod
    def _pick_representative_group(groups, source_channels):
        """Return ``(ordinal, group, channel_available)`` for the preview.

        One physical file may expand into several logical sources (HDF splits
        by sample rate), and a selected channel commonly lives in only some of
        them.  Planning stays deliberately no-load, so the runner cannot see
        which channels a source holds — but the caller can: BatchSheet already
        has the probe result.  ``source_channels`` maps a source key to its
        channel names; sources missing from the map are unknown, not empty, so
        they never disqualify a group.

        Without the map the first planned group wins, exactly as before.
        """

        if not source_channels:
            return 1, groups[0], True
        known = {
            key: frozenset(str(name) for name in names)
            for key, names in source_channels.items()
        }
        for ordinal, group in enumerate(groups, start=1):
            if all(
                member.channel in known[member.source_key]
                for member in group.members
                if member.source_key in known
            ):
                return ordinal, group, True
        return 1, groups[0], False

    def preview_outputs(
        self, preset, output_dir, *, source_channels=None,
    ) -> BatchOutputPreview:
        """Return UI-safe output counts without loading unresolved sources.

        ``source_channels`` is an optional ``{source key: channel names}`` map
        used only to pick a representative group the user can actually see
        rendered; omitting it preserves the historical planning result.
        """

        output_issues = validate_outputs(preset.outputs)
        if output_issues:
            raise ValueError('; '.join(str(issue) for issue in output_issues))
        tasks = list(self._expand_tasks(preset, allow_source_load=False))
        requested_params = normalize_batch_params(preset.params, preset.method)
        render_tasks = []
        for source_key, channel in tasks:
            fd = self._known_file_data(source_key)
            if fd is not None:
                identity = self._build_task_identity(
                    fd,
                    file_id=source_key,
                    channel=channel,
                    method=preset.method,
                    params=requested_params,
                )
            else:
                identity = self._build_unresolved_task_identity(
                    source_key,
                    channel=channel,
                    method=preset.method,
                    params=requested_params,
                    group_identity=self._source_group_identity_hints.get(
                        source_key,
                    ),
                )
            render_tasks.append(RenderTask(source_key, channel, identity))

        required = self._required_artifacts(preset.outputs)
        output_dir = Path(output_dir)
        data_extension = required.get('data')
        image_extension = required.get('image')
        data_conflicting_tasks = set()
        if data_extension is not None:
            for task in render_tasks:
                path = output_dir / f'{task.identity.stem}.{data_extension}'
                if path.exists():
                    data_conflicting_tasks.add(task.identity.task_id)

        group_by = str(requested_params.get(
            'render_group_by', 'none',
        ) or 'none').strip().lower()
        groups = (
            group_render_tasks(render_tasks, requested_params)
            if image_extension is not None else ()
        )
        # Ungrouped formal runs execute ``_expand_tasks`` order.  The grouping
        # helper intentionally sorts singleton groups for stable identities,
        # so restore execution order here before selecting the representative.
        if group_by == 'none' and groups:
            groups_by_id = {group.identity.group_id: group for group in groups}
            groups = tuple(
                groups_by_id[task.identity.task_id] for task in render_tasks
            )
        image_conflicting_groups = set()
        image_conflicting_tasks = set()
        for group in groups:
            path = output_dir / f'{group.identity.stem}.{image_extension}'
            if not path.exists():
                continue
            image_conflicting_groups.add(group.identity.group_id)
            if group.group_by == 'none':
                image_conflicting_tasks.update(
                    member.identity.task_id for member in group.members
                )

        data_conflict_count = len(data_conflicting_tasks)
        image_conflict_count = len(image_conflicting_groups)
        if group_by == 'none':
            conflict_count = len(
                data_conflicting_tasks | image_conflicting_tasks
            )
            group_count = 0
        else:
            conflict_count = data_conflict_count + image_conflict_count
            group_count = len(groups)
        data_artifact_count = (
            len(render_tasks) if data_extension is not None else 0
        )
        image_artifact_count = len(groups)
        width, height = preset.outputs.resolved_image_dimensions()
        representative = None
        if groups:
            ordinal, group, channel_available = self._pick_representative_group(
                groups, source_channels,
            )
            representative = BatchRepresentativeGroup(
                group_id=group.identity.group_id,
                display_name=group.display_name,
                group_by=group.group_by,
                member_count=len(group.members),
                required_source_count=len({
                    member.source_key for member in group.members
                }),
                planned_stem=group.identity.stem,
                ordinal=ordinal,
                total_groups=len(groups),
                channel_available=channel_available,
            )
        return BatchOutputPreview(
            task_count=len(tasks),
            artifact_count=data_artifact_count + image_artifact_count,
            conflict_count=conflict_count,
            image_format=str(preset.outputs.image_format).lower().lstrip('.'),
            image_width=width,
            image_height=height,
            image_dpi=int(preset.outputs.image_dpi),
            conflict_policy=str(preset.outputs.conflict_policy).lower(),
            group_count=group_count,
            data_artifact_count=data_artifact_count,
            image_artifact_count=image_artifact_count,
            data_conflict_count=data_conflict_count,
            image_conflict_count=image_conflict_count,
            representative_group=representative,
        )

    def preview_group(
        self,
        preset,
        group_id: str,
        temp_dir,
        *,
        cancel_token: threading.Event | None = None,
    ) -> BatchPreviewResult:
        """Render exactly one planned group into a caller-owned temp directory.

        Planning is deliberately no-load.  The selected group is then executed
        through the normal ``run()`` path with an image-only, no-manifest
        output contract, which keeps preprocessing, figure specification,
        renderer, dimensions, and DPI identical to a formal run.
        """
        requested_params = normalize_batch_params(preset.params, preset.method)
        tasks = list(self._expand_tasks(preset, allow_source_load=False))
        render_tasks = []
        for source_key, channel in tasks:
            fd = self._known_file_data(source_key)
            identity = (
                self._build_task_identity(
                    fd, file_id=source_key, channel=channel,
                    method=preset.method, params=requested_params,
                )
                if fd is not None else self._build_unresolved_task_identity(
                    source_key, channel=channel, method=preset.method,
                    params=requested_params,
                    group_identity=self._source_group_identity_hints.get(source_key),
                )
            )
            render_tasks.append(RenderTask(source_key, channel, identity))
        groups = group_render_tasks(render_tasks, requested_params)
        group = next(
            (candidate for candidate in groups
             if candidate.identity.group_id == str(group_id)),
            None,
        )
        if group is None:
            return BatchPreviewResult(
                image_path=None, group_id=str(group_id), display_name="",
                loaded_source_count=0, message="代表输出组已失效",
            )

        # Target pairs are runtime-only and bound to the selected group.  They
        # neither mutate the supplied preset nor enter a persisted preset.
        preview_outputs = replace(
            preset.outputs,
            export_data=False,
            export_image=True,
            image_format="png",
            write_manifest=False,
        )
        preview_preset = replace(
            preset,
            target_pairs=tuple(
                (member.source_key, member.channel) for member in group.members
            ),
            outputs=preview_outputs,
        )
        result = self.run(
            preview_preset, temp_dir, cancel_token=cancel_token,
        )
        matched_group = next(
            (
                candidate for candidate in result.render_groups
                if candidate.group_id == group.identity.group_id
            ),
            None,
        )
        if matched_group is not None and matched_group.image_path:
            preview_image_path = matched_group.image_path
        else:
            images = [
                item.image_path for item in result.items
                if item.image_path and item.status in {"done", "resumed"}
            ]
            preview_image_path = images[0] if images else None
        return BatchPreviewResult(
            image_path=preview_image_path,
            group_id=group.identity.group_id,
            display_name=group.display_name,
            loaded_source_count=len({member.source_key for member in group.members}),
            warnings=tuple(result.warnings),
            status=result.status,
            message="; ".join(result.blocked),
        )

    def run(self, preset, output_dir,
            progress_callback: Callable[[int, int], None] | None = None,
            *,
            on_event: Callable[[BatchProgressEvent], None] | None = None,
            cancel_token: threading.Event | None = None,
            resume_manifest=None,
            retry_failed_manifest=None) -> BatchRunResult:
        output_dir = Path(output_dir)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            err = f"cannot create output dir: {exc}"
            if on_event:
                on_event(BatchProgressEvent(
                    kind='run_finished',
                    final_status='blocked',
                ))
            return BatchRunResult(status='blocked', blocked=[err])

        try:
            requested_params = normalize_batch_params(
                preset.params, preset.method,
            )
            output_settings = self._requested_output_settings(preset.outputs)
            recipe_id = recipe_fingerprint(
                requested_params,
                preset.method,
                outputs=output_settings,
            )
        except Exception as exc:
            if on_event:
                on_event(BatchProgressEvent(
                    kind='run_finished', final_status='blocked',
                ))
            return BatchRunResult(status='blocked', blocked=[str(exc)])

        recorder = None
        manifest_errors: list[str] = []
        run_migration_warnings: tuple[str, ...] = tuple(
            getattr(preset.outputs, 'migration_warnings', ()) or ()
        )
        if bool(getattr(preset.outputs, 'write_manifest', True)):
            try:
                normalized_recipe = {
                    'method': preset.method,
                    'params': requested_params,
                    'rpm_channel': preset.rpm_channel,
                    'rpm_signal': preset.rpm_signal,
                    'outputs': output_settings,
                }
                execution_scope = self._lazy_pattern_execution_scope(preset)
                if execution_scope is not None:
                    normalized_recipe['execution_scope'] = execution_scope
                manifest_dir = output_dir / '.tracelab' / 'runs'
                recorder = BatchManifestRecorder(
                    manifest_dir,
                    preset_name=preset.name,
                    normalized_recipe=normalized_recipe,
                    recipe_fingerprint=recipe_id,
                    requested_outputs=output_settings,
                )
                recorder.start()
            except Exception as exc:
                err = f"cannot create batch manifest: {exc}"
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='run_finished', final_status='blocked',
                    ))
                return BatchRunResult(status='blocked', blocked=[err])

        def finish_result(status, items=None, blocked=None, render_groups=None):
            result_items = list(items or ())
            result_blocked = list(blocked or ())
            result_render_groups = list(render_groups or ())
            result_blocked.extend(manifest_errors)
            result_status = status
            degraded_reasons = list(dict.fromkeys(
                item.degraded_reason
                for item in result_items
                if item.degraded_reason
            ))
            degraded_count = sum(
                bool(item.degraded_reason) for item in result_items
            )
            if degraded_count and result_status == 'done':
                result_status = 'partial'
            if manifest_errors and result_status == 'done':
                result_status = 'partial'
            summary = derive_summary(
                {'status': item.status} for item in result_items
            )
            manifest_path = None
            run_id = recorder.run_id if recorder is not None else None
            if recorder is not None:
                try:
                    manifest_path = str(recorder.finish(
                        run_status=result_status,
                        blocked_reasons=result_blocked,
                    ))
                    summary = derive_summary(recorder.entries)
                except Exception as exc:
                    result_blocked.append(f"cannot finalize batch manifest: {exc}")
                    if result_status == 'done':
                        result_status = 'partial'
            if on_event:
                on_event(BatchProgressEvent(
                    kind='run_finished', final_status=result_status,
                ))
            return BatchRunResult(
                status=result_status,
                items=result_items,
                blocked=result_blocked,
                manifest_path=manifest_path,
                summary=summary,
                run_id=run_id,
                degraded_count=degraded_count,
                warnings=list(dict.fromkeys([
                    *run_migration_warnings,
                    *degraded_reasons,
                    *(warning for item in result_items for warning in item.warnings),
                ])),
                render_groups=result_render_groups,
            )

        def physical_path_for(source_key, fd=None):
            if fd is not None:
                value = getattr(fd, 'filepath', None)
                if value not in (None, ''):
                    return value
            physical_key = self._physical_for_source(source_key)
            if physical_key is None:
                return None
            return self._physical_paths.get(physical_key, physical_key)

        def record_item(item, source_key, fd=None):
            if recorder is None:
                return
            source_path = physical_path_for(source_key, fd)
            source_identity = item.source_identity
            if not source_identity and source_path not in (None, ''):
                source_identity = str(
                    Path(source_path).expanduser().resolve(strict=False)
                )
            source = source_file_facts(
                source_path,
                source_identity=source_identity or f"file_id:{source_key!r}",
            )
            source.update({
                'group_identity': item.group_identity or 'default',
                'display_name': item.file_name,
            })
            artifacts = dict(item.artifact_facts or {})
            if item.status == 'done':
                if item.data_path:
                    try:
                        data_format = str(
                            preset.outputs.data_format
                        ).lower().lstrip('.')
                        artifacts['data'] = artifact_facts(
                            item.data_path,
                            kind='data',
                            artifact_format=(
                                data_format if data_format == 'xlsx' else 'csv'
                            ),
                            cancel_token=cancel_token,
                        )
                    except OSError as exc:
                        item.warnings.append(f"data checksum unavailable: {exc}")
                if item.image_path:
                    try:
                        width, height = preset.outputs.resolved_image_dimensions()
                        artifacts['image'] = artifact_facts(
                            item.image_path,
                            kind='image',
                            artifact_format=str(
                                preset.outputs.image_format
                            ).lower().lstrip('.'),
                            width=width,
                            height=height,
                            dpi=int(preset.outputs.image_dpi),
                            cancel_token=cancel_token,
                        )
                    except OSError as exc:
                        item.warnings.append(f"image checksum unavailable: {exc}")
                item.artifact_facts = artifacts
                if any(
                    facts.get('checksum_status') != 'complete'
                    for facts in artifacts.values()
                ):
                    item.warnings.append('artifact checksum incomplete')
                    if cancel_token is not None and cancel_token.is_set():
                        item.status = 'cancelled'
                        item.message = 'cancelled during artifact checksum'
            unit = ''
            if fd is not None:
                unit = str(
                    (getattr(fd, 'channel_units', None) or {}).get(
                        item.signal, '',
                    ) or ''
                )
            entry = {
                'task_id': item.task_id,
                'source_id': source_key,
                'source': source,
                'channel': item.signal,
                'channel_unit': unit,
                'method': item.method,
                'requested_params': requested_params,
                'effective_facts': item.effective_params,
                'status': item.status,
                'message': item.message,
                'warnings': list(item.warnings),
                'requested_outputs': dict(item.requested_outputs),
                'effective_outputs': dict(item.effective_outputs),
                'degraded_reason': item.degraded_reason,
                'started_at': item.started_at,
                'finished_at': item.finished_at,
                'artifacts': artifacts,
            }
            try:
                recorder.record(entry)
            except Exception as exc:
                manifest_errors.append(f"cannot update batch manifest: {exc}")

        recipe_issues = (
            *validate_outputs(preset.outputs),
            *validate_recipe(
                preset.method,
                preset.params,
                rpm_channel=preset.rpm_channel,
                rpm_signal=preset.rpm_signal,
            ),
        )
        if recipe_issues:
            err = "; ".join(str(issue) for issue in recipe_issues)
            return finish_result('blocked', blocked=[err])

        if resume_manifest is not None and retry_failed_manifest is not None:
            return finish_result(
                'blocked',
                blocked=['resume_manifest and retry_failed_manifest are mutually exclusive'],
            )

        resume_data = None
        resume_policy = str(
            getattr(preset.outputs, 'resume_policy', 'none') or 'none'
        ).strip().lower()
        if resume_manifest is not None and resume_policy != 'manifest':
            return finish_result(
                'blocked',
                blocked=[
                    'resume_manifest requires outputs.resume_policy="manifest"'
                ],
            )
        if resume_policy == 'manifest':
            try:
                if resume_manifest is not None:
                    resume_data = load_batch_manifest(resume_manifest)
                else:
                    manifest_dirs = (
                        output_dir / '.tracelab' / 'runs', output_dir,
                    )
                    candidates = sorted(
                        (
                            path
                            for directory in manifest_dirs
                            if directory.is_dir()
                            for path in directory.glob('batch-manifest__*.json')
                            if not path.name.endswith('.partial.json')
                        ),
                        key=lambda path: path.stat().st_mtime_ns,
                        reverse=True,
                    )
                    for candidate in candidates:
                        loaded = load_batch_manifest(candidate)
                        if loaded.get('recipe_fingerprint') == recipe_id:
                            resume_data = loaded
                            break
            except Exception as exc:
                return finish_result(
                    'blocked', blocked=[f"cannot load resume manifest: {exc}"],
                )

        retry_scope = None
        retry_data = None
        if retry_failed_manifest is not None:
            try:
                retry_data = load_batch_manifest(retry_failed_manifest)
                retry_scope = retry_failed_scope(
                    retry_data,
                    recipe_fingerprint=recipe_id,
                )
            except ManifestRecipeMismatch as exc:
                return finish_result('blocked', blocked=[str(exc)])
            except Exception as exc:
                return finish_result(
                    'blocked', blocked=[f"cannot load retry manifest: {exc}"],
                )
            if not retry_scope:
                return finish_result(
                    'blocked',
                    blocked=['retry manifest has no failed or cancelled tasks'],
                )

        group_by = str(requested_params.get(
            'render_group_by', 'none',
        ) or 'none').strip().lower()
        explicit_grouping = preset.method == 'time' and group_by != 'none'

        def apply_retry_scope(tasks, render_tasks, render_groups):
            if retry_scope is None:
                return tasks, render_tasks, render_groups
            if not explicit_grouping:
                selected = [
                    (source_key, channel)
                    for source_key, channel in tasks
                    if (source_key, channel, preset.method) in retry_scope
                ]
                return selected, render_tasks, render_groups
            selected_groups = tuple(
                group for group in render_groups
                if group.identity.group_id in retry_scope.group_ids
                or any(
                    (member.source_key, member.channel, preset.method)
                    in retry_scope
                    for member in group.members
                )
            )
            selected_pairs = {
                (member.source_key, member.channel)
                for group in selected_groups
                for member in group.members
            }
            return (
                [task for task in tasks if task in selected_pairs],
                [
                    task for task in render_tasks
                    if (task.source_key, task.channel) in selected_pairs
                ],
                list(selected_groups),
            )
        deferred_path_scope = bool(
            tuple(getattr(preset, 'target_signals', ()) or ())
            and not tuple(getattr(preset, 'target_pairs', ()) or ())
            and not tuple(getattr(preset, 'source_ids', ()) or ())
            and (
                tuple(getattr(preset, 'source_paths', ()) or ())
                or (
                    tuple(getattr(preset, 'file_paths', ()) or ())
                    and not tuple(getattr(preset, 'file_ids', ()) or ())
                )
            )
        )
        try:
            tasks = list(self._expand_tasks(
                preset,
                allow_source_load=False,
            ))
        except Exception as exc:
            for physical_key in tuple(self._disk_cache):
                self._evict_physical(physical_key)
            return finish_result('blocked', blocked=[str(exc)])
        recovery_scope_manifest = retry_data
        if recovery_scope_manifest is None and resume_data is not None:
            recovery_scope_manifest = resume_data
        if not tasks and explicit_grouping:
            tasks = self._recover_lazy_manifest_tasks(
                preset,
                recovery_scope_manifest,
                recipe_id=recipe_id,
                requested_params=requested_params,
            )
        if retry_scope is not None and not explicit_grouping:
            tasks = [
                (source_key, channel)
                for source_key, channel in tasks
                if (source_key, channel, preset.method) in retry_scope
            ]
        deferred_paths = {
            str(path)
            for path in (
                tuple(getattr(preset, 'source_paths', ()) or ())
                or tuple(getattr(preset, 'file_paths', ()) or ())
            )
        }
        deferred_path_scope = deferred_path_scope and any(
            str(source_key) in deferred_paths for source_key, _channel in tasks
        )
        tasks, render_tasks, render_groups = self._build_run_plan(
            tasks,
            preset=preset,
            requested_params=requested_params,
            explicit_grouping=explicit_grouping,
        )
        tasks, render_tasks, render_groups = apply_retry_scope(
            tasks, render_tasks, render_groups,
        )

        try:
            effective_plan = self._resolve_effective_outputs(preset.outputs)
            run_migration_warnings = effective_plan.migration_warnings
        except _ImageBackendUnavailable as exc:
            requested = self._requested_artifacts(preset.outputs)
            failed_plan = EffectiveOutputPlan(
                requested=requested,
                effective={},
                render_backend_types=None,
                degraded_reason='',
                migration_warnings=tuple(
                    getattr(preset.outputs, 'migration_warnings', ()) or ()
                ),
            )
            failed_items = []
            for source_key, signal_name in tasks:
                fd = self._known_file_data(source_key)
                identity = next(
                    task.identity for task in render_tasks
                    if task.source_key == source_key and task.channel == signal_name
                )
                item = BatchItemResult(
                    method=preset.method,
                    file_id=source_key,
                    file_name=(
                        str(fd.filename) if fd is not None else str(source_key)
                    ),
                    signal=signal_name,
                    status='failed',
                    message=str(exc),
                    task_id=identity.task_id,
                    source_identity=identity.source_identity,
                    group_identity=identity.group_identity,
                    requested_outputs=dict(requested),
                    effective_outputs={},
                    warnings=list(failed_plan.migration_warnings),
                    finished_at=utc_now(),
                )
                failed_items.append(item)
                record_item(item, source_key, fd)
            if recorder is not None:
                for group in render_groups:
                    try:
                        recorder.upsert_render_group(
                            self._render_group_manifest_entry(
                                group,
                                failed_plan,
                                status='failed',
                                message=str(exc),
                            )
                        )
                    except Exception as manifest_exc:
                        manifest_errors.append(
                            f'cannot update batch manifest: {manifest_exc}'
                        )
            return finish_result(
                'blocked', items=failed_items, blocked=[str(exc)],
            )

        if deferred_path_scope:
            tasks, render_tasks, render_groups = [], [], []
        if not tasks:
            try:
                tasks = list(self._expand_tasks(
                    preset,
                    allow_source_load=True,
                ))
            except Exception as exc:
                for physical_key in tuple(self._disk_cache):
                    self._evict_physical(physical_key)
                return finish_result('blocked', blocked=[str(exc)])
            if not tasks:
                for physical_key in tuple(self._disk_cache):
                    self._evict_physical(physical_key)
                return finish_result(
                    'blocked', blocked=['no matching batch tasks'],
                )
            if retry_scope is not None and not explicit_grouping:
                tasks = [
                    (source_key, channel)
                    for source_key, channel in tasks
                    if (source_key, channel, preset.method) in retry_scope
                ]
                if not tasks:
                    for physical_key in tuple(self._disk_cache):
                        self._evict_physical(physical_key)
                    return finish_result(
                        'blocked', blocked=['no matching batch tasks'],
                    )
            tasks, render_tasks, render_groups = self._build_run_plan(
                tasks,
                preset=preset,
                requested_params=requested_params,
                explicit_grouping=explicit_grouping,
            )
            tasks, render_tasks, render_groups = apply_retry_scope(
                tasks, render_tasks, render_groups,
            )

        items: list[BatchItemResult] = []
        blocked: list[str] = []
        cancelled = False
        total = len(tasks)
        prev_physical_key = None
        requested_artifacts = self._required_artifacts(preset.outputs)

        def task_file_name(source_key):
            fd = self._known_file_data(source_key)
            if fd is not None:
                return getattr(fd, 'filename', str(source_key))
            physical_key = self._physical_for_source(source_key)
            if physical_key is not None:
                return self._physical_paths.get(physical_key, physical_key)
            return str(source_key)

        def cancelled_item(source_key, signal, message):
            fd = self._known_file_data(source_key)
            if fd is not None:
                identity = self._build_task_identity(
                    fd,
                    file_id=source_key,
                    channel=signal,
                    method=preset.method,
                    params=requested_params,
                )
            else:
                identity = self._build_unresolved_task_identity(
                    source_key,
                    channel=signal,
                    method=preset.method,
                    params=requested_params,
                )
            return BatchItemResult(
                method=preset.method,
                file_id=source_key,
                file_name=task_file_name(source_key),
                signal=signal,
                status='cancelled',
                message=message,
                task_id=(identity.task_id if identity else ''),
                source_identity=(identity.source_identity if identity else ''),
                group_identity=(identity.group_identity if identity else ''),
                requested_outputs=dict(requested_artifacts),
                effective_outputs=dict(requested_artifacts),
                started_at=None,
                finished_at=utc_now(),
            )

        def emit_cancelled_range(start_index, message='batch cancelled'):
            for task_index in range(start_index, total + 1):
                key, signal = tasks[task_index - 1]
                item = cancelled_item(key, signal, message)
                items.append(item)
                record_item(item, key, self._known_file_data(key))
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='task_cancelled',
                        task_index=task_index,
                        total=total,
                        file_name=item.file_name,
                        signal=signal,
                        method=preset.method,
                        task_id=item.task_id,
                        message=item.message,
                    ))

        if render_groups:
            group_for_task = {
                (member.source_key, member.channel): group
                for group in render_groups
                for member in group.members
            }
            member_for_task = {
                member.identity.task_id: member
                for group in render_groups
                for member in group.members
            }
            recovery_manifest = retry_data
            if (
                recovery_manifest is None
                and resume_data is not None
                and resume_data.get('recipe_fingerprint') == recipe_id
            ):
                recovery_manifest = resume_data
            group_recovery = {
                group.identity.group_id: self._plan_group_recovery(
                    group,
                    resume_manifest=recovery_manifest,
                    retry_scope=retry_scope,
                    image_format=str(
                        effective_plan.effective.get('image', '')
                    ),
                    cancel_token=cancel_token,
                )
                for group in render_groups
            }
            reusable_data_entries = {
                member.identity.task_id: entry
                for member in member_for_task.values()
                for entry in [self._resumable_group_data_entry(
                    recovery_manifest, member, cancel_token=cancel_token,
                )]
                if entry is not None
            }
            prior_data_entries = {
                str(entry.get('task_id')): entry
                for entry in (recovery_manifest or {}).get('entries', ())
                if entry.get('task_id')
            }
            prior_group_entries = {
                str(entry.get('group_id')): entry
                for entry in (recovery_manifest or {}).get('render_groups', ())
                if entry.get('group_id')
            }

            def planned_group_item(member, *, status, message='', entry=None):
                artifacts = dict((entry or {}).get('artifacts') or {})
                data = artifacts.get('data') or {}
                source = (entry or {}).get('source') or {}
                return BatchItemResult(
                    method='time',
                    file_id=member.source_key,
                    file_name=str(
                        source.get('display_name')
                        or task_file_name(member.source_key)
                    ),
                    signal=member.channel,
                    status=status,
                    data_path=(data.get('path') if status == 'resumed' else None),
                    message=message,
                    task_id=member.identity.task_id,
                    source_identity=member.identity.source_identity,
                    group_identity=member.identity.group_identity,
                    effective_params=dict(
                        (entry or {}).get('effective_facts') or {}
                    ),
                    warnings=list(dict.fromkeys([
                        *effective_plan.migration_warnings,
                        *((entry or {}).get('warnings') or []),
                    ])),
                    requested_outputs=dict(effective_plan.requested),
                    effective_outputs=dict(effective_plan.effective),
                    degraded_reason=effective_plan.degraded_reason,
                    artifact_facts=(artifacts if status == 'resumed' else {}),
                    started_at=utc_now(),
                    finished_at=utc_now(),
                )

            group_results: dict[str, list[TaskComputeResult]] = {
                group.identity.group_id: [] for group in render_groups
            }
            group_blocked: dict[str, str] = {}
            group_failed: dict[str, str] = {}
            deferred_group_terminals: dict[str, tuple[int, str, str]] = {}
            resolved_group_terminals: list[
                tuple[int, str, str, BatchItemResult, str | None]
            ] = []
            render_group_outcomes: list[RenderGroupResult] = []
            spool_class = None
            spool_module = None
            if (
                'image' in effective_plan.effective
                and any(
                    decision.image_write_required
                    for decision in group_recovery.values()
                )
            ):
                from . import batch_series_spool as spool_module

                spool_class = spool_module.BatchSeriesSpool
            for group in render_groups:
                decision = group_recovery[group.identity.group_id]
                if spool_module is not None and decision.image_write_required:
                    try:
                        spool_module.validate_group_shape(
                            member_count=len(group.members),
                            panel_count=(
                                len(group.members)
                                if group.layout == 'subplot' else 0
                            ),
                        )
                    except ValueError as exc:
                        group_blocked[group.identity.group_id] = str(exc)
                if recorder is not None:
                    try:
                        reusable = decision.reusable_group
                        recorder.upsert_render_group(
                            self._render_group_manifest_entry(
                                group,
                                effective_plan,
                                status=(
                                    'done' if reusable is not None
                                    else 'degraded'
                                    if effective_plan.degraded_reason else 'pending'
                                ),
                                message=(
                                    'manifest-proven group resume'
                                    if reusable is not None
                                    else effective_plan.degraded_reason
                                ),
                                warnings=(
                                    reusable.get('warnings', ())
                                    if reusable is not None else ()
                                ),
                                artifact=(
                                    reusable.get('artifact')
                                    if reusable is not None else None
                                ),
                            )
                        )
                    except Exception as exc:
                        manifest_errors.append(
                            f'cannot update batch manifest: {exc}'
                        )

            prev_physical_key = None
            run_spool_blocked = False
            if spool_class is not None:
                spool_context = spool_class()
            else:
                spool_context = nullcontext(None)
            with spool_context as spool:
                for index, (source_key, signal_name) in enumerate(tasks, start=1):
                    group = group_for_task.get((source_key, signal_name))
                    physical_key = self._physical_for_source(source_key)
                    if (
                        prev_physical_key is not None
                        and physical_key != prev_physical_key
                    ):
                        self._evict_physical(prev_physical_key)
                        prev_physical_key = None
                    if cancel_token is not None and cancel_token.is_set():
                        cancelled = True
                        emit_cancelled_range(index)
                        break

                    member = next(
                        candidate for candidate in group.members
                        if candidate.source_key == source_key
                        and candidate.channel == signal_name
                    )
                    decision = group_recovery[group.identity.group_id]
                    task_id = member.identity.task_id
                    data_write_eligible = bool(
                        'data' in effective_plan.effective
                        and task_id in decision.data_write_task_ids
                    )
                    payload_required = bool(
                        'image' in effective_plan.effective
                        and task_id in decision.payload_task_ids
                        and group.identity.group_id not in group_blocked
                        and not run_spool_blocked
                    )
                    data_reservation = None
                    data_conflict_status = ''
                    data_conflict_message = ''
                    if data_write_eligible:
                        data_extension = str(
                            effective_plan.effective.get('data', 'csv')
                        ).lower().lstrip('.')
                        conflict_policy = str(
                            getattr(
                                preset.outputs,
                                'conflict_policy',
                                'auto_number',
                            )
                        ).strip().lower()
                        reservation_stem = member.identity.stem
                        prior_data = (
                            prior_data_entries.get(task_id) or {}
                        ).get('artifacts', {}).get('data') or {}
                        prior_data_path = prior_data.get('path')
                        if prior_data_path:
                            reservation_stem = Path(prior_data_path).stem
                            conflict_policy = 'overwrite'
                        try:
                            data_reservation = reserve_output_paths(
                                output_dir,
                                reservation_stem,
                                (data_extension,),
                                conflict_policy=conflict_policy,
                            )
                            if data_reservation.status == 'skipped':
                                data_conflict_status = 'skipped'
                                data_conflict_message = (
                                    'task data skipped without manifest provenance'
                                )
                        except FileExistsError as exc:
                            data_conflict_status = 'failed'
                            data_conflict_message = str(exc)
                        if data_conflict_status:
                            data_write_eligible = False

                    if not data_write_eligible and not payload_required:
                        entry = reusable_data_entries.get(task_id)
                        if entry is not None:
                            item = planned_group_item(
                                member,
                                status='resumed',
                                message='manifest-proven data resume',
                                entry=entry,
                            )
                        else:
                            item = planned_group_item(
                                member,
                                status=data_conflict_status or 'done',
                                message=data_conflict_message,
                            )
                            if data_reservation is not None:
                                if data_reservation.warning:
                                    item.warnings.append(data_reservation.warning)
                                data_reservation.release()
                        items.append(item)
                        record_item(item, source_key, self._known_file_data(source_key))
                        if data_conflict_status == 'failed':
                            blocked.append(
                                f'{item.file_name}:{signal_name}: '
                                f'{data_conflict_message}'
                            )
                        if on_event:
                            on_event(BatchProgressEvent(
                                kind=(
                                    'task_failed'
                                    if item.status == 'failed'
                                    else 'task_skipped'
                                    if item.status == 'skipped'
                                    else 'task_resumed'
                                ),
                                task_index=index,
                                total=total,
                                file_name=item.file_name,
                                signal=signal_name,
                                method='time',
                                task_id=item.task_id,
                                message=item.message,
                            ))
                        continue

                    fid, fd_or_fail = self._resolve_task_file(source_key)
                    physical_key = self._physical_for_source(source_key)
                    if physical_key is not None:
                        prev_physical_key = physical_key
                    fname = (
                        fd_or_fail.path
                        if isinstance(fd_or_fail, _LoadFailure)
                        else str(fd_or_fail.filename)
                    )
                    started_at = utc_now()
                    if on_event:
                        on_event(BatchProgressEvent(
                            kind='task_started',
                            task_index=index,
                            total=total,
                            file_name=fname,
                            signal=signal_name,
                            method=preset.method,
                        ))
                    try:
                        if isinstance(fd_or_fail, _LoadFailure):
                            raise IOError(fd_or_fail.error)
                        if signal_name not in fd_or_fail.data.columns:
                            raise ValueError(f'missing signal: {signal_name}')
                        computed = self._compute_group_task(
                            preset,
                            source_key,
                            fd_or_fail,
                            signal_name,
                            output_dir,
                            spool,
                            group,
                            data_write_eligible=data_write_eligible,
                            payload_required=payload_required,
                            data_reservation=data_reservation,
                            effective=effective_plan,
                            cancel_token=cancel_token,
                        )
                        item = computed.item
                        if not data_write_eligible:
                            entry = reusable_data_entries.get(task_id)
                            if data_conflict_status:
                                item.status = data_conflict_status
                                item.message = data_conflict_message
                                item.data_path = None
                                item.artifact_facts = {}
                                if (
                                    data_reservation is not None
                                    and data_reservation.warning
                                ):
                                    item.warnings.append(data_reservation.warning)
                                if data_conflict_status == 'failed':
                                    blocked.append(
                                        f'{fname}:{signal_name}: '
                                        f'{data_conflict_message}'
                                    )
                            elif entry is not None:
                                data = (entry.get('artifacts') or {}).get('data') or {}
                                item.status = 'resumed'
                                item.message = 'manifest-proven data resume'
                                item.data_path = data.get('path')
                                item.artifact_facts = dict(
                                    entry.get('artifacts') or {}
                                )
                        item.started_at = started_at
                        item.finished_at = utc_now()
                        items.append(item)
                        if group is not None:
                            group_results[group.identity.group_id].append(computed)
                        if computed.render_error and group is not None:
                            if computed.render_status == 'failed':
                                group_failed[
                                    group.identity.group_id
                                ] = computed.render_error
                            elif 'run spool exceeds' in computed.render_error:
                                run_spool_blocked = True
                                for candidate in render_groups:
                                    successful = sum(
                                        bool(result.series_refs)
                                        for result in group_results[
                                            candidate.identity.group_id
                                        ]
                                    )
                                    if successful < len(candidate.members):
                                        group_blocked[
                                            candidate.identity.group_id
                                        ] = computed.render_error
                            else:
                                group_blocked[
                                    group.identity.group_id
                                ] = computed.render_error
                        record_item(item, source_key, fd_or_fail)
                        defer_terminal = bool(
                            computed.series_refs
                            and item.status in {'done', 'resumed'}
                        )
                        if defer_terminal:
                            deferred_group_terminals[item.task_id] = (
                                index, fname, signal_name,
                            )
                        elif on_event:
                            on_event(BatchProgressEvent(
                                kind=(
                                    'task_failed' if item.status == 'failed'
                                    else 'task_skipped' if item.status == 'skipped'
                                    else 'task_resumed' if item.status == 'resumed'
                                    else 'task_done'
                                ),
                                task_index=index,
                                total=total,
                                file_name=fname,
                                signal=signal_name,
                                method=preset.method,
                                task_id=item.task_id,
                                message=item.message,
                                data_path=item.data_path,
                                error=(item.message if item.status == 'failed' else None),
                            ))
                        if (
                            not defer_terminal
                            and progress_callback
                            and item.status == 'done'
                        ):
                            progress_callback(index, total)
                    except _BatchCancelled as exc:
                        if data_reservation is not None:
                            data_reservation.release()
                        cancelled = True
                        identity = next(
                            task.identity for task in render_tasks
                            if task.source_key == source_key
                            and task.channel == signal_name
                        )
                        item = BatchItemResult(
                            method='time',
                            file_id=source_key,
                            file_name=fname,
                            signal=signal_name,
                            status='cancelled',
                            message=str(exc),
                            task_id=identity.task_id,
                            source_identity=identity.source_identity,
                            group_identity=identity.group_identity,
                            requested_outputs=dict(effective_plan.requested),
                            effective_outputs=dict(effective_plan.effective),
                            degraded_reason=effective_plan.degraded_reason,
                            started_at=started_at,
                            finished_at=utc_now(),
                        )
                        items.append(item)
                        record_item(
                            item,
                            source_key,
                            None if isinstance(fd_or_fail, _LoadFailure)
                            else fd_or_fail,
                        )
                        if on_event:
                            on_event(BatchProgressEvent(
                                kind='task_cancelled',
                                task_index=index,
                                total=total,
                                file_name=fname,
                                signal=signal_name,
                                method='time',
                                task_id=item.task_id,
                                message=item.message,
                            ))
                        emit_cancelled_range(index + 1)
                        break
                    except Exception as exc:
                        if data_reservation is not None:
                            data_reservation.release()
                        identity = next(
                            task.identity for task in render_tasks
                            if task.source_key == source_key
                            and task.channel == signal_name
                        )
                        item = BatchItemResult(
                            method='time',
                            file_id=source_key,
                            file_name=fname,
                            signal=signal_name,
                            status='failed',
                            message=str(exc),
                            task_id=identity.task_id,
                            source_identity=identity.source_identity,
                            group_identity=identity.group_identity,
                            requested_outputs=dict(effective_plan.requested),
                            effective_outputs=dict(effective_plan.effective),
                            degraded_reason=effective_plan.degraded_reason,
                            started_at=started_at,
                            finished_at=utc_now(),
                        )
                        items.append(item)
                        blocked.append(f'{fname}:{signal_name}: {exc}')
                        if group is not None:
                            group_results[group.identity.group_id].append(
                                TaskComputeResult(item=item, render_error=str(exc))
                            )
                        record_item(
                            item,
                            source_key,
                            None if isinstance(fd_or_fail, _LoadFailure)
                            else fd_or_fail,
                        )
                        if on_event:
                            on_event(BatchProgressEvent(
                                kind='task_failed',
                                task_index=index,
                                total=total,
                                file_name=fname,
                                signal=signal_name,
                                method='time',
                                error=str(exc),
                                task_id=item.task_id,
                                message=item.message,
                            ))

                for physical_key in tuple(self._disk_cache):
                    self._evict_physical(physical_key)

                for group in render_groups:
                    group_id = group.identity.group_id
                    results = group_results[group_id]
                    decision = group_recovery[group_id]
                    if cancelled:
                        outcome = RenderGroupResult(
                            group_id=group_id,
                            status='cancelled',
                            message='batch cancelled before group image completed',
                        )
                    elif decision.reusable_group is not None:
                        reusable = decision.reusable_group
                        outcome = RenderGroupResult(
                            group_id=group_id,
                            status='done',
                            image_path=(reusable.get('artifact') or {}).get('path'),
                            message='manifest-proven group resume',
                            warnings=list(reusable.get('warnings') or ()),
                            artifact=dict(reusable.get('artifact') or {}),
                            effective_facts=dict(
                                reusable.get('effective_facts') or {}
                            ),
                        )
                    elif effective_plan.degraded_reason:
                        outcome = RenderGroupResult(
                            group_id=group_id,
                            status='degraded',
                            message=effective_plan.degraded_reason,
                        )
                    elif group_id in group_failed:
                        outcome = RenderGroupResult(
                            group_id=group_id,
                            status='failed',
                            message=group_failed[group_id],
                        )
                    elif group_id in group_blocked:
                        outcome = RenderGroupResult(
                            group_id=group_id,
                            status='blocked',
                            message=group_blocked[group_id],
                        )
                    else:
                        if recorder is not None:
                            try:
                                recorder.upsert_render_group(
                                    self._render_group_manifest_entry(
                                        group,
                                        effective_plan,
                                        status='running',
                                    )
                                )
                            except Exception as exc:
                                manifest_errors.append(
                                    f'cannot update batch manifest: {exc}'
                                )
                        try:
                            prior_group = prior_group_entries.get(group_id) or {}
                            prior_artifact = prior_group.get('artifact') or {}
                            prior_image_path = prior_artifact.get('path')
                            outcome = self._render_group(
                                group,
                                results,
                                preset,
                                output_dir,
                                spool,
                                effective=effective_plan,
                                reservation_stem=(
                                    Path(prior_image_path).stem
                                    if prior_image_path else None
                                ),
                                conflict_policy_override=(
                                    'overwrite' if prior_image_path else None
                                ),
                                recorder=recorder,
                                cancel_token=cancel_token,
                            )
                        except _BatchCancelled as exc:
                            cancelled = True
                            outcome = RenderGroupResult(
                                group_id=group_id,
                                status='cancelled',
                                message=str(exc),
                            )
                        except Exception as exc:
                            outcome = RenderGroupResult(
                                group_id=group_id,
                                status='failed',
                                message=str(exc),
                            )
                    render_group_outcomes.append(outcome)
                    if outcome.warnings:
                        for computed in results:
                            if computed.series_refs:
                                computed.item.warnings = list(dict.fromkeys([
                                    *computed.item.warnings,
                                    *outcome.warnings,
                                ]))
                                record_item(computed.item, computed.item.file_id)
                    if outcome.status == 'cancelled':
                        cancelled = True
                        for computed in results:
                            item = computed.item
                            if item.status not in {'done', 'resumed'}:
                                continue
                            item.status = 'cancelled'
                            item.message = (
                                outcome.message
                                or 'batch cancelled before group image completed'
                            )
                            item.finished_at = utc_now()
                            record_item(item, item.file_id)
                    for computed in results:
                        item = computed.item
                        event_context = deferred_group_terminals.pop(
                            item.task_id, None,
                        )
                        if event_context is None:
                            continue
                        task_index, file_name, signal_name = event_context
                        resolved_group_terminals.append((
                            task_index,
                            file_name,
                            signal_name,
                            item,
                            outcome.image_path,
                        ))
                    if outcome.status not in {'done', 'degraded'}:
                        blocked.append(
                            f'{group.identity.stem}: {outcome.message or outcome.status}'
                        )
                    if recorder is not None:
                        try:
                            recorder.upsert_render_group(
                                self._render_group_manifest_entry(
                                    group,
                                    effective_plan,
                                    status=outcome.status,
                                    message=outcome.message,
                                    warnings=outcome.warnings,
                                    artifact=outcome.artifact,
                                    effective_facts=outcome.effective_facts,
                                )
                            )
                        except Exception as exc:
                            manifest_errors.append(
                                f'cannot update batch manifest: {exc}'
                            )

                for (
                    task_index,
                    file_name,
                    signal_name,
                    item,
                    image_path,
                ) in sorted(resolved_group_terminals, key=lambda value: value[0]):
                    if on_event:
                        on_event(BatchProgressEvent(
                            kind=(
                                'task_cancelled'
                                if item.status == 'cancelled'
                                else 'task_resumed'
                                if item.status == 'resumed'
                                else 'task_done'
                            ),
                            task_index=task_index,
                            total=total,
                            file_name=file_name,
                            signal=signal_name,
                            method=preset.method,
                            task_id=item.task_id,
                            message=item.message,
                            data_path=item.data_path,
                            image_path=image_path,
                        ))
                    if progress_callback and item.status == 'done':
                        progress_callback(task_index, total)

            if cancelled:
                status = 'cancelled'
            elif blocked and not any(
                item.status in {'done', 'skipped', 'resumed'} for item in items
            ):
                status = 'blocked'
            elif blocked:
                status = 'partial'
            else:
                status = 'done'
            return finish_result(
                status, items=items, blocked=blocked,
                render_groups=render_group_outcomes,
            )

        for index, (source_key, signal_name) in enumerate(tasks, start=1):
            # Logical groups from one container share a physical cache entry.
            # Eviction therefore happens only when the physical path changes,
            # never merely because the next task has a different source_id.
            physical_key = self._physical_for_source(source_key)
            if (
                prev_physical_key is not None
                and physical_key != prev_physical_key
            ):
                self._evict_physical(prev_physical_key)
                prev_physical_key = None

            if cancel_token is not None and cancel_token.is_set():
                cancelled = True
                emit_cancelled_range(index)
                break
            render_task = next(
                task for task in render_tasks
                if task.source_key == source_key
                and task.channel == signal_name
            )

            if resume_data is not None:
                resumed_item = self._resume_item(
                    preset,
                    source_key,
                    signal_name,
                    resume_data,
                    recipe_id,
                    requested_params,
                    cancel_token=cancel_token,
                )
                if cancel_token is not None and cancel_token.is_set():
                    cancelled = True
                    emit_cancelled_range(
                        index, message='cancelled during resume checksum',
                    )
                    break
                if resumed_item is not None:
                    resumed_item.started_at = utc_now()
                    resumed_item.finished_at = resumed_item.started_at
                    items.append(resumed_item)
                    fd = self._known_file_data(source_key)
                    record_item(resumed_item, source_key, fd)
                    if on_event:
                        on_event(BatchProgressEvent(
                            kind='task_resumed',
                            task_index=index,
                            total=total,
                            file_name=resumed_item.file_name,
                            signal=signal_name,
                            method=preset.method,
                            task_id=resumed_item.task_id,
                            message=resumed_item.message,
                            data_path=resumed_item.data_path,
                            image_path=resumed_item.image_path,
                        ))
                    continue

            if (
                explicit_grouping
                and set(effective_plan.effective) == {'data'}
                and str(
                    getattr(preset.outputs, 'conflict_policy', 'auto_number')
                ).strip().lower() in {'error', 'skip'}
            ):
                data_extension = str(
                    effective_plan.effective['data']
                ).lower().lstrip('.')
                policy = str(preset.outputs.conflict_policy).strip().lower()
                reservation = None
                conflict_status = ''
                conflict_message = ''
                try:
                    reservation = reserve_output_paths(
                        output_dir,
                        render_task.identity.stem,
                        (data_extension,),
                        conflict_policy=policy,
                    )
                    if reservation.status == 'skipped':
                        conflict_status = 'skipped'
                        conflict_message = (
                            'task data skipped without manifest provenance'
                        )
                except FileExistsError as exc:
                    conflict_status = 'failed'
                    conflict_message = str(exc)
                finally:
                    if reservation is not None:
                        reservation.release()
                if conflict_status:
                    item = BatchItemResult(
                        method='time',
                        file_id=source_key,
                        file_name=task_file_name(source_key),
                        signal=signal_name,
                        status=conflict_status,
                        message=conflict_message,
                        task_id=render_task.identity.task_id,
                        source_identity=render_task.identity.source_identity,
                        group_identity=render_task.identity.group_identity,
                        requested_outputs=dict(effective_plan.requested),
                        effective_outputs=dict(effective_plan.effective),
                        finished_at=utc_now(),
                    )
                    items.append(item)
                    record_item(item, source_key, self._known_file_data(source_key))
                    if conflict_status == 'failed':
                        blocked.append(
                            f'{item.file_name}:{signal_name}: {conflict_message}'
                        )
                    continue

            # Resolve the file (lazy load if disk path, live lookup if registered fid)
            fid, fd_or_fail = self._resolve_task_file(source_key)

            physical_key = self._physical_for_source(source_key)
            if physical_key is not None:
                prev_physical_key = physical_key

            # Determine file_name for events (works for _LoadFailure too)
            if isinstance(fd_or_fail, _LoadFailure):
                fname = fd_or_fail.path
            else:
                fname = getattr(fd_or_fail, 'filename', str(fid))

            if cancel_token is not None and cancel_token.is_set():
                cancelled = True
                emit_cancelled_range(index)
                break

            started_at = utc_now()
            if on_event:
                on_event(BatchProgressEvent(
                    kind='task_started',
                    task_index=index, total=total,
                    file_name=fname, signal=signal_name, method=preset.method,
                ))
            try:
                if isinstance(fd_or_fail, _LoadFailure):
                    raise IOError(fd_or_fail.error)
                if signal_name not in fd_or_fail.data.columns:
                    raise ValueError(f"missing signal: {signal_name}")
                item = self._run_one(preset, fid, fd_or_fail,
                                     signal_name, output_dir,
                                     cancel_token=cancel_token,
                                     effective=effective_plan,
                                     identity=render_task.identity)
                item.started_at = started_at
                item.finished_at = utc_now()
                items.append(item)
                record_item(item, source_key, fd_or_fail)
                if item.status == 'skipped':
                    blocked.append(
                        f"{fname}:{signal_name}: {item.message}; "
                        + "; ".join(item.warnings)
                    )
                if on_event:
                    kind = (
                        'task_skipped' if item.status == 'skipped'
                        else 'task_cancelled' if item.status == 'cancelled'
                        else 'task_done'
                    )
                    on_event(BatchProgressEvent(
                        kind=kind,
                        task_index=index, total=total,
                        file_name=fname, signal=signal_name,
                        method=preset.method,
                        task_id=item.task_id,
                        message=item.message,
                        data_path=item.data_path,
                        image_path=item.image_path,
                    ))
                # progress_callback fires ONLY on task_done (legacy contract
                # was "called once per completed task"). Failed tasks do NOT
                # bump it — see spec §4.4 / §8.
                if progress_callback and item.status == 'done':
                    progress_callback(index, total)
                if item.status == 'cancelled':
                    cancelled = True
                    emit_cancelled_range(index + 1)
                    break
            except _BatchCancelled as exc:
                cancelled = True
                identity = render_task.identity
                items.append(BatchItemResult(
                    method=preset.method,
                    file_id=fid,
                    file_name=fname,
                    signal=signal_name,
                    status='cancelled',
                    message=str(exc),
                    task_id=(identity.task_id if identity else ''),
                    source_identity=(identity.source_identity if identity else ''),
                    group_identity=(identity.group_identity if identity else ''),
                    requested_outputs=dict(requested_artifacts),
                    effective_outputs=dict(requested_artifacts),
                    started_at=started_at,
                    finished_at=utc_now(),
                ))
                record_item(items[-1], source_key, (
                    None if isinstance(fd_or_fail, _LoadFailure) else fd_or_fail
                ))
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='task_cancelled',
                        task_index=index,
                        total=total,
                        file_name=fname,
                        signal=signal_name,
                        method=preset.method,
                        task_id=items[-1].task_id,
                        message=str(exc),
                    ))
                emit_cancelled_range(index + 1)
                break
            except Exception as exc:
                identity = render_task.identity
                items.append(BatchItemResult(
                    method=preset.method, file_id=fid,
                    file_name=fname, signal=signal_name,
                    status='failed', message=str(exc),
                    task_id=(identity.task_id if identity else ''),
                    source_identity=(identity.source_identity if identity else ''),
                    group_identity=(identity.group_identity if identity else ''),
                    requested_outputs=dict(requested_artifacts),
                    effective_outputs=(
                        {} if isinstance(exc, _ImageBackendUnavailable)
                        else dict(requested_artifacts)
                    ),
                    started_at=started_at,
                    finished_at=utc_now(),
                ))
                blocked.append(f"{fname}:{signal_name}: {exc}")
                record_item(items[-1], source_key, (
                    None if isinstance(fd_or_fail, _LoadFailure) else fd_or_fail
                ))
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='task_failed',
                        task_index=index, total=total,
                        file_name=fname, signal=signal_name,
                        method=preset.method, error=str(exc),
                        task_id=items[-1].task_id,
                        message=str(exc),
                    ))

        # Evict every physical source, including an auxiliary cross-source RPM
        # container that may have been loaded during the final task.
        for physical_key in tuple(self._disk_cache):
            self._evict_physical(physical_key)

        if cancelled:
            status = 'cancelled'
        elif blocked and not any(
            item.status in {'done', 'skipped', 'resumed'} for item in items
        ):
            status = 'blocked'
        elif blocked:
            status = 'partial'
        else:
            status = 'done'
        return finish_result(status, items=items, blocked=blocked)

    def _physical_cache_key(self, path) -> str:
        raw = str(path)
        key = raw if self._loader is not None else canonical_source_path(raw)
        self._physical_paths.setdefault(key, raw)
        return key

    def _grouped_task_sort_key(self, source_key) -> tuple[str]:
        """Order grouped execution by canonical physical source and member."""

        fd = self._known_file_data(source_key)
        path = getattr(fd, 'filepath', None) if fd is not None else None
        physical_key = self._physical_for_source(source_key)
        if path in (None, '') and physical_key is not None:
            path = self._physical_paths.get(physical_key, physical_key)
        physical = (
            canonical_source_path(path)
            if path not in (None, '')
            else f'live:{source_key!r}'
        )
        return (physical,)

    def _group_member_source_facts(self, member: RenderTask) -> dict[str, Any]:
        source_key = member.source_key
        fd = self._known_file_data(source_key)
        path = getattr(fd, 'filepath', None) if fd is not None else None
        if path in (None, ''):
            physical_key = self._physical_for_source(source_key)
            if physical_key is not None:
                path = self._physical_paths.get(physical_key, physical_key)
        return source_file_facts(
            path,
            source_identity=member.identity.source_identity,
        )

    @staticmethod
    def _strict_source_facts_match(previous, current) -> bool:
        if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
            return False
        for source in (previous, current):
            if any(key not in source for key in ('identity', 'size', 'mtime_ns')):
                return False
            identity = source['identity']
            if not isinstance(identity, str) or not identity:
                return False
            for key in ('size', 'mtime_ns'):
                value = source[key]
                if value is not None and (
                    not isinstance(value, int) or isinstance(value, bool)
                ):
                    return False
        return all(
            previous[key] == current[key]
            for key in ('identity', 'size', 'mtime_ns')
        )

    def _recover_lazy_manifest_tasks(
        self,
        preset,
        manifest: Mapping[str, Any] | None,
        *,
        recipe_id: str,
        requested_params: Mapping[str, Any],
    ) -> list[tuple[object, str]]:
        """Recover a prior lazy pattern scope without opening a source."""

        source_paths = tuple(getattr(preset, 'source_paths', ()) or ())
        pattern = str(getattr(preset, 'signal_pattern', '') or '').strip()
        current_scope = self._lazy_pattern_execution_scope(preset)
        if (
            manifest is None
            or manifest.get('recipe_fingerprint') != recipe_id
            or not source_paths
            or current_scope is None
            or (manifest.get('normalized_recipe') or {}).get(
                'execution_scope'
            ) != current_scope
        ):
            return []
        allowed_paths = {
            canonical_source_path(path): path for path in source_paths
        }
        recovered = []
        seen = set()
        covered_paths = set()
        for entry in manifest.get('entries', ()):
            if entry.get('method') != preset.method:
                continue
            channel = entry.get('channel')
            source_id = entry.get('source_id')
            source = entry.get('source')
            if not isinstance(channel, str) or not self._matches(channel, pattern):
                continue
            if not isinstance(source, Mapping):
                return []
            source_path = source.get('path')
            if source_path in (None, ''):
                return []
            canonical_path = canonical_source_path(source_path)
            if canonical_path not in allowed_paths:
                return []
            current_identity = str(
                Path(allowed_paths[canonical_path]).expanduser().resolve(
                    strict=False,
                )
            )
            current_source = source_file_facts(
                allowed_paths[canonical_path],
                source_identity=current_identity,
            )
            if not self._strict_source_facts_match(source, current_source):
                return []
            self._register_source_locator(source_id, allowed_paths[canonical_path])
            group_identity = str(source.get('group_identity') or 'default')
            self._source_group_identity_hints[source_id] = group_identity
            identity = self._build_unresolved_task_identity(
                source_id,
                channel=channel,
                method=preset.method,
                params=requested_params,
                group_identity=group_identity,
            )
            if (
                identity.task_id != entry.get('task_id')
                or identity.source_identity != source.get('identity')
            ):
                return []
            task = (source_id, channel)
            if task not in seen:
                seen.add(task)
                recovered.append(task)
            covered_paths.add(canonical_path)
        if covered_paths != set(allowed_paths):
            return []
        return recovered

    def _resumable_group_data_entry(
        self,
        manifest: Mapping[str, Any] | None,
        member: RenderTask,
        *,
        cancel_token=None,
    ) -> Mapping[str, Any] | None:
        """Return exact task-data provenance for one grouped member."""

        if manifest is None:
            return None
        current_source = self._group_member_source_facts(member)
        candidates = [
            entry for entry in manifest.get('entries', ())
            if entry.get('task_id') == member.identity.task_id
            and entry.get('source_id') == member.source_key
            and entry.get('status') in {'done', 'resumed'}
            and not entry.get('degraded_reason')
        ]
        for candidate in candidates:
            previous_source = candidate.get('source')
            if not isinstance(previous_source, Mapping):
                continue
            if not self._strict_source_facts_match(
                previous_source, current_source,
            ):
                continue
            data = (candidate.get('artifacts') or {}).get('data')
            if not isinstance(data, Mapping):
                continue
            data_format = str(data.get('format', '')).strip().lower().lstrip('.')
            if not data_format:
                continue
            matched = find_resumable_entry(
                manifest,
                recipe_fingerprint=str(manifest.get('recipe_fingerprint') or ''),
                task_id=member.identity.task_id,
                source_id=member.source_key,
                source_identity=member.identity.source_identity,
                source_stat=current_source,
                required_artifacts={'data': data_format},
                cancel_token=cancel_token,
            )
            if matched is candidate:
                return candidate
        return None

    def _plan_group_recovery(
        self,
        group: RenderGroup,
        *,
        resume_manifest=None,
        retry_scope: RetryScope | None = None,
        image_format: str = 'png',
        cancel_token=None,
    ) -> GroupRecoveryDecision:
        """Plan grouped data, payload, and image work before source loading."""

        all_task_ids = frozenset(
            member.identity.task_id for member in group.members
        )
        if resume_manifest is None:
            return GroupRecoveryDecision(
                data_write_task_ids=all_task_ids,
                payload_task_ids=all_task_ids,
                image_write_required=True,
                reusable_group=None,
            )

        reusable_data_ids = frozenset(
            member.identity.task_id
            for member in group.members
            if self._resumable_group_data_entry(
                resume_manifest, member, cancel_token=cancel_token,
            ) is not None
        )
        data_write_ids = all_task_ids - reusable_data_ids

        reusable_group = None
        canonical_image_format = str(image_format).lower().lstrip('.')
        if retry_scope is None and canonical_image_format:
            members = tuple(
                GroupMemberResumeFact(
                    task_id=member.identity.task_id,
                    source=self._group_member_source_facts(member),
                )
                for member in group.members
            )
            reusable_group = find_resumable_group(
                resume_manifest,
                recipe_fingerprint=str(
                    resume_manifest.get('recipe_fingerprint') or ''
                ),
                group_id=group.identity.group_id,
                members=members,
                image_format=canonical_image_format,
                cancel_token=cancel_token,
            )

        image_write_required = reusable_group is None
        return GroupRecoveryDecision(
            data_write_task_ids=data_write_ids,
            payload_task_ids=(all_task_ids if image_write_required else frozenset()),
            image_write_required=image_write_required,
            reusable_group=reusable_group,
        )

    def _build_run_plan(
        self,
        tasks,
        *,
        preset,
        requested_params,
        explicit_grouping,
    ):
        """Build one complete canonical task and render-group plan."""

        planned_tasks = list(tasks)
        for source_key, _channel in planned_tasks:
            fd = self._known_file_data(source_key)
            if (
                fd is None
                and self._physical_for_source(source_key) is None
                and isinstance(source_key, (str, Path))
                and Path(str(source_key)).suffix
            ):
                self._register_source_locator(source_key, source_key)
        if explicit_grouping:
            planned_tasks.sort(
                key=lambda task: self._grouped_task_sort_key(task[0]),
            )

        render_tasks = []
        for source_key, channel in planned_tasks:
            fd = self._known_file_data(source_key)
            if fd is not None:
                identity = self._build_task_identity(
                    fd,
                    file_id=source_key,
                    channel=channel,
                    method=preset.method,
                    params=requested_params,
                )
            else:
                identity = self._build_unresolved_task_identity(
                    source_key,
                    channel=channel,
                    method=preset.method,
                    params=requested_params,
                    group_identity=self._source_group_identity_hints.get(
                        source_key,
                    ),
                )
            render_tasks.append(RenderTask(source_key, channel, identity))

        render_groups = (
            group_render_tasks(render_tasks, requested_params)
            if explicit_grouping and 'image' in self._required_artifacts(
                preset.outputs
            ) else ()
        )
        return planned_tasks, render_tasks, render_groups

    def _register_source_locator(self, source_id, path) -> None:
        physical_key = self._physical_cache_key(path)
        previous = self._source_locators.get(source_id)
        if previous is not None and previous != physical_key:
            raise ValueError(
                f"source_id {source_id!r} maps to multiple physical paths"
            )
        self._source_locators[source_id] = physical_key

    def _cache_source_descriptors(
        self, physical_key: str, raw_path, descriptors,
    ) -> tuple[object, ...]:
        source_ids = []
        for descriptor in descriptors:
            source_id = descriptor.source_id
            self._register_source_locator(source_id, raw_path)
            self._source_channel_cache[source_id] = frozenset(
                str(name) for name in descriptor.channel_names
            )
            self._source_group_identity_hints[source_id] = str(
                descriptor.group_id or 'default'
            )
            source_ids.append(source_id)
        source_ids = tuple(dict.fromkeys(source_ids))
        self._descriptor_source_ids[physical_key] = source_ids
        return source_ids

    def _bind_runtime_source_locators(self, preset) -> None:
        source_ids = tuple(getattr(preset, 'source_ids', ()) or ())
        source_paths = tuple(getattr(preset, 'source_paths', ()) or ())
        if not source_ids or not source_paths:
            return
        if len(source_paths) == 1 and len(source_ids) > 1:
            source_paths = source_paths * len(source_ids)
        if len(source_ids) != len(source_paths):
            raise ValueError(
                "source_ids and source_paths must be parallel runtime scopes"
            )
        for source_id, path in zip(source_ids, source_paths):
            self._register_source_locator(source_id, path)
        if self._loader is not None:
            return
        unresolved_by_physical: dict[str, set[object]] = {}
        for source_id in source_ids:
            if self._known_file_data(source_id) is not None:
                continue
            physical_key = self._source_locators[source_id]
            unresolved_by_physical.setdefault(physical_key, set()).add(
                source_id,
            )
        for physical_key, unresolved_ids in unresolved_by_physical.items():
            if physical_key in self._descriptor_probe_cache:
                continue
            raw_path = self._physical_paths.get(physical_key, physical_key)
            probe = self._metadata_descriptor_probe(raw_path)
            if probe is None:
                continue
            try:
                descriptors = tuple(probe(
                    raw_path, context=self._source_context,
                ))
            except (OSError, SourceUnavailableError) as exc:
                # Descriptor probing is a no-load planning enhancement.  A
                # source can disappear after the UI discovered it, so retain
                # the stable unresolved identity and let run() perform the
                # authoritative load.  Deliberately do not catch ValueError or
                # arbitrary RuntimeError: malformed descriptor implementations
                # remain visible programming/configuration errors.
                self._descriptor_probe_failures[physical_key] = str(exc)
                self._descriptor_probe_cache.add(physical_key)
                continue
            found_ids = set(self._cache_source_descriptors(
                physical_key, raw_path, descriptors,
            )) & unresolved_ids
            missing_ids = unresolved_ids - found_ids
            if missing_ids:
                missing = ', '.join(sorted(str(item) for item in missing_ids))
                raise ValueError(
                    f'batch source probe did not return source_id(s): {missing}'
                )
            self._descriptor_probe_cache.add(physical_key)

    def _path_source_keys_without_load(self, paths) -> list[object]:
        scoped_keys = []
        for path in dict.fromkeys(paths):
            physical_key = self._physical_cache_key(path)
            if physical_key not in self._descriptor_probe_cache:
                raw_path = self._physical_paths.get(physical_key, physical_key)
                probe = self._metadata_descriptor_probe(raw_path)
                if probe is None:
                    scoped_keys.append(path)
                    continue
                try:
                    descriptors = tuple(probe(
                        raw_path, context=self._source_context,
                    ))
                except (OSError, SourceUnavailableError) as exc:
                    self._descriptor_probe_failures[physical_key] = str(exc)
                    self._descriptor_probe_cache.add(physical_key)
                    scoped_keys.append(path)
                    continue
                self._cache_source_descriptors(
                    physical_key, raw_path, descriptors,
                )
                self._descriptor_probe_cache.add(physical_key)
            source_ids = self._descriptor_source_ids.get(physical_key, ())
            if source_ids:
                scoped_keys.extend(source_ids)
            else:
                scoped_keys.append(path)
        return list(dict.fromkeys(scoped_keys))

    def _metadata_descriptor_probe(self, path):
        """Return a probe only when its no-sample cost is explicit."""

        registry = self._source_registry
        probe = getattr(registry, 'probe_sources', None)
        if not callable(probe):
            return None
        adapter_for = getattr(registry, 'adapter_for', None)
        if callable(adapter_for):
            probe_cost = getattr(adapter_for(path), 'probe_cost', None)
        else:
            probe_cost_for = getattr(registry, 'probe_cost_for', None)
            probe_cost = (
                probe_cost_for(path)
                if callable(probe_cost_for)
                else getattr(registry, 'probe_cost', None)
            )
        return probe if str(probe_cost or '').lower() == 'metadata' else None

    @staticmethod
    def _loaded_file_data(value):
        if isinstance(value, LoadedSource):
            value.file_data.source_metadata.setdefault(
                'source_id', value.source_id,
            )
            value.file_data.source_metadata.setdefault(
                'group_id', value.group_id,
            )
            return value.file_data
        return value

    def _known_file_data(self, source_key):
        value = self.files.get(source_key)
        if value is not None:
            return self._loaded_file_data(value)
        resolved = self._source_cache.get(source_key)
        return resolved.file_data if resolved is not None else None

    def _normalize_loaded_sources(
        self, result, *, physical_key: str, expected_source_id=None,
    ) -> tuple[_ResolvedSource, ...]:
        if isinstance(result, (LoadedSource,)) or hasattr(result, 'data'):
            entries = (result,)
        elif isinstance(result, (tuple, list)):
            entries = tuple(result)
        else:
            raise TypeError(
                "batch source loader must return FileData, LoadedSource, or a tuple"
            )
        if not entries:
            raise ValueError("source loader returned no logical sources")

        resolved: list[_ResolvedSource] = []
        seen_ids = set()
        for index, entry in enumerate(entries):
            if isinstance(entry, LoadedSource):
                source_id = entry.source_id
                group_id = str(entry.group_id or 'default')
                fd = entry.file_data
                display_name = str(entry.display_name or fd.filename)
            elif hasattr(entry, 'data'):
                fd = entry
                metadata = getattr(fd, 'source_metadata', {}) or {}
                if len(entries) == 1 and expected_source_id is not None:
                    source_id = expected_source_id
                else:
                    source_id = metadata.get('source_id')
                    if source_id in (None, ''):
                        source_id = (
                            physical_key if len(entries) == 1
                            else f"{physical_key}#group:{index}"
                        )
                group_id = str(
                    metadata.get('group_id')
                    or metadata.get('group_identity')
                    or getattr(fd, 'label_suffix', '')
                    or ('default' if len(entries) == 1 else index)
                )
                display_name = str(getattr(fd, 'filename', source_id))
            else:
                raise TypeError(
                    "batch source tuple entries must be FileData or LoadedSource"
                )
            if source_id in seen_ids:
                raise ValueError(
                    f"physical source returned duplicate source_id {source_id!r}"
                )
            seen_ids.add(source_id)
            fd.source_metadata.setdefault('source_id', source_id)
            fd.source_metadata.setdefault('group_id', group_id)
            self._source_channel_cache[source_id] = frozenset(
                str(name) for name in fd.get_signal_channels()
            )
            resolved.append(_ResolvedSource(
                source_id=source_id,
                physical_path=physical_key,
                group_id=group_id,
                file_data=fd,
                display_name=display_name,
            ))
        return tuple(resolved)

    def _load_physical_sources(
        self, physical_key: str, *, expected_source_id=None,
    ) -> tuple[_ResolvedSource, ...]:
        cached = self._disk_cache.get(physical_key)
        if isinstance(cached, _LoadFailure):
            raise IOError(cached.error)
        if cached is not None:
            return cached

        raw_path = self._physical_paths.get(physical_key, physical_key)
        try:
            if self._loader is not None:
                loaded = self._loader(raw_path)
            else:
                loaded = self._source_registry.load_sources(
                    raw_path,
                    context=self._source_context,
                )
            sources = self._normalize_loaded_sources(
                loaded,
                physical_key=physical_key,
                expected_source_id=(
                    expected_source_id if self._loader is not None else None
                ),
            )
        except Exception as exc:
            failure = _LoadFailure(str(raw_path), str(exc))
            self._disk_cache[physical_key] = failure
            raise

        self._disk_cache[physical_key] = sources
        for source in sources:
            self._source_cache[source.source_id] = source
            self._source_locators.setdefault(source.source_id, physical_key)
        return sources

    def _evict_physical(self, physical_key: str) -> None:
        self._disk_cache.pop(physical_key, None)
        stale = [
            source_id for source_id, source in self._source_cache.items()
            if source.physical_path == physical_key
        ]
        for source_id in stale:
            self._source_cache.pop(source_id, None)

    def _physical_for_source(self, source_key) -> str | None:
        cached = self._source_cache.get(source_key)
        if cached is not None:
            return cached.physical_path
        return self._source_locators.get(source_key)

    def _resolve_task_file(self, source_key):
        """Resolve a logical source key without reloading its physical file."""

        fd = self._known_file_data(source_key)
        if fd is not None:
            return source_key, fd

        physical_key = self._source_locators.get(source_key)
        if physical_key is None and isinstance(source_key, (str, Path)):
            raw = str(source_key)
            if Path(raw).suffix:
                physical_key = self._physical_cache_key(raw)
                self._source_locators[source_key] = physical_key
        if physical_key is None:
            return source_key, _LoadFailure(
                str(source_key), f"unknown source_id: {source_key}",
            )

        try:
            sources = self._load_physical_sources(
                physical_key,
                expected_source_id=source_key,
            )
        except Exception as exc:  # noqa: BLE001
            raw_path = self._physical_paths.get(physical_key, physical_key)
            return source_key, _LoadFailure(str(raw_path), str(exc))

        resolved = self._source_cache.get(source_key)
        if resolved is not None:
            return source_key, resolved.file_data
        if len(sources) == 1 and self._loader is not None:
            # Legacy injected loaders return a bare FileData keyed by path.
            return source_key, sources[0].file_data
        available = ", ".join(str(source.source_id) for source in sources)
        return source_key, _LoadFailure(
            self._physical_paths.get(physical_key, physical_key),
            f"source_id {source_key!r} not returned by physical source; "
            f"available: {available}",
        )

    def _scope_source_keys(self, preset, *, allow_source_load=False):
        self._bind_runtime_source_locators(preset)
        source_ids = tuple(getattr(preset, 'source_ids', ()) or ())
        if source_ids:
            unique_ids = list(dict.fromkeys(source_ids))
            if allow_source_load and self._loader is None:
                physical_keys = list(dict.fromkeys(
                    self._source_locators[source_id]
                    for source_id in unique_ids
                    if (
                        source_id in self._source_locators
                        and self._known_file_data(source_id) is None
                    )
                ))
                if len(physical_keys) == 1:
                    # One container may own multiple logical groups. Keeping
                    # that one FileData set avoids a probe-then-reload while
                    # still respecting the one-physical-file memory bound.
                    self._load_physical_sources(physical_keys[0])
                else:
                    for physical_key in physical_keys:
                        raw_path = self._physical_paths.get(
                            physical_key, physical_key,
                        )
                        probe = getattr(
                            self._source_registry, 'probe_sources', None,
                        )
                        if callable(probe):
                            descriptors = probe(
                                raw_path, context=self._source_context,
                            )
                            for descriptor in descriptors:
                                self._source_channel_cache[
                                    descriptor.source_id
                                ] = frozenset(
                                    str(name)
                                    for name in descriptor.channel_names
                                )
                        else:
                            # Compatibility fallback for injected registries
                            # without the descriptor API: load one physical
                            # source, retain only channel names, then evict it
                            # before inspecting the next source.
                            self._load_physical_sources(physical_key)
                            self._evict_physical(physical_key)
            # Keep all logical groups from one physical container adjacent so
            # the run loop can evict that container exactly once.
            grouped: dict[object, list[object]] = {}
            for source_id in unique_ids:
                group_key = self._source_locators.get(
                    source_id, ('live', source_id),
                )
                grouped.setdefault(group_key, []).append(source_id)
            return [
                source_id
                for group in grouped.values()
                for source_id in group
            ]

        source_paths = tuple(getattr(preset, 'source_paths', ()) or ())
        if source_paths:
            if not allow_source_load:
                if self._loader is None:
                    return self._path_source_keys_without_load(source_paths)
                return list(dict.fromkeys(source_paths))
            discovered = []
            for path in dict.fromkeys(source_paths):
                physical_key = self._physical_cache_key(path)
                sources = self._load_physical_sources(physical_key)
                discovered.extend(source.source_id for source in sources)
            return list(dict.fromkeys(discovered))

        legacy = list(getattr(preset, 'file_ids', ()) or ())
        legacy_paths = tuple(getattr(preset, 'file_paths', ()) or ())
        if (
            legacy_paths
            and not allow_source_load
            and not legacy
            and self._loader is None
        ):
            return self._path_source_keys_without_load(legacy_paths)
        if legacy_paths and allow_source_load and self._loader is None:
            for path in dict.fromkeys(legacy_paths):
                physical_key = self._physical_cache_key(path)
                sources = self._load_physical_sources(physical_key)
                legacy.extend(source.source_id for source in sources)
        else:
            legacy.extend(legacy_paths)
            for path in legacy_paths:
                self._register_source_locator(path, path)
        if legacy:
            return list(dict.fromkeys(legacy))
        return list(self.files.keys())

    def _resolve_files(self, preset):
        """Yield logical source keys and loaded data for legacy pattern mode."""

        if preset.source == 'current_single':
            keys = [preset.signal[0]] if preset.signal is not None else []
        else:
            keys = self._scope_source_keys(preset, allow_source_load=True)
        for source_key in keys:
            fid, fd = self._resolve_task_file(source_key)
            yield fid, fd

    def _expand_tasks(self, preset, *, allow_source_load=False):
        if preset.method not in self.SUPPORTED_METHODS:
            return
        self._bind_runtime_source_locators(preset)
        if preset.source == 'current_single':
            if preset.signal is None:
                return
            fid, ch = preset.signal
            fd = self._known_file_data(fid)
            if fd is not None and ch in fd.data.columns:
                yield fid, ch
            elif fid in self._source_locators:
                yield fid, ch
            return
        if preset.target_pairs:
            # Runtime-exact scope takes precedence over the legacy cartesian
            # ``file_ids/file_paths × target_signals`` expansion.  Do not
            # silently discard missing pairs here; run() reports them as
            # per-task failures after lazy source resolution.
            for pair in preset.target_pairs:
                if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                    continue
                yield pair[0], str(pair[1])
            return
        if preset.target_signals:
            source_keys = self._scope_source_keys(
                preset, allow_source_load=allow_source_load,
            )
            policy = str(
                getattr(preset, 'target_policy', 'common') or 'common'
            ).strip().lower()
            if policy not in {'common', 'available_per_source', 'exact_pairs'}:
                raise ValueError(f"unsupported target_policy: {policy}")
            if policy == 'exact_pairs':
                return

            selected = tuple(str(ch) for ch in preset.target_signals)
            params = dict(getattr(preset, 'params', {}) or {})
            x_channel = str(params.get('x_channel', '') or '').strip()
            needs_custom_x = (
                preset.method == 'time'
                and str(params.get('x_source', 'time') or 'time').lower()
                == 'channel'
                and bool(x_channel)
            )
            channels_by_source = {}
            for source_key in source_keys:
                fd = self._known_file_data(source_key)
                if fd is not None:
                    available = set(fd.get_signal_channels())
                else:
                    cached_channels = self._source_channel_cache.get(source_key)
                    available = (
                        None if cached_channels is None
                        else set(cached_channels)
                    )
                channels_by_source[source_key] = available

            if policy == 'common':
                known_sets = [
                    channels for channels in channels_by_source.values()
                    if channels is not None
                ]
                common = tuple(
                    channel for channel in selected
                    if all(channel in channels for channels in known_sets)
                )
                for source_key in source_keys:
                    for channel in common:
                        yield source_key, channel
                return

            for source_key in source_keys:
                available = channels_by_source[source_key]
                for channel in selected:
                    if available is not None and channel not in available:
                        continue
                    if (
                        needs_custom_x
                        and available is not None
                        and x_channel not in available
                    ):
                        continue
                    yield source_key, channel
            return
        # Pattern fallback (legacy / test path): the pre-probe planning pass may
        # enumerate already-resident sources only.  Lazy sources are expanded
        # by run() after the effective image decision succeeds.
        if not allow_source_load:
            pattern = preset.signal_pattern.strip()
            for source_key in self._scope_source_keys(
                preset, allow_source_load=False,
            ):
                fd = self._known_file_data(source_key)
                if fd is None:
                    continue
                for ch in fd.get_signal_channels():
                    if preset.method.startswith('order') and ch == preset.rpm_channel:
                        continue
                    if self._matches(ch, pattern):
                        yield source_key, ch
            return
        # UI never produces pattern mode (always uses target_signals via free_config).
        files_iter = list(self._resolve_files(preset))
        pattern = preset.signal_pattern.strip()
        for fid, fd in files_iter:
            if isinstance(fd, _LoadFailure):
                continue
            for ch in fd.get_signal_channels():
                if preset.method.startswith('order') and ch == preset.rpm_channel:
                    continue
                if self._matches(ch, pattern):
                    yield fid, ch

    @staticmethod
    def _matches(channel, pattern):
        """通道名匹配规则：

        - 空 pattern → 匹配所有通道
        - pattern 大小写不敏感地包含在 channel 中（substring） → 匹配
        - 否则按 pattern 当正则解析（IGNORECASE，re.search 半匹配） → 匹配

        **注意：** substring 优先级高于 regex。所以包含正则元字符
        （如 ``motor.speed``）的字面量信号名会先按 substring 匹配；
        若 substring 未命中，``.`` 才被解释为"任意字符"，可能产生
        意料之外的命中（如匹配到 ``motorXspeed``）。需要严格字面量
        匹配的调用方应自行做 `re.escape(pattern)`。
        """
        if not pattern:
            return True
        channel_l = channel.lower()
        pattern_l = pattern.lower()
        if pattern_l in channel_l:
            return True
        try:
            return re.search(pattern, channel, flags=re.IGNORECASE) is not None
        except re.error:
            return False

    def _compute_group_task(
        self,
        preset: AnalysisPreset,
        source_key: object,
        fd,
        signal_name: str,
        output_dir: Path,
        spool: BatchSeriesSpool,
        group: RenderGroup,
        *,
        data_write_eligible: bool,
        payload_required: bool,
        data_reservation=None,
        effective: EffectiveOutputPlan,
        cancel_token=None,
    ) -> TaskComputeResult:
        """Compute one explicit-group task and publish only its data unit."""

        params = normalize_batch_params(preset.params, preset.method)
        group_member = next(
            member for member in group.members
            if member.source_key == source_key
            and member.channel == signal_name
        )
        identity = group_member.identity
        started_at = utc_now()
        reservation = data_reservation
        data_path = None
        status = 'done'
        message = ''
        warnings: list[str] = list(effective.migration_warnings)
        try:
            self._check_cancel(cancel_token, 'preprocess')
            signal = fd.data[signal_name].to_numpy(dtype=float, copy=False)
            time = fd.time_array
            fs_raw = params.get('fs')
            fs = float(fd.fs if fs_raw in (None, '') else fs_raw)
            x_values = None
            if str(params.get('x_source', 'time') or 'time').lower() == 'channel':
                x_channel = str(params.get('x_channel', '') or '').strip()
                if x_channel not in fd.data.columns:
                    raise ValueError(f'missing X channel: {x_channel}')
                x_values = fd.data[x_channel].to_numpy(dtype=float, copy=False)
            preprocessed = preprocess_batch_signal(
                signal, time, fs, params, x_values=x_values,
            )
            raise_for_issues(validate_task(
                'time',
                params,
                fs=preprocessed.effective_fs,
                sample_count=len(preprocessed.signal),
                time=preprocessed.time,
            ))
            effective_params = dict(params)
            effective_params['fs'] = preprocessed.effective_fs
            effective_params['filter'] = dict(preprocessed.effective['filter'])
            effective_params['preprocess'] = dict(preprocessed.effective)
            warnings.extend(preprocessed.warnings)
            frame = self._compute_preprocessed_time_dataframe(
                preprocessed.pre_filter_signal,
                preprocessed.signal,
                preprocessed.time,
                preprocessed.effective_fs,
                effective_params,
            )
            self._check_cancel(cancel_token, 'compute')

            if data_write_eligible:
                data_extension = str(
                    effective.effective.get('data', 'csv')
                ).lower().lstrip('.')
                conflict_policy = str(
                    getattr(preset.outputs, 'conflict_policy', 'auto_number')
                ).strip().lower()
                if reservation is None:
                    reservation = reserve_output_paths(
                        output_dir,
                        identity.stem,
                        (data_extension,),
                        conflict_policy=conflict_policy,
                    )
                reservation.before_publish = lambda: self._check_cancel(
                    cancel_token, 'artifact publish',
                )
                if reservation.status == 'skipped':
                    status = 'skipped'
                    message = 'task data skipped without manifest provenance'
                    if reservation.warning:
                        warnings.append(reservation.warning)
                else:
                    while True:
                        try:
                            published = atomic_write_set(
                                reservation,
                                {data_extension: lambda path: self._write_dataframe(
                                    frame, path,
                                )},
                            )
                            data_path = published[data_extension]
                            break
                        except OutputPublishRace:
                            if conflict_policy != 'auto_number':
                                raise
                            reservation.release()
                            reservation = reserve_output_paths(
                                output_dir,
                                identity.stem,
                                (data_extension,),
                                conflict_policy='auto_number',
                            )
                            reservation.before_publish = lambda: self._check_cancel(
                                cancel_token, 'artifact publish',
                            )

            panel = (
                group.members.index(group_member)
                if group.layout == 'subplot' else 0
            )
            refs: tuple[SpooledSeriesRef, ...] = ()
            render_error = ''
            render_status = ''
            if payload_required:
                series = self._build_time_series(
                    fd=fd,
                    signal_name=signal_name,
                    preprocessed=preprocessed,
                    source_label=str(fd.filename),
                    params=params,
                    panel=panel,
                    family_key=group_member.identity.task_id,
                )
                try:
                    refs = spool.append(
                        group.identity.group_id,
                        group_member.identity.task_id,
                        series,
                    )
                except ValueError as exc:
                    render_error = str(exc)
                    render_status = 'blocked'
                except _BatchCancelled:
                    raise
                except Exception as exc:
                    render_error = str(exc)
                    render_status = 'failed'

            facts = {}
            if data_path is not None:
                stat = Path(data_path).stat()
                facts['data'] = {
                    'kind': 'data',
                    'path': str(Path(data_path).resolve(strict=False)),
                    'format': str(effective.effective['data']),
                    'size': int(stat.st_size),
                }
            item = BatchItemResult(
                method='time',
                file_id=source_key,
                file_name=str(fd.filename),
                signal=signal_name,
                status=status,
                data_path=str(data_path) if data_path is not None else None,
                message=message,
                task_id=identity.task_id,
                source_identity=identity.source_identity,
                group_identity=identity.group_identity,
                effective_params=effective_params,
                warnings=list(dict.fromkeys(warnings)),
                requested_outputs=dict(effective.requested),
                effective_outputs=dict(effective.effective),
                degraded_reason=effective.degraded_reason,
                artifact_facts=facts,
                started_at=started_at,
                finished_at=utc_now(),
            )
            return TaskComputeResult(
                item=item,
                series_refs=refs,
                render_error=render_error,
                render_status=render_status,
            )
        finally:
            if reservation is not None:
                reservation.release()

    def _render_group(
        self,
        group: RenderGroup,
        results: Sequence[TaskComputeResult],
        preset: AnalysisPreset,
        output_dir: Path,
        spool: BatchSeriesSpool,
        *,
        effective: EffectiveOutputPlan,
        reservation_stem: str | None = None,
        conflict_policy_override: str | None = None,
        recorder=None,
        cancel_token=None,
    ) -> RenderGroupResult:
        """Publish one explicit group image in its own atomic transaction."""

        usable = [result for result in results if result.series_refs]
        if not usable:
            return RenderGroupResult(
                group_id=group.identity.group_id,
                status='failed',
                message='no successful render payloads',
                warnings=list(effective.migration_warnings),
            )
        refs = tuple(
            ref for result in usable for ref in result.series_refs
        )
        loaded = ()
        reservation = None
        try:
            loaded = spool.load(refs)
            self._check_cancel(cancel_token, 'group render')
            params = normalize_batch_params(preset.params, preset.method)
            x_source = str(params.get('x_source', 'time') or 'time').lower()
            if x_source == 'channel':
                x_channel = str(params.get('x_channel', '') or '').strip()
                x_unit = next((item.x_unit for item in loaded if item.x_unit), '')
                x_label = f'{x_channel} ({x_unit})' if x_unit else x_channel
            else:
                x_label = 'Time (s)'
            result_by_task = {
                result.item.task_id: result for result in results
            }
            panel_titles = tuple(
                (
                    member.channel
                    if group.group_by == 'source'
                    else result_by_task[member.identity.task_id].item.file_name
                    if member.identity.task_id in result_by_task
                    else member.channel
                )
                for member in group.members
            ) if group.layout == 'subplot' else ()
            spec = self._build_time_figure_spec(
                loaded,
                params=params,
                x_label=x_label,
                panel_titles=panel_titles,
            )
            statistics_facts: dict[str, Any] = {}
            statistics_warnings: list[str] = []
            statistics_config = params.get('chart_statistics') or {}
            if bool(statistics_config.get('enabled', False)):
                diagnostics = [
                    {
                        'code': item.code,
                        'message': item.message,
                        'panel': item.panel,
                    }
                    for item in spec.diagnostics
                ]
                statistics_facts = {
                    'chart_statistics': {
                        'config': dict(statistics_config),
                        'row_count': len(spec.statistics),
                        'rows': [
                            {
                                'series_key': item.series_key,
                                'panel': item.panel,
                                'branch': item.branch_label,
                                'sample_count': item.sample_count,
                                'minimum': item.minimum,
                                'maximum': item.maximum,
                                'mean': item.mean,
                            }
                            for item in spec.statistics
                        ],
                        'diagnostics': diagnostics,
                    },
                }
                statistics_warnings = [item['code'] for item in diagnostics]
            image_extension = str(effective.effective['image'])
            conflict_policy = str(
                conflict_policy_override
                or getattr(preset.outputs, 'conflict_policy', 'auto_number')
            ).strip().lower()
            reservation = reserve_output_paths(
                output_dir,
                reservation_stem or group.identity.stem,
                (image_extension,),
                conflict_policy=conflict_policy,
            )
            reservation.before_publish = lambda: self._check_cancel(
                cancel_token, 'group image publish',
            )
            if reservation.status == 'skipped':
                return RenderGroupResult(
                    group_id=group.identity.group_id,
                    status='skipped',
                    message='group image skipped without manifest provenance',
                    warnings=list(dict.fromkeys([
                        *effective.migration_warnings,
                        *([reservation.warning] if reservation.warning else []),
                    ])),
                )
            BatchRenderContext, BatchRenderOptions = effective.render_backend_types
            width, height = preset.outputs.resolved_image_dimensions()
            options = BatchRenderOptions(
                width_px=width,
                height_px=height,
                dpi=int(preset.outputs.image_dpi),
                format=image_extension,
                background=str(preset.outputs.image_background),
                line_width=float(preset.outputs.image_line_width),
            )
            member_fact = f'{len(usable)}/{len(group.members)}'
            facts = dict(params)
            facts.update(statistics_facts)
            if len(usable) != len(group.members):
                facts['members'] = member_fact
            context = BatchRenderContext(
                source_display_name=group.display_name,
                group='',
                channel='',
                unit='',
                method='time',
                task_id=group.identity.group_id,
                effective_facts=facts,
            )
            while True:
                attempt_warnings: list[str] = []

                def write_image(path):
                    return self._write_image(
                        ('time', spec),
                        path,
                        params=params,
                        options=options,
                        context=context,
                        warnings_out=attempt_warnings,
                    )

                try:
                    published = atomic_write_set(
                        reservation, {image_extension: write_image},
                    )
                    warnings = list(dict.fromkeys([
                        *effective.migration_warnings,
                        *statistics_warnings,
                        *attempt_warnings,
                    ]))
                    break
                except OutputPublishRace:
                    if conflict_policy != 'auto_number':
                        raise
                    reservation.release()
                    reservation = reserve_output_paths(
                        output_dir,
                        reservation_stem or group.identity.stem,
                        (image_extension,),
                        conflict_policy='auto_number',
                    )
                    reservation.before_publish = lambda: self._check_cancel(
                        cancel_token, 'group image publish',
                    )
            image_path = published[image_extension]
            artifact = artifact_facts(
                image_path,
                kind='image',
                artifact_format=image_extension,
                width=width,
                height=height,
                dpi=int(preset.outputs.image_dpi),
                cancel_token=cancel_token,
            )
            if (
                artifact.get('checksum_status') != 'complete'
                and cancel_token is not None
                and cancel_token.is_set()
            ):
                return RenderGroupResult(
                    group_id=group.identity.group_id,
                    status='cancelled',
                    image_path=str(image_path),
                    message='cancelled during group artifact checksum',
                    warnings=warnings,
                    artifact=artifact,
                    effective_facts=statistics_facts,
                )
            return RenderGroupResult(
                group_id=group.identity.group_id,
                status=(
                    'done' if len(usable) == len(group.members) else 'partial'
                ),
                image_path=str(image_path),
                warnings=warnings,
                artifact=artifact,
                effective_facts=statistics_facts,
            )
        finally:
            if reservation is not None:
                reservation.release()
            spool.release_loaded(loaded)

    def _render_group_manifest_entry(
        self,
        group: RenderGroup,
        effective: EffectiveOutputPlan,
        *,
        status: str,
        message: str = '',
        warnings: Sequence[str] = (),
        artifact: Mapping[str, Any] | None = None,
        effective_facts: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        members = []
        for member in group.members:
            source_key = member.source_key
            fd = self._known_file_data(source_key)
            path = getattr(fd, 'filepath', None) if fd is not None else None
            if path in (None, ''):
                physical_key = self._physical_for_source(source_key)
                if physical_key is not None:
                    path = self._physical_paths.get(physical_key, physical_key)
            members.append({
                'task_id': member.identity.task_id,
                'source': source_file_facts(
                    path,
                    source_identity=member.identity.source_identity,
                ),
            })
        return {
            'group_id': group.identity.group_id,
            'stem': group.identity.stem,
            'group_by': group.group_by,
            'layout': group.layout,
            'members': members,
            'requested_outputs': dict(effective.requested),
            'effective_outputs': dict(effective.effective),
            'degraded_reason': effective.degraded_reason,
            'status': str(status),
            'message': str(message),
            'warnings': list(dict.fromkeys(
                str(item)
                for item in (*effective.migration_warnings, *warnings)
                if item
            )),
            'artifact': dict(artifact) if artifact is not None else None,
            'effective_facts': dict(effective_facts or {}),
        }

    def _run_one(self, preset, fid, fd, signal_name, output_dir, *,
                 cancel_token=None, effective: EffectiveOutputPlan | None = None,
                 identity=None):
        method = preset.method
        requested_params = normalize_batch_params(preset.params, method)
        if identity is None:
            identity = self._build_task_identity(
                fd,
                file_id=fid,
                channel=signal_name,
                method=method,
                params=requested_params,
            )
        effective = effective or self._resolve_effective_outputs(preset.outputs)
        requested_outputs = dict(effective.requested)
        effective_outputs = dict(effective.effective)
        degraded_reason = effective.degraded_reason
        migration_warnings = list(effective.migration_warnings)
        render_backend_types = effective.render_backend_types
        output_extensions = tuple(effective_outputs.values())
        conflict_policy = str(
            getattr(preset.outputs, 'conflict_policy', 'auto_number')
        ).strip().lower()
        reservation = reserve_output_paths(
            output_dir,
            identity.stem,
            output_extensions,
            conflict_policy=conflict_policy,
        )
        reservation.before_publish = lambda: self._check_cancel(
            cancel_token, "artifact publish",
        )
        if reservation.status == 'skipped':
            data_format = str(preset.outputs.data_format).lower().lstrip('.')
            data_extension = data_format if data_format == 'xlsx' else 'csv'
            image_extension = str(
                getattr(preset.outputs, 'image_format', 'png')
            ).lower().lstrip('.')
            existing_extensions = sorted(
                ext for ext, path in reservation.paths.items() if path.exists()
            )
            missing_extensions = sorted(
                ext for ext, path in reservation.paths.items() if not path.exists()
            )
            conflict_facts = (
                f"existing={','.join(existing_extensions) or 'none'}; "
                f"missing={','.join(missing_extensions) or 'none'}"
            )
            return BatchItemResult(
                method=method,
                file_id=fid,
                file_name=fd.filename,
                signal=signal_name,
                status='skipped',
                data_path=(
                    str(reservation.paths[data_extension])
                    if 'data' in effective_outputs
                    and reservation.paths[data_extension].exists()
                    else None
                ),
                image_path=(
                    str(reservation.paths[image_extension])
                    if 'image' in effective_outputs
                    and reservation.paths[image_extension].exists()
                    else None
                ),
                message=(
                    'artifact set skipped without manifest provenance; '
                    + conflict_facts
                ),
                task_id=identity.task_id,
                source_identity=identity.source_identity,
                group_identity=identity.group_identity,
                warnings=list(dict.fromkeys([
                    *migration_warnings,
                    reservation.warning,
                    conflict_facts,
                ])),
                requested_outputs=dict(requested_outputs),
                effective_outputs=dict(effective_outputs),
                degraded_reason=degraded_reason,
            )

        try:
            self._check_cancel(cancel_token, "preprocess")
            sig = fd.data[signal_name].to_numpy(dtype=float, copy=False)
            time = fd.time_array
            fs_raw = requested_params.get('fs')
            fs = float(fd.fs if fs_raw in (None, '') else fs_raw)

            warnings_out: list[str] = []
            rpm = None
            if method == 'order_time':
                rpm = self._rpm_values(
                    fd,
                    preset,
                    target_source_id=fid,
                    warnings_out=warnings_out,
                )

            x_values = None
            if method == 'time' and str(requested_params.get(
                'x_source', 'time',
            ) or 'time').strip().lower() == 'channel':
                x_channel = str(
                    requested_params.get('x_channel', '') or ''
                ).strip()
                if x_channel not in fd.data.columns:
                    raise ValueError(f"missing X channel: {x_channel}")
                x_values = fd.data[x_channel].to_numpy(
                    dtype=float, copy=False,
                )

            preprocessed = preprocess_batch_signal(
                sig,
                time,
                fs,
                requested_params,
                rpm=rpm,
                x_values=x_values,
            )
            sig = preprocessed.signal
            time = preprocessed.time
            fs = preprocessed.effective_fs
            rpm = preprocessed.rpm
            raise_for_issues(validate_task(
                method,
                requested_params,
                fs=fs,
                sample_count=len(sig),
                time=time,
                rpm_channel=preset.rpm_channel,
                rpm_signal=preset.rpm_signal,
                rpm_values=rpm,
            ))
            effective_params = dict(requested_params)
            effective_params['fs'] = fs
            effective_params['filter'] = dict(preprocessed.effective['filter'])
            effective_params['preprocess'] = dict(preprocessed.effective)
            if method == 'order_time':
                if preset.rpm_signal is not None:
                    effective_params['rpm_source'] = {
                        'mode': 'channel',
                        'source_id': preset.rpm_signal[0],
                        'channel': str(preset.rpm_signal[1]),
                    }
                else:
                    effective_params['rpm_source'] = {
                        'mode': 'channel',
                        'source_id': fid,
                        'channel': str(
                            preset.rpm_channel or _guess_rpm_channel(fd)
                        ),
                    }
            warnings = list(dict.fromkeys([
                *migration_warnings,
                *preprocessed.warnings,
                *warnings_out,
            ]))

            spectro = None
            fft_df = None
            time_df = None
            if method == 'time':
                self._check_cancel(cancel_token, "compute")
                time_df = self._compute_preprocessed_time_dataframe(
                    preprocessed.pre_filter_signal,
                    sig,
                    time,
                    fs,
                    effective_params,
                )
                image_payload = ('time', time_df)
                if 'image' in effective_outputs:
                    time_series = self._build_time_series(
                        fd=fd,
                        signal_name=signal_name,
                        preprocessed=preprocessed,
                        source_label=str(fd.filename),
                        params=requested_params,
                        panel=0,
                        family_key=identity.task_id,
                    )
                    x_source = str(requested_params.get(
                        'x_source', 'time',
                    ) or 'time').strip().lower()
                    if x_source == 'channel':
                        x_channel = str(requested_params.get(
                            'x_channel', '',
                        ) or '').strip()
                        x_unit = time_series[0].x_unit if time_series else ''
                        x_label = (
                            f'{x_channel} ({x_unit})' if x_unit else x_channel
                        )
                    else:
                        x_label = 'Time (s)'
                    image_payload = ('time', self._build_time_figure_spec(
                        time_series,
                        params=requested_params,
                        x_label=x_label,
                        panel_titles=(str(fd.filename),),
                    ))
            elif method == 'fft':
                effective_nfft = self._resolve_effective_nfft(
                    method, len(sig), fs, effective_params,
                )
                effective_params['nfft_effective'] = effective_nfft
                compute_params = dict(effective_params)
                compute_params['nfft'] = effective_nfft
                compute_params['filter'] = {'enabled': False}
                self._check_cancel(cancel_token, "compute")
                fft_df = self._compute_fft_dataframe(sig, fs, compute_params)
                image_payload = ('fft', fft_df)
            elif method == 'fft_time':
                effective_nfft = self._resolve_effective_nfft(
                    method, len(sig), fs, effective_params,
                )
                effective_params['nfft_effective'] = effective_nfft
                compute_params = dict(effective_params)
                compute_params['nfft'] = effective_nfft
                compute_params['filter'] = {'enabled': False}
                self._check_cancel(cancel_token, "compute")
                spectro = self._compute_fft_time_spectro(
                    sig, time, fs, compute_params, channel_name=signal_name,
                )
                image_payload = ('fft_time', spectro)
            else:
                if method == 'order_time':
                    effective_nfft = self._resolve_effective_nfft(
                        method, len(sig), fs, effective_params,
                    )
                    effective_params['nfft_effective'] = effective_nfft
                    compute_params = dict(effective_params)
                    compute_params['nfft'] = effective_nfft
                    compute_params['filter'] = {'enabled': False}
                    self._check_cancel(cancel_token, "compute")
                    spectro = self._compute_order_time_spectro(
                        sig, rpm, time, fs, compute_params,
                    )
                    image_payload = ('order_time', spectro)
                else:  # pragma: no cover - guarded by _expand_tasks
                    raise ValueError(f"unsupported method: {method}")
            self._check_cancel(cancel_token, "compute")

            data_format = str(preset.outputs.data_format).lower().lstrip('.')
            data_extension = data_format if data_format == 'xlsx' else 'csv'
            image_extension = str(
                getattr(preset.outputs, 'image_format', 'png')
            ).lower().lstrip('.')
            resolution = None
            colorbar_label = None
            image_params = None
            render_options = None
            render_context = None
            unit = self._channel_unit(fd, signal_name)
            if 'image' in effective_outputs:
                migrated_params = db_reference.migrate_legacy_reference_params(
                    effective_params
                )
                facts = self._channel_reference_facts(fd, signal_name)
                resolution = db_reference.resolve_db_reference(
                    mode=migrated_params.get('db_reference_mode', 'auto'),
                    manual_value=migrated_params.get('db_reference'),
                    facts=facts,
                    user_catalog=self._db_reference_user_catalog,
                    system_catalog=self._db_reference_system_catalog,
                    prefer_channel_metadata=self._prefer_channel_metadata,
                )
                image_params = dict(migrated_params)
                image_params['db_reference'] = resolution.value
                image_params['db_reference_resolution'] = resolution
                render_db, output_scale = self._batch_output_scale(
                    method, image_params
                )
                weighting = str(image_params.get('weighting', 'None'))
                colorbar_label = db_reference.format_amplitude_label(
                    resolution,
                    weighting=weighting,
                    output_scale=output_scale,
                )
                effective_params['db_reference'] = resolution.value
                effective_params['db_reference_mode'] = migrated_params.get(
                    'db_reference_mode', 'auto',
                )
                effective_params['db_reference_source'] = resolution.source
                BatchRenderContext, BatchRenderOptions = render_backend_types

                width, height = preset.outputs.resolved_image_dimensions()
                render_options = BatchRenderOptions(
                    width_px=width,
                    height_px=height,
                    dpi=int(preset.outputs.image_dpi),
                    format=image_extension,
                    background=str(preset.outputs.image_background),
                    line_width=float(preset.outputs.image_line_width),
                )
                render_context = BatchRenderContext(
                    source_display_name=str(fd.filename),
                    group=identity.group_identity,
                    channel=signal_name,
                    unit=str(unit),
                    method=method,
                    task_id=identity.task_id,
                    effective_facts=effective_params,
                )

            # Resolved after the image decision on purpose: a slice workbook
            # must quote the dB reference and the effective facts the *page*
            # was drawn with, so both read them from the same locals rather
            # than resolving a second time (design §6.2 / acceptance 11).
            export_frame_factory = None
            if preset.outputs.export_data:
                # Preserve the matrix-first image-only path.
                if time_df is not None:
                    export_frame_factory = lambda frame=time_df: frame
                elif fft_df is not None:
                    export_frame_factory = lambda: image_payload[1]
                else:
                    export_frame_factory = self._slice_workbook_factory(
                        spectro,
                        method=method,
                        params=(
                            image_params if image_params is not None
                            else effective_params
                        ),
                        fact_params=effective_params,
                        data_extension=data_extension,
                        resolution=resolution,
                        fd=fd,
                        signal_name=signal_name,
                        unit=unit,
                        warnings_out=warnings,
                        owns_clamp_warning=image_params is None,
                    ) or spectro.to_long_dataframe
            # The holder transfers sole ownership of the export payload to the
            # data writer. Clearing the local reference ensures a heatmap long
            # table is collectible before a 4K/vector render allocates its
            # figure/RGBA buffers; image_payload keeps only the matrix result.
            # A slice workbook is a few hundred rows and does not need that,
            # but it travels the same way so there is only one shape of
            # write/retry path to reason about.
            export_frame_holder = (
                [export_frame_factory()]
                if export_frame_factory is not None else []
            )

            while True:
                attempt_warnings = []
                writers = {}
                if export_frame_holder:
                    def write_data(path, holder=export_frame_holder):
                        payload = holder.pop()
                        try:
                            self._check_cancel(cancel_token, "data write")
                            result = (
                                self._write_workbook(payload, path)
                                if isinstance(payload, dict)
                                else self._write_dataframe(payload, path)
                            )
                            self._check_cancel(cancel_token, "data write")
                            return result
                        finally:
                            del payload
                            holder.clear()

                    writers[data_extension] = write_data
                if image_params is not None:
                    def write_image(path):
                        self._check_cancel(cancel_token, "image render/write")
                        result = self._write_image(
                            image_payload,
                            path,
                            params=image_params,
                            options=render_options,
                            context=render_context,
                            warnings_out=attempt_warnings,
                        )
                        self._check_cancel(cancel_token, "image render/write")
                        return result

                    writers[image_extension] = write_image
                try:
                    published = atomic_write_set(reservation, writers)
                    warnings.extend(attempt_warnings)
                    break
                except OutputPublishRace:
                    if conflict_policy != 'auto_number':
                        raise
                    self._check_cancel(
                        cancel_token, "output reservation retry",
                    )
                    reservation = reserve_output_paths(
                        output_dir,
                        identity.stem,
                        output_extensions,
                        conflict_policy='auto_number',
                    )
                    reservation.before_publish = lambda: self._check_cancel(
                        cancel_token, "artifact publish",
                    )
                    if export_frame_factory is not None:
                        export_frame_holder.append(export_frame_factory())

            data_path = (
                published.get(data_extension)
                if 'data' in effective_outputs else None
            )
            image_path = (
                published.get(image_extension)
                if 'image' in effective_outputs else None
            )
            published_facts = {}
            if data_path is not None:
                data_stat = Path(data_path).stat()
                published_facts['data'] = {
                    'kind': 'data',
                    'path': str(Path(data_path).resolve(strict=False)),
                    'format': data_extension,
                    'size': int(data_stat.st_size),
                }
            if image_path is not None:
                image_stat = Path(image_path).stat()
                width, height = preset.outputs.resolved_image_dimensions()
                published_facts['image'] = {
                    'kind': 'image',
                    'path': str(Path(image_path).resolve(strict=False)),
                    'format': image_extension,
                    'size': int(image_stat.st_size),
                    'width': width,
                    'height': height,
                    'dpi': int(preset.outputs.image_dpi),
                }
            return BatchItemResult(
                method=method,
                file_id=fid,
                file_name=fd.filename,
                signal=signal_name,
                status='done',
                data_path=str(data_path) if data_path else None,
                image_path=str(image_path) if image_path else None,
                colorbar_label=colorbar_label,
                db_reference_value=(
                    resolution.value if resolution is not None else None
                ),
                db_reference_source=(
                    resolution.source if resolution is not None else None
                ),
                task_id=identity.task_id,
                source_identity=identity.source_identity,
                group_identity=identity.group_identity,
                effective_params=effective_params,
                warnings=(
                    [*warnings, degraded_reason]
                    if degraded_reason else warnings
                ),
                requested_outputs=dict(requested_outputs),
                effective_outputs=dict(effective_outputs),
                degraded_reason=degraded_reason,
                artifact_facts=published_facts,
            )
        finally:
            reservation.release()

    def _slice_workbook_factory(
        self,
        spectro,
        *,
        method: str,
        params: Mapping[str, Any],
        fact_params: Mapping[str, Any],
        data_extension: str,
        resolution,
        fd,
        signal_name: str,
        unit: str,
        warnings_out: list,
        owns_clamp_warning: bool = False,
    ):
        """A sheet-dict producer for the slice workbook, or ``None``.

        ``None`` means "keep exporting the historical long table". Three ways
        to get there, all of them deliberate:

        * the preset enables no slice -- then the data file must stay
          byte-identical to what the same preset produced before this feature
          existed (design D21, acceptance 12);
        * the requested format is csv, which cannot carry two sheets
          (design D22) -- a warning says so;
        * the optional Qt renderer is not installed, so no curve was drawn and
          there is nothing for the table to have to match.

        The returned callable is the *only* producer: it is called once up
        front and again by the ``OutputPublishRace`` retry, exactly like the
        long-table factory it replaces.

        ``owns_clamp_warning`` is set when this run writes no image. Design
        §4.5 gave the out-of-range warning to ``build_heatmap``, which is
        silent on a data-only run -- and that is exactly the run where nobody
        sees the chart's own annotation, so the clamp would reach the manifest
        through no channel at all. The chart still owns it whenever one is
        drawn, so the two paths can never both report the same clamp.
        """
        raw_slice = params.get('slice') if isinstance(params, Mapping) else None
        if not isinstance(raw_slice, Mapping) or not raw_slice.get('enabled', False):
            # Normalization keeps slice only when enabled; do not import the Qt renderer.
            return None
        contract = _load_slice_render_contract()
        if contract is None:
            return None
        plan = contract.plan_heatmap_slice(spectro.x, spectro.y, params)
        if not plan.enabled:
            return None
        if data_extension != 'xlsx':
            if _SLICE_CSV_FALLBACK_WARNING not in warnings_out:
                warnings_out.append(_SLICE_CSV_FALLBACK_WARNING)
            return None
        if owns_clamp_warning:
            axis_values = spectro.x if plan.axis == 'time' else spectro.y
            axis_name = (
                spectro.x_name if plan.axis == 'time' else spectro.y_name
            )
            clamp = contract.slice_clamp_warning(
                plan,
                float(np.nanmin(axis_values)),
                float(np.nanmax(axis_values)),
                _slice_axis_labels(axis_name)[3],
            )
            if clamp is not None and clamp not in warnings_out:
                warnings_out.append(clamp)

        render_db = bool(contract.render_in_db(method, params))
        reference = None
        amplitude_label = contract.linear_amplitude_label(unit)
        if render_db:
            if resolution is None:
                # Data-only run: no image block resolved one, so repeat its
                # exact call (real channel facts + the injected catalogs)
                # rather than the renderer's facts-free fallback.
                migrated = db_reference.migrate_legacy_reference_params(params)
                resolution = db_reference.resolve_db_reference(
                    mode=migrated.get('db_reference_mode', 'auto'),
                    manual_value=migrated.get('db_reference'),
                    facts=self._channel_reference_facts(fd, signal_name),
                    user_catalog=self._db_reference_user_catalog,
                    system_catalog=self._db_reference_system_catalog,
                    prefer_channel_metadata=self._prefer_channel_metadata,
                )
            reference = float(resolution.value)
            amplitude_label = db_reference.format_amplitude_label(
                resolution,
                weighting=str(params.get('weighting', 'None')),
                output_scale='db',
            )

        facts = contract.effective_fact_items(fact_params, params)
        method_label = contract.method_labels.get(method, method)
        source = str(fd.filename)

        def build_sheets():
            return spectro.to_slice_sheets(
                plan,
                render_db=render_db,
                reference=reference,
                amplitude_label=amplitude_label,
                facts=facts,
                source=source,
                channel=signal_name,
                unit=unit,
                method=method_label,
            )

        return build_sheets

    @staticmethod
    def _channel_unit(fd, channel: str) -> str:
        channel_meta = (
            (getattr(fd, 'channel_metadata', None) or {}).get(channel, {}) or {}
        )
        return str(
            channel_meta.get('unit')
            or (getattr(fd, 'channel_units', None) or {}).get(channel, '')
            or ''
        )

    def _build_time_series(
        self,
        *,
        fd,
        signal_name: str,
        preprocessed: BatchPreprocessResult,
        source_label: str,
        params: Mapping[str, Any],
        panel: int,
        family_key: str = '',
    ) -> tuple[BatchSeries, ...]:
        from .batch_render import BatchSeries

        x_source = str(params.get('x_source', 'time') or 'time').strip().lower()
        if x_source == 'channel':
            x_channel = str(params.get('x_channel', '') or '').strip()
            if x_channel not in fd.data.columns:
                raise ValueError(f"missing X channel: {x_channel}")
            if preprocessed.x_values is None:
                raise ValueError(f"X channel was not aligned: {x_channel}")
            x = preprocessed.x_values
            x_unit = self._channel_unit(fd, x_channel)
        else:
            x = preprocessed.time
            x_unit = 's'

        unit = self._channel_unit(fd, signal_name)
        source = str(source_label or '').strip()
        base_label = f'{source} / {signal_name}' if source else signal_name
        filter_state = params.get('filter') or {}
        filter_enabled = bool(filter_state.get('enabled', False))
        if not filter_enabled:
            return (BatchSeries(
                x=x,
                y=preprocessed.signal,
                label=base_label,
                unit=unit,
                x_unit=x_unit,
                linestyle='-',
                panel=panel,
                family_key=family_key,
                series_key=f'{family_key}:value',
                variant='value',
            ),)

        show_original = bool(filter_state.get('show_original', True))
        show_filtered = bool(filter_state.get('show_filtered', True))
        if not show_original and not show_filtered:
            raise ValueError(
                "时域导出至少需要原始或滤波后一项"
            )
        show_both = show_original and show_filtered
        series = []
        if show_original:
            series.append(BatchSeries(
                x=x,
                y=preprocessed.pre_filter_signal,
                label=(f'{base_label} · original' if show_both else base_label),
                unit=unit,
                x_unit=x_unit,
                linestyle='-',
                panel=panel,
                family_key=family_key,
                series_key=f'{family_key}:original',
                variant='original',
            ))
        if show_filtered:
            series.append(BatchSeries(
                x=x,
                y=preprocessed.signal,
                label=(f'{base_label} · filtered' if show_both else base_label),
                unit=unit,
                x_unit=x_unit,
                linestyle='--',
                panel=panel,
                family_key=family_key,
                series_key=f'{family_key}:filtered',
                variant='filtered',
            ))
        return tuple(series)

    @staticmethod
    def _build_time_figure_spec(
        series: Sequence[BatchSeries],
        *,
        params: Mapping[str, Any],
        x_label: str,
        panel_titles: Sequence[str] = (),
    ) -> BatchTimeFigureSpec:
        from .batch_render import BatchTimeFigureSpec

        x_source = str(params.get('x_source', 'time') or 'time').strip().lower()
        x_origin = (
            'absolute'
            if x_source == 'channel'
            else str(params.get('x_origin', 'zero') or 'zero').strip().lower()
        )
        from .batch_statistics import StatisticSeriesInput, plan_chart_statistics
        stats_plan = plan_chart_statistics(
            tuple(StatisticSeriesInput(
                x=item.x, y=item.y, series_key=item.series_key,
                family_key=item.family_key, label=item.label,
                variant=item.variant, panel=item.panel,
            ) for item in series),
            dict(params).get('chart_statistics') or {},
            x_source=x_source,
            x_origin=x_origin,
        )
        return BatchTimeFigureSpec(
            series=tuple(series),
            layout=str(
                params.get('render_layout', 'overlay') or 'overlay'
            ).strip().lower(),
            x_source=x_source,
            x_origin=x_origin,
            x_label=str(x_label),
            panel_titles=tuple(panel_titles),
            statistics=stats_plan.rows,
            diagnostics=stats_plan.diagnostics,
        )

    @staticmethod
    def _build_task_identity(fd, *, file_id, channel, method, params):
        """Use adapter group identity even when display suffixes collide."""

        metadata = getattr(fd, 'source_metadata', {}) or {}
        group_id = metadata.get('group_id')
        if group_id not in (None, ''):
            source = SimpleNamespace(
                filepath=fd.filepath,
                label_suffix=str(group_id),
                source_metadata={'group_identity': str(group_id)},
            )
        else:
            source = fd
        return build_task_output_identity(
            source,
            file_id=file_id,
            channel=channel,
            method=method,
            params=params,
        )

    def _build_unresolved_task_identity(
        self,
        source_key,
        *,
        channel,
        method,
        params,
        group_identity=None,
    ):
        physical_key = self._physical_for_source(source_key)
        source_path = (
            self._physical_paths.get(physical_key, physical_key)
            if physical_key is not None else None
        )
        if group_identity in (None, ''):
            group_identity = self._source_group_identity_hints.get(source_key)
        if group_identity in (None, ''):
            group_identity = f'unresolved-source:{source_key}'
        source = SimpleNamespace(
            filepath=source_path,
            label_suffix=str(group_identity),
            source_metadata={
                'group_identity': str(group_identity),
            },
        )
        return build_task_output_identity(
            source,
            file_id=source_key,
            channel=channel,
            method=method,
            params=params,
        )

    def _resume_item(
        self,
        preset,
        source_key,
        signal_name,
        manifest,
        recipe_id,
        requested_params,
        *,
        cancel_token=None,
    ):
        """Return a checksum-proven resumed item without resolving the source."""

        candidates = [
            entry for entry in manifest.get('entries', [])
            if (
                entry.get('source_id') == source_key
                and entry.get('channel') == signal_name
                and entry.get('method') == preset.method
                and entry.get('status') in {'done', 'resumed'}
            )
        ]
        if not candidates:
            return None

        fd = self._known_file_data(source_key)
        physical_key = self._physical_for_source(source_key)
        source_path = (
            getattr(fd, 'filepath', None) if fd is not None else None
        )
        if source_path in (None, '') and physical_key is not None:
            source_path = self._physical_paths.get(physical_key, physical_key)

        for candidate in candidates:
            source = candidate.get('source') or {}
            if fd is not None:
                identity = self._build_task_identity(
                    fd,
                    file_id=source_key,
                    channel=signal_name,
                    method=preset.method,
                    params=requested_params,
                )
            elif source_path not in (None, ''):
                group_identity = str(
                    source.get('group_identity') or 'default'
                )
                unresolved = SimpleNamespace(
                    filepath=source_path,
                    label_suffix=group_identity,
                    source_metadata={'group_identity': group_identity},
                )
                identity = build_task_output_identity(
                    unresolved,
                    file_id=source_key,
                    channel=signal_name,
                    method=preset.method,
                    params=requested_params,
                )
            else:
                continue
            current_source = source_file_facts(
                source_path,
                source_identity=identity.source_identity,
            )
            matched = find_resumable_entry(
                manifest,
                recipe_fingerprint=recipe_id,
                task_id=identity.task_id,
                source_id=source_key,
                source_identity=identity.source_identity,
                source_stat=current_source,
                required_artifacts=self._required_artifacts(preset.outputs),
                cancel_token=cancel_token,
            )
            if matched is None:
                continue
            artifacts = dict(matched.get('artifacts') or {})
            data = artifacts.get('data') or {}
            image = artifacts.get('image') or {}
            return BatchItemResult(
                method=preset.method,
                file_id=source_key,
                file_name=str(
                    source.get('display_name')
                    or getattr(fd, 'filename', source_key)
                ),
                signal=signal_name,
                status='resumed',
                data_path=data.get('path'),
                image_path=image.get('path'),
                message='manifest-proven resume',
                task_id=identity.task_id,
                source_identity=identity.source_identity,
                group_identity=identity.group_identity,
                effective_params=dict(matched.get('effective_facts') or {}),
                warnings=list(matched.get('warnings') or []),
                requested_outputs=dict(
                    matched.get('requested_outputs')
                    or self._required_artifacts(preset.outputs)
                ),
                effective_outputs=dict(
                    matched.get('effective_outputs')
                    or self._required_artifacts(preset.outputs)
                ),
                degraded_reason=str(matched.get('degraded_reason') or ''),
                artifact_facts=artifacts,
            )
        return None

    @staticmethod
    def _channel_reference_facts(fd, ch):
        """Build a :class:`db_reference.ChannelReferenceFacts` for one batch
        task's ``(FileData, signal_name)`` target (plan Task 9 Step 9.3),
        reading ONLY ``FileData`` metadata -- never a sample array (mirrors
        ``MainWindow._channel_reference_facts``; duplicated here rather than
        imported because ``batch.py`` must never import ``mf4_analyzer.ui.*``).
        """
        if fd is None or ch is None:
            return db_reference.ChannelReferenceFacts(quantity='', unit='')
        ch_meta = (getattr(fd, 'channel_metadata', None) or {}).get(ch) or {}
        unit = (
            ch_meta.get('unit')
            or (getattr(fd, 'channel_units', None) or {}).get(ch, '')
            or ''
        )
        # Mirror MainWindow._channel_reference_facts: reverse toolchain unit
        # encoding (U_ prefix, Y for /) at the facts boundary so batch export's
        # dB labels/refs match the interactive path (U_Nm -> Nm, mYs2 -> m/s2).
        unit = db_reference.canonicalize_source_unit(unit)
        quantity = ch_meta.get('quantity') or ''
        metadata_reference = ch_meta.get('db_reference')
        is_audio_source_fn = getattr(fd, 'is_audio_source', None)
        try:
            is_audio = bool(is_audio_source_fn()) if callable(is_audio_source_fn) else False
        except Exception:
            is_audio = False
        return db_reference.ChannelReferenceFacts(
            quantity=str(quantity),
            unit=str(unit),
            metadata_reference=metadata_reference,
            is_audio_source=is_audio,
        )

    @staticmethod
    def _batch_output_scale(kind, params):
        """Return ``(render_db, output_scale)`` -- the amp-mode resolution
        shared by ``_run_one`` (records ``colorbar_label`` on
        ``BatchItemResult``) and ``_build_export_scene`` (actually draws the
        image), so the two can never drift on which scale a preset's
        ``amplitude_mode``/``amp_y`` selects."""
        default_amp_mode = 'amplitude_db' if kind == 'fft_time' else 'amplitude'
        amp_mode = str(params.get('amplitude_mode', default_amp_mode)).lower()
        amp_y = str(params.get('amp_y', '')).lower()
        render_db = 'db' in amp_mode or amp_y == 'db'
        return render_db, ('db' if render_db else 'linear')

    @staticmethod
    def _image_reference_resolution(params):
        """The effective dB-reference resolution for a batch image render.

        ``_run_one`` (Task 9 Step 9.3) always pre-attaches an already-
        resolved ``db_reference_resolution`` -- built from the task's real
        ``(FileData, signal_name)`` facts and the injected catalog snapshot
        -- onto its OUTPUT param copy before calling ``_write_image``; this
        just returns that unchanged. Direct calls to ``_build_export_scene``/
        ``_write_image`` that bypass ``_run_one`` (existing unit tests call
        these ``@staticmethod``s directly with a bare params dict, no file
        context -- 2026-06-20 static-image-writer-test-api-wider-than-plan)
        resolve against EMPTY facts and the immutable factory catalog
        instead, through the exact same ``db_reference.resolve_db_reference``
        priority chain, so both paths share ONE formatting/validation rule
        and neither ever silently coerces an invalid reference via
        ``max(ref, 1e-12)`` (spec §7 R3 / plan Task 9 Step 9.4)."""
        existing = params.get('db_reference_resolution')
        if isinstance(existing, db_reference.DbReferenceResolution):
            return existing
        migrated = db_reference.migrate_legacy_reference_params(params)
        return db_reference.resolve_db_reference(
            mode=migrated.get('db_reference_mode', 'auto'),
            manual_value=migrated.get('db_reference'),
            facts=db_reference.ChannelReferenceFacts(quantity='', unit=''),
            user_catalog=(),
            system_catalog=db_reference.FACTORY_CATALOG_V1,
            prefer_channel_metadata=True,
        )

    @staticmethod
    def _check_cancel(cancel_token, stage):
        if cancel_token is not None and cancel_token.is_set():
            raise _BatchCancelled(f"cancelled during {stage}")

    @staticmethod
    def _apply_time_range(sig, time, params, rpm=None):
        time_range = params.get('time_range')
        if not time_range or time is None:
            return sig, time, rpm
        lo, hi = time_range
        mask = (time >= float(lo)) & (time <= float(hi))
        sig = sig[mask]
        time = time[mask]
        if rpm is not None:
            rpm = rpm[mask]
        return sig, time, rpm

    @staticmethod
    def _suggest_fs_from_time_axis(time, fallback_fs):
        arr = np.asarray(time, dtype=float)
        if arr.size < 2:
            return float(fallback_fs)
        dt = np.diff(arr)
        positive = dt[dt > 0]
        if positive.size == 0:
            return float(fallback_fs)
        median_dt = float(np.median(positive))
        if not np.isfinite(median_dt) or median_dt <= 0:
            return float(fallback_fs)
        return 1.0 / median_dt

    @classmethod
    def _uniform_time_axis_for_spectrogram(cls, time, fs, length):
        """Return a spectrogram-safe time axis and matching Fs.

        Batch FFT-vs-Time mirrors the single-file UX: jittered MF4
        timestamps are rebuilt to ``arange(n) / suggested_fs`` using the
        median-dt estimate instead of failing every task with the raw
        ``non-uniform time axis`` validator error.
        """
        fs = float(fs)
        if time is None:
            return np.arange(int(length), dtype=float) / fs, fs
        time_arr = np.asarray(time, dtype=float)
        if time_arr.size < 2:
            return time_arr, fs

        from .signal.spectrogram import (
            DEFAULT_TIME_JITTER_TOLERANCE,
            SpectrogramAnalyzer,
        )

        try:
            SpectrogramAnalyzer._validate_time_axis(
                time_arr, fs, DEFAULT_TIME_JITTER_TOLERANCE,
            )
            return time_arr, fs
        except ValueError as exc:
            if 'non-uniform time axis' not in str(exc):
                raise

        suggested = cls._suggest_fs_from_time_axis(time_arr, fs)
        if not (np.isfinite(suggested) and suggested > 0):
            suggested = fs
        return np.arange(len(time_arr), dtype=float) / float(suggested), float(suggested)

    @staticmethod
    def _time_axis_or_fallback(time, fs, n_samples):
        if time is not None:
            arr = np.asarray(time, dtype=float)
            if arr.size == int(n_samples):
                return arr
        fs = float(fs)
        if not np.isfinite(fs) or fs <= 0:
            raise ValueError("缺少有效采样率")
        return np.arange(int(n_samples), dtype=float) / fs

    @staticmethod
    def _filter_state(params):
        state = params.get("filter") or {}
        return state if isinstance(state, dict) else {}

    @classmethod
    def _filter_enabled(cls, params):
        return bool(cls._filter_state(params).get("enabled", False))

    @classmethod
    def _filter_spec_from_params(cls, params):
        if not cls._filter_enabled(params):
            return None
        from .signal.filters import FilterSpec

        return FilterSpec.from_dict(cls._filter_state(params).get("spec") or {})

    @classmethod
    def _apply_filter_if_enabled(cls, sig, fs, params):
        spec = cls._filter_spec_from_params(params)
        if spec is None:
            return np.asarray(sig, dtype=float), None
        from .signal import filters as _filters

        guarded, _msg = _filters.nyquist_guard(spec, fs)
        return _filters.apply(sig, guarded, fs), guarded

    @classmethod
    def _compute_time_dataframe(cls, sig, time, fs, params):
        x = cls._time_axis_or_fallback(time, fs, len(sig))
        filter_state = cls._filter_state(params)
        if not cls._filter_enabled(params):
            return pd.DataFrame({
                "time_s": x,
                "series": ["original"] * len(sig),
                "value": np.asarray(sig, dtype=float),
            })

        show_original = bool(filter_state.get("show_original", True))
        show_filtered = bool(filter_state.get("show_filtered", True))
        if not show_original and not show_filtered:
            raise ValueError("时域导出至少需要原始或滤波后一项")

        frames = []
        if show_original:
            frames.append(pd.DataFrame({
                "time_s": x,
                "series": ["original"] * len(sig),
                "value": np.asarray(sig, dtype=float),
            }))
        if show_filtered:
            filtered, _spec = cls._apply_filter_if_enabled(sig, fs, params)
            frames.append(pd.DataFrame({
                "time_s": x,
                "series": ["filtered"] * len(filtered),
                "value": filtered,
            }))
        return pd.concat(frames, ignore_index=True)

    @classmethod
    def _compute_preprocessed_time_dataframe(
        cls, pre_filter_signal, filtered_signal, time, fs, params,
    ):
        """Build TimeDomain rows from the canonical preprocessing outputs."""

        x = cls._time_axis_or_fallback(time, fs, len(filtered_signal))
        filter_state = cls._filter_state(params)
        if not cls._filter_enabled(params):
            return pd.DataFrame({
                "time_s": x,
                "series": ["original"] * len(filtered_signal),
                "value": np.asarray(filtered_signal, dtype=float),
            })

        show_original = bool(filter_state.get("show_original", True))
        show_filtered = bool(filter_state.get("show_filtered", True))
        if not show_original and not show_filtered:
            raise ValueError("时域导出至少需要原始或滤波后一项")

        frames = []
        if show_original:
            frames.append(pd.DataFrame({
                "time_s": x,
                "series": ["original"] * len(pre_filter_signal),
                "value": np.asarray(pre_filter_signal, dtype=float),
            }))
        if show_filtered:
            frames.append(pd.DataFrame({
                "time_s": x,
                "series": ["filtered"] * len(filtered_signal),
                "value": np.asarray(filtered_signal, dtype=float),
            }))
        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _compute_fft_dataframe(sig, fs, params):
        sig, _spec = BatchRunner._apply_filter_if_enabled(sig, fs, params)
        nfft = BatchRunner._resolve_fft_nfft(len(sig), fs, params)
        win = params.get('window', params.get('win', 'hanning'))
        weighting = str(params.get('weighting', 'None'))
        avg_mode = str(params.get('avg_mode', '单帧'))
        avg_overlap = BatchRunner._avg_overlap_fraction(params)
        if avg_mode == '线性平均':
            freq, amp, _psd = FFTAnalyzer.compute_averaged_fft(
                sig, fs, win, int(nfft), avg_overlap, weighting=weighting,
            )
        elif avg_mode == '峰值保持':
            freq, amp = FFTAnalyzer.compute_peak_hold_fft(
                sig, fs, win=win, nfft=int(nfft), overlap=avg_overlap,
                weighting=weighting,
            )
        else:
            freq, amp = FFTAnalyzer.compute_fft(
                sig,
                fs,
                win=win,
                nfft=nfft,
                weighting=weighting,
            )
        amp = BatchRunner._convert_fft_amplitude_definition(
            amp,
            avg_mode=avg_mode,
            requested=params.get('amplitude_definition', 'native'),
        )
        return pd.DataFrame({'frequency_hz': freq, 'amplitude': amp})

    @staticmethod
    def _convert_fft_amplitude_definition(amp, *, avg_mode, requested):
        """Convert an FFT mode's native linear amplitude to peak or RMS."""

        requested = str(requested or 'native').strip().lower()
        native = 'rms' if str(avg_mode) == '线性平均' else 'peak'
        values = np.asarray(amp, dtype=float)
        if requested == 'native' or requested == native:
            return values
        if native == 'rms' and requested == 'peak':
            return values * np.sqrt(2.0)
        if native == 'peak' and requested == 'rms':
            return values / np.sqrt(2.0)
        # Runner preflight owns the user-facing field error. Keep this helper
        # fail-closed for direct test/caller use that bypasses run().
        raise ValueError(
            "amplitude_definition must be native, peak, or rms"
        )

    @staticmethod
    def _avg_overlap_fraction(params):
        try:
            value = float(params.get('avg_overlap', 50))
        except (TypeError, ValueError):
            value = 50.0
        if value > 1.0:
            value /= 100.0
        return max(0.0, min(0.95, value))

    @staticmethod
    def _resolve_fft_nfft(n_samples, fs, params):
        nfft_raw = params.get('nfft')
        avg_mode = str(params.get('avg_mode', '单帧'))
        if isinstance(nfft_raw, str):
            nfft = None if nfft_raw.strip() in ('', '自动', 'auto') else int(nfft_raw)
        elif nfft_raw is None or nfft_raw <= 0:
            nfft = None
        else:
            nfft = int(nfft_raw)
        if nfft is None and avg_mode in {'线性平均', '峰值保持'}:
            t_win_s = float(params.get('t_win_s', 1.5))
            return int(resolve_nfft(
                float(fs), int(n_samples), t_win_s,
                BatchRunner._avg_overlap_fraction(params),
            ))
        return nfft

    @staticmethod
    def _resolve_effective_nfft(method, n_samples, fs, params):
        raw = params.get('nfft')
        auto = raw is None or raw == ''
        if isinstance(raw, str):
            auto = raw.strip().lower() in {'auto', '自动'}
        elif isinstance(raw, (int, float, np.integer, np.floating)):
            auto = float(raw) <= 0
        if not auto:
            return int(raw)
        if method == 'fft':
            resolved = BatchRunner._resolve_fft_nfft(n_samples, fs, params)
            return int(n_samples if resolved is None else resolved)
        if method == 'order_time':
            return int(resolve_order_nfft(
                float(params.get('samples_per_rev', 256)),
                float(params.get('order_res', 0.1)),
                int(n_samples),
            ))
        return int(resolve_nfft(
            float(fs),
            int(n_samples),
            float(params.get('t_win_s', 1.0)),
            float(params.get('overlap', 0.5)),
        ))

    @classmethod
    def _compute_order_time_spectro(cls, sig, rpm, time, fs, params) -> "_Spectro2D":
        """Compute time-order spectrogram via COT and return a ``_Spectro2D``.

        ``matrix`` is x-major ``(len(times), len(orders))`` so that
        ``to_long_dataframe()`` round-trips through ``_matrix_to_long_dataframe``
        without any transpose. The transpose needed for ``imshow`` (rows=y) is
        applied in ``_write_image``.
        """
        from .signal.order_cot import COTOrderAnalyzer, COTParams

        sig, _spec = cls._apply_filter_if_enabled(sig, fs, params)

        # Defensive: COT requires strictly monotonic t. Even microsecond
        # jitter in MF4 timestamps would raise ValueError. If not strict,
        # rebuild a uniform fallback from len + fs.
        time_arr = np.asarray(time, dtype=float)
        if len(time_arr) < 2 or np.any(np.diff(time_arr) <= 0):
            time_arr = np.arange(len(time_arr), dtype=float) / float(fs)

        cot_params = COTParams(
            samples_per_rev=int(params.get('samples_per_rev', 256)),
            nfft=int(params.get('nfft', 1024)),
            window=str(params.get('window', 'hanning')),
            max_order=float(params.get('max_order', params.get('max_ord', 20))),
            order_res=float(params.get('order_res', 0.1)),
            time_res=float(params.get('time_res', 0.05)),
            fs=float(fs),
            weighting=str(params.get('weighting', 'None')),
        )
        result = COTOrderAnalyzer.compute(sig, rpm, time_arr, cot_params)
        return _Spectro2D(
            x=np.asarray(result.times, dtype=float),
            y=np.asarray(result.orders, dtype=float),
            matrix=np.asarray(result.amplitude, dtype=float),
            x_name='time_s',
            y_name='order',
            metadata=dict(getattr(result, 'metadata', {}) or {}),
        )

    @classmethod
    def _compute_order_time_dataframe(cls, sig, rpm, time, fs, params):
        """Thin wrapper — delegates to ``_compute_order_time_spectro``.

        As of 2026-04-28 the legacy frequency-domain path
        (``OrderAnalyzer`` time-order result builder) is no longer invoked
        here; COT handles all RPM regimes (sweep, coast-down, steady-state)
        without smearing. ``samples_per_rev`` defaults to 256 when absent from
        preset params; the COT pipeline requires ``time`` to be strictly
        monotonically increasing.
        """
        return cls._compute_order_time_spectro(sig, rpm, time, fs, params).to_long_dataframe()

    @classmethod
    def _compute_fft_time_spectro(cls, sig, time, fs, params, *,
                                  channel_name='') -> "_Spectro2D":
        """Compute one-sided FFT-vs-time spectrogram and return a ``_Spectro2D``.

        ``SpectrogramAnalyzer.compute`` returns ``amplitude`` with shape
        ``(freq_bins, frames)``. ``_Spectro2D.matrix`` is x-major
        ``(len(times), len(frequencies))``, so we store ``amplitude.T``
        (``(frames, freq_bins)``). The exported dataframe stays in linear
        amplitude — the dB conversion is a display-only choice in
        ``_write_image``.
        """
        from .signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
        sig, _spec = cls._apply_filter_if_enabled(sig, fs, params)
        time, fs = cls._uniform_time_axis_for_spectrogram(time, fs, len(sig))
        sp = SpectrogramParams(
            fs=float(fs),
            nfft=int(params.get('nfft', 1024)),
            window=str(params.get('window', 'hanning')),
            overlap=float(params.get('overlap', 0.5)),
            remove_mean=bool(params.get('remove_mean', True)),
            weighting=str(params.get('weighting', 'None')),
        )
        result = SpectrogramAnalyzer.compute(
            signal=sig, time=time, params=sp,
            channel_name=channel_name or 'signal',
        )
        return _Spectro2D(
            x=np.asarray(result.times, dtype=float),
            y=np.asarray(result.frequencies, dtype=float),
            matrix=np.asarray(result.amplitude.T, dtype=float),
            x_name='time_s',
            y_name='frequency_hz',
            metadata=dict(getattr(result, 'metadata', {}) or {}),
        )

    @classmethod
    def _compute_fft_time_dataframe(cls, sig, time, fs, params, *, channel_name=''):
        """Thin wrapper — delegates to ``_compute_fft_time_spectro``.

        ``SpectrogramAnalyzer.compute`` returns ``amplitude`` with shape
        ``(freq_bins, frames)``. ``_matrix_to_long_dataframe`` requires
        ``matrix.shape == (len(x_values), len(y_values))`` (x-major), so we
        transpose to ``(frames, freq_bins)`` before flattening. The exported
        dataframe stays in linear amplitude — the dB conversion is a
        display-only choice in ``_write_image``.
        """
        return cls._compute_fft_time_spectro(
            sig, time, fs, params, channel_name=channel_name,
        ).to_long_dataframe()

    @staticmethod
    def _strict_finite_time_axis(values, expected_length: int) -> bool:
        try:
            axis = np.asarray(values, dtype=float)
        except (TypeError, ValueError):
            return False
        return bool(
            axis.ndim == 1
            and len(axis) == int(expected_length)
            and len(axis) >= 2
            and np.all(np.isfinite(axis))
            and np.all(np.diff(axis) > 0.0)
        )

    def _rpm_values(
        self,
        fd,
        preset,
        *,
        target_source_id=None,
        warnings_out: list[str] | None = None,
    ):
        if preset.rpm_signal is not None:
            rpm_source_id, rpm_ch = preset.rpm_signal
            if target_source_id is None:
                target_source_id = (
                    preset.signal[0]
                    if preset.signal is not None
                    else (getattr(fd, 'source_metadata', {}) or {}).get(
                        'source_id', getattr(fd, 'filepath', 'target'),
                    )
                )
            if rpm_source_id == target_source_id:
                rpm_fd = fd
            else:
                _rpm_id, rpm_fd = self._resolve_task_file(rpm_source_id)
            if isinstance(rpm_fd, _LoadFailure) or rpm_ch not in rpm_fd.data.columns:
                detail = (
                    rpm_fd.error if isinstance(rpm_fd, _LoadFailure)
                    else f"missing channel {rpm_ch!r}"
                )
                raise ValueError(
                    "cross-source RPM resolution failed "
                    f"(target source {target_source_id!r}, "
                    f"rpm source {rpm_source_id!r}): {detail}"
                )
            factor = float(preset.params.get('rpm_factor', 1.0))
            rpm = rpm_fd.data[rpm_ch].to_numpy(dtype=float, copy=False)
            if rpm_source_id == target_source_id:
                return rpm * factor

            target_time = fd.time_array
            rpm_time = rpm_fd.time_array
            valid_target = self._strict_finite_time_axis(
                target_time, len(fd.data),
            )
            valid_rpm = self._strict_finite_time_axis(
                rpm_time, len(rpm),
            )
            if not (valid_target and valid_rpm):
                raise ValueError(
                    "cross-source RPM timebase incompatible "
                    f"(target source {target_source_id!r}, "
                    f"rpm source {rpm_source_id!r}): time axes must be "
                    "finite and strictly increasing"
                )
            target_time = np.asarray(target_time, dtype=float)
            rpm_time = np.asarray(rpm_time, dtype=float)
            if target_time[-1] < rpm_time[0] or target_time[0] > rpm_time[-1]:
                raise ValueError(
                    "cross-source RPM timebase incompatible "
                    f"(target source {target_source_id!r}, "
                    f"rpm source {rpm_source_id!r}): time ranges do not overlap"
                )
            return np.interp(target_time, rpm_time, rpm) * factor
        rpm_channel = preset.rpm_channel
        if not rpm_channel:
            rpm_channel = _guess_rpm_channel(fd)
            if rpm_channel and warnings_out is not None:
                warnings_out.append(
                    f"未指定转速通道，已按名称匹配使用 {rpm_channel} —— 请确认"
                )
        if not rpm_channel or rpm_channel not in fd.data.columns:
            raise ValueError("rpm channel is required for order batch analysis")
        factor = float(preset.params.get('rpm_factor', 1.0))
        return fd.data[rpm_channel].to_numpy(dtype=float, copy=False) * factor

    @staticmethod
    def _write_dataframe(df, path):
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
                    starts = range(0, len(df), _XLSX_MAX_DATA_ROWS) or (0,)
                    for sheet_index, start in enumerate(
                        starts, start=1,
                    ):
                        df.iloc[start:start + _XLSX_MAX_DATA_ROWS].to_excel(
                            writer,
                            sheet_name=f"数据{sheet_index}",
                            index=False,
                        )
            else:
                df.to_csv(temp_path, index=False)

        return atomic_write(path, write)

    @staticmethod
    def _write_workbook(sheets: "dict[str, pd.DataFrame]", path):
        """Publish several named sheets as one xlsx, atomically.

        The sibling of :meth:`_write_dataframe` for the slice export: same
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
            if len(frame) > _XLSX_MAX_DATA_ROWS:
                raise ValueError(
                    f"worksheet {name!r} has {len(frame)} rows, above the "
                    f"xlsx limit of {_XLSX_MAX_DATA_ROWS}"
                )

        def write(temp_path):
            with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
                for name, frame in sheets.items():
                    frame.to_excel(writer, sheet_name=name, index=False)

        return atomic_write(path, write)

    @staticmethod
    def _write_image(
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


def _guess_rpm_channel(fd):
    for ch in fd.get_signal_channels():
        low = ch.lower()
        if 'rpm' in low or 'speed' in low or 'tach' in low:
            return ch
    return ''


@dataclass(frozen=True)
class _Spectro2D:
    """2-D analysis result kept matrix-first to avoid a long→wide pivot
    round-trip on export. ``matrix`` is x-major: shape (len(x), len(y)).

    ``metadata`` preserves analyzer-owned display coverage such as
    ``coverage_start`` / ``coverage_end``.  It is deliberately absent from
    :meth:`to_long_dataframe` so CSV values and column order stay unchanged.
    """
    x: np.ndarray
    y: np.ndarray
    matrix: np.ndarray
    x_name: str
    y_name: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_long_dataframe(self) -> pd.DataFrame:
        return _matrix_to_long_dataframe(
            self.x, self.y, self.matrix, self.x_name, self.y_name)

    def slice_curve(self, axis: str, index: int) -> np.ndarray:
        """Amplitudes along one slice pick, straight off the x-major matrix.

        ``matrix`` here is **x-major**, shape ``(len(x), len(y))`` -- the
        transpose of what the renderer's ``_extract_heatmap`` hands to
        ``_builder._slice_curve_values`` (it applies ``x_major.T``). So the
        indexing is mirrored: fixing a *time* takes a matrix **row** and the
        curve runs along ``y``; fixing a *frequency/order* takes a **column**
        and the curve runs along ``x``. ``tests/test_batch_slice_export.py``
        pins this against the rendered curves point by point, because getting
        it backwards yields a plausible-looking table of the wrong values.
        """
        matrix = np.asarray(self.matrix, dtype=float)
        if str(axis).strip().lower() == 'time':
            return matrix[int(index), :]
        return matrix[:, int(index)]

    def to_slice_sheets(
        self,
        plan,
        *,
        render_db: bool,
        reference: float | None = None,
        amplitude_label: str = '',
        facts: "Sequence[str]" = (),
        source: str = '',
        channel: str = '',
        unit: str = '',
        method: str = '',
    ) -> "dict[str, pd.DataFrame]":
        """``{"切片信息": df, "<时间|频率|阶次>切片": df}`` for one slice plan.

        One wide sheet with a position per column, so a reader can select a few
        columns in Excel and get the comparison chart the multi-position slice
        exists for (design D23), plus a key/value sheet that makes the file
        self-describing.

        Values are written in the **charted** caliber only -- dB when the page
        renders dB -- with the caliber and its reference recorded on the info
        sheet rather than doubling the column count with a parallel linear set
        (design D24).
        """
        fixed_name = self.x_name if plan.axis == 'time' else self.y_name
        curve_name = self.y_name if plan.axis == 'time' else self.x_name
        curve_coords = np.asarray(
            self.y if plan.axis == 'time' else self.x, dtype=float
        )
        dimension, sheet_name, prefix, position_unit, decimals = (
            _slice_axis_labels(fixed_name)
        )

        columns: dict[str, np.ndarray] = {curve_name: curve_coords}
        for pick in plan.picks:
            values = self.slice_curve(plan.axis, pick.index)
            if render_db:
                from .signal.spectrogram import SpectrogramAnalyzer

                # Element-wise, so converting the picked line alone is
                # numerically identical to slicing the renderer's full
                # ``display_matrix``.
                values = np.asarray(
                    SpectrogramAnalyzer.amplitude_to_db(
                        values, reference=float(reference or 1.0)
                    ),
                    dtype=float,
                )
            name = f'{prefix}={pick.value:.{decimals}f}{position_unit}'
            suffix = 2
            while name in columns:
                name = (
                    f'{prefix}={pick.value:.{decimals}f}{position_unit}'
                    f'#{suffix}'
                )
                suffix += 1
            columns[name] = np.asarray(values, dtype=float)

        def _positions(attribute: str) -> str:
            # Four decimals, not the column headers' 1-2: the whole point of
            # printing request and landing side by side is that a reader can
            # see they differ (design D11), and 620.0 vs 615.2 Hz rounds to the
            # same header text more often than not.
            joined = ', '.join(
                f'{getattr(pick, attribute):.4f}' for pick in plan.picks
            )
            return f'{joined} {position_unit}'.strip()

        clamped = plan.clamped_picks
        notes = []
        if clamped:
            notes.append(
                '夹取到数据边界：'
                + ', '.join(f'{pick.value:.{decimals}f}' for pick in clamped)
            )
        if plan.merged:
            notes.append(
                f'{len(plan.picks) + plan.merged} 个位置夹取后合并为 '
                f'{len(plan.picks)} 个'
            )

        info: list[tuple[str, str]] = [
            ('来源文件', str(source)),
            ('通道', str(channel)),
            ('单位', str(unit)),
            ('方法', str(method)),
        ]
        info.extend(_slice_fact_rows(facts))
        info.append(('幅值口径', str(amplitude_label)))
        if render_db:
            info.append(('dB 参考值', f'{float(reference or 1.0):g}'))
        info.extend([
            ('切片维度', f'固定{dimension}'),
            ('切片位置 请求', _positions('requested')),
            ('切片位置 落点', _positions('value')),
            ('切片位置 备注', '；'.join(notes) if notes else '—'),
        ])
        return {
            # An em dash rather than an empty cell: a blank reads as "the
            # exporter forgot" and round-trips out of xlsx as NaN, while a
            # unit-less channel is a fact worth stating.
            '切片信息': pd.DataFrame(
                {'项目': [key for key, _ in info],
                 '值': [value if value else '—' for _, value in info]}
            ),
            sheet_name: pd.DataFrame(columns),
        }


def _matrix_to_long_dataframe(x_values, y_values, matrix, x_name, y_name):
    x_values = np.asarray(x_values, dtype=float)
    y_values = np.asarray(y_values, dtype=float)
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (len(x_values), len(y_values)):
        raise ValueError(
            f"matrix shape {matrix.shape} does not match "
            f"({len(x_values)}, {len(y_values)})"
        )
    xs = np.repeat(x_values, len(y_values))
    ys = np.tile(y_values, len(x_values))
    return pd.DataFrame({x_name: xs, y_name: ys, 'amplitude': matrix.reshape(-1)})
