import numpy as np
import pandas as pd

from mf4_analyzer.io.file_data import FileData


def test_explicit_fs_skips_time_column_inference():
    df = pd.DataFrame({
        "Time": np.linspace(100.0, 101.0, 8),
        "audio": np.zeros(8, dtype=np.float32),
    })

    fd = FileData(
        "x.wav",
        df,
        ["Time", "audio"],
        {"audio": ""},
        fs=48_000.0,
        source_metadata={"source_kind": "audio"},
    )

    assert fd.fs == 48_000.0
    assert fd._time_source == "audio"
    assert fd.time_array[0] == 0.0
    assert fd.time_array[1] == 1.0 / 48_000.0


def test_is_audio_source_only_uses_source_kind():
    df = pd.DataFrame({"audio": np.zeros(10, dtype=np.float32)})
    audio = FileData(
        "x.wav",
        df,
        ["audio"],
        {"audio": ""},
        fs=48_000.0,
        source_metadata={"source_kind": "audio", "container": "wav"},
    )
    plain_with_audio_name = FileData("y.wav", df, ["audio"], {"audio": ""})

    assert audio.is_audio_source() is True
    assert plain_with_audio_name.is_audio_source() is False


def test_no_fs_keeps_legacy_generated_1000hz_behavior():
    df = pd.DataFrame({"sig": np.zeros(100)})

    fd = FileData("z.csv", df, ["sig"], {"sig": ""})

    assert fd.fs == 1000.0
    assert fd._time_source == "generated"
    assert fd.time_array[1] == 0.001
