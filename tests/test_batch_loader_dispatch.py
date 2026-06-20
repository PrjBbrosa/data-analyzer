import numpy as np
import pandas as pd

from mf4_analyzer.batch import _default_loader
from mf4_analyzer.io.loader import DataLoader


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

    monkeypatch.setattr(DataLoader, "load_audio_video", staticmethod(fake_load_audio_video))

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
