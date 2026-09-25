from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import AUDIO_VIDEO_EXTS, DataLoader
from mf4_analyzer.io.source_adapters import (
    LoadedSource,
    SourceAdapterRegistry,
    SourceDescriptor,
    SourceUnavailableError,
    UnsupportedSourceFormatError,
    bind_extension_runtime,
)
from tests._helpers.mf4_factory import (
    write_signal_groups_mf4,
    write_single_channel_mf4,
)


REQUIRED_EXTENSIONS = {
    ".mf4", ".mdf", ".blf", ".tdms", ".csv", ".fdc", ".asc",
    ".xlsx", ".xls", ".hdf", ".wwt", ".zfd", ".mat",
} | AUDIO_VIDEO_EXTS


@pytest.fixture(autouse=True)
def _reset_extension_runtime_binding():
    bind_extension_runtime(None)
    yield
    bind_extension_runtime(None)


def _single3():
    frame = pd.DataFrame({"Time": [0.0, 0.1], "sig": [1.0, 2.0]})
    return frame, ["Time", "sig"], {"sig": "V"}


def _single5():
    frame = pd.DataFrame({"audio": np.zeros(8, dtype=np.float32)})
    return (
        frame,
        ["audio"],
        {"audio": ""},
        48_000.0,
        {"source_kind": "audio", "fs": 48_000.0},
    )


def _group(*, t0: float, label: str = "1000Hz·2"):
    frame = pd.DataFrame({"Time": [t0, t0 + 0.001], "sig": [1.0, 2.0]})
    return {
        "data": frame,
        "channels": ["Time", "sig"],
        "units": {"sig": "V"},
        "channel_metadata": {"sig": {"unit": "V"}},
        "source_metadata": {"source_kind": "wwt"},
        "label_suffix": label,
    }


def test_default_registry_declares_every_product_extension_and_media_extension():
    registry = SourceAdapterRegistry.default()

    assert set(registry.supported_extensions) == REQUIRED_EXTENSIONS
    assert registry.adapter_for("UPPER.MF4").key == "mdf"
    assert registry.adapter_for("capture.fdc").key == "tabular"
    assert registry.adapter_for("track.wav").key == "media"


def test_unknown_extension_is_never_routed_to_an_mdf_or_csv_fallback():
    registry = SourceAdapterRegistry.default()

    with pytest.raises(UnsupportedSourceFormatError, match=r"\.unknown"):
        registry.adapter_for("measurement.unknown")
    with pytest.raises(UnsupportedSourceFormatError, match="no extension"):
        registry.adapter_for("README")


@pytest.mark.parametrize(
    ("path", "loader_name", "result"),
    [
        ("run.tdms", "load_tdms", (*_single3(), None, {"source_kind": "tdms"})),
        ("run.csv", "load_csv", _single3()),
        ("run.fdc", "load_csv", _single3()),
        ("run.asc", "load_ascii", (*_single3(), None, {"source_kind": "ascii"})),
        ("run.xlsx", "load_excel", _single3()),
        ("run.xls", "load_excel", _single3()),
        ("run.wav", "load_audio_video", _single5()),
    ],
)
def test_single3_and_single5_adapters_normalize_to_loaded_source(
    monkeypatch, path, loader_name, result,
):
    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: True
    )
    monkeypatch.setattr(DataLoader, loader_name, staticmethod(lambda _path: result))
    adapter = SourceAdapterRegistry.default().adapter_for(path)

    loaded = adapter.load_sources(path)
    probed = adapter.probe_sources(path)

    assert len(loaded) == len(probed) == 1
    assert isinstance(loaded[0], LoadedSource)
    assert isinstance(loaded[0].file_data, FileData)
    assert isinstance(probed[0], SourceDescriptor)
    assert not hasattr(probed[0], "file_data")
    assert probed[0].channel_names == ("sig",) if "sig" in result[1] else ("audio",)
    assert probed[0].source_id == loaded[0].source_id
    assert probed[0].group_id == loaded[0].group_id == "root"
    assert probed[0].metadata['sample_count'] == len(loaded[0].file_data.time_array)
    assert probed[0].metadata['sample_rate'] == loaded[0].file_data.fs


