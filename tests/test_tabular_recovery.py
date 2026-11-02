"""Import gaps stay observable and never manufacture a table's time axis."""
import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import DataLoader


def _write_table(tmp_path, kind, frame):
    path = tmp_path / f"input.{kind}"
    if kind == "csv":
        frame.to_csv(path, index=False)
        return path, DataLoader.load_csv
    frame.to_excel(path, index=False)
    return path, DataLoader.load_excel


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_table_gaps_preserve_rows_finite_samples_and_time(tmp_path, kind):
    frame = pd.DataFrame({
        "Time": [3., 3.1, 3.2, 3.3, 3.4],
        "Signal": [None, 20., "broken", 40., None],
        "Other": [1., 2., 3., 4., 5.],
    })
    path, read = _write_table(tmp_path, kind, frame)
    data, channels, _ = read(path)
    assert channels == list(frame.columns)
    np.testing.assert_allclose(data["Time"], frame["Time"])
    np.testing.assert_allclose(data["Other"], frame["Other"])
    np.testing.assert_allclose(data["Signal"], [np.nan, 20., np.nan, 40., np.nan], equal_nan=True)
    metadata = data.attrs["source_metadata"]
    assert metadata["time_column"] == "Time"
    diag = metadata["import_diagnostics"]
    assert diag["state"] == "partial"
    gap = next(issue for issue in diag["issues"] if issue["code"] == "nonfinite_samples")
    assert gap["sample_count"] == 3
    assert gap["source_rows"] == [2, 4, 6]


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
@pytest.mark.parametrize("time", [[0., "broken", 2.], ["broken", 1., 2.],
                                 [0., np.inf, 2.], [0., 0., 1.], [0., 2., 1.]])
def test_table_bad_time_is_not_filled_or_replaced(tmp_path, kind, time):
    path, read = _write_table(tmp_path, kind, pd.DataFrame({"Time": time, "Signal": [1., 2., 3.]}))
    with pytest.raises(ValueError, match="时间"):
        read(path)
    with pytest.raises(ValueError, match="时间"):
        read(path, sampling_rate=100.)


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_table_missing_time_requires_explicit_sampling_rate(tmp_path, kind):
    path, read = _write_table(tmp_path, kind, pd.DataFrame({"Signal": [1., 2., 3.]}))
    with pytest.raises(ValueError, match="时间"):
        read(path)
    data, channels, units = read(path, sampling_rate=50.)
    metadata = data.attrs["source_metadata"]
    assert channels == ["Time", "Signal"]
    assert metadata["time_axis_origin"] == "explicit_sampling_rate"
    fd = FileData(str(path), data, channels, units, source_metadata=metadata)
    np.testing.assert_allclose(fd.time_array, [0., .02, .04])
    assert fd.fs == 50.


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_table_drops_only_unusable_columns_and_reports_identity(tmp_path, kind):
    path, read = _write_table(tmp_path, kind, pd.DataFrame({
        "Time": [0., 1., 2.], "Good": [3., 4., 5.], "Bad": ["x", "y", "z"],
    }))
    data, channels, _ = read(path)
    assert channels == ["Time", "Good"]
    assert len(data) == 3
    issue = next(i for i in data.attrs["source_metadata"]["import_diagnostics"]["issues"]
                 if i["code"] == "unusable_channel")
    assert issue["channel"] == "Bad" and issue["column_index"] == 2


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_table_all_unusable_signals_fails(tmp_path, kind):
    path, read = _write_table(tmp_path, kind, pd.DataFrame({"Time": [0., 1.], "Bad": ["x", "y"]}))
    with pytest.raises(ValueError, match="数值|通道"):
        read(path)


def test_csv_first_bad_signal_row_is_not_mistaken_for_units(tmp_path):
    path = tmp_path / "first.csv"
    path.write_text("Time,Signal\n0,broken\n1,2\n2,3\n")
    data, _, _ = DataLoader.load_csv(path)
    assert data["Time"].tolist() == [0, 1, 2]
    assert np.isnan(data["Signal"].iloc[0])


@pytest.mark.parametrize("bad", ["1,2,3", "1", '1,"unterminated'])
def test_csv_malformed_row_is_not_silently_truncated(tmp_path, bad):
    path = tmp_path / "bad.csv"
    path.write_text(f"Time,Signal\n0,1\n{bad}\n2,3\n")
    with pytest.raises(ValueError, match="CSV|列数"):
        DataLoader.load_csv(path)


def test_csv_blank_data_row_is_not_dropped(tmp_path):
    path = tmp_path / "blank.csv"
    path.write_text("Time,Signal\n0,1\n\n2,3\n")
    with pytest.raises(ValueError, match="时间"):
        DataLoader.load_csv(path)


