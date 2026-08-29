"""Portable synthetic WWT bytes for owner tests.

Builds tiny, fully anonymous WinWert files from the product encoder constants.
Channel Zeit groups use n >= ``_MIN_TIMESERIES_SAMPLES`` (100) so they become
Navigator sources; auxiliary / tolerance arrays stay in 4–32 points so they
remain document records rather than source channels.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from mf4_analyzer.io.wwt_display import (
    AXIS_COLOR,
    CURVE_BASE,
    CURVE_SELECTOR,
    CURVE_STRIDE,
    CURVE_TICKS,
    GLOBAL_X_OFF,
    LINE_WIDTH_OFF,
    RECORD_COUNT_OFF,
    WINDOW_RECT_OFF,
    WINDOW_UNIT_SCALE,
    WwtWindowRectMm,
    curve_offset,
    palette_color,
    write_curve,
)
from mf4_analyzer.io.wwt_format import (
    _HEADER_SIZE,
    _MAGIC_PREFIX,
    _MIN_TIMESERIES_SAMPLES,
)
from mf4_analyzer.io.wwt_quantize import physical_to_raw
from mf4_analyzer.io.wwt_writer import (
    _DEFAULT_MAGIC,
    _encode_field,
    _finite_minmax,
    _pack_record,
)

# Channel Zeit groups below this threshold become curve-definition blocks.
CHANNEL_N = 128
AUX_N = 16

CHAN_X = "ChanX"
CHAN_Y = "ChanY"
LIMIT_HI = "LimitHi"
LIMIT_LO = "LimitLo"
LINE_X = "LineX"
MEAS_Y = "MeasY"
TOL_Y = "TolY"
FORM_Y = "FormY"
GAP_X = "GapX"
GAP_Y_POS = "y_pos"
GAP_Y_SPEED = "y_speed"
WIN_A = "WinA"
WIN_B = "WinB"
TIME_NAME = "Time"

CHAN_X_UNIT = "mm"
CHAN_Y_UNIT = "N"
MEAS_Y_UNIT = "mm"
TOL_Y_UNIT = "mm"
LINE_X_UNIT = "mm"
FORM_Y_UNIT = "N"

CHAN_X_LO, CHAN_X_HI = -100.0, 100.0
CHAN_X_TICK, CHAN_X_GRID = 10.0, 5.0
CHAN_Y_LO, CHAN_Y_HI = -50.0, 50.0
CHAN_Y_TICK, CHAN_Y_GRID = 10.0, 2.5
MEAS_Y_LO, MEAS_Y_HI = 0.0, 1.0
MEAS_Y_TICK, MEAS_Y_GRID = 0.2, 0.05
TOL_Y_LO, TOL_Y_HI = 0.0, 1.0
TOL_Y_TICK, TOL_Y_GRID = 0.2, 0.05
LINE_X_LO, LINE_X_HI = -10.0, 10.0
LINE_X_TICK, LINE_X_GRID = 5.0, 1.0

CHAN_Y_COLOR = palette_color(3)  # dark blue
TOL_Y_COLOR = palette_color(1)  # red
FORM_Y_COLOR = palette_color(2)  # green

DT = 0.001
T0 = 0.0
LINE_WIDTH_MM = 0.2
FORMULA = "abs(k2)"

RECT_WIN_A = WwtWindowRectMm(20.0, 40.0, 90.0, 50.0)
RECT_WIN_B = WwtWindowRectMm(120.0, 40.0, 70.0, 50.0)

MULTI_WINDOW_COUNT = 3
MULTI_FORMULA_COUNT = 1

_PLOT_K_X = 4200.0
_PLOT_K_Y = 2400.0
_ORIGIN_C = 100.0


@dataclass(frozen=True)
class WwtRecordSpec:
    tag: str
    name: str
    unit: str = ""
    n: int = 0
    values: np.ndarray | None = None
    dt: float | None = None
    t0: float | None = None
    formula: str | None = None


@dataclass(frozen=True)
class WwtCurveSpec:
    record_index: int
    label: str
    lo: float
    hi: float
    x_record_index: int = 0
    visible: bool = False
    selected: bool = False
    tick_interval: float = 0.0
    grid_interval: float = 0.0
    color: tuple[int, bytes] | None = None


@dataclass(frozen=True)
class WwtWindowSpec:
    rect_mm: WwtWindowRectMm
    x_axis: WwtCurveSpec
    curves: tuple[WwtCurveSpec, ...]
    global_x: int = 0
    line_width_mm: float = LINE_WIDTH_MM


def _emit(data: bytes, path: str | Path | None) -> Path | bytes:
    if path is None:
        return data
    out = Path(path)
    out.write_bytes(data)
    return out


def _linspace(lo: float, hi: float, n: int) -> np.ndarray:
    return np.linspace(float(lo), float(hi), int(n), dtype=np.float64)


def encode_window_rect(rect: WwtWindowRectMm) -> bytes:
    left = int(round(rect.x * WINDOW_UNIT_SCALE))
    right = int(round((rect.x + rect.width) * WINDOW_UNIT_SCALE))
    bottom = int(round(-rect.y * WINDOW_UNIT_SCALE))
    top = int(round((-rect.y + rect.height) * WINDOW_UNIT_SCALE))
    return struct.pack("<hhhh", left, top, right, bottom)


def _pack_one_record(spec: WwtRecordSpec, *, source_filename: str) -> bytes:
    tag = spec.tag
    if tag == "Zeit":
        n = int(spec.n)
        dt = float(spec.dt if spec.dt is not None else DT)
        t0 = float(spec.t0 if spec.t0 is not None else T0)
        t_end = t0 + dt * (n - 1) if n else t0
        return _pack_record(
            b"Zeit",
            n,
            name=spec.name,
            unit=spec.unit or "s",
            source_filename=source_filename,
            a=1.0,
            b=dt,
            c=t0,
            min_v=min(t0, t_end),
            max_v=max(t0, t_end) if t0 != t_end else t0 + 1.0,
            xkanalnr=0,
        )
    if tag == "Pars":
        formula = spec.formula or ""
        payload = formula.encode("latin-1") + b"\x00"
        return _pack_record(
            b"Pars",
            int(spec.n or 1),
            name=spec.name,
            unit=spec.unit,
            source_filename=source_filename,
            a=1.0,
            b=1.0,
            c=0.0,
            min_v=0.0,
            max_v=1.0,
            payload=payload,
        )
    if spec.values is None:
        raise ValueError(f"record {spec.name!r} needs values")
    values = np.asarray(spec.values, dtype=np.float64)
    n = int(spec.n or values.size)
    lo, hi = _finite_minmax(values)
    payload = physical_to_raw(values, tag, scale=1.0, offset=0.0, n=n)
    return _pack_record(
        tag.encode("ascii"),
        n,
        name=spec.name,
        unit=spec.unit,
        source_filename=source_filename,
        a=1.0,
        b=1.0,
        c=0.0,
        min_v=lo,
        max_v=hi,
        xkanalnr=0,
        payload=payload,
    )


def _write_curve_row(
    buf: bytearray,
    *,
    curve: int,
    spec: WwtCurveSpec,
    is_x_axis: bool = False,
) -> None:
    color = spec.color
    if color is None:
        color = AXIS_COLOR if is_x_axis else palette_color(max(spec.record_index, 1))
    write_curve(
        buf,
        0,
        curve,
        label=spec.label,
        lo=spec.lo,
        hi=spec.hi,
        x_curve=spec.x_record_index,
        visible=spec.visible,
        plot_k=_PLOT_K_X if is_x_axis else _PLOT_K_Y,
        origin_c=_ORIGIN_C,
        color=color,
    )
    off = curve_offset(0, curve)
    # write_curve always clears ticks when lo/hi are set; restore native values.
    struct.pack_into(
        "<dd", buf, off + CURVE_TICKS,
        float(spec.tick_interval), float(spec.grid_interval),
    )
    struct.pack_into("<H", buf, off + CURVE_SELECTOR, 1 if spec.selected else 0)


def _build_trailer(
    record_count: int,
    window: WwtWindowSpec,
    records: Sequence[WwtRecordSpec],
) -> bytes:
    buf = bytearray(CURVE_BASE + record_count * CURVE_STRIDE)
    buf[0:13] = b"DatenFenste2\x00"
    struct.pack_into("<d", buf, LINE_WIDTH_OFF, float(window.line_width_mm))
    struct.pack_into("<I", buf, RECORD_COUNT_OFF, int(record_count))
    buf[WINDOW_RECT_OFF:WINDOW_RECT_OFF + 8] = encode_window_rect(window.rect_mm)
    struct.pack_into("<H", buf, GLOBAL_X_OFF, int(window.global_x) & 0xFFFF)

    by_index = {spec.record_index: spec for spec in window.curves}
    for index, record in enumerate(records):
        if index == 0:
            row = window.x_axis
            _write_curve_row(buf, curve=0, spec=row, is_x_axis=True)
            continue
        spec = by_index.get(index)
        if spec is None:
            unit = f" [{record.unit}]" if record.unit else ""
            spec = WwtCurveSpec(
                record_index=index,
                label=f"{record.name}{unit}",
                lo=0.0,
                hi=1.0,
                x_record_index=window.global_x,
                visible=False,
                selected=False,
            )
        _write_curve_row(buf, curve=index, spec=spec, is_x_axis=False)
    return bytes(buf)


def write_wwt_bytes(
    records: Sequence[WwtRecordSpec],
    windows: Sequence[WwtWindowSpec] = (),
    *,
    title: str = "synthetic",
    comment: str = "factory",
    source_filename: str = "synthetic.wwt",
    magic: bytes = _DEFAULT_MAGIC,
) -> bytes:
    """Encode a synthetic WWT body plus zero or more DatenFenste2 windows."""
    if not records:
        raise ValueError("at least one record is required")
    if not magic.startswith(_MAGIC_PREFIX):
        raise ValueError(f"WWT magic must start with WinWert: {magic!r}")
    count = len(records)
    head = bytearray(_HEADER_SIZE)
    mag = bytes(magic)[:15].ljust(15, b"\0")
    head[0:15] = mag
    head[0x00F:0x10F] = _encode_field(title, 256)
    head[0x10F:0x20F] = _encode_field(comment, 256)
    struct.pack_into("<H", head, 0x20F, count)

    chunks: list[bytes] = [bytes(head)]
    for spec in records:
        chunks.append(_pack_one_record(spec, source_filename=source_filename))
    for window in windows:
        chunks.append(_build_trailer(count, window, records))
    return b"".join(chunks)


def write_wwt_file(
    path: str | Path,
    records: Sequence[WwtRecordSpec],
    windows: Sequence[WwtWindowSpec] = (),
    **kwargs,
) -> Path:
    out = Path(path)
    out.write_bytes(write_wwt_bytes(
        records, windows, source_filename=kwargs.pop("source_filename", out.name), **kwargs
    ))
    return out


def _axis_curve(
    label: str,
    lo: float,
    hi: float,
    *,
    x_record_index: int,
    tick: float,
    grid: float,
) -> WwtCurveSpec:
    return WwtCurveSpec(
        record_index=0,
        label=label,
        lo=lo,
        hi=hi,
        x_record_index=x_record_index,
        visible=False,
        selected=False,
        tick_interval=tick,
        grid_interval=grid,
        color=AXIS_COLOR,
    )


def _y_curve(
    record_index: int,
    label: str,
    lo: float,
    hi: float,
    *,
    x_record_index: int,
    tick: float,
    grid: float,
    visible: bool = True,
    selected: bool = True,
    color: tuple[int, bytes] | None = None,
) -> WwtCurveSpec:
    return WwtCurveSpec(
        record_index=record_index,
        label=label,
        lo=lo,
        hi=hi,
        x_record_index=x_record_index,
        visible=visible,
        selected=selected,
        tick_interval=tick,
        grid_interval=grid,
        color=color,
    )


def channel_xy_with_auxiliaries(path=None) -> Path | bytes:
    """One window: channel X/Y plus invisible limit/line auxiliary records."""
    n = CHANNEL_N
    aux = AUX_N
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec("Real", CHAN_X, CHAN_X_UNIT, n=n, values=_linspace(CHAN_X_LO, CHAN_X_HI, n)),
        WwtRecordSpec("Real", CHAN_Y, CHAN_Y_UNIT, n=n, values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n)),
        WwtRecordSpec("Zeit", "TimeAux", "s", n=aux, dt=DT, t0=T0),
        WwtRecordSpec("Real", LIMIT_HI, CHAN_Y_UNIT, n=aux, values=np.full(aux, 40.0)),
        WwtRecordSpec("Real", LIMIT_LO, CHAN_Y_UNIT, n=aux, values=np.full(aux, -40.0)),
        WwtRecordSpec("Real", LINE_X, CHAN_X_UNIT, n=aux, values=_linspace(-80.0, 80.0, aux)),
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A,
            global_x=1,
            x_axis=_axis_curve(
                f"{CHAN_X} [{CHAN_X_UNIT}]", CHAN_X_LO, CHAN_X_HI,
                x_record_index=1, tick=CHAN_X_TICK, grid=CHAN_X_GRID,
            ),
            curves=(
                _y_curve(
                    2, f"{CHAN_Y} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
                    x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
                    color=CHAN_Y_COLOR,
                ),
                _y_curve(
                    4, f"{LIMIT_HI} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
                    x_record_index=6, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
                    visible=False, selected=False,
                ),
                _y_curve(
                    5, f"{LIMIT_LO} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
                    x_record_index=6, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
                    visible=False, selected=False,
                ),
                _y_curve(
                    6, f"{LINE_X} [{LINE_X_UNIT}]", LINE_X_LO, LINE_X_HI,
                    x_record_index=6, tick=LINE_X_TICK, grid=LINE_X_GRID,
                    visible=False, selected=False,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def measurement_plus_record_only_tolerance(
    *, meas_n: int = CHANNEL_N, tol_n: int = AUX_N, path=None,
) -> Path | bytes:
    """Channel measurement XY plus a record-only tolerance with its own X."""
    if meas_n < _MIN_TIMESERIES_SAMPLES:
        raise ValueError(
            f"meas_n must be >= {_MIN_TIMESERIES_SAMPLES} so the measurement "
            "Zeit group becomes Navigator channels"
        )
    if tol_n >= _MIN_TIMESERIES_SAMPLES:
        raise ValueError(
            f"tol_n must be < {_MIN_TIMESERIES_SAMPLES} so the tolerance "
            "stays a record-only curve"
        )
    if tol_n < 2:
        raise ValueError("tol_n must be at least 2")
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=meas_n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_X, CHAN_X_UNIT, n=meas_n,
            values=_linspace(CHAN_X_LO, CHAN_X_HI, meas_n),
        ),
        WwtRecordSpec(
            "Real", MEAS_Y, MEAS_Y_UNIT, n=meas_n,
            values=_linspace(MEAS_Y_LO, MEAS_Y_HI, meas_n),
        ),
        WwtRecordSpec("Zeit", "TimeTol", "s", n=tol_n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", LINE_X, LINE_X_UNIT, n=tol_n,
            values=_linspace(LINE_X_LO, LINE_X_HI, tol_n),
        ),
        WwtRecordSpec(
            "Real", TOL_Y, TOL_Y_UNIT, n=tol_n,
            values=_linspace(0.2, 0.8, tol_n),
        ),
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A,
            global_x=1,
            x_axis=_axis_curve(
                f"{CHAN_X} [{CHAN_X_UNIT}]", CHAN_X_LO, CHAN_X_HI,
                x_record_index=1, tick=CHAN_X_TICK, grid=CHAN_X_GRID,
            ),
            curves=(
                _y_curve(
                    2, f"{MEAS_Y} [{MEAS_Y_UNIT}]", MEAS_Y_LO, MEAS_Y_HI,
                    x_record_index=1, tick=MEAS_Y_TICK, grid=MEAS_Y_GRID,
                    color=CHAN_Y_COLOR,
                ),
                _y_curve(
                    5, f"{TOL_Y} [{TOL_Y_UNIT}]", TOL_Y_LO, TOL_Y_HI,
                    x_record_index=4, tick=TOL_Y_TICK, grid=TOL_Y_GRID,
                    selected=False, color=TOL_Y_COLOR,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def multi_window_overlap_and_formula(path=None) -> Path | bytes:
    """Three windows, a Pars formula, independent X/Y refs, one exact overlap."""
    n = CHANNEL_N
    aux = AUX_N
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec("Real", CHAN_X, CHAN_X_UNIT, n=n, values=_linspace(CHAN_X_LO, CHAN_X_HI, n)),
        WwtRecordSpec("Real", CHAN_Y, CHAN_Y_UNIT, n=n, values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n)),
        WwtRecordSpec("Pars", FORM_Y, FORM_Y_UNIT, n=50000, formula=FORMULA),
        WwtRecordSpec("Zeit", "TimeAux", "s", n=aux, dt=DT, t0=T0),
        WwtRecordSpec("Real", LINE_X, LINE_X_UNIT, n=aux, values=_linspace(LINE_X_LO, LINE_X_HI, aux)),
        WwtRecordSpec("Real", TOL_Y, TOL_Y_UNIT, n=aux, values=_linspace(0.2, 0.8, aux)),
    )
    chan_y_curve = _y_curve(
        2, f"{CHAN_Y} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
        x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
        color=CHAN_Y_COLOR,
    )
    form_curve = _y_curve(
        3, f"{FORM_Y} [{FORM_Y_UNIT}]", 0.0, CHAN_Y_HI,
        x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
        color=FORM_Y_COLOR,
    )
    tol_curve = _y_curve(
        6, f"{TOL_Y} [{TOL_Y_UNIT}]", TOL_Y_LO, TOL_Y_HI,
        x_record_index=5, tick=TOL_Y_TICK, grid=TOL_Y_GRID,
        selected=False, color=TOL_Y_COLOR,
    )
    axis_a = _axis_curve(
        f"{WIN_A} [{CHAN_X_UNIT}]", CHAN_X_LO, CHAN_X_HI,
        x_record_index=1, tick=CHAN_X_TICK, grid=CHAN_X_GRID,
    )
    axis_b = _axis_curve(
        f"{WIN_B} [{LINE_X_UNIT}]", LINE_X_LO, LINE_X_HI,
        x_record_index=5, tick=LINE_X_TICK, grid=LINE_X_GRID,
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A, global_x=1, x_axis=axis_a,
            curves=(chan_y_curve,),
        ),
        WwtWindowSpec(
            rect_mm=RECT_WIN_B, global_x=1, x_axis=axis_a,
            curves=(form_curve,),
        ),
        WwtWindowSpec(
            rect_mm=RECT_WIN_B, global_x=5, x_axis=axis_b,
            curves=(tol_curve,),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def record_only_gap_curves(path=None) -> Path | bytes:
    """Record-only WinWert lines with the exact ``-1e300`` gap sentinel."""
    n = CHANNEL_N
    aux = 7
    gap_x = np.linspace(-30.0, 30.0, aux, dtype=np.float64)
    y_pos = np.array(
        [5.5, 5.5, -1e300, -9e299, -5.5, -5.5, -5.5],
        dtype=np.float64,
    )
    y_speed = np.array(
        [60.0, 90.0, -1e300, 60.0, 90.0, -1e300, 60.0],
        dtype=np.float64,
    )
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_X, CHAN_X_UNIT, n=n,
            values=_linspace(CHAN_X_LO, CHAN_X_HI, n),
        ),
        WwtRecordSpec(
            "Real", CHAN_Y, CHAN_Y_UNIT, n=n,
            values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n),
        ),
        WwtRecordSpec("Zeit", "TimeGap", "s", n=aux, dt=DT, t0=T0),
        WwtRecordSpec("Real", GAP_X, "deg", n=aux, values=gap_x),
        WwtRecordSpec("Real", GAP_Y_POS, "deg", n=aux, values=y_pos),
        WwtRecordSpec("Real", GAP_Y_SPEED, "deg/s", n=aux, values=y_speed),
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A,
            global_x=4,
            x_axis=_axis_curve(
                f"{GAP_X} [deg]", -30.0, 30.0,
                x_record_index=4, tick=10.0, grid=5.0,
            ),
            curves=(
                _y_curve(
                    5, f"{GAP_Y_POS} [deg]", -10.0, 10.0,
                    x_record_index=4, tick=5.0, grid=1.0,
                ),
                _y_curve(
                    6, f"{GAP_Y_SPEED} [deg/s]", 0.0, 100.0,
                    x_record_index=4, tick=20.0, grid=10.0,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)
