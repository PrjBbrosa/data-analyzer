import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.batch import _default_loader
from mf4_analyzer.io import source_adapters
from mf4_analyzer.io.source_adapters import UnsupportedSourceFormatError


def _stub_import(monkeypatch, method, loader):
    def run_import(operation, path, *, kwargs=None):
        assert operation == method
        assert kwargs in (None, {})
        return loader(path)

    monkeypatch.setattr(source_adapters, "run_import", run_import)


def test_default_loader_dispatches_audio_video(monkeypatch, tmp_path):
    path = tmp_path / "tone.wav"
    path.write_bytes(b"not decoded by this test")
    df = pd.DataFrame({"audio": np.zeros(4, dtype=np.float32)})
    called = {}

    def fake_load_audio_video(fp):
        called["path"] = fp
        return (
            df,
            ["audio"],
            {"audio": ""},
            48_000.0,
            {"source_kind": "audio", "fs": 48_000.0, "channels": 1},
        )

    _stub_import(monkeypatch, "load_audio_video", fake_load_audio_video)

    fd = _default_loader(str(path))

    assert called["path"] == str(path)
    assert fd.is_audio_source() is True
    assert fd.fs == 48_000.0
    assert fd._time_source == "audio"


def test_default_loader_dispatches_csv(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("Time,sig\n0,1\n0.1,2\n0.2,3\n", encoding="utf-8")

    fd = _default_loader(str(path))

    assert fd.is_audio_source() is False
    assert list(fd.data.columns) == ["Time", "sig"]
    assert fd.fs == 10.0


def test_default_loader_dispatches_fdc_as_csv(monkeypatch, tmp_path):
    path = tmp_path / "data.fdc"
    path.write_text("Time,sig\n0,1\n0.1,2\n0.2,3\n", encoding="utf-8")
    called = {}

    def fake_load_csv(fp):
        called["path"] = fp
        return pd.DataFrame({"Time": [0.0, 0.1], "sig": [1.0, 2.0]}), ["Time", "sig"], {}

    _stub_import(monkeypatch, "load_csv", fake_load_csv)

    fd = _default_loader(str(path))

    assert called["path"] == str(path)
    assert fd.is_audio_source() is False
    assert list(fd.data.columns) == ["Time", "sig"]


def test_default_loader_dispatches_asc_as_csv(monkeypatch, tmp_path):
    path = tmp_path / "data.asc"
    path.write_text("Time,sig\n0,1\n0.1,2\n", encoding="utf-8")
    called = {}

    def fake_load_ascii(fp):
        called["path"] = fp
        return (
            pd.DataFrame({"Time": [0.0, 0.1], "sig": [1.0, 2.0]}),
            ["Time", "sig"], {}, None,
            {"source_kind": "ascii", "ascii_kind": "delimited"},
        )

    _stub_import(monkeypatch, "load_ascii", fake_load_ascii)

    fd = _default_loader(str(path))

    assert called["path"] == str(path)
    assert list(fd.data.columns) == ["Time", "sig"]


def test_default_loader_dispatches_tdms(monkeypatch, tmp_path):
    path = tmp_path / "data.tdms"
    path.write_bytes(b"handled by mocked loader")
    called = {}

    def fake_load_tdms(fp):
        called["path"] = fp
        return (
            pd.DataFrame({"Time": [0.0, 0.1], "sig": [1.0, 2.0]}),
            ["Time", "sig"],
            {"sig": "V"},
            None,
            {"source_kind": "tdms"},
        )

    _stub_import(monkeypatch, "load_tdms", fake_load_tdms)

    fd = _default_loader(str(path))

    assert called["path"] == str(path)
    assert list(fd.data.columns) == ["Time", "sig"]


def test_default_loader_rejects_unknown_extension_without_mdf_fallback(tmp_path):
    path = tmp_path / "data.unknown"
    path.write_bytes(b"not an MDF")

    with pytest.raises(UnsupportedSourceFormatError, match=r"\.unknown"):
        _default_loader(str(path))


def test_default_loader_canoe_asc_without_dbc_is_unavailable(tmp_path):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    from mf4_analyzer.io.source_adapters import SourceUnavailableError
    from tests._helpers.blf_factory import write_sample_asc

    path = write_sample_asc(tmp_path / "log.asc", n=2)
    with pytest.raises(SourceUnavailableError, match="DBC"):
        _default_loader(str(path))