def test_delimited_ascii_keeps_gap_diagnostics(tmp_path):
    path = tmp_path / "gap.asc"
    path.write_text("Time\tSignal\n0\t1\n1\tbroken\n2\t3\n")
    data, _, _, _, metadata = DataLoader.load_ascii(path)
    assert np.isnan(data["Signal"].iloc[1])
    assert metadata["source_kind"] == "ascii"
    assert metadata["import_diagnostics"]["state"] == "partial"


def test_csv_decimal_comma_gap_retains_other_values(tmp_path):
    path = tmp_path / "decimal.csv"
    path.write_text("Zeit;Signal\n0,0;100,5\n0,1;broken\n0,2;102,5\n")
    data, _, _ = DataLoader.load_csv(path)
    np.testing.assert_allclose(data["Zeit"], [0., .1, .2])
    np.testing.assert_allclose(data["Signal"], [100.5, np.nan, 102.5], equal_nan=True)


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_single_time_sample_does_not_imply_default_rate(tmp_path, kind):
    path, read = _write_table(tmp_path, kind, pd.DataFrame({"Time": [4.], "Signal": [7.]}))
    data, channels, units = read(path)
    fd = FileData(str(path), data, channels, units, source_metadata=data.attrs["source_metadata"])
    assert fd.time_array.tolist() == [4.]
    assert fd.fs == 0.


def test_first_all_invalid_csv_row_is_not_a_units_row(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("Time,Signal\nbroken,broken\n1,2\n2,3\n")
    with pytest.raises(ValueError, match="时间"):
        DataLoader.load_csv(path)


def test_tiny_interval_does_not_create_infinite_sampling_rate(tmp_path):
    path = tmp_path / "tiny.csv"
    path.write_text("Time,Signal\n0,1\n1e-320,2\n2e-320,3\n")
    with pytest.raises(ValueError, match="时间"):
        DataLoader.load_csv(path)


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_explicit_sampling_rate_cannot_generate_nonfinite_time(tmp_path, kind):
    path, read = _write_table(tmp_path, kind, pd.DataFrame({"Signal": [1., 2., 3.]}))
    with pytest.raises(ValueError, match="时间"):
        read(path, sampling_rate=1e-320)


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_actual_source_adapter_keeps_table_gap_facts(tmp_path, kind):
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry

    path, _ = _write_table(tmp_path, kind, pd.DataFrame({"Time": [0., .1, .2], "Signal": [1., None, 3.]}))
    source, = SourceAdapterRegistry.default().load_sources(str(path))
    assert source.file_data.fs == pytest.approx(10.)
    assert np.isnan(source.file_data.data["Signal"].iloc[1])
    assert source.metadata["import_diagnostics"]["state"] == "partial"


def test_excel_datetime_time_is_not_interpreted_as_numeric_seconds(tmp_path):
    path, read = _write_table(tmp_path, "xlsx", pd.DataFrame({
        "Time": pd.to_datetime(["2026-01-01", "2026-01-02"]), "Signal": [1., 2.],
    }))
    with pytest.raises(ValueError, match="时间"):
        read(path)


def test_complex_signal_does_not_lose_imaginary_part_without_notice():
    from mf4_analyzer.io.tabular_data import prepare_numeric_table

    data, channels, _ = prepare_numeric_table(
        pd.DataFrame({"Time": [0., 1.], "Good": [3., 4.], "Complex": [1+2j, 3+4j]}),
        source_kind="excel", source_filename="complex.xlsx",
    )
    assert channels == ["Time", "Good"]
    assert data.attrs["source_metadata"]["import_diagnostics"]["state"] == "partial"


@pytest.mark.parametrize("unit, values", [("ms", [0, 10, 20]), ("us", [0, 10000, 20000]),
                                         ("ns", [0, 10000000, 20000000])])
def test_csv_declared_time_unit_is_normalized_to_seconds(tmp_path, unit, values):
    path = tmp_path / "units.csv"
    path.write_text(f"Time,Signal\n{unit},N\n" + "".join(f"{t},{i}\n" for i, t in enumerate(values)))
    data, channels, units = DataLoader.load_csv(path)
    metadata = data.attrs["source_metadata"]
    fd = FileData(str(path), data, channels, units, source_metadata=metadata)
    np.testing.assert_allclose(fd.time_array, [0., .01, .02])
    assert fd.fs == pytest.approx(100.)
    assert units["Time"] == "s"
    assert metadata["original_time_unit"] == unit
    assert any(i["code"] == "time_unit_converted" for i in metadata["import_diagnostics"]["issues"])
