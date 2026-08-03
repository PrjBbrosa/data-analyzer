"""Data export for the batch heatmap slice (design §6, plan stage 5).

The load-bearing test here is
``test_workbook_values_match_the_rendered_slice_curves``: the workbook reads
``_Spectro2D.matrix``, which is **x-major**, while the renderer reads the
transpose ``_extract_heatmap`` hands it. Two mirrored index expressions both
produce a plausible table, and only one of them is the curve on the page, so
the orientation is pinned point by point rather than by inspection.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.batch import (
    AnalysisPreset,
    BatchOutput,
    BatchRunner,
    _Spectro2D,
)
from mf4_analyzer.io import FileData


def _make_file(tmp_path, fs=1024.0, name="sample.csv"):
    n = 2048
    t = np.arange(n, dtype=float) / fs
    frame = pd.DataFrame({
        "Time": t,
        "sig": np.sin(2 * np.pi * 102.4 * t) + 0.3 * np.sin(2 * np.pi * 256.0 * t),
        "rpm": np.full(n, 3072.0),
    })
    path = tmp_path / name
    frame.to_csv(path, index=False)
    return FileData(path, frame, list(frame.columns), {}, idx=0)


def _spectro():
    """A tiny hand-built payload with a distinct value in every cell."""
    return _Spectro2D(
        x=np.asarray([10.0, 20.0, 40.0]),
        y=np.asarray([1.0, 4.0]),
        # x-major: rows = X (time), columns = Y (frequency).
        matrix=np.asarray([[0.10, 0.20], [0.30, 0.40], [0.50, 0.60]]),
        x_name="time_s",
        y_name="frequency_hz",
    )


def _run(tmp_path, *, params, outputs, method="fft_time", out="out"):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name=f"slice {method}",
        method=method,
        target_signals=("sig",),
        params=params,
        outputs=outputs,
    )
    preset = dataclasses.replace(preset, file_ids=(1,))
    if method == "order_time":
        preset = dataclasses.replace(preset, rpm_channel="rpm")
    result = BatchRunner({1: fd}).run(preset, tmp_path / out)
    assert result.status == "done", result.blocked
    return result.items[0]


def _base_params(fs=1024.0):
    return {
        "fs": fs, "window": "hanning", "nfft": 256,
        "overlap": 0.5, "remove_mean": True,
    }


def _slice_params(axis="time", positions=(0.5, 1.2), fs=1024.0, **extra):
    params = _base_params(fs)
    params["slice"] = {
        "enabled": True, "axis": axis, "positions": list(positions),
    }
    params.update(extra)
    return params


def _xlsx_outputs(**kwargs):
    return BatchOutput(
        export_data=True, export_image=False, data_format="xlsx", **kwargs
    )


def _info(book):
    sheet = book["切片信息"]
    return dict(zip(sheet["项目"], sheet["值"]))


# ---------------------------------------------------------------------------
# Workbook shape (design §6.2, acceptance 10)
# ---------------------------------------------------------------------------


def test_slice_workbook_has_exactly_the_info_and_slice_sheets(tmp_path):
    item = _run(tmp_path, params=_slice_params(), outputs=_xlsx_outputs())

    book = pd.read_excel(item.data_path, sheet_name=None)

    assert list(book) == ["切片信息", "时间切片"]


@pytest.mark.parametrize(
    ("method", "axis", "positions", "sheet", "index_column", "prefix"),
    [
        ("fft_time", "time", (0.5, 1.2), "时间切片", "frequency_hz", "t="),
        ("fft_time", "y", (100.0, 260.0), "频率切片", "time_s", "f="),
        ("order_time", "time", (0.5,), "时间切片", "order", "t="),
        ("order_time", "y", (2.0,), "阶次切片", "time_s", "阶次="),
    ],
)
def test_sheet_and_columns_follow_the_axis_and_method(
    tmp_path, method, axis, positions, sheet, index_column, prefix,
):
    params = _slice_params(axis=axis, positions=positions)
    if method == "order_time":
        params.update({"max_order": 10.0, "order_res": 0.5, "time_res": 0.2})

    item = _run(tmp_path, params=params, outputs=_xlsx_outputs(), method=method)

    book = pd.read_excel(item.data_path, sheet_name=None)
    assert list(book) == ["切片信息", sheet]
    columns = list(book[sheet].columns)
    assert columns[0] == index_column
    assert len(columns) == 1 + len(positions)
    assert all(name.startswith(prefix) for name in columns[1:])


def test_column_labels_carry_the_landed_value_and_its_unit(tmp_path):
    sheets = _spectro().to_slice_sheets(
        _plan("time", (0, 2)), render_db=False,
    )
    assert list(sheets["时间切片"].columns) == [
        "frequency_hz", "t=10.00s", "t=40.00s",
    ]

    sheets = _spectro().to_slice_sheets(_plan("y", (1,)), render_db=False)
    assert list(sheets["频率切片"].columns) == ["time_s", "f=4.0Hz"]


def _plan(axis, indices):
    from mf4_analyzer.batch_render_qt._models import BatchSlicePick, BatchSlicePlan

    spectro = _spectro()
    coords = spectro.x if axis == "time" else spectro.y
    return BatchSlicePlan(
        axis=axis,
        picks=tuple(
            BatchSlicePick(
                index=index, value=float(coords[index]),
                requested=float(coords[index]),
            )
            for index in indices
        ),
    )


# ---------------------------------------------------------------------------
# Orientation: one matrix, one plan, one set of numbers (acceptance 11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axis", ["time", "y"])
def test_slice_curve_reads_the_x_major_matrix_the_mirrored_way(axis):
    """``_Spectro2D.matrix`` is the transpose of the renderer's display matrix.

    Guards the single most invertible line in this feature: on the x-major
    producer a fixed *time* is a matrix **row**, whereas on the renderer's
    row-major display matrix the very same slice is a **column**.
    """
    spectro = _spectro()
    from mf4_analyzer.batch_render_qt._builder import _slice_curve_values

    for index in range(len(spectro.x if axis == "time" else spectro.y)):
        np.testing.assert_array_equal(
            spectro.slice_curve(axis, index),
            _slice_curve_values(spectro.matrix.T, axis, index),
        )


@pytest.mark.parametrize(
    ("axis", "positions"),
    [("time", (0.5, 1.2)), ("y", (100.0, 260.0))],
)
def test_workbook_values_match_the_rendered_slice_curves(
    qapp, tmp_path, axis, positions,
):
    """The table and the drawn curve are the same numbers, point by point.

    Acceptance item 11: the workbook and the chart may not have two
    calculation paths. This runs the real export, then renders the same
    payload with the same params through the real scene builder and compares
    every sample of every curve.
    """
    from mf4_analyzer.batch_image_options import BatchRenderOptions
    from mf4_analyzer.batch_render_qt import BatchRenderContext
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    params = _slice_params(axis=axis, positions=positions)
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="slice parity", method="fft_time", target_signals=("sig",),
        params=params, outputs=_xlsx_outputs(),
    )
    preset = dataclasses.replace(preset, file_ids=(1,))
    runner = BatchRunner({1: fd})
    result = runner.run(preset, tmp_path / "out")
    assert result.status == "done", result.blocked
    item = result.items[0]

    spectro = runner._compute_fft_time_spectro(
        fd.data["sig"].to_numpy(dtype=float),
        fd.time_array,
        1024.0,
        dict(params, nfft=256, filter={"enabled": False}),
        channel_name="sig",
    )
    scene = build_batch_scene(
        ("fft_time", spectro),
        params=dict(item.effective_params),
        context=BatchRenderContext(
            source_display_name=str(fd.filename), channel="sig",
            method="fft_time",
        ),
        options=BatchRenderOptions(width_px=960, height_px=640),
    )
    try:
        scene.show_and_settle()
        qapp.processEvents()
        assert len(scene.slice_curves) == len(positions)

        table = pd.read_excel(item.data_path, sheet_name=None)
        sheet = table["时间切片" if axis == "time" else "频率切片"]
        assert len(sheet.columns) == 1 + len(scene.slice_curves)

        for column, curve in zip(sheet.columns[1:], scene.slice_curves):
            drawn_x, drawn_y = curve.getData()
            np.testing.assert_allclose(
                sheet[sheet.columns[0]].to_numpy(dtype=float), drawn_x,
            )
            np.testing.assert_allclose(
                sheet[column].to_numpy(dtype=float), drawn_y,
            )
    finally:
        scene.close()


def test_workbook_writes_the_charted_db_caliber_not_linear(tmp_path):
    """Design D24: the sheet holds what the page shows, dB when dB."""
    item = _run(tmp_path, params=_slice_params(), outputs=_xlsx_outputs())

    book = pd.read_excel(item.data_path, sheet_name=None)
    values = book["时间切片"]["t=0.50s"].to_numpy(dtype=float)

    assert np.all(values < 0.0)  # linear amplitudes here are all < 1
    info = _info(book)
    assert "dB" in str(info["幅值口径"])
    assert str(info["dB 参考值"]) == "1"


def test_linear_preset_writes_linear_values_and_says_so(tmp_path):
    item = _run(
        tmp_path,
        params=_slice_params(amplitude_mode="amplitude"),
        outputs=_xlsx_outputs(),
    )

    book = pd.read_excel(item.data_path, sheet_name=None)
    values = book["时间切片"]["t=0.50s"].to_numpy(dtype=float)

    assert np.all(values >= 0.0)
    info = _info(book)
    assert "dB" not in str(info["幅值口径"])
    assert "dB 参考值" not in info


# ---------------------------------------------------------------------------
# 切片信息 (design §6.2 / plan §5.2)
# ---------------------------------------------------------------------------


def test_info_sheet_facts_come_from_the_page_header_picker(tmp_path):
    """Plan §5.2: one shared selector, so the sheet cannot contradict the page."""
    from mf4_analyzer.batch_render_qt._page import effective_fact_items

    item = _run(tmp_path, params=_slice_params(), outputs=_xlsx_outputs())

    info = _info(pd.read_excel(item.data_path, sheet_name=None))
    header = dict(
        text.split("=", 1)
        for text in effective_fact_items(item.effective_params, {})
    )

    assert str(info["NFFT"]) == header["NFFT"]
    assert info["窗"] == header["window"]
    assert info["重叠"] == header["overlap"]
    assert str(info["采样率 Fs"]) == header["Fs"]


def test_info_sheet_identifies_the_source_channel_and_dimension(tmp_path):
    item = _run(tmp_path, params=_slice_params(), outputs=_xlsx_outputs())

    info = _info(pd.read_excel(item.data_path, sheet_name=None))

    assert info["来源文件"] == "sample.csv"
    assert info["通道"] == "sig"
    assert info["方法"] == "FFT vs Time"
    assert info["切片维度"] == "固定时间"
    assert info["切片位置 备注"] == "—"


def test_info_sheet_separates_the_request_from_where_it_landed(tmp_path):
    """Design D11: the exported cell is a grid center, not the typed value."""
    item = _run(
        tmp_path, params=_slice_params(positions=(1.2,)),
        outputs=_xlsx_outputs(),
    )

    info = _info(pd.read_excel(item.data_path, sheet_name=None))

    assert info["切片位置 请求"] == "1.2000 s"
    assert info["切片位置 落点"] != info["切片位置 请求"]
    assert info["切片位置 落点"].endswith(" s")


def test_info_sheet_reports_clamped_and_merged_positions(tmp_path):
    """Out-of-range positions never fail the run (D12) but must be disclosed."""
    item = _run(
        tmp_path, params=_slice_params(positions=(40.0, 50.0)),
        outputs=_xlsx_outputs(),
    )

    book = pd.read_excel(item.data_path, sheet_name=None)
    note = _info(book)["切片位置 备注"]

    assert "夹取" in note
    assert "合并" in note
    # Both requests land on the last frame, so only one column survives.
    assert len(book["时间切片"].columns) == 2


# ---------------------------------------------------------------------------
# Fallbacks (design D21 / D22, acceptance 12 / 13)
# ---------------------------------------------------------------------------


def test_csv_with_slice_enabled_falls_back_to_the_long_table_and_warns(tmp_path):
    item = _run(
        tmp_path, params=_slice_params(),
        outputs=BatchOutput(
            export_data=True, export_image=False, data_format="csv",
        ),
    )

    frame = pd.read_csv(item.data_path)

    assert list(frame.columns) == ["time_s", "frequency_hz", "amplitude"]
    assert any(
        warning.startswith("slice.csv_fallback:") for warning in item.warnings
    ), item.warnings


def test_csv_fallback_warning_is_recorded_once(tmp_path):
    item = _run(
        tmp_path, params=_slice_params(),
        outputs=BatchOutput(
            export_data=True, export_image=False, data_format="csv",
        ),
    )

    assert sum(
        warning.startswith("slice.csv_fallback:") for warning in item.warnings
    ) == 1


def test_slice_disabled_csv_is_byte_identical_to_having_no_slice_field(tmp_path):
    """Acceptance 12: an existing preset's data file may not move one byte."""
    without = _run(
        tmp_path, params=_base_params(),
        outputs=BatchOutput(
            export_data=True, export_image=False, data_format="csv",
        ),
        out="without",
    )
    disabled = _base_params()
    disabled["slice"] = {"enabled": False, "axis": "time", "positions": [5.0]}
    off = _run(
        tmp_path, params=disabled,
        outputs=BatchOutput(
            export_data=True, export_image=False, data_format="csv",
        ),
        out="off",
    )

    assert Path(without.data_path).read_bytes() == Path(off.data_path).read_bytes()
    assert not any(
        warning.startswith("slice.") for warning in off.warnings
    ), off.warnings


