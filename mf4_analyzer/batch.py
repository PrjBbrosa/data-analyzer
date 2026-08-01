"""Batch analysis presets and GUI-free runner.

Two preset entry points are supported:

* ``from_current_single``: capture the currently selected one-off analysis.
* ``free_config``: describe a reusable rule that selects matching signals.

The runner intentionally depends only on ``FileData`` plus pure analysis and
output modules, so a desktop worker can delegate work without GUI objects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping, Sequence
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
from .batch_grouping import RenderTask, group_render_tasks
from .batch_manifest import (
    BatchManifestRecorder,
    ManifestRecipeMismatch,
    artifact_facts,
    derive_summary,
    find_resumable_entry,
    load_batch_manifest,
    retry_failed_scope,
    source_file_facts,
    utc_now,
)
from .batch_preprocess import BatchPreprocessResult, preprocess_batch_signal
from .batch_recipe import normalize_batch_params, recipe_fingerprint
from .batch_validation import (
    raise_for_issues,
    resolve_output_image_dimensions,
    validate_outputs,
    validate_recipe,
    validate_task,
)
from .io.source_adapters import (
    DEFAULT_SOURCE_ADAPTER_REGISTRY,
    LoadedSource,
    canonical_source_path,
)
from .signal import resolve_nfft, resolve_order_nfft
from .signal.fft import FFTAnalyzer

if TYPE_CHECKING:
    from .batch_render import BatchSeries, BatchTimeFigureSpec


_RENDER_BACKEND_DEGRADED_REASON = (
    '图片/PDF 导出后端不可用，本次仅导出数据文件'
)
_RENDER_BACKEND_IMAGE_ONLY_ERROR = (
    '图片/PDF 导出后端不可用，无法完成图片/PDF 导出'
)


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
    conflict_policy: str = 'auto_number'
    write_manifest: bool = True
    resume_policy: str = 'none'

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

    @staticmethod
    def _probe_image_backend():
        """Import the renderer types before reserving any output paths."""

        from .batch_render import BatchRenderContext, BatchRenderOptions

        return BatchRenderContext, BatchRenderOptions

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
                    'image_height', 'image_dpi', 'conflict_policy',
                    'write_manifest', 'resume_policy',
                )
                if hasattr(outputs, field_name)
            }

    def preview_outputs(self, preset, output_dir) -> BatchOutputPreview:
        """Return UI-safe output counts without loading unresolved sources."""

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
                physical_key = self._physical_for_source(source_key)
                path = (
                    self._physical_paths.get(physical_key, physical_key)
                    if physical_key is not None else str(source_key)
                )
                source = SimpleNamespace(
                    filepath=path,
                    label_suffix=str(source_key),
                    source_metadata={'group_identity': str(source_key)},
                )
                identity = build_task_output_identity(
                    source,
                    file_id=source_key,
                    channel=channel,
                    method=preset.method,
                    params=requested_params,
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

        groups = (
            group_render_tasks(render_tasks, requested_params)
            if image_extension is not None else ()
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

        group_by = str(requested_params.get(
            'render_group_by', 'none',
        ) or 'none').strip().lower()
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
        if bool(getattr(preset.outputs, 'write_manifest', True)):
            try:
                recorder = BatchManifestRecorder(
                    output_dir,
                    preset_name=preset.name,
                    normalized_recipe={
                        'method': preset.method,
                        'params': requested_params,
                        'rpm_channel': preset.rpm_channel,
                        'rpm_signal': preset.rpm_signal,
                        'outputs': output_settings,
                    },
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

        def finish_result(status, items=None, blocked=None):
            result_items = list(items or ())
            result_blocked = list(blocked or ())
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
                warnings=degraded_reasons,
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
                    candidates = sorted(
                        (
                            path for path in output_dir.glob(
                                'batch-manifest__*.json'
                            )
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
        if retry_failed_manifest is not None:
            try:
                retry_scope = retry_failed_scope(
                    retry_failed_manifest,
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

        try:
            tasks = list(self._expand_tasks(
                preset,
                allow_source_load=not (
                    resume_data is not None or retry_scope is not None
                ),
            ))
        except Exception as exc:
            for physical_key in tuple(self._disk_cache):
                self._evict_physical(physical_key)
            return finish_result('blocked', blocked=[str(exc)])
        if retry_scope is not None:
            tasks = [
                (source_key, channel)
                for source_key, channel in tasks
                if (source_key, channel, preset.method) in retry_scope
            ]
        if not tasks:
            for physical_key in tuple(self._disk_cache):
                self._evict_physical(physical_key)
            return finish_result('blocked', blocked=['no matching batch tasks'])

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
                                     cancel_token=cancel_token)
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
                if not isinstance(fd_or_fail, _LoadFailure):
                    identity = self._build_task_identity(
                        fd_or_fail,
                        file_id=fid,
                        channel=signal_name,
                        method=preset.method,
                        params=normalize_batch_params(preset.params, preset.method),
                    )
                else:
                    identity = self._build_unresolved_task_identity(
                        source_key,
                        channel=signal_name,
                        method=preset.method,
                        params=requested_params,
                    )
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
                if not isinstance(fd_or_fail, _LoadFailure):
                    identity = self._build_task_identity(
                        fd_or_fail,
                        file_id=fid,
                        channel=signal_name,
                        method=preset.method,
                        params=normalize_batch_params(preset.params, preset.method),
                    )
                else:
                    identity = self._build_unresolved_task_identity(
                        source_key,
                        channel=signal_name,
                        method=preset.method,
                        params=requested_params,
                    )
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

    def _register_source_locator(self, source_id, path) -> None:
        physical_key = self._physical_cache_key(path)
        previous = self._source_locators.get(source_id)
        if previous is not None and previous != physical_key:
            raise ValueError(
                f"source_id {source_id!r} maps to multiple physical paths"
            )
        self._source_locators[source_id] = physical_key

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
                return list(dict.fromkeys(source_paths))
            discovered = []
            for path in dict.fromkeys(source_paths):
                physical_key = self._physical_cache_key(path)
                sources = self._load_physical_sources(physical_key)
                discovered.extend(source.source_id for source in sources)
            return list(dict.fromkeys(discovered))

        legacy = list(getattr(preset, 'file_ids', ()) or ())
        legacy_paths = tuple(getattr(preset, 'file_paths', ()) or ())
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
                    if available is None or channel in available:
                        yield source_key, channel
            return
        # Pattern fallback (legacy / test path): eager load to enumerate channels.
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

    def _run_one(self, preset, fid, fd, signal_name, output_dir, *,
                 cancel_token=None):
        method = preset.method
        requested_params = normalize_batch_params(preset.params, method)
        identity = self._build_task_identity(
            fd,
            file_id=fid,
            channel=signal_name,
            method=method,
            params=requested_params,
        )
        requested_outputs = self._required_artifacts(preset.outputs)
        effective_outputs = dict(requested_outputs)
        degraded_reason = ''
        render_backend_types = None
        if 'image' in requested_outputs:
            try:
                render_backend_types = self._probe_image_backend()
            except (ImportError, ModuleNotFoundError) as exc:
                if 'data' not in requested_outputs:
                    raise _ImageBackendUnavailable(
                        _RENDER_BACKEND_IMAGE_ONLY_ERROR
                    ) from exc
                effective_outputs.pop('image')
                degraded_reason = _RENDER_BACKEND_DEGRADED_REASON
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
                warnings=[reservation.warning, conflict_facts],
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

            rpm = None
            if method == 'order_time':
                rpm = self._rpm_values(
                    fd, preset, target_source_id=fid,
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
                rpm_mode = str(
                    requested_params.get('rpm_mode', 'channel') or 'channel'
                ).strip().lower()
                if rpm_mode in {'manual', 'fixed', '手动'}:
                    effective_params['rpm_source'] = {
                        'mode': 'manual',
                        'value': float(requested_params.get('manual_rpm')),
                    }
                elif preset.rpm_signal is not None:
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
            warnings = list(preprocessed.warnings)

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
            export_df = None
            if preset.outputs.export_data:
                # Preserve the matrix-first image-only path.
                if time_df is not None:
                    export_df = time_df
                elif fft_df is not None:
                    export_df = fft_df
                else:
                    export_df = spectro.to_long_dataframe()
            export_frame_factory = None
            if export_df is not None:
                if spectro is not None:
                    export_frame_factory = spectro.to_long_dataframe
                elif time_df is not None:
                    export_frame_factory = lambda frame=time_df: frame
                else:
                    export_frame_factory = lambda: image_payload[1]
            export_frame_holder = [export_df] if export_df is not None else []
            # The holder transfers sole ownership of a heatmap long table to
            # the data writer. Clearing this local reference ensures the long
            # table is collectible before a 4K/vector render allocates its
            # figure/RGBA buffers; image_payload keeps only the matrix result.
            export_df = None

            resolution = None
            colorbar_label = None
            image_params = None
            render_options = None
            render_context = None
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
                )
                channel_meta = (
                    (getattr(fd, 'channel_metadata', None) or {}).get(
                        signal_name, {}
                    ) or {}
                )
                unit = (
                    channel_meta.get('unit')
                    or (getattr(fd, 'channel_units', None) or {}).get(
                        signal_name, ''
                    )
                    or ''
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

            while True:
                attempt_warnings = []
                writers = {}
                if export_frame_holder:
                    def write_data(path, holder=export_frame_holder):
                        frame = holder.pop()
                        try:
                            self._check_cancel(cancel_token, "data write")
                            result = self._write_dataframe(frame, path)
                            self._check_cancel(cancel_token, "data write")
                            return result
                        finally:
                            del frame
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
            ),)

        show_original = bool(filter_state.get('show_original', True))
        show_filtered = bool(filter_state.get('show_filtered', True))
        if not show_original and not show_filtered:
            raise ValueError(
                "æ—¶åŸŸå¯¼å‡ºè‡³å°‘éœ€è¦åŽŸå§‹æˆ–æ»¤æ³¢åŽä¸€é¡¹"
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
        return BatchTimeFigureSpec(
            series=tuple(series),
            layout=str(
                params.get('render_layout', 'overlay') or 'overlay'
            ).strip().lower(),
            x_source=x_source,
            x_origin=x_origin,
            x_label=str(x_label),
            panel_titles=tuple(panel_titles),
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
        group_identity='default',
    ):
        physical_key = self._physical_for_source(source_key)
        source_path = (
            self._physical_paths.get(physical_key, physical_key)
            if physical_key is not None else None
        )
        source = SimpleNamespace(
            filepath=source_path,
            label_suffix=str(group_identity or 'default'),
            source_metadata={
                'group_identity': str(group_identity or 'default'),
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

    def _rpm_values(self, fd, preset, *, target_source_id=None):
        rpm_mode = str(preset.params.get('rpm_mode', '')).strip().lower()
        if rpm_mode in {'manual', 'fixed', '手动'}:
            manual_rpm = float(preset.params.get('manual_rpm'))
            return np.full(len(fd.data), manual_rpm, dtype=float)
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
                df.to_excel(temp_path, index=False, engine='openpyxl')
            else:
                df.to_csv(temp_path, index=False)

        return atomic_write(path, write)

    @staticmethod
    def _build_export_scene(payload, params=None):
        """Headless compatibility wrapper for legacy direct-call tests."""
        from .batch_render import _build_batch_figure

        kind, _data = payload
        render_params = dict(params or {})
        resolution = BatchRunner._image_reference_resolution(render_params)
        render_params['db_reference_resolution'] = resolution
        render_db, output_scale = BatchRunner._batch_output_scale(kind, render_params)
        label = db_reference.format_amplitude_label(
            resolution,
            weighting=str(render_params.get('weighting', 'None')),
            output_scale=output_scale,
        )
        figure = _build_batch_figure(payload, params=render_params)
        return figure, {
            'figure': figure,
            'colorbar_label': label,
            'render_db': render_db,
        }

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
    round-trip on export. ``matrix`` is x-major: shape (len(x), len(y))."""
    x: np.ndarray
    y: np.ndarray
    matrix: np.ndarray
    x_name: str
    y_name: str

    def to_long_dataframe(self) -> pd.DataFrame:
        return _matrix_to_long_dataframe(
            self.x, self.y, self.matrix, self.x_name, self.y_name)


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
