"""Small inputs and allocation spies for non-MDF loader admission."""
from pathlib import Path
from types import SimpleNamespace
import zipfile

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.import_limits import ImportLimits, ImportResourceError, budget_context
from mf4_analyzer.io.loader import DataLoader


def _limits(memory=1024 * 1024, **kwargs):
    return ImportLimits(max_memory_bytes=memory, **kwargs)


def _forbidden(*args, **kwargs):
    pytest.fail("payload materialized before budget admission")


def test_ascii_header_never_reads_whole_text(tmp_path, monkeypatch):
    from tests.test_ascii_loader import _fixed_width_text
    path = tmp_path / "fixed.asc"
    path.write_text(_fixed_width_text())
    monkeypatch.setattr(Path, "read_text", _forbidden)
    data, channels, units, fs, _ = DataLoader.load_ascii(path)
    assert channels == ["Load", "Speed"] and fs == 2000.
    assert len(data) == 8 and units["Load"] == "Nm"


def test_csv_units_never_read_whole_text(tmp_path, monkeypatch):
    path = tmp_path / "units.csv"
    path.write_text("Time,Signal\ns,N\n0,1\n1,2\n")
    monkeypatch.setattr(Path, "read_text", _forbidden)
    data, _, units = DataLoader.load_csv(path)
    assert units == {"Time": "s", "Signal": "N"}
    assert data["Signal"].tolist() == [1, 2]


def test_csv_fallback_probes_only_bounded_prefix(tmp_path, monkeypatch):
    path = tmp_path / "fallback.csv"
    path.write_text("Time,Signal\n" + "".join(f"{i},{i}\n" for i in range(50)))
    monkeypatch.setattr("mf4_analyzer.io.csv_format.sniff_csv_layout", lambda p: None)
    original = pd.read_csv
    calls = []
    def checked_read(*args, **kwargs):
        if not calls:
            assert kwargs.get("nrows") == 10
            assert not isinstance(args[0], (str, Path)), "fallback should use the bounded text prefix"
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(pd, "read_csv", checked_read)
    data, _, _ = DataLoader.load_csv(path)
    assert len(data) == 50


@pytest.mark.parametrize("kind", ["csv", "ascii"])
def test_table_budget_rejects_before_pandas(tmp_path, monkeypatch, kind):
    path = tmp_path / f"limited.{kind}"
    if kind == "csv":
        path.write_text("Time,Signal\n" + "".join(f"{i},{i}\n" for i in range(100)))
        read = DataLoader.load_csv
        monkeypatch.setattr(pd, "read_csv", _forbidden)
    else:
        from tests.test_ascii_loader import _fixed_width_text
        path.write_text(_fixed_width_text())
        read = DataLoader.load_ascii
        monkeypatch.setattr(pd, "read_fwf", _forbidden)
    with budget_context(_limits(64)), pytest.raises(ImportResourceError):
        read(path)


def test_delimited_ascii_preserves_resource_error(tmp_path):
    path = tmp_path / "limited.asc"
    path.write_text("Time,Signal\n0,1\n1,2\n")
    with budget_context(_limits(1)), pytest.raises(ImportResourceError):
        DataLoader.load_ascii(path)


def test_excel_zip_declared_size_rejected_before_parser(tmp_path, monkeypatch):
    path = tmp_path / "small-compressed.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b" " * 200_000)
    assert path.stat().st_size < 4096
    monkeypatch.setattr(pd, "read_excel", _forbidden)
    with budget_context(_limits(4096)), pytest.raises(ImportResourceError):
        DataLoader.load_excel(path)


def test_tdms_metadata_rejects_before_read(tmp_path, monkeypatch):
    from nptdms import ChannelObject, TdmsFile, TdmsWriter
    path = tmp_path / "limited.tdms"
    with TdmsWriter(path) as writer:
        writer.write_segment([ChannelObject("G", "Signal", np.arange(100.), {"wf_increment": .1})])
    monkeypatch.setattr(TdmsFile, "read", _forbidden)
    with budget_context(_limits(256)), pytest.raises(ImportResourceError):
        DataLoader.load_tdms(path)


