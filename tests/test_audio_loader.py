import wave

import numpy as np
import pytest

from mf4_analyzer.db_reference import ChannelReferenceFacts, resolve_db_reference
from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import AUDIO_DEFAULT_UNIT, AUDIO_VIDEO_EXTS, DataLoader


def _write_mono_wav(path, fs, samples):
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(fs)
        handle.writeframes(pcm.tobytes())


def _write_stereo_wav(path, fs, left, right):
    pcm_l = np.clip(left, -1.0, 1.0)
    pcm_r = np.clip(right, -1.0, 1.0)
    interleaved = np.empty(len(pcm_l) * 2, dtype="<i2")
    interleaved[0::2] = (pcm_l * 32767).astype("<i2")
    interleaved[1::2] = (pcm_r * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(fs)
        handle.writeframes(interleaved.tobytes())


def _pcm16_expected_float32(samples):
    """Independent PCM16 → float32 oracle (truncate toward 0, decode / 32768).

    Encoder delay is not part of this conversion; WAV PCM has delay 0.
    """
    pcm = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    return pcm.astype(np.float32) / np.float32(32768.0)


def test_audio_video_exts_cover_common_formats():
    assert {".mp4", ".mov", ".mkv", ".m4v", ".mp3", ".m4a", ".aac", ".wav", ".flac"} <= AUDIO_VIDEO_EXTS


def test_audio_default_unit_is_sound_pressure_pa():
    assert AUDIO_DEFAULT_UNIT == "Pa"


def test_load_audio_video_mono_wav(tmp_path):
    pytest.importorskip("av")
    fs = 48_000
    n = 4_800
    t = np.arange(n, dtype=float) / fs
    source = 0.5 * np.sin(2 * np.pi * 1000 * t)
    path = tmp_path / "tone.wav"
    _write_mono_wav(path, fs, source)

    data, channels, units, got_fs, meta = DataLoader.load_audio_video(path)

    assert got_fs == 48_000.0
    assert channels == ["audio"]
    assert units == {"audio": AUDIO_DEFAULT_UNIT}
    assert meta["source_kind"] == "audio"
    assert meta["fs"] == 48_000.0
    assert meta["channels"] == 1
    loaded = np.asarray(data["audio"], dtype=np.float32)
    expected = _pcm16_expected_float32(source)
    assert loaded.dtype == np.float32
    assert len(loaded) == n, (
        "WAV PCM has encoder delay 0; decoded frames must match the source "
        f"exactly (got {len(loaded)}, expected {n})"
    )
    np.testing.assert_allclose(loaded, expected, rtol=0, atol=0)
    assert float(np.max(np.abs(loaded))) > 0.4, "silent mono must not pass"

    fd = FileData(
        str(path), data, channels, units, fs=got_fs, source_metadata=meta,
    )
    facts = ChannelReferenceFacts(
        quantity="",
        unit=fd.channel_units["audio"],
        is_audio_source=fd.is_audio_source(),
    )
    assert facts.unit == "Pa"
    assert facts.is_audio_source is True
    resolution = resolve_db_reference(mode="auto", facts=facts)
    assert resolution.source == "system"
    assert resolution.value == 2e-5
    assert resolution.quantity == "sound pressure"


def test_load_audio_video_stereo_defaults_both_channels_to_pa(tmp_path):
    pytest.importorskip("av")
    fs = 8_000
    n = 800
    t = np.arange(n, dtype=float) / fs
    left = 0.25 * np.sin(2 * np.pi * 440 * t)
    right = -left
    path = tmp_path / "stereo.wav"
    _write_stereo_wav(path, fs, left, right)

    data, channels, units, _got_fs, meta = DataLoader.load_audio_video(path)

    assert channels == ["L", "R"]
    assert units == {"L": "Pa", "R": "Pa"}
    assert meta["source_kind"] == "audio"
    assert meta["channels"] == 2
    loaded_l = np.asarray(data["L"], dtype=np.float32)
    loaded_r = np.asarray(data["R"], dtype=np.float32)
    expected_l = _pcm16_expected_float32(left)
    expected_r = _pcm16_expected_float32(right)
    assert len(loaded_l) == n and len(loaded_r) == n
    np.testing.assert_allclose(loaded_l, expected_l, rtol=0, atol=0)
    np.testing.assert_allclose(loaded_r, expected_r, rtol=0, atol=0)
    assert not np.allclose(loaded_l, loaded_r)
    assert float(np.max(np.abs(loaded_l))) > 0.2
    assert float(np.max(np.abs(loaded_r))) > 0.2


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


def test_load_audio_video_invalid_sample_rate_raises(monkeypatch):
    """An audio stream with no resolvable sample rate must raise, not return
    fs=0 (which would make FileData build an inf time axis via arange(n)/0)."""
    av = pytest.importorskip("av")

    class _Frame:
        sample_rate = None

        def to_ndarray(self):
            return np.zeros((1, 64), dtype=np.float32)

    class _Resampler:
        def __init__(self, **kwargs):
            pass

        def resample(self, frame):
            return [_Frame()] if frame is not None else []

    class _CodecCtx:
        name = "pcm_s16le"
        rate = None
        layout = None

    class _Stream:
        rate = None
        channels = 1
        codec_context = _CodecCtx()
        layout = None

    class _Streams:
        audio = [_Stream()]

    class _Format:
        name = "wav"

    class _Container:
        format = _Format()
        streams = _Streams()

        def decode(self, _stream):
            return [_Frame()]

        def close(self):
            pass

    monkeypatch.setattr(av, "open", lambda _path: _Container())
    monkeypatch.setattr(av, "AudioResampler", _Resampler)

    with pytest.raises(ValueError, match="采样率"):
        DataLoader.load_audio_video("no_rate.wav")