@pytest.mark.parametrize(
    ("path", "loader_name"),
    [
        ("run.hdf", "load_hdf"),
        ("run.wwt", "load_wwt"),
        ("run.zfd", "load_zfd"),
        ("run.mat", "load_mat"),
    ],
)
def test_group_adapters_keep_multiple_logical_sources_and_stable_ids(
    monkeypatch, path, loader_name,
):
    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: True
    )
    groups = [_group(t0=0.0), _group(t0=10.0)]
    monkeypatch.setattr(DataLoader, loader_name, staticmethod(lambda _path: groups))
    adapter = SourceAdapterRegistry.default().adapter_for(path)

    descriptors = adapter.probe_sources(path)
    loaded = adapter.load_sources(path)

    assert len(descriptors) == len(loaded) == 2
    assert len({item.group_id for item in descriptors}) == 2
    assert len({item.source_id for item in descriptors}) == 2
    assert [item.source_id for item in descriptors] == [
        item.source_id for item in loaded
    ]
    assert all(item.metadata["probe_cost"] == "full" for item in descriptors)
    assert all(
        not any(isinstance(value, pd.DataFrame) for value in item.metadata.values())
        for item in descriptors
    )


def test_wwt_identity_includes_exact_n_dt_t0_even_when_labels_collide(monkeypatch):
    monkeypatch.setattr(DataLoader, "load_wwt", staticmethod(lambda _path: [
        _group(t0=0.0, label="1000Hz·2"),
        _group(t0=1.0, label="1000Hz·2"),
    ]))
    adapter = SourceAdapterRegistry.default().adapter_for("run.wwt")

    sources = adapter.load_sources("run.wwt")

    assert sources[0].display_name == sources[1].display_name
    assert sources[0].group_id != sources[1].group_id
    for group_id in (source.group_id for source in sources):
        assert "n=2" in group_id
        assert "dt=" in group_id
        assert "t0=" in group_id


def test_mdf_probe_is_metadata_only_and_matches_load_identity(tmp_path):
    path = write_single_channel_mf4(tmp_path / "signal.mf4", name="sig", unit="V")
    adapter = SourceAdapterRegistry.default().adapter_for(path)

    descriptor = adapter.probe_sources(path)[0]
    loaded = adapter.load_sources(path)[0]

    assert adapter.probe_cost == "metadata"
    assert descriptor.metadata["probe_cost"] == "metadata"
    assert descriptor.channel_names == ("sig",)
    assert descriptor.units == {"sig": "V"}
    assert descriptor.source_id == loaded.source_id


def test_mdf_probe_translates_missing_file_domain_error(tmp_path):
    adapter = SourceAdapterRegistry.default().adapter_for("missing.mf4")
    missing = tmp_path / "moved-before-preview.mf4"

    with pytest.raises(SourceUnavailableError, match="moved-before-preview"):
        adapter.probe_sources(missing)


def test_mdf_probe_does_not_translate_programming_value_error(
    monkeypatch,
):
    def broken_mdf(_path):
        raise ValueError("metadata implementation bug")

    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._loader.MDF", broken_mdf,
    )
    adapter = SourceAdapterRegistry.default().adapter_for("broken.mf4")

    with pytest.raises(ValueError, match="metadata implementation bug"):
        adapter.probe_sources("broken.mf4")


def test_registry_reports_current_mdf_and_tdms_capability_boundaries():
    registry = SourceAdapterRegistry.default()
    mdf = registry.adapter_for("signal.mf4")
    tdms = registry.adapter_for("signal.tdms")

    assert "quantity/reference metadata not yet exposed" in " ".join(
        mdf.capability_notes
    )
    assert tdms.may_return_multiple is False
    assert "flattens TDMS groups" in " ".join(tdms.capability_notes)