def test_slice_disabled_xlsx_stays_one_long_sheet(tmp_path):
    item = _run(tmp_path, params=_base_params(), outputs=_xlsx_outputs())

    book = pd.read_excel(item.data_path, sheet_name=None)

    assert list(book) == ["数据1"]
    assert list(book["数据1"].columns) == ["time_s", "frequency_hz", "amplitude"]


def test_long_table_is_used_when_the_optional_renderer_is_absent(
    tmp_path, monkeypatch,
):
    """No drawn curve, nothing for a table to match -- keep the old export."""
    import mf4_analyzer.batch as batch_module

    monkeypatch.setattr(
        batch_module, "_load_slice_render_contract", lambda: None,
    )
    item = _run(tmp_path, params=_slice_params(), outputs=_xlsx_outputs())

    book = pd.read_excel(item.data_path, sheet_name=None)

    assert list(book) == ["数据1"]


# ---------------------------------------------------------------------------
# _write_workbook and the publish-race retry (design §8, plan §5.1 item 4)
# ---------------------------------------------------------------------------


def test_write_workbook_publishes_every_sheet_under_its_own_name(tmp_path):
    sheets = {
        "切片信息": pd.DataFrame({"项目": ["通道"], "值": ["sig"]}),
        "时间切片": pd.DataFrame({"frequency_hz": [1.0, 2.0], "t=1.00s": [3.0, 4.0]}),
    }

    published = BatchRunner._write_workbook(sheets, tmp_path / "book.xlsx")

    book = pd.read_excel(published, sheet_name=None)
    assert list(book) == ["切片信息", "时间切片"]
    np.testing.assert_allclose(book["时间切片"]["t=1.00s"], [3.0, 4.0])


