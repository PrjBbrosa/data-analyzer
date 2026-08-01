from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.batch_recipe import normalize_batch_params
from mf4_analyzer.io import FileData
from mf4_analyzer.io.source_adapters import LoadedSource, SourceDescriptor


def _file_data(path, channels, *, time=None, label_suffix=""):
    if time is None:
        time = np.arange(16, dtype=float) / 16.0
    frame = {"Time": np.asarray(time, dtype=float)}
    for index, channel in enumerate(channels):
        frame[channel] = np.sin(
            2.0 * np.pi * (index + 1) * np.asarray(time, dtype=float)
        )
    data = pd.DataFrame(frame)
    return FileData(
        path,
        data,
        list(data.columns),
        {},
        idx=-1,
        label_suffix=label_suffix,
    )


def _loaded(source_id, path, group_id, channels, *, label_suffix=""):
    file_data = _file_data(path, channels, label_suffix=label_suffix)
    file_data.source_metadata.update({
        "source_id": source_id,
        "group_id": group_id,
    })
    return LoadedSource(
        source_id=source_id,
        source_path=str(path),
        group_id=group_id,
        display_name=Path(path).name,
        file_data=file_data,
        metadata={"group_id": group_id},
    )


class _Registry:
    probe_cost = "metadata"

    def __init__(self, sources_by_path):
        self.sources_by_path = {
            str(path): tuple(sources)
            for path, sources in sources_by_path.items()
        }
        self.calls = []
        self.probe_calls = []

    def probe_sources(self, path, *, context=None):
        self.probe_calls.append(str(path))
        return tuple(
            SourceDescriptor(
                source_id=source.source_id,
                source_path=str(path),
                group_id=source.group_id,
                display_name=source.display_name,
                channel_names=tuple(source.file_data.get_signal_channels()),
                units=dict(source.file_data.channel_units),
                fs=float(source.file_data.fs),
                metadata={"probe_cost": "metadata"},
            )
            for source in self.sources_by_path[str(path)]
        )

    def load_sources(self, path, *, context=None):
        self.calls.append(str(path))
        return self.sources_by_path[str(path)]


def _free_preset(*, signals, policy="common"):
    return AnalysisPreset.free_config(
        name="source integration",
        method="fft",
        target_signals=signals,
        target_policy=policy,
        params={"nfft": 8, "window": "hanning"},
        outputs=BatchOutput(export_data=True, export_image=False),
    )


def test_multi_group_source_ids_share_one_physical_load_and_distinct_outputs(tmp_path):
    physical_path = tmp_path / "groups.hdf"
    sources = (
        _loaded("hdf:group-a", physical_path, "raster:a", ("sig",),
                label_suffix="same"),
        _loaded("hdf:group-b", physical_path, "raster:b", ("sig",),
                label_suffix="same"),
    )
    registry = _Registry({physical_path: sources})
    preset = replace(
        _free_preset(signals=("sig",)),
        source_ids=("hdf:group-a", "hdf:group-b"),
        source_paths=(str(physical_path), str(physical_path)),
    )

    runner = BatchRunner({}, source_registry=registry)
    result = runner.run(preset, tmp_path / "out")

    assert result.status == "done"
    assert registry.calls == [str(physical_path)]
    assert [item.file_id for item in result.items] == [
        "hdf:group-a", "hdf:group-b",
    ]
    assert len({item.task_id for item in result.items}) == 2
    assert len({item.data_path for item in result.items}) == 2
    assert runner._disk_cache == {}


def test_live_source_id_with_parallel_path_never_reloads_physical_file(tmp_path):
    physical_path = tmp_path / "snapshot.csv"
    source_id = "live:snapshot"
    live_file = _file_data(physical_path, ("sig",))
    registry = _Registry({})
    preset = replace(
        _free_preset(signals=("sig",)),
        source_ids=(source_id,),
        source_paths=(str(physical_path),),
    )

    result = BatchRunner(
        {source_id: live_file}, source_registry=registry,
    ).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert registry.calls == []
    assert [(item.file_id, item.signal) for item in result.items] == [
        (source_id, "sig"),
    ]