def test_blf_without_dbc_context_is_limited_and_cannot_probe_or_load(monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: True
    )
    adapter = SourceAdapterRegistry.default().adapter_for("capture.blf")

    availability = adapter.availability()

    assert availability.status == "limited"
    assert availability.missing_context == ("dbc_paths",)
    assert "DBC" in availability.reason
    with pytest.raises(SourceUnavailableError, match="DBC"):
        adapter.probe_sources("capture.blf")
    with pytest.raises(SourceUnavailableError, match="DBC"):
        adapter.load_sources("capture.blf")


def test_missing_optional_reader_is_reported_before_load(monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available",
        lambda name: name != "xlrd",
    )
    adapter = SourceAdapterRegistry.default().adapter_for("legacy.xls")

    availability = adapter.availability()

    assert availability.status == "unavailable"
    assert availability.missing_packages == ("xlrd",)
    with pytest.raises(SourceUnavailableError, match="xlrd"):
        adapter.probe_sources("legacy.xls")


def test_blf_probe_uses_decoder_context_and_keeps_load_identity(monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: True
    )
    monkeypatch.setattr(
        DataLoader,
        "probe_blf_dbc",
        staticmethod(lambda _path, dbc_paths: SimpleNamespace(
            is_match=True,
            signal_names=("EngineSpeed", "Torque"),
            strength="strong",
            decoded_signal_count=2,
        )),
    )
    monkeypatch.setattr(
        DataLoader,
        "load_blf",
        staticmethod(lambda _path, dbc_paths=None: _single3()),
    )
    adapter = SourceAdapterRegistry.default().adapter_for("capture.blf")
    context = {"dbc_paths": ("powertrain.dbc",)}

    descriptor = adapter.probe_sources("capture.blf", context=context)[0]
    loaded = adapter.load_sources("capture.blf", context=context)[0]

    assert adapter.probe_cost == "full"
    assert adapter.availability(context).status == "ready"
    assert descriptor.channel_names == ("EngineSpeed", "Torque")
    assert descriptor.source_id == loaded.source_id


def test_adapter_for_sniffs_canoe_asc_onto_blf_adapter(tmp_path):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    from tests._helpers.blf_factory import write_sample_asc

    registry = SourceAdapterRegistry.default()
    canoe = write_sample_asc(tmp_path / "log.asc", n=2)
    table = tmp_path / "table.asc"
    table.write_text("Time\tSpeed\n0.0\t10\n", encoding="utf-8")
    missing = tmp_path / "missing.asc"

    assert registry.adapter_for(canoe).key == "blf"
    assert registry.adapter_for(table).key == "ascii"
    assert registry.adapter_for(missing).key == "ascii"
    assert registry.adapter_for("run.asc").key == "ascii"
    assert registry.adapter_for(".asc").key == "ascii"


def test_asc_sniff_importerror_points_at_python_can(tmp_path, monkeypatch):
    """P3: ImportError during .asc sniff must not fall through to ASCII."""
    path = tmp_path / "maybe_canoe.asc"
    path.write_text(
        "date Thu Jan 01 00:00:00.000 am 2026\n"
        "base hex timestamps absolute\n",
        encoding="utf-8",
    )

    def _boom(_path):
        raise ImportError("No module named 'can'")

    monkeypatch.setattr(
        "mf4_analyzer.io.asc_can_format.sniff_canoe_asc", _boom,
    )
    registry = SourceAdapterRegistry.default()
    with pytest.raises(ImportError, match="python-can"):
        registry.adapter_for(path)


def test_mdf_channel_facts_lookup_failure_unit_is_none(monkeypatch):
    """P3: channel lookup failure → unit None (not \"\")."""
    from types import SimpleNamespace

    from mf4_analyzer.io import source_adapters as sa

    monkeypatch.setattr(
        sa, "unique_mdf_channel_locations", lambda _mdf: {"sig": (0, 0)},
    )

    class _Channels:
        def __getitem__(self, _index):
            raise IndexError("channel missing")

    mdf = SimpleNamespace(groups=[SimpleNamespace(channels=_Channels())])
    _names, units, channel_metadata = sa._mdf_channel_facts(mdf)[:3]
    assert units["sig"] is None
    assert channel_metadata["sig"]["unit"] is None


