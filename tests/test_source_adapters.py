from __future__ import annotations

from types import SimpleNamespace

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
)
from tests._helpers.mf4_factory import write_single_channel_mf4


REQUIRED_EXTENSIONS = {
    ".mf4", ".mdf", ".blf", ".tdms", ".csv", ".fdc", ".asc",
    ".xlsx", ".xls", ".hdf", ".wwt", ".zfd", ".mat",
} | AUDIO_VIDEO_EXTS


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
        ("run.tdms", "load_tdms", _single3()),
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