def test_source_paths_expand_explicit_signals_across_all_logical_sources(tmp_path):
    physical_path = tmp_path / "path-only-groups.hdf"
    registry = _Registry({
        physical_path: (
            _loaded("hdf:path-a", physical_path, "raster:a", ("sig",)),
            _loaded("hdf:path-b", physical_path, "raster:b", ("sig",)),
        )
    })
    preset = replace(
        _free_preset(signals=("sig",)),
        source_paths=(str(physical_path),),
    )

    result = BatchRunner({}, source_registry=registry).run(
        preset, tmp_path / "out",
    )

    assert result.status == "done"
    assert registry.calls == [str(physical_path)]
    assert [(item.file_id, item.signal) for item in result.items] == [
        ("hdf:path-a", "sig"),
        ("hdf:path-b", "sig"),
    ]


def test_source_paths_metadata_preview_and_fresh_run_share_logical_identity(
    tmp_path,
):
    physical_path = tmp_path / "preview-path-groups.hdf"
    sources = (
        _loaded("hdf:preview-a", physical_path, "raster:a", ("sig",)),
        _loaded("hdf:preview-b", physical_path, "raster:b", ("sig",)),
    )
    preset = replace(
        _free_preset(signals=("sig",)),
        source_paths=(str(physical_path),),
    )
    preview_registry = _Registry({physical_path: sources})
    preview_runner = BatchRunner({}, source_registry=preview_registry)

    preview = preview_runner.preview_outputs(preset, tmp_path / "preview")
    preview_pairs = list(preview_runner._expand_tasks(
        preset, allow_source_load=False,
    ))
    _, preview_render_tasks, _ = preview_runner._build_run_plan(
        preview_pairs,
        preset=preset,
        requested_params=normalize_batch_params(preset.params, preset.method),
        explicit_grouping=False,
    )

    assert preview.task_count == 2
    assert preview_pairs == [
        ("hdf:preview-a", "sig"),
        ("hdf:preview-b", "sig"),
    ]
    assert preview_registry.probe_calls == [str(physical_path)]
    assert preview_registry.calls == []

    run_registry = _Registry({physical_path: sources})
    result = BatchRunner({}, source_registry=run_registry).run(
        preset, tmp_path / "run",
    )

    assert result.status == "done"
    assert run_registry.probe_calls == [str(physical_path)]
    assert run_registry.calls == [str(physical_path)]
    assert [
        (item.file_id, item.signal, item.task_id) for item in result.items
    ] == [
        (task.source_key, task.channel, task.identity.task_id)
        for task in preview_render_tasks
    ]


@pytest.mark.parametrize("probe_cost", ("full", None))
def test_source_paths_preview_never_uses_non_metadata_probe(
    tmp_path, probe_cost,
):
    physical_path = tmp_path / "preview-full-cost.hdf"
    registry = _Registry({
        physical_path: (
            _loaded("hdf:full-cost", physical_path, "raster:a", ("sig",)),
        )
    })
    registry.probe_cost = probe_cost

    def forbidden_probe(path, *, context=None):
        pytest.fail("preview must not use a full/unknown-cost source probe")

    def forbidden_load(path, *, context=None):
        pytest.fail("preview must not load source samples")

    registry.probe_sources = forbidden_probe
    registry.load_sources = forbidden_load
    preset = replace(
        _free_preset(signals=("sig",)),
        source_paths=(str(physical_path),),
    )

    preview = BatchRunner({}, source_registry=registry).preview_outputs(
        preset, tmp_path / "preview",
    )

    assert preview.task_count == 1


def test_legacy_file_paths_migrate_to_all_registry_logical_sources(tmp_path):
    physical_path = tmp_path / "legacy-groups.hdf"
    registry = _Registry({
        physical_path: (
            _loaded("hdf:legacy-a", physical_path, "legacy:a", ("sig",)),
            _loaded("hdf:legacy-b", physical_path, "legacy:b", ("sig",)),
        )
    })
    preset = replace(
        _free_preset(signals=("sig",)),
        file_paths=(str(physical_path),),
    )

    result = BatchRunner({}, source_registry=registry).run(
        preset, tmp_path / "out",
    )

    assert result.status == "done"
    assert registry.calls == [str(physical_path)]
    assert [item.file_id for item in result.items] == [
        "hdf:legacy-a", "hdf:legacy-b",
    ]