def _audio(monkeypatch, arrays, *, samples=8, channels=2):
    av = pytest.importorskip("av")
    converted = []
    class Frame:
        sample_rate = 8000
        def __init__(self, arr):
            self.arr = arr
            self.samples = samples
            self.layout = SimpleNamespace(channels=tuple(range(channels)))
        def to_ndarray(self):
            converted.append(self.arr.shape)
            return self.arr
    class Resampler:
        def __init__(self, **kwargs):
            pass
        def resample(self, frame):
            return [] if frame is None else [frame]
    stream = SimpleNamespace(rate=8000, channels=channels, layout=None,
                             codec_context=SimpleNamespace(name="test", rate=8000, layout=None))
    container = SimpleNamespace(streams=SimpleNamespace(audio=[stream]),
                                format=SimpleNamespace(name="test"), closed=False)
    container.decode = lambda stream: iter(Frame(a) for a in arrays)
    def close():
        container.closed = True
    container.close = close
    monkeypatch.setattr(av, "open", lambda path: container)
    monkeypatch.setattr(av, "AudioResampler", Resampler)
    return converted, container


def test_audio_declared_frame_budget_precedes_ndarray(tmp_path, monkeypatch):
    converted, container = _audio(monkeypatch, [np.zeros((2, 8), dtype="f4")])
    with budget_context(_limits(32)), pytest.raises(ImportResourceError):
        DataLoader.load_audio_video("tiny.wav")
    assert converted == [] and container.closed


@pytest.mark.parametrize("shape", [(1, 8), (3, 8), (8, 2), (2, 2, 4), (16,), (2, 7)])
def test_audio_shape_mismatch_is_not_reshaped_or_truncated(monkeypatch, shape):
    _, container = _audio(monkeypatch, [np.zeros(shape, dtype="f4")])
    with pytest.raises(ValueError, match="通道|维度|样本"):
        DataLoader.load_audio_video("mismatch.wav")
    assert container.closed


def test_head_rpm_injection_admitted_before_interp(tmp_path, monkeypatch):
    from tests._helpers.head_hdf_factory import write_head_hdf
    from mf4_analyzer.io.head_hdf import parse_head_hdf
    path = write_head_hdf(tmp_path / "rpm.hdf", n_scans=4, channels=[
        {"name": "acc", "factor": 2, "samples": np.arange(8.), "quantity": "acceleration", "unit": "m/s2", "calibration": 1.},
        {"name": "rpm", "factor": 1, "samples": np.arange(4.) + 1., "quantity": "speed of rotation", "unit": "deg/s", "calibration": 1.},
    ])
    with budget_context(_limits()) as budget:
        parse_head_hdf(path)
        parsed = budget.used_bytes
    monkeypatch.setattr(np, "interp", _forbidden)
    with budget_context(_limits(parsed)), pytest.raises(ImportResourceError):
        DataLoader.load_hdf(path)


def test_can_frame_batch_retains_warnings_and_legacy_callback(tmp_path, monkeypatch):
    from mf4_analyzer.io.can_frames import CanFrameBatch
    original = [(1., 123, b"\x01")]
    observed = []
    def read(path, *, progress_callback, warning_callback):
        warning_callback("compatibility reader used")
        return original
    monkeypatch.setattr("mf4_analyzer.io.asc_can_format._read_asc_frames", read)
    frames = DataLoader.read_blf_frames(tmp_path / "sample.asc", warning_callback=observed.append)
    assert isinstance(frames, list) and isinstance(frames, CanFrameBatch)
    assert frames == original and frames[0] == original[0]
    assert frames.warnings == ("compatibility reader used",)
    assert observed == ["compatibility reader used"]


def test_blf_frame_batch_has_empty_warnings(tmp_path, monkeypatch):
    monkeypatch.setattr("mf4_analyzer.io.blf_format._read_blf_frames",
                        lambda *a, **k: [(1., 123, b"\x01")])
    frames = DataLoader.read_blf_frames(tmp_path / "sample.blf")
    assert isinstance(frames, list) and frames.warnings == ()


@pytest.mark.parametrize("kind", ["blf", "asc-fast", "asc-fallback"])
def test_can_frame_budget_stops_accumulation(tmp_path, monkeypatch, kind):
    can = pytest.importorskip("can")
    from tests.test_asc_can_loader import _classic_line, _write_asc
    from mf4_analyzer.io.asc_can_format import _read_asc_frames_python_can
    path = tmp_path / "sample.asc"
    if kind == "asc-fast":
        _write_asc(path, [_classic_line(1.), _classic_line(2.)])
        monkeypatch.setattr("mf4_analyzer.io.asc_can_format._read_asc_frames_python_can", _forbidden)
        read = DataLoader.read_blf_frames
    else:
        class Reader:
            stopped = False
            def __init__(self, path):
                pass
            def __iter__(self):
                for i in range(100):
                    assert i < 2, "reader continued after budget failure"
                    yield can.Message(timestamp=float(i), arbitration_id=123, data=b"12345678")
            def stop(self):
                Reader.stopped = True
        monkeypatch.setattr(can.io, "BLFReader" if kind == "blf" else "ASCReader", Reader)
        path = path.with_suffix(".blf") if kind == "blf" else path
        read = DataLoader.read_blf_frames if kind == "blf" else _read_asc_frames_python_can
    with budget_context(_limits(200)), pytest.raises(ImportResourceError):
        read(path)
    if kind != "asc-fast":
        assert Reader.stopped


