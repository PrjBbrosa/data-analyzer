from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.batch_types import FrfPairRule
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


def _loaded(
    source_id, path, group_id, channels, *, label_suffix="", time=None,
):
    file_data = _file_data(
        path, channels, label_suffix=label_suffix, time=time,
    )
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


def _frf_source_preset():
    return AnalysisPreset.free_config(
        name="FRF source integration",
        method="frf",
        frf_pair_rules=(FrfPairRule("command", ("response",)),),
        params={
            "estimator": "h1",
            "t_win_s": 0.5,
            "overlap": 0.5,
            "nfft_mode": "auto",
            "window": "hanning",
            "detrend": "none",
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )


def test_frf_planned_resolved_and_resumed_source_ids_stay_identical(tmp_path):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    physical_path = tmp_path / "frf-groups.hdf"
    time = np.arange(400, dtype=float) / 100.0
    sources = (
        _loaded(
            "frf:group-a", physical_path, "raster:a",
            ("command", "response"), time=time,
        ),
        _loaded(
            "frf:group-b", physical_path, "raster:b",
            ("command", "response"), time=time,
        ),
    )
    preset = replace(
        _frf_source_preset(), source_paths=(str(physical_path),),
    )
    registry = _Registry({physical_path: sources})
    runner = BatchRunner({}, source_registry=registry)
    plan = runner._frf_execution_plan(preset)
    output_settings = runner._requested_output_settings(preset.outputs)
    planned = [
        (
            task.source_id,
            runner._build_frf_task_identity(
                task, None,
                params=normalize_batch_params(preset.params, "frf"),
                output_settings=output_settings,
            ).task_id,
        )
        for task in plan.tasks
    ]

    first = runner.run(preset, tmp_path / "out")

    assert first.status == "done"
    assert [(item.file_id, item.task_id) for item in first.items] == planned
    manifest = load_batch_manifest(first.manifest_path)
    assert [entry["source_id"] for entry in manifest["entries"]] == [
        "frf:group-a", "frf:group-b",
    ]

    resume_preset = replace(
        preset,
        outputs=replace(preset.outputs, resume_policy="manifest"),
    )
    resumed = BatchRunner(
        {}, source_registry=_Registry({physical_path: sources}),
    ).run(
        resume_preset,
        tmp_path / "out",
        resume_manifest=manifest,
    )

    assert resumed.status == "done"
    assert [item.status for item in resumed.items] == ["resumed", "resumed"]
    assert [(item.file_id, item.task_id) for item in resumed.items] == planned


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


def test_zfd_disk_one_bad_one_good_continues_without_success_artifact(tmp_path):
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry
    from tests.zfd_fixtures import write_minimal_zfd, write_truncated_last_channel

    good = write_minimal_zfd(
        tmp_path / "good.zfd",
        dt=0.001,
        count=16,
        name="temp",
    )
    bad = write_truncated_last_channel(
        tmp_path / "bad.zfd", count=16, drop_bytes=24,
    )
    adapter = SourceAdapterRegistry.default().adapter_for(good)
    good_id = adapter.load_sources(good)[0].source_id
    preset = replace(
        _free_preset(signals=("temp",), policy="available_per_source"),
        source_ids=("zfd-bad", good_id),
        source_paths=(str(bad), str(good)),
    )

    result = BatchRunner({}).run(preset, tmp_path / "out")

    statuses = {item.file_id: item.status for item in result.items}
    assert statuses.get("zfd-bad") == "failed"
    assert statuses.get(good_id) == "done"
    bad_item = next(item for item in result.items if item.file_id == "zfd-bad")
    good_item = next(item for item in result.items if item.file_id == good_id)
    assert not getattr(bad_item, "data_path", None)
    assert "不完整" in (bad_item.message or "")
    assert good_item.data_path
    assert Path(good_item.data_path).exists()


def test_native_rpm_follows_the_clock_not_the_signal_amplitude(tmp_path):
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    time = np.array([0.0, 1.0, 2.0])
    store = NativeSignalStore.build(
        "native-rpm",
        [AxisSpec("t", "clk", "time", "s", time, fs_status="known", fs_hz=1.0)],
        [
            ChannelSpec(0, 1, "sig", "t", np.array([0.2, 1.0, 1.8]), unit="Nm"),
            ChannelSpec(0, 2, "rpm", "t", np.array([100.0, 200.0, 300.0]), unit="rpm"),
        ],
    )
    fd = FileData.from_native_store(tmp_path / "rpm.mf4", store)
    preset = AnalysisPreset.from_current_single(
        name="rpm",
        method="order_time",
        signal=("native-rpm", "sig"),
        rpm_signal=("native-rpm", "rpm"),
        params={"rpm_factor": 1.0},
    )
    rpm = BatchRunner({"native-rpm": fd})._rpm_values(
        fd, preset, target_source_id="native-rpm", target_channel="sig",
    )
    np.testing.assert_allclose(rpm, [100.0, 200.0, 300.0])


def test_custom_x_runner_rejects_an_equal_length_nonoverlapping_clock(tmp_path):
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    store = NativeSignalStore.build(
        "native-x",
        [
            AxisSpec("sig", "clk-sig", "time", "s", np.array([0.0, 1.0, 2.0]), fs_status="known", fs_hz=1.0),
            AxisSpec("xpos", "clk-x", "time", "s", np.array([10.0, 11.0, 12.0]), fs_status="known", fs_hz=1.0),
        ],
        [
            ChannelSpec(0, 1, "sig", "sig", np.array([1.0, 2.0, 3.0]), unit="Nm"),
            ChannelSpec(1, 1, "xpos", "xpos", np.array([4.0, 5.0, 6.0]), unit="mm"),
        ],
    )
    fd = FileData.from_native_store(tmp_path / "x.mf4", store)
    preset = AnalysisPreset.from_current_single(
        name="custom x",
        method="time",
        signal=("native-x", "sig"),
        params={"x_source": "channel", "x_channel": "xpos"},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({"native-x": fd}).run(preset, tmp_path / "out")
    assert result.items
    item = result.items[0]
    assert item.status == "failed"
    assert "不重叠" in (item.message or "")
    assert not item.data_path


def test_native_time_export_keeps_unknown_fs_and_a_single_sample(tmp_path):
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    store = NativeSignalStore.build(
        "native-unknown",
        [AxisSpec("t", "clk", "time", "s", np.array([1.25]))],
        [ChannelSpec(0, 1, "sig", "t", np.array([7.5]), unit="Nm")],
    )
    fd = FileData.from_native_store(tmp_path / "one.mf4", store)
    preset = AnalysisPreset.from_current_single(
        name="one point",
        method="time",
        signal=("native-unknown", "sig"),
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({"native-unknown": fd}).run(preset, tmp_path / "out")
    item = result.items[0]
    assert item.status == "done", item.message
    text = Path(item.data_path).read_text(encoding="utf-8")
    assert "7.5" in text
    assert "1.25" in text


def test_native_frf_job_uses_the_prepared_lower_rate(tmp_path):
    from mf4_analyzer.batch_compute import _prepare_native_frf_task
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    left_fs = 2000.0
    right_fs = 1000.0
    left_time = np.arange(4000) / left_fs
    right_time = np.arange(2000) / right_fs
    tone = 80.0
    store = NativeSignalStore.build(
        "native-frf",
        [
            AxisSpec("in", "clk-in", "time", "s", left_time, fs_status="known", fs_hz=left_fs),
            AxisSpec("out", "clk-out", "time", "s", right_time, fs_status="known", fs_hz=right_fs),
        ],
        [
            ChannelSpec(0, 1, "stimulus", "in", np.sin(2.0 * np.pi * tone * left_time), unit="Nm"),
            ChannelSpec(1, 1, "response", "out", 2.0 * np.sin(2.0 * np.pi * tone * right_time), unit="Nm"),
        ],
    )
    fd = FileData.from_native_store(tmp_path / "frf.mf4", store)
    prepared = _prepare_native_frf_task(
        fd, "stimulus", "response",
        {
            "align_then_compute": True,
            "estimator": "h1",
            "t_win_s": 0.5,
            "overlap": 0.0,
            "nfft_mode": "auto",
            "window": "hanning",
            "periodic_window": True,
            "detrend": "none",
        },
    )
    assert prepared.fs == pytest.approx(right_fs)
    assert prepared.input_values.shape == prepared.output_values.shape
    assert prepared.input_time.shape == prepared.output_time.shape


def _native_same_rate_frf(path, *, count=100, fs=100.0):
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    time = np.arange(count) / fs
    store = NativeSignalStore.build(
        "native-budget",
        [AxisSpec("t0", "clock", "time", "s", time, fs_status="known", fs_hz=fs)],
        [
            ChannelSpec(0, 0, "stimulus", "t0", np.linspace(0.0, 1.0, count), unit="Nm"),
            ChannelSpec(0, 1, "response", "t0", np.linspace(1.0, 2.0, count), unit="Nm"),
        ],
    )
    return FileData.from_native_store(path, store)


def test_native_frf_prepare_passes_the_owner_byte_limit(tmp_path, monkeypatch):
    """生产 prepare_pair 必须拿到中立额度，不能靠默认 None 绕过准入。"""
    from mf4_analyzer.analysis_signal_prepare import prepare_pair
    from mf4_analyzer.batch_compute import _prepare_native_frf_task
    from mf4_analyzer.io.import_limits import analysis_request_byte_limit

    captured = {}
    real = prepare_pair

    def spy(*args, **kwargs):
        captured["byte_limit"] = kwargs.get("byte_limit", "missing")
        captured["resource_budget"] = kwargs.get("resource_budget", "missing")
        return real(*args, **kwargs)

    monkeypatch.setattr("mf4_analyzer.analysis_signal_prepare.prepare_pair", spy)
    fd = _native_same_rate_frf(tmp_path / "budget.mf4")
    _prepare_native_frf_task(
        fd, "stimulus", "response",
        {"align_then_compute": False, "t_win_s": 0.2, "overlap": 0.0, "nfft_mode": "auto",
         "window": "hanning", "periodic_window": True, "detrend": "none"},
    )
    assert captured["byte_limit"] == analysis_request_byte_limit(None)
    assert captured["byte_limit"] == 512 * 1024 * 1024
    assert captured["byte_limit"] is not None
    assert captured["resource_budget"] is None


def test_native_frf_prepare_reports_a_resource_refusal(tmp_path):
    from mf4_analyzer.batch_compute import BatchFrfDataError, _prepare_native_frf_task
    from mf4_analyzer.io.import_limits import ImportLimits, budget_context

    fd = _native_same_rate_frf(tmp_path / "tight.mf4")
    with budget_context(ImportLimits(max_memory_bytes=1600, max_output_bytes=800)):
        with pytest.raises(BatchFrfDataError, match="预算") as caught:
            _prepare_native_frf_task(
                fd, "stimulus", "response",
                {"align_then_compute": False, "t_win_s": 0.2, "overlap": 0.0,
                 "nfft_mode": "auto", "window": "hanning", "periodic_window": True,
                 "detrend": "none"},
            )
    assert "缩小" in str(caught.value)


def _native_integer_ratio_frf(path, *, origin=0.0, left_fs=2000.0, right_fs=1000.0, duration=4.0, tone=80.0, gain=2.0, delay=0.0):
    """Same-origin integer-ratio pair. The right clock is not pre-cropped."""
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    left_n = int(duration * left_fs)
    right_n = int(duration * right_fs)
    left_time = origin + np.arange(left_n) / left_fs
    right_time = origin + np.arange(right_n) / right_fs
    stimulus = np.sin(2.0 * np.pi * tone * (left_time - origin))
    response = gain * np.sin(2.0 * np.pi * tone * (right_time - origin - delay))
    store = NativeSignalStore.build(
        "native-frf-range",
        [
            AxisSpec("in", "clk-in", "time", "s", left_time, fs_status="known", fs_hz=left_fs),
            AxisSpec("out", "clk-out", "time", "s", right_time, fs_status="known", fs_hz=right_fs),
        ],
        [
            ChannelSpec(0, 1, "stimulus", "in", stimulus, unit="Nm"),
            ChannelSpec(1, 1, "response", "out", response, unit="Nm"),
        ],
    )
    return FileData.from_native_store(path, store)


def _frf_range_params(time_range):
    return {
        "align_then_compute": True,
        "time_range": time_range,
        "estimator": "h1",
        "t_win_s": 0.25,
        "overlap": 0.0,
        "nfft_mode": "auto",
        "window": "hanning",
        "periodic_window": True,
        "detrend": "none",
    }


def test_native_frf_range_keeps_the_shared_clock_origin(tmp_path):
    """[.1001, 3.5] is a same-origin 2:1 request. Cropped first samples differ."""
    from mf4_analyzer.batch_compute import BatchFrfDataError, prepare_frf_task

    fd = _native_integer_ratio_frf(tmp_path / "origin.mf4")
    outcomes = {}
    for label, span in (("0", (0.0, 3.5)), ("0.1001", (0.1001, 3.5)), ("0.1006", (0.1006, 3.5))):
        try:
            prepared = prepare_frf_task(fd, "stimulus", "response", _frf_range_params(span))
        except BatchFrfDataError as exc:
            outcomes[label] = ("error", str(exc))
            continue
        outcomes[label] = (
            "ready",
            float(prepared.fs),
            float(prepared.input_time[0]),
            float(prepared.output_time[0]),
            float(prepared.input_time[-1]),
            int(prepared.input_values.size),
        )
    assert outcomes["0"][0] == "ready", outcomes
    assert outcomes["0.1006"][0] == "ready", outcomes
    assert outcomes["0.1001"][0] == "ready", outcomes
    ready = outcomes["0.1001"]
    assert ready[1] == pytest.approx(1000.0)
    assert 0.1001 - 1e-9 <= ready[2] <= ready[4] <= 3.5 + 1e-9
    assert 0.1001 - 1e-9 <= ready[3] <= 3.5 + 1e-9


def test_fractional_clock_offset_stays_rejected(tmp_path):
    """A half-sample origin shift is not an integer-grid relationship."""
    from mf4_analyzer.batch_compute import BatchFrfDataError, prepare_frf_task
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    left_fs = 2000.0
    right_fs = 1000.0
    left_time = np.arange(8000) / left_fs
    right_time = 0.5 / left_fs + np.arange(4000) / right_fs
    store = NativeSignalStore.build(
        "native-frf-fraction",
        [
            AxisSpec("in", "clk-in", "time", "s", left_time, fs_status="known", fs_hz=left_fs),
            AxisSpec("out", "clk-out", "time", "s", right_time, fs_status="known", fs_hz=right_fs),
        ],
        [
            ChannelSpec(0, 1, "stimulus", "in", np.sin(left_time), unit="Nm"),
            ChannelSpec(1, 1, "response", "out", np.sin(right_time), unit="Nm"),
        ],
    )
    fd = FileData.from_native_store(tmp_path / "fraction.mf4", store)
    with pytest.raises(BatchFrfDataError, match="原点") as caught:
        prepare_frf_task(fd, "stimulus", "response", _frf_range_params((0.0, 3.5)))
    assert "分数" in str(caught.value)


def test_batch_runner_accepts_shared_origin_range(tmp_path):
    """BatchRunner.run is the normal entry, not only the private prepare helper."""
    fd = _native_integer_ratio_frf(tmp_path / "runner.mf4", delay=0.0)
    source_id = fd.native_store.source_id
    preset = replace(
        AnalysisPreset.free_config(
            name="shared origin range",
            method="frf",
            frf_pair_rules=(FrfPairRule("stimulus", ("response",)),),
            params={
                "align_then_compute": True,
                "time_range": [0.1001, 3.5],
                "estimator": "h1",
                "t_win_s": 0.25,
                "overlap": 0.0,
                "nfft_mode": "auto",
                "window": "hanning",
                "periodic_window": True,
                "detrend": "none",
            },
            outputs=BatchOutput(export_data=True, export_image=False),
        ),
        source_ids=(source_id,),
        source_paths=(str(tmp_path / "runner.mf4"),),
    )
    result = BatchRunner({source_id: fd}).run(preset, tmp_path / "out")
    assert result.status == "done", getattr(result, "blocked", None) or [
        (item.status, item.message) for item in result.items
    ]
    assert result.items
    item = result.items[0]
    assert item.status == "done", item.message
    frame = pd.read_csv(item.data_path)
    band = (
        (frame["coherence"] >= 0.99)
        & (np.abs(frame["frequency_hz"] - 80.0) <= 4.0)
    )
    assert bool(band.any())
    gain = frame.loc[band, "magnitude_db"].to_numpy(dtype=float)
    phase = frame.loc[band, "phase_deg_unwrapped"].to_numpy(dtype=float)
    assert np.max(np.abs(gain - 20.0 * np.log10(2.0))) <= 0.1
    assert np.max(np.abs(phase)) <= 1.0