def test_write_workbook_forces_the_xlsx_suffix(tmp_path):
    published = BatchRunner._write_workbook(
        {"切片信息": pd.DataFrame({"项目": ["a"], "值": ["b"]})},
        tmp_path / "book.csv",
    )

    assert Path(published).suffix == ".xlsx"


def test_write_workbook_refuses_a_sheet_above_the_xlsx_row_ceiling(tmp_path):
    from mf4_analyzer.batch import _XLSX_MAX_DATA_ROWS

    oversized = pd.DataFrame({"a": np.zeros(_XLSX_MAX_DATA_ROWS + 1)})

    with pytest.raises(ValueError, match="above the xlsx limit"):
        BatchRunner._write_workbook({"数据": oversized}, tmp_path / "big.xlsx")


def test_publish_race_retry_rebuilds_the_workbook(tmp_path, monkeypatch):
    """Plan §5.1 item 4: the retry path must cover the workbook branch too.

    ``atomic_write_set`` raises ``OutputPublishRace`` after the holder has
    already surrendered its payload, so a factory that only knew how to make
    long tables would republish the wrong artifact -- or none at all.
    """
    import mf4_analyzer.batch as batch_module

    real = batch_module.atomic_write_set
    calls = []

    def racing_write_set(reservation, writers):
        calls.append(reservation)
        if len(calls) == 1:
            raise batch_module.OutputPublishRace("simulated race")
        return real(reservation, writers)

    monkeypatch.setattr(batch_module, "atomic_write_set", racing_write_set)

    item = _run(tmp_path, params=_slice_params(), outputs=_xlsx_outputs())

    assert len(calls) == 2
    book = pd.read_excel(item.data_path, sheet_name=None)
    assert list(book) == ["切片信息", "时间切片"]
    assert len(book["时间切片"].columns) == 3