def test_mdf_probe_empty_unit_stays_empty_string(tmp_path):
    """Channel present with no unit stays \"\" (not None)."""
    path = write_single_channel_mf4(tmp_path / "nounit.mf4", name="sig", unit="")
    adapter = SourceAdapterRegistry.default().adapter_for(path)
    descriptor = adapter.probe_sources(path)[0]
    assert descriptor.units["sig"] == ""


def test_canoe_asc_probe_and_load_match_blf_frame_sequence(tmp_path, monkeypatch):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    pytest.importorskip("cantools", reason="cantools not installed")
    from tests._helpers.blf_factory import (
        write_sample_asc,
        write_sample_blf,
        write_two_message_dbc,
    )

    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: True
    )
    registry = SourceAdapterRegistry.default()
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    asc = write_sample_asc(tmp_path / "log.asc", n=3)
    blf = write_sample_blf(tmp_path / "log.blf", n=3)
    context = {"dbc_paths": (str(dbc),)}

    assert registry.availability_for(asc).status == "limited"
    descriptors = registry.probe_sources(asc, context=context)
    assert len(descriptors) == 1
    assert descriptors[0].metadata["source_kind"] == "canoe_asc"
    assert descriptors[0].source_id.startswith("blf:")
    assert "EngineSpeed" in descriptors[0].channel_names

    asc_loaded = registry.load_sources(asc, context=context)[0]
    blf_loaded = registry.load_sources(blf, context=context)[0]
    assert "EngineSpeed" in asc_loaded.file_data.channels
    assert list(asc_loaded.file_data.data["EngineSpeed"]) == pytest.approx(
        list(blf_loaded.file_data.data["EngineSpeed"])
    )


def test_zfd_adapter_probe_and_load_reject_truncated_file(tmp_path):
    from tests.zfd_fixtures import write_truncated_last_channel

    path = write_truncated_last_channel(tmp_path / "cut.zfd", count=16, drop_bytes=24)
    adapter = SourceAdapterRegistry.default().adapter_for(path)
    with pytest.raises(ValueError, match="不完整"):
        adapter.probe_sources(path)
    with pytest.raises(ValueError, match="不完整"):
        adapter.load_sources(path)


def test_zfd_adapter_and_filedata_share_verified_axis(tmp_path):
    from tests.zfd_fixtures import write_minimal_zfd

    path = write_minimal_zfd(
        tmp_path / "axis.zfd",
        dt=2.0,
        count=5,
        values=[1.0, 2.0, 3.0, 4.0, 5.0],
        t0=1.5,
        name="probe",
    )
    groups = DataLoader.load_zfd(str(path))
    g = groups[0]
    fd = FileData(
        str(path),
        g["data"],
        g["channels"],
        g["units"],
        source_metadata=g["source_metadata"],
        channel_metadata=g["channel_metadata"],
        label_suffix=g["label_suffix"],
    )
    loaded = SourceAdapterRegistry.default().adapter_for(path).load_sources(path)
    assert len(loaded) == 1
    other = loaded[0].file_data
    t = g["data"]["Time"].to_numpy()
    assert len(fd.time_array) == len(other.time_array) == 5
    assert fd.time_array[0] == pytest.approx(other.time_array[0]) == pytest.approx(1.5)
    assert t[1] - t[0] == pytest.approx(2.0)
    assert fd.fs == pytest.approx(other.fs) == pytest.approx(0.5)
    assert "zfd:count=5:dt=" in loaded[0].group_id
    assert "t0=" not in loaded[0].group_id