def test_audio_budget_is_cumulative_across_frames(monkeypatch):
    arrays = [np.ones((2, 8), dtype="f4") for _ in range(3)]
    converted, container = _audio(monkeypatch, arrays)
    with budget_context(_limits(1000)), pytest.raises(ImportResourceError):
        DataLoader.load_audio_video("chunks.wav")
    assert len(converted) == 1 and container.closed


def test_audio_multichannel_chunks_preserve_all_values(monkeypatch):
    arrays = [np.arange(24, dtype="f4").reshape(3, 8), np.arange(24, 48, dtype="f4").reshape(3, 8)]
    _audio(monkeypatch, arrays, channels=3)
    data, names, units, fs, _ = DataLoader.load_audio_video("three.wav")
    assert names == ["ch0", "ch1", "ch2"] and fs == 8000
    for i, name in enumerate(names):
        np.testing.assert_array_equal(data[name], np.concatenate([a[i] for a in arrays]))
        assert units[name] == "Pa"


def test_tdms_huge_metadata_length_in_tiny_file_precedes_read(tmp_path, monkeypatch):
    from nptdms import TdmsFile
    path = tmp_path / "declaration.tdms"
    path.write_bytes(b"tiny fixture")
    class MetadataChannel:
        dtype = np.dtype("f8")
        def __len__(self):
            return 1_000_000_000
    metadata = SimpleNamespace(groups=lambda: [SimpleNamespace(channels=lambda: [MetadataChannel()])])
    monkeypatch.setattr(TdmsFile, "read_metadata", lambda *a, **k: metadata)
    monkeypatch.setattr(TdmsFile, "read", _forbidden)
    with budget_context(_limits()), pytest.raises(ImportResourceError, match="native/scaled"):
        DataLoader.load_tdms(path)


def test_audio_metadata_budget_precedes_resampler(monkeypatch):
    av = pytest.importorskip("av")
    converted, container = _audio(monkeypatch, [np.zeros((2, 8), dtype="f4")], samples=1_000_000_000)
    monkeypatch.setattr(av.AudioResampler, "resample", _forbidden)
    with budget_context(_limits()), pytest.raises(ImportResourceError):
        DataLoader.load_audio_video("declared.wav")
    assert converted == [] and container.closed


def test_can_fallback_reuses_discarded_fast_frame_budget(tmp_path):
    from tests.test_asc_can_loader import _write_late_unsupported_asc
    path = _write_late_unsupported_asc(tmp_path / "late.asc", classic_before=800, classic_after=20)
    # Every retained payload is 8B, including the x line accepted by the
    # compatibility reader. The discarded fast prefix isn't another copy.
    with budget_context(_limits(821 * 200)):
        frames = DataLoader.read_blf_frames(path)
    assert len(frames) == 821 and frames.warnings


def test_csv_multiline_units_and_gap_rows_keep_source_identity(tmp_path):
    path = tmp_path / "multiline.csv"
    path.write_text('Time,Signal,Note\ns,N,label\n0,1,"first\nline"\n1,broken,second\n2,3,third\n')
    # Pass the physical-line layout explicitly; the sniff remains a heuristic.
    from mf4_analyzer.io.csv_format import CsvLayout
    data, channels, units = DataLoader._load_csv_with_layout(path, CsvLayout(0, 1, 2, ",", "utf-8", ".", None))
    assert channels == ["Time", "Signal"]
    assert units == {"Time": "s", "Signal": "N"}
    assert np.isnan(data[channels[1]].iloc[1])
    issue = next(i for i in data.attrs["source_metadata"]["import_diagnostics"]["issues"] if i["code"] == "nonfinite_samples")
    assert issue["source_rows"] == [5]


def test_native_three_channel_pcm_preserves_every_sample(tmp_path):
    import wave
    pytest.importorskip("av")
    pcm = (np.arange(384, dtype=np.int16).reshape(128, 3) - 192) * 100
    path = tmp_path / "three.wav"
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(3)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(pcm.astype("<i2").tobytes())
    data, channels, units, fs, _ = DataLoader.load_audio_video(path)
    assert channels == ["ch0", "ch1", "ch2"] and fs == 8000
    assert units == dict.fromkeys(channels, "Pa")
    np.testing.assert_array_equal(data.to_numpy(), pcm.astype(np.float32) / np.float32(32768.))
