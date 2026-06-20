import wave

import numpy as np
import pytest

from mf4_analyzer.io.loader import AUDIO_VIDEO_EXTS, DataLoader


def _write_mono_wav(path, fs, samples):
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(fs)
        handle.writeframes(pcm.tobytes())


def test_audio_video_exts_cover_common_formats():
    assert {".mp4", ".mov", ".mkv", ".m4v", ".mp3", ".m4a", ".aac", ".wav", ".flac"} <= AUDIO_VIDEO_EXTS


def test_load_audio_video_mono_wav(tmp_path):
    pytest.importorskip("av")
    fs = 48_000
    n = 4_800
    t = np.arange(n, dtype=float) / fs
    path = tmp_path / "tone.wav"
    _write_mono_wav(path, fs, 0.5 * np.sin(2 * np.pi * 1000 * t))

    data, channels, units, got_fs, meta = DataLoader.load_audio_video(path)

    assert got_fs == 48_000.0
    assert channels == ["audio"]
    assert units == {"audio": ""}
    assert meta["source_kind"] == "audio"
    assert meta["fs"] == 48_000.0
    assert meta["channels"] == 1
    assert len(data) == pytest.approx(n, abs=int(fs * 0.05))
    assert data["audio"].dtype == np.float32


def test_load_audio_video_no_audio_stream_raises(monkeypatch):
    av = pytest.importorskip("av")

    class _Streams:
        audio = []

    class _Container:
        streams = _Streams()

        def close(self):
            pass

    monkeypatch.setattr(av, "open", lambda _path: _Container())

    with pytest.raises(ValueError, match="文件不含音轨"):
        DataLoader.load_audio_video("silent.mp4")