@pytest.mark.parametrize(
    ("policy", "expected_pairs"),
    (
        (
            "common",
            {("hdf:group-a", "shared"), ("hdf:group-b", "shared")},
        ),
        (
            "available_per_source",
            {
                ("hdf:group-a", "left"),
                ("hdf:group-a", "shared"),
                ("hdf:group-b", "shared"),
                ("hdf:group-b", "right"),
            },
        ),
    ),
)
def test_disk_multi_group_policy_uses_loaded_logical_channel_sets(
    tmp_path, policy, expected_pairs,
):
    physical_path = tmp_path / "policy.hdf"
    registry = _Registry({
        physical_path: (
            _loaded(
                "hdf:group-a", physical_path, "raster:a", ("left", "shared"),
            ),
            _loaded(
                "hdf:group-b", physical_path, "raster:b", ("shared", "right"),
            ),
        )
    })
    preset = replace(
        _free_preset(signals=("left", "shared", "right"), policy=policy),
        source_ids=("hdf:group-a", "hdf:group-b"),
        source_paths=(str(physical_path), str(physical_path)),
    )

    result = BatchRunner({}, source_registry=registry).run(
        preset, tmp_path / "out",
    )

    assert result.status == "done"
    assert registry.calls == [str(physical_path)]
    assert {(item.file_id, item.signal) for item in result.items} == expected_pairs


def test_interleaved_source_ids_are_executed_file_major_without_reload(tmp_path):
    path_a = tmp_path / "a.hdf"
    path_b = tmp_path / "b.hdf"
    registry = _Registry({
        path_a: (
            _loaded("a:one", path_a, "a:one", ("sig",)),
            _loaded("a:two", path_a, "a:two", ("sig",)),
        ),
        path_b: (
            _loaded("b:one", path_b, "b:one", ("sig",)),
        ),
    })
    preset = replace(
        _free_preset(signals=("sig",)),
        source_ids=("a:one", "b:one", "a:two"),
        source_paths=(str(path_a), str(path_b), str(path_a)),
    )

    result = BatchRunner({}, source_registry=registry).run(
        preset, tmp_path / "out",
    )

    assert result.status == "done"
    assert registry.calls == [str(path_a), str(path_b)]
    assert [item.file_id for item in result.items] == [
        "a:one", "a:two", "b:one",
    ]