def _modular_snapshot(tmp_path, *, media_status: str, matlab_status: str = "not_installed"):
    from mf4_analyzer.extensions.contract import ReasonCode
    from mf4_analyzer.extensions.runtime import (
        ComponentAvailability,
        MODE_MODULAR,
        RuntimeSnapshot,
        STATUS_READY,
    )

    def _one(name: str, status: str) -> ComponentAvailability:
        return ComponentAvailability(
            component=name,
            status=status,
            reason_code=None if status == STATUS_READY else ReasonCode.COMPONENT_MISSING,
        )

    return RuntimeSnapshot(
        mode=MODE_MODULAR,
        app_root=tmp_path,
        core=None,
        active=None,
        lease=None,
        components={
            "media": _one("media", media_status),
            "matlab": _one("matlab", matlab_status),
        },
    )


def test_modular_media_ignores_find_spec_success_when_component_missing(
    tmp_path, monkeypatch,
):
    from mf4_analyzer.extensions.runtime import STATUS_NOT_INSTALLED
    from mf4_analyzer.io.source_adapters import OPEN_EXTENSION_MANAGER_ACTION

    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: True
    )
    bind_extension_runtime(
        _modular_snapshot(tmp_path, media_status=STATUS_NOT_INSTALLED)
    )
    availability = SourceAdapterRegistry.default().adapter_for("clip.wav").availability()

    assert availability.status == "unavailable"
    assert availability.component == "media"
    assert availability.component_status == STATUS_NOT_INSTALLED
    assert availability.action == OPEN_EXTENSION_MANAGER_ACTION
    assert availability.action_label == "打开扩展管理"
    assert availability.missing_packages == ()
    with pytest.raises(SourceUnavailableError, match="打开扩展管理"):
        SourceAdapterRegistry.default().adapter_for("clip.wav").load_sources("clip.wav")


def test_modular_ready_media_does_not_require_find_spec(tmp_path, monkeypatch):
    from mf4_analyzer.extensions.runtime import STATUS_READY

    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: False
    )
    bind_extension_runtime(_modular_snapshot(tmp_path, media_status=STATUS_READY))
    availability = SourceAdapterRegistry.default().adapter_for("clip.mp4").availability()

    assert availability.status == "ready"
    assert availability.component == "media"
    assert availability.action == ""


def test_modular_ready_media_does_not_require_manager_or_network(tmp_path):
    from mf4_analyzer.extensions.runtime import STATUS_READY

    bind_extension_runtime(_modular_snapshot(tmp_path, media_status=STATUS_READY))
    availability = SourceAdapterRegistry.default().adapter_for("clip.wav").availability()
    matlab = SourceAdapterRegistry.default().adapter_for("run.mat").availability()

    assert availability.status == "ready"
    assert matlab.status == "unavailable"
    assert matlab.action == "open_extension_manager"


def test_source_and_bundled_still_use_find_spec_for_optional_readers(monkeypatch):
    from mf4_analyzer.extensions.runtime import MODE_BUNDLED, RuntimeSnapshot

    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available",
        lambda name: name != "av",
    )
    source_media = SourceAdapterRegistry.default().adapter_for("clip.wav").availability()
    assert source_media.status == "unavailable"
    assert source_media.missing_packages == ("av",)
    assert source_media.action == ""

    bind_extension_runtime(
        RuntimeSnapshot(
            mode=MODE_BUNDLED,
            app_root=Path("."),
            core=None,
            active=None,
            lease=None,
            components={},
        )
    )
    bundled_media = SourceAdapterRegistry.default().adapter_for("clip.wav").availability()
    assert bundled_media.status == "unavailable"
    assert bundled_media.missing_packages == ("av",)
    assert bundled_media.action == ""


def test_modular_does_not_change_base_mdf_find_spec_gate(tmp_path, monkeypatch):
    from mf4_analyzer.extensions.runtime import STATUS_READY

    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available",
        lambda name: name != "asammdf",
    )
    bind_extension_runtime(_modular_snapshot(tmp_path, media_status=STATUS_READY))
    mdf = SourceAdapterRegistry.default().adapter_for("run.mf4").availability()
    assert mdf.status == "unavailable"
    assert mdf.missing_packages == ("asammdf",)
    assert mdf.action == ""