def test_three_disk_sources_stay_lazy_and_compute_file_major(tmp_path, monkeypatch):
    paths = [tmp_path / f"source-{index}.hdf" for index in range(3)]
    source_ids = tuple(f"source-{index}" for index in range(3))
    registry = _Registry({
        path: (_loaded(source_id, path, source_id, ("sig",)),)
        for path, source_id in zip(paths, source_ids)
    })
    events = []
    original_load = registry.load_sources

    def traced_load(path, *, context=None):
        events.append(("load", str(path)))
        registry.active_path = str(path)
        return original_load(path, context=context)

    registry.load_sources = traced_load
    preset = replace(
        _free_preset(signals=("sig",), policy="available_per_source"),
        source_ids=source_ids,
        source_paths=tuple(str(path) for path in paths),
    )
    runner = BatchRunner({}, source_registry=registry)
    peak = {"count": 0}

    class WatchDict(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            peak["count"] = max(peak["count"], len(self))

    runner._disk_cache = WatchDict()
    original_compute = BatchRunner._compute_fft_dataframe

    def traced_compute(*args, **kwargs):
        events.append(("compute", registry.active_path))
        return original_compute(*args, **kwargs)

    monkeypatch.setattr(
        BatchRunner, "_compute_fft_dataframe", staticmethod(traced_compute),
    )

    result = runner.run(preset, tmp_path / "out")

    assert result.status == "done"
    assert peak["count"] <= 1
    assert events == [
        event
        for path in paths
        for event in (("load", str(path)), ("compute", str(path)))
    ]
    assert registry.probe_calls == [str(path) for path in paths]


def test_runner_unknown_disk_extension_blocks_with_registry_error(tmp_path):
    path = tmp_path / "measurement.unknown"
    path.write_bytes(b"unknown")
    preset = replace(
        _free_preset(signals=("sig",)),
        source_paths=(str(path),),
    )
    runner = BatchRunner({})

    result = runner.run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert ".unknown" in result.blocked[0]
    assert "Unsupported source format" in result.blocked[0]
    assert runner._disk_cache == {}


def test_common_policy_uses_only_selected_channels_present_in_every_source(tmp_path):
    files = {
        "source-a": _file_data(tmp_path / "a.csv", ("a", "shared")),
        "source-b": _file_data(tmp_path / "b.csv", ("shared", "b")),
    }
    preset = replace(
        _free_preset(signals=("a", "shared", "b"), policy="common"),
        source_ids=("source-a", "source-b"),
    )

    tasks = list(BatchRunner(files)._expand_tasks(preset))

    assert tasks == [
        ("source-a", "shared"),
        ("source-b", "shared"),
    ]


def test_available_per_source_policy_emits_only_existing_combinations(tmp_path):
    files = {
        "source-a": _file_data(tmp_path / "a.csv", ("a", "shared")),
        "source-b": _file_data(tmp_path / "b.csv", ("shared", "b")),
    }
    preset = replace(
        _free_preset(
            signals=("a", "shared", "b"),
            policy="available_per_source",
        ),
        source_ids=("source-a", "source-b"),
    )

    tasks = list(BatchRunner(files)._expand_tasks(preset))

    assert tasks == [
        ("source-a", "a"),
        ("source-a", "shared"),
        ("source-b", "shared"),
        ("source-b", "b"),
    ]


def test_available_per_source_blocks_when_signal_exists_in_zero_sources(tmp_path):
    files = {
        "source-a": _file_data(tmp_path / "a.csv", ("a",)),
        "source-b": _file_data(tmp_path / "b.csv", ("b",)),
    }
    preset = replace(
        _free_preset(signals=("missing",), policy="available_per_source"),
        source_ids=("source-a", "source-b"),
    )

    result = BatchRunner(files).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.blocked == ["no matching batch tasks"]


def test_exact_pairs_policy_never_expands_to_cartesian_product(tmp_path):
    files = {
        "source-a": _file_data(tmp_path / "a.csv", ("left", "right")),
        "source-b": _file_data(tmp_path / "b.csv", ("left", "right")),
    }
    preset = replace(
        _free_preset(signals=("left", "right"), policy="exact_pairs"),
        source_ids=("source-a", "source-b"),
        target_pairs=(("source-a", "left"), ("source-b", "right")),
    )

    tasks = list(BatchRunner(files)._expand_tasks(preset))

    assert tasks == [
        ("source-a", "left"),
        ("source-b", "right"),
    ]


def test_cross_source_rpm_interpolates_on_real_target_timestamps(tmp_path):
    target_time = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    rpm_time = np.array([0.0, 0.5, 1.0])
    target = _file_data(tmp_path / "target.csv", ("sig",), time=target_time)
    rpm_source = _file_data(tmp_path / "rpm.csv", ("rpm",), time=rpm_time)
    rpm_source.data["rpm"] = np.array([1000.0, 1500.0, 2000.0])
    preset = AnalysisPreset.from_current_single(
        name="cross rpm",
        method="order_time",
        signal=("target-source", "sig"),
        rpm_signal=("rpm-source", "rpm"),
        params={"rpm_factor": 2.0},
    )

    rpm = BatchRunner({
        "target-source": target,
        "rpm-source": rpm_source,
    })._rpm_values(target, preset, target_source_id="target-source")

    np.testing.assert_allclose(
        rpm,
        np.interp(target_time, rpm_time, rpm_source.data["rpm"]) * 2.0,
    )


@pytest.mark.parametrize(
    "rpm_time",
    (
        np.array([2.0, 2.5, 3.0]),
        np.array([0.0, 0.5, 0.4]),
    ),
)
def test_cross_source_rpm_rejects_incompatible_timebase_with_both_ids(
    tmp_path, rpm_time,
):
    target = _file_data(
        tmp_path / "target.csv", ("sig",), time=np.array([0.0, 0.5, 1.0]),
    )
    rpm_source = _file_data(tmp_path / "rpm.csv", ("rpm",), time=rpm_time)
    rpm_source.data["rpm"] = np.array([1000.0, 1500.0, 2000.0])
    preset = AnalysisPreset.from_current_single(
        name="cross rpm",
        method="order_time",
        signal=("target-source", "sig"),
        rpm_signal=("rpm-source", "rpm"),
        params={},
    )

    with pytest.raises(ValueError) as exc_info:
        BatchRunner({
            "target-source": target,
            "rpm-source": rpm_source,
        })._rpm_values(target, preset, target_source_id="target-source")

    message = str(exc_info.value)
    assert "target-source" in message
    assert "rpm-source" in message


def test_channel_rpm_defaults_to_same_target_source(tmp_path):
    source = _file_data(tmp_path / "same.csv", ("sig", "rpm"))
    source.data["rpm"] = np.linspace(1000.0, 2000.0, len(source.data))
    preset = AnalysisPreset.from_current_single(
        name="same rpm",
        method="order_time",
        signal=("source-a", "sig"),
        rpm_channel="rpm",
        params={"rpm_factor": 0.5},
    )

    rpm = BatchRunner({"source-a": source})._rpm_values(
        source,
        preset,
        target_source_id="source-a",
    )

    np.testing.assert_allclose(rpm, source.data["rpm"] * 0.5)