def test_mdf_probe_filters_all_group_time_masters(tmp_path):
    path = write_signal_groups_mf4(tmp_path / "two-groups.mf4", [
        [("a", [1, 2], [0, 1])],
        [("b", [3, 4], [0, 1])],
    ])
    adapter = SourceAdapterRegistry.default().adapter_for(str(path))
    descriptor = adapter.probe_sources(str(path))[0]
    assert set(descriptor.channel_names) == {"a", "b"}
    assert descriptor.source_id == adapter.load_sources(str(path))[0].source_id


def test_mdf_channel_facts_use_channel_type_not_display_name():
    from mf4_analyzer.io import source_adapters as sa

    class _Channel:
        def __init__(self, name, kind, sync=0):
            self.name = name
            self.channel_type = kind
            self.sync_type = sync
            self.unit = "V"
            self.conversion = None
            self.source = None

    class _Fake:
        def __init__(self, version, channels):
            self.version = version
            self.groups = [SimpleNamespace(channels=channels)]
            self.channels_db = {}
            for index, channel in enumerate(channels):
                self.channels_db.setdefault(channel.name, []).append((0, index))

    v3 = _Fake("3.30", [
        _Channel("Zeit", 1),
        _Channel("time", 0),
    ])
    names, _units, _meta = sa._mdf_channel_facts(v3)[:3]
    assert names == ("time",)

    v4 = _Fake("4.10", [
        _Channel("time", 2, 1),
        _Channel("angle", 2, 2),
        _Channel("virt", 3, 1),
        _Channel("t", 0, 0),
    ])
    names, _units, meta = sa._mdf_channel_facts(v4)[:3]
    assert set(names) == {"angle", "t"}
    assert meta["t"]["physical_occurrence"] == (0, 3)


def test_mdf_probe_does_not_read_samples(tmp_path, monkeypatch):
    path = write_single_channel_mf4(tmp_path / "signal.mf4")
    from mf4_analyzer.io import loader as loader_mod

    real = loader_mod.ensure_mdf()

    class _Spy:
        def __init__(self, source):
            self._source = source

        def __getattr__(self, name):
            return getattr(self._source, name)

        def get(self, *args, **kwargs):
            raise AssertionError("probe read samples")

        def close(self):
            self._source.close()

    monkeypatch.setattr(
        loader_mod, "MDF", lambda source: _Spy(real(source)),
    )
    adapter = SourceAdapterRegistry.default().adapter_for(str(path))
    descriptor = adapter.probe_sources(str(path))[0]
    assert "sig" in descriptor.channel_names


def test_mdf_probe_and_load_share_time_collision_names(tmp_path):
    axis = [0.0, 0.1, 0.2, 0.3]
    path = write_signal_groups_mf4(tmp_path / "time-sig.mf4", [[
        ("Time", [10.0, 20.0, 30.0, 40.0], axis, "Nm"),
        ("sig", [1.0, 2.0, 3.0, 4.0], axis, "V"),
        ("t", [4.0, 3.0, 2.0, 1.0], axis),
    ]])
    adapter = SourceAdapterRegistry.default().adapter_for(str(path))
    probed = adapter.probe_sources(str(path))[0]
    loaded = adapter.load_sources(str(path))[0]
    fd = loaded.file_data
    assert probed.channel_names == tuple(fd.get_signal_channels())
    assert set(probed.channel_names) == {"Time [0:1]", "sig", "t"}
    assert probed.metadata["renamed_channels"] == fd.source_metadata["renamed_channels"]
    assert fd.source_metadata["time_column"] == "Time"
    assert fd.time_array.tolist() == pytest.approx(axis)
    assert fd.fs == pytest.approx(10.0)
    assert probed.units["Time [0:1]"] == "Nm"
    assert fd.channel_units["Time [0:1]"] == "Nm"
    assert fd.channel_metadata["t"]["physical_occurrence"] == (0, 3)
