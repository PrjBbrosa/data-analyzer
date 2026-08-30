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
SPEED_ALIAS_Y = "y_speed"
SPEED_ALIAS_POS = "y_pos"
SPEED_ALIAS_STEER = "Steering speed"
SPEED_ALIAS_TORQUE = "Steering torque"
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
RECT_ZERO_WIDTH = WwtWindowRectMm(20.0, 40.0, 0.0, 50.0)

MULTI_WINDOW_COUNT = 3
MULTI_FORMULA_COUNT = 1
THREE_EXACT_OVERLAP_COUNT = 3
CATALOG_32_COUNT = 32
COHORT_A_N = CHANNEL_N
COHORT_B_N = 160
COHORT_A_Y = "CohortA_Y"
COHORT_B_Y = "CohortB_Y"
CHAN_Z = "ChanZ"
PARS_ABTRIEB = "Abtrieb - mech. Krafteinleitung"
PARS_F_SPUST = "Theor. F_Spust. min"
UNRESOLVED_K51_K52_FORMULA = "abs(k51-(k52*0.85/(0.01787512/2))/1000)"
SHARED_AXIS_OWNER_TICK = 0.05
SHARED_AXIS_OWNER_GRID = 0.05
SPEED_ALIAS_UNIT_DEG = "deg/s"
SPEED_ALIAS_UNIT_DEGREE = "\u00b0/s"
SPEED_ALIAS_UNIT_TORQUE = "Nm"
SPEED_ALIAS_LO, SPEED_ALIAS_HI = 0.0, 460.0
SPEED_ALIAS_TICK, SPEED_ALIAS_GRID = 20.0, 10.0
SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI = -10.0, 10.0
SPEED_ALIAS_TORQUE_TICK, SPEED_ALIAS_TORQUE_GRID = 1.0, 0.5
SPEED_ALIAS_MISMATCH_HI = 100.0
NLTNP_X_LO, NLTNP_X_HI = -660.0, 540.0
NLTNP_X_TICK, NLTNP_X_GRID = 120.0, 60.0
HUGE_ZEIT_N = 2_000_000_000

# SFNS-like Custom X + native viewport (synthetic; not customer testdoc bytes).
SFNS_RACK_TRAVEL = "Rack Travel"
SFNS_RACK_FORCE = "Rack Force"
SFNS_RACK_TRAVEL_UNIT = "mm"
SFNS_RACK_FORCE_UNIT = "N"
SFNS_NATIVE_X_LO, SFNS_NATIVE_X_HI = -100.0, 100.0
SFNS_NATIVE_X_TICK, SFNS_NATIVE_X_GRID = 20.0, 10.0
SFNS_DATA_X_LO, SFNS_DATA_X_HI = -83.0, 83.0
SFNS_CURSOR_A, SFNS_CURSOR_B = -60.0, -45.0
SFNS_Y_LO, SFNS_Y_HI = -50.0, 50.0
SFNS_Y_TICK, SFNS_Y_GRID = 10.0, 5.0
SFNS_Y_UP_OFFSET = 20.0
SFNS_Y_DOWN_OFFSET = -20.0
SFNS_Y_SLOPE = 0.05
SFNS_N_HALF = 201
SFNS_VARIANTS = (
    "cycle",
    "noisy",
    "unidirectional",
    "two_cycles",
    "same_direction",
    "nan_gap",
    "inf_gap",
)
SENTINEL_RAW = -1e300
SENTINEL_SCALE = 2.0
SENTINEL_INDEX = 10


def palette_hex(color: tuple[int, bytes]) -> str:
    """WinWert palette entry ``(index, rgb)`` → ``#rrggbb``."""
    rgb = bytes(color[1])
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

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
    scale: float = 1.0
    offset: float = 0.0
    pack_raw: bool = False
    formula_nul_terminated: bool = True


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
        payload = formula.encode("latin-1")
        if spec.formula_nul_terminated:
            payload += b"\x00"
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
    scale = float(spec.scale)
    offset = float(spec.offset)
    lo, hi = _finite_minmax(values)
    if spec.pack_raw:
        payload = np.ascontiguousarray(values.astype("<f8", copy=False)).tobytes()
    else:
        payload = physical_to_raw(values, tag, scale=scale, offset=offset, n=n)
    return _pack_record(
        tag.encode("ascii"),
        n,
        name=spec.name,
        unit=spec.unit,
        source_filename=source_filename,
        a=scale,
        b=1.0,
        c=offset,
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


def shared_axis_evaluation_before_owner(
    *, meas_n: int = CHANNEL_N, tol_n: int = AUX_N, path=None,
) -> Path | bytes:
    """YP scene: unselected Tol (tick=0/grid=0) is listed before the owner.

    Same unit+range so D6 joins them onto the owner's axis. Record index of
    the evaluation line is lower than the selected measurement so native_y
    currently records the evaluation line's 0/0 ticks.
    """
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
            "Real", LINE_X, LINE_X_UNIT, n=tol_n,
            values=_linspace(LINE_X_LO, LINE_X_HI, tol_n),
        ),
        WwtRecordSpec(
            "Real", TOL_Y, TOL_Y_UNIT, n=tol_n,
            values=_linspace(0.2, 0.8, tol_n),
        ),
        WwtRecordSpec(
            "Real", MEAS_Y, MEAS_Y_UNIT, n=meas_n,
            values=_linspace(MEAS_Y_LO, MEAS_Y_HI, meas_n),
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
                    3, f"{TOL_Y} [{TOL_Y_UNIT}]", MEAS_Y_LO, MEAS_Y_HI,
                    x_record_index=2, tick=0.0, grid=0.0,
                    selected=False, color=TOL_Y_COLOR,
                ),
                _y_curve(
                    4, f"{MEAS_Y} [{MEAS_Y_UNIT}]", MEAS_Y_LO, MEAS_Y_HI,
                    x_record_index=1,
                    tick=SHARED_AXIS_OWNER_TICK, grid=SHARED_AXIS_OWNER_GRID,
                    color=CHAN_Y_COLOR,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def speed_unit_alias_shared_axis(path=None) -> Path | bytes:
    """NLTNP-like window: ``deg/s`` auxiliary joins selected ``°/s`` owner.

    Channel-backed torque (Nm) and steering speed stay independent owners.
    Record-only ``y_pos`` / ``y_speed`` use the same lo/hi/ticks as those
    owners so only the unit glyph should decide whether speed shares a slot.
    """
    n = CHANNEL_N
    aux = AUX_N
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_X, CHAN_X_UNIT, n=n,
            values=_linspace(CHAN_X_LO, CHAN_X_HI, n),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_TORQUE, SPEED_ALIAS_UNIT_TORQUE, n=n,
            values=_linspace(SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI, n),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_STEER, SPEED_ALIAS_UNIT_DEGREE, n=n,
            values=_linspace(SPEED_ALIAS_LO, SPEED_ALIAS_HI, n),
        ),
        WwtRecordSpec(
            "Real", LINE_X, LINE_X_UNIT, n=aux,
            values=_linspace(LINE_X_LO, LINE_X_HI, aux),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_POS, SPEED_ALIAS_UNIT_TORQUE, n=aux,
            values=_linspace(SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI, aux),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_Y, SPEED_ALIAS_UNIT_DEG, n=aux,
            values=_linspace(SPEED_ALIAS_LO, SPEED_ALIAS_HI, aux),
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
                    2, f"{SPEED_ALIAS_TORQUE} [{SPEED_ALIAS_UNIT_TORQUE}]",
                    SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI,
                    x_record_index=1,
                    tick=SPEED_ALIAS_TORQUE_TICK, grid=SPEED_ALIAS_TORQUE_GRID,
                    color=CHAN_Y_COLOR,
                ),
                _y_curve(
                    3, f"{SPEED_ALIAS_STEER} [{SPEED_ALIAS_UNIT_DEGREE}]",
                    SPEED_ALIAS_LO, SPEED_ALIAS_HI,
                    x_record_index=1,
                    tick=SPEED_ALIAS_TICK, grid=SPEED_ALIAS_GRID,
                    color=CHAN_Y_COLOR,
                ),
                _y_curve(
                    5, f"{SPEED_ALIAS_POS} [{SPEED_ALIAS_UNIT_TORQUE}]",
                    SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI,
                    x_record_index=4,
                    tick=SPEED_ALIAS_TORQUE_TICK, grid=SPEED_ALIAS_TORQUE_GRID,
                    selected=False, color=TOL_Y_COLOR,
                ),
                _y_curve(
                    6, f"{SPEED_ALIAS_Y} [{SPEED_ALIAS_UNIT_DEG}]",
                    SPEED_ALIAS_LO, SPEED_ALIAS_HI,
                    x_record_index=4,
                    tick=SPEED_ALIAS_TICK, grid=SPEED_ALIAS_GRID,
                    selected=False, color=TOL_Y_COLOR,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def nltnp_like_dual_axis(path=None) -> Path | bytes:
    """NLTNP-like overlay window for native range/tick lifecycle tests.

    X ``-660..540`` (major 120, grid 60). Torque ``-10..10 Nm`` (1 / 0.5)
    and speed ``0..460`` (20 / 10) each have a selected channel-backed
    owner plus a record-only companion. Does not depend on ``testdoc/``.
    """
    n = CHANNEL_N
    aux = AUX_N
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_X, CHAN_X_UNIT, n=n,
            values=_linspace(NLTNP_X_LO, NLTNP_X_HI, n),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_TORQUE, SPEED_ALIAS_UNIT_TORQUE, n=n,
            values=_linspace(SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI, n),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_STEER, SPEED_ALIAS_UNIT_DEGREE, n=n,
            values=_linspace(SPEED_ALIAS_LO, SPEED_ALIAS_HI, n),
        ),
        WwtRecordSpec(
            "Real", LINE_X, LINE_X_UNIT, n=aux,
            values=_linspace(LINE_X_LO, LINE_X_HI, aux),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_POS, SPEED_ALIAS_UNIT_TORQUE, n=aux,
            values=_linspace(SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI, aux),
        ),
        WwtRecordSpec(
            "Real", SPEED_ALIAS_Y, SPEED_ALIAS_UNIT_DEG, n=aux,
            values=_linspace(SPEED_ALIAS_LO, SPEED_ALIAS_HI, aux),
        ),
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A,
            global_x=1,
            x_axis=_axis_curve(
                f"{CHAN_X} [{CHAN_X_UNIT}]", NLTNP_X_LO, NLTNP_X_HI,
                x_record_index=1, tick=NLTNP_X_TICK, grid=NLTNP_X_GRID,
            ),
            curves=(
                _y_curve(
                    2, f"{SPEED_ALIAS_TORQUE} [{SPEED_ALIAS_UNIT_TORQUE}]",
                    SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI,
                    x_record_index=1,
                    tick=SPEED_ALIAS_TORQUE_TICK, grid=SPEED_ALIAS_TORQUE_GRID,
                    color=CHAN_Y_COLOR,
                ),
                _y_curve(
                    3, f"{SPEED_ALIAS_STEER} [{SPEED_ALIAS_UNIT_DEGREE}]",
                    SPEED_ALIAS_LO, SPEED_ALIAS_HI,
                    x_record_index=1,
                    tick=SPEED_ALIAS_TICK, grid=SPEED_ALIAS_GRID,
                    color=CHAN_Y_COLOR,
                ),
                _y_curve(
                    5, f"{SPEED_ALIAS_POS} [{SPEED_ALIAS_UNIT_TORQUE}]",
                    SPEED_ALIAS_TORQUE_LO, SPEED_ALIAS_TORQUE_HI,
                    x_record_index=4,
                    tick=SPEED_ALIAS_TORQUE_TICK, grid=SPEED_ALIAS_TORQUE_GRID,
                    selected=False, color=TOL_Y_COLOR,
                ),
                _y_curve(
                    6, f"{SPEED_ALIAS_Y} [{SPEED_ALIAS_UNIT_DEG}]",
                    SPEED_ALIAS_LO, SPEED_ALIAS_HI,
                    x_record_index=4,
                    tick=SPEED_ALIAS_TICK, grid=SPEED_ALIAS_GRID,
                    selected=False, color=TOL_Y_COLOR,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def two_window_non_overlap(path=None) -> Path | bytes:
    """Two visible windows with distinct non-overlapping millimetre rects."""
    n = CHANNEL_N
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
        WwtRecordSpec(
            "Real", MEAS_Y, MEAS_Y_UNIT, n=n,
            values=_linspace(MEAS_Y_LO, MEAS_Y_HI, n),
        ),
    )
    chan_y = _y_curve(
        2, f"{CHAN_Y} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
        x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
        color=CHAN_Y_COLOR,
    )
    meas_y = _y_curve(
        3, f"{MEAS_Y} [{MEAS_Y_UNIT}]", MEAS_Y_LO, MEAS_Y_HI,
        x_record_index=1, tick=MEAS_Y_TICK, grid=MEAS_Y_GRID,
        color=CHAN_Y_COLOR,
    )
    axis = _axis_curve(
        f"{CHAN_X} [{CHAN_X_UNIT}]", CHAN_X_LO, CHAN_X_HI,
        x_record_index=1, tick=CHAN_X_TICK, grid=CHAN_X_GRID,
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A, global_x=1, x_axis=axis, curves=(chan_y,),
        ),
        WwtWindowSpec(
            rect_mm=RECT_WIN_B, global_x=1, x_axis=axis, curves=(meas_y,),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def valid_and_zero_width_windows(path=None) -> Path | bytes:
    """One usable window plus a structurally valid ``right == left`` block."""
    n = CHANNEL_N
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
    )
    chan_y = _y_curve(
        2, f"{CHAN_Y} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
        x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
        color=CHAN_Y_COLOR,
    )
    axis = _axis_curve(
        f"{CHAN_X} [{CHAN_X_UNIT}]", CHAN_X_LO, CHAN_X_HI,
        x_record_index=1, tick=CHAN_X_TICK, grid=CHAN_X_GRID,
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A, global_x=1, x_axis=axis, curves=(chan_y,),
        ),
        WwtWindowSpec(
            rect_mm=RECT_ZERO_WIDTH, global_x=1, x_axis=axis, curves=(chan_y,),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def huge_zeit_n_header_only(path=None) -> Path | bytes:
    """Header-only Zeit declaring ``HUGE_ZEIT_N`` points with no sample payload."""
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=HUGE_ZEIT_N, dt=DT, t0=T0),
    )
    return _emit(write_wwt_bytes(records), path)


def sentinel_non_unit_scale_real(
    *, n: int = CHANNEL_N, index: int = SENTINEL_INDEX, path=None,
) -> Path | bytes:
    """Real record whose raw payload is ``-1e300`` with scale != 1.0."""
    if n < _MIN_TIMESERIES_SAMPLES:
        raise ValueError(
            f"n must be >= {_MIN_TIMESERIES_SAMPLES} so the Zeit group "
            "becomes a Navigator source"
        )
    if not 0 <= index < n:
        raise ValueError("sentinel index must fall inside the record")
    raw = _linspace(0.0, 1.0, n)
    raw[index] = SENTINEL_RAW
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_Y, CHAN_Y_UNIT, n=n, values=raw,
            scale=SENTINEL_SCALE, offset=0.0, pack_raw=True,
        ),
    )
    return _emit(write_wwt_bytes(records), path)


def _single_channel_window(y_index: int, y_name: str, y_unit: str) -> WwtWindowSpec:
    return WwtWindowSpec(
        rect_mm=RECT_WIN_A,
        global_x=0,
        x_axis=_axis_curve(
            f"{TIME_NAME} [s]", 0.0, 1.0,
            x_record_index=0, tick=0.1, grid=0.05,
        ),
        curves=(
            _y_curve(
                y_index, f"{y_name} [{y_unit}]", CHAN_Y_LO, CHAN_Y_HI,
                x_record_index=0, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
                color=CHAN_Y_COLOR,
            ),
        ),
    )


def unterminated_pars_formula(path=None) -> Path | bytes:
    """Pars payload is a 256-byte ``k1`` pad with no NUL terminator."""
    n = CHANNEL_N
    formula = "k1" + (" " * 254)
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_Y, CHAN_Y_UNIT, n=n,
            values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n),
        ),
        WwtRecordSpec(
            "Pars", FORM_Y, FORM_Y_UNIT, n=n, formula=formula,
            formula_nul_terminated=False,
        ),
    )
    return _emit(
        write_wwt_bytes(records, (_single_channel_window(1, CHAN_Y, CHAN_Y_UNIT),)),
        path,
    )


def aux_cohort_materialized_pars(path=None) -> Path | bytes:
    """Pars that evaluates on an auxiliary short Zeit block, not a source group."""
    n = CHANNEL_N
    aux = AUX_N
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_Y, CHAN_Y_UNIT, n=n,
            values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n),
        ),
        WwtRecordSpec("Zeit", "TimeAux", "s", n=aux, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", "AuxY", CHAN_Y_UNIT, n=aux,
            values=_linspace(1.0, 2.0, aux),
        ),
        WwtRecordSpec("Pars", "AuxForm", CHAN_Y_UNIT, n=aux, formula="abs(k3)"),
    )
    return _emit(
        write_wwt_bytes(records, (_single_channel_window(1, CHAN_Y, CHAN_Y_UNIT),)),
        path,
    )


def merged_zeit_formula_cohort(path=None) -> Path | bytes:
    """Two Zeit blocks share ``(n, dt, t0)``; formula refs both channel cohorts."""
    n = CHANNEL_N
    records = (
        WwtRecordSpec("Zeit", "TimeA", "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", "ChanA", CHAN_Y_UNIT, n=n,
            values=_linspace(0.0, 1.0, n),
        ),
        WwtRecordSpec("Zeit", "TimeB", "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", "ChanB", CHAN_Y_UNIT, n=n,
            values=_linspace(2.0, 3.0, n),
        ),
        WwtRecordSpec("Pars", "SumAB", CHAN_Y_UNIT, n=n, formula="k1+k3"),
    )
    return _emit(
        write_wwt_bytes(records, (_single_channel_window(1, "ChanA", CHAN_Y_UNIT),)),
        path,
    )


def two_zeit_cohorts_record_only_on_owner_a(path=None) -> Path | bytes:
    """One physical WWT that splits into two Navigator sources.

    Zeit A and Zeit B use different ``n`` (both >= ``_MIN_TIMESERIES_SAMPLES``)
    so they become two logical fids. The short auxiliary Y stays a document
    record and is bound only to owner A (the first Zeit cohort).
    """
    n_a = COHORT_A_N
    n_b = COHORT_B_N
    aux = AUX_N
    if n_a < _MIN_TIMESERIES_SAMPLES or n_b < _MIN_TIMESERIES_SAMPLES:
        raise ValueError("both Zeit cohorts must become Navigator sources")
    if n_a == n_b:
        raise ValueError("cohorts must differ in n so they do not merge")
    if aux >= _MIN_TIMESERIES_SAMPLES:
        raise ValueError("aux Y must stay a record-only curve")
    records = (
        WwtRecordSpec("Zeit", "TimeA", "s", n=n_a, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_X, CHAN_X_UNIT, n=n_a,
            values=_linspace(CHAN_X_LO, CHAN_X_HI, n_a),
        ),
        WwtRecordSpec(
            "Real", COHORT_A_Y, CHAN_Y_UNIT, n=n_a,
            values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n_a),
        ),
        WwtRecordSpec("Zeit", "TimeB", "s", n=n_b, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", COHORT_B_Y, CHAN_Y_UNIT, n=n_b,
            values=_linspace(0.0, 1.0, n_b),
        ),
        WwtRecordSpec("Zeit", "TimeTol", "s", n=aux, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", LINE_X, LINE_X_UNIT, n=aux,
            values=_linspace(LINE_X_LO, LINE_X_HI, aux),
        ),
        WwtRecordSpec(
            "Real", TOL_Y, TOL_Y_UNIT, n=aux,
            values=_linspace(0.2, 0.8, aux),
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
                    2, f"{COHORT_A_Y} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
                    x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
                    color=CHAN_Y_COLOR,
                ),
                _y_curve(
                    7, f"{TOL_Y} [{TOL_Y_UNIT}]", TOL_Y_LO, TOL_Y_HI,
                    x_record_index=6, tick=TOL_Y_TICK, grid=TOL_Y_GRID,
                    selected=False, color=TOL_Y_COLOR,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


def catalog_32_unresolved_k51_k52(path=None) -> Path | bytes:
    """32-record catalog whose Pars at 16/17 both reference out-of-range k51/k52.

    Distinctive ASCII names let formatter tests assert channel names without
    embedding the full ``abs(...)`` formula. Indices 16 and 17 match the
    customer-sample warning shape (``record 16`` / ``record 17``) that user
    copy must not leak.
    """
    n = CHANNEL_N
    aux = AUX_N
    records: list[WwtRecordSpec] = [
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_X, CHAN_X_UNIT, n=n,
            values=_linspace(CHAN_X_LO, CHAN_X_HI, n),
        ),
        WwtRecordSpec(
            "Real", CHAN_Y, CHAN_Y_UNIT, n=n,
            values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n),
        ),
    ]
    while len(records) < 16:
        idx = len(records)
        records.append(
            WwtRecordSpec(
                "Real", f"Pad{idx:02d}", CHAN_Y_UNIT, n=aux,
                values=_linspace(0.0, 1.0, aux),
            )
        )
    records.append(
        WwtRecordSpec(
            "Pars", PARS_ABTRIEB, FORM_Y_UNIT, n=1,
            formula=UNRESOLVED_K51_K52_FORMULA,
        )
    )
    records.append(
        WwtRecordSpec(
            "Pars", PARS_F_SPUST, FORM_Y_UNIT, n=1,
            formula=UNRESOLVED_K51_K52_FORMULA,
        )
    )
    while len(records) < CATALOG_32_COUNT:
        idx = len(records)
        records.append(
            WwtRecordSpec(
                "Real", f"Pad{idx:02d}", CHAN_Y_UNIT, n=aux,
                values=_linspace(0.0, 1.0, aux),
            )
        )
    if len(records) != CATALOG_32_COUNT:
        raise ValueError(f"expected {CATALOG_32_COUNT} records, got {len(records)}")
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
            ),
        ),
    )
    return _emit(write_wwt_bytes(tuple(records), windows), path)


def three_exact_overlap_windows(path=None) -> Path | bytes:
    """Three visible windows that share one native millimetre rect.

    Native layout should relocate the overlaps (``exact_overlap_relocated``)
    while still placing every generated View. User warning text must not
    contain ``4 → 3``-style arrows.
    """
    n = CHANNEL_N
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
        WwtRecordSpec(
            "Real", MEAS_Y, MEAS_Y_UNIT, n=n,
            values=_linspace(MEAS_Y_LO, MEAS_Y_HI, n),
        ),
        WwtRecordSpec(
            "Real", CHAN_Z, CHAN_Y_UNIT, n=n,
            values=_linspace(-1.0, 1.0, n),
        ),
    )
    axis = _axis_curve(
        f"{CHAN_X} [{CHAN_X_UNIT}]", CHAN_X_LO, CHAN_X_HI,
        x_record_index=1, tick=CHAN_X_TICK, grid=CHAN_X_GRID,
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A, global_x=1, x_axis=axis,
            curves=(
                _y_curve(
                    2, f"{CHAN_Y} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
                    x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
                    color=CHAN_Y_COLOR,
                ),
            ),
        ),
        WwtWindowSpec(
            rect_mm=RECT_WIN_A, global_x=1, x_axis=axis,
            curves=(
                _y_curve(
                    3, f"{MEAS_Y} [{MEAS_Y_UNIT}]", MEAS_Y_LO, MEAS_Y_HI,
                    x_record_index=1, tick=MEAS_Y_TICK, grid=MEAS_Y_GRID,
                    color=CHAN_Y_COLOR,
                ),
            ),
        ),
        WwtWindowSpec(
            rect_mm=RECT_WIN_A, global_x=1, x_axis=axis,
            curves=(
                _y_curve(
                    4, f"{CHAN_Z} [{CHAN_Y_UNIT}]", CHAN_Y_LO, CHAN_Y_HI,
                    x_record_index=1, tick=CHAN_Y_TICK, grid=CHAN_Y_GRID,
                    color=FORM_Y_COLOR,
                ),
            ),
        ),
    )
    return _emit(write_wwt_bytes(records, windows), path)


@dataclass(frozen=True)
class WwtBatchChoiceSet:
    """Distinct-filename batch: N display-bearing WWTs plus optional no-display."""

    display_paths: tuple[Path, ...]
    no_display_path: Path | None
    ordered_paths: tuple[Path, ...]


@dataclass(frozen=True)
class SfnsLikeSeries:
    """Custom-X Rack Travel / Rack Force arrays for cursor and WWT builders."""

    x: np.ndarray
    y: np.ndarray
    variant: str


def _sfns_force(x: np.ndarray, *, going_up: np.ndarray, y_offset: float = 0.0) -> np.ndarray:
    """Deterministic hysteresis: same X maps to two distinct Y values."""
    baseline = SFNS_Y_SLOPE * np.asarray(x, dtype=np.float64) + float(y_offset)
    return np.where(
        np.asarray(going_up, dtype=bool),
        baseline + SFNS_Y_UP_OFFSET,
        baseline + SFNS_Y_DOWN_OFFSET,
    )


def _sfns_add_turn_chatter(x: np.ndarray) -> np.ndarray:
    """Quantisation chatter around the turn, not a new physical reversal."""
    x = np.asarray(x, dtype=np.float64).copy()
    chatter = np.resize(
        np.asarray((0.20, 0.10, 0.0, -0.10, -0.20, -0.10, 0.0, 0.10)),
        x.size,
    )
    near_turn = (
        np.abs(x - SFNS_DATA_X_HI) < 4.0
    ) | (
        np.abs(x - SFNS_DATA_X_LO) < 4.0
    )
    x[near_turn] = x[near_turn] + chatter[near_turn]
    return x


def sfns_like_hysteresis_arrays(
    variant: str = "cycle", *, y_offset: float = 0.0, n_half: int = SFNS_N_HALF,
) -> SfnsLikeSeries:
    """Build SFNS-like Custom X/Y arrays.

    ``variant``:
      cycle — one hysteresis loop ``-83 → 83 → -83``
      noisy — same loop with chatter around the turn
      unidirectional — outward stroke only
      two_cycles — two full loops (four major legs)
      same_direction — two same-direction visits split by a NaN gap
      nan_gap / inf_gap — non-finite hole inside the outward stroke
    """
    if variant not in SFNS_VARIANTS:
        raise ValueError(f"unknown SFNS-like variant: {variant!r}")
    n_half = int(n_half)
    if n_half < 8:
        raise ValueError("n_half must be large enough for major-leg detection")
    up = _linspace(SFNS_DATA_X_LO, SFNS_DATA_X_HI, n_half)
    down = _linspace(SFNS_DATA_X_HI, SFNS_DATA_X_LO, n_half)[1:]
    up_y = _sfns_force(up, going_up=np.ones(up.size, dtype=bool), y_offset=y_offset)
    down_y = _sfns_force(down, going_up=np.zeros(down.size, dtype=bool), y_offset=y_offset)

    if variant == "unidirectional":
        x, y = up, up_y
    elif variant == "same_direction":
        x = np.concatenate((up, np.asarray((np.nan,)), up))
        y = np.concatenate((up_y, np.asarray((np.nan,)), up_y + 4.0))
    elif variant in {"nan_gap", "inf_gap"}:
        hole = np.nan if variant == "nan_gap" else np.inf
        mid = n_half // 2
        x = np.concatenate((up[:mid], np.asarray((hole,)), up[mid:], down))
        y = np.concatenate((up_y[:mid], np.asarray((hole,)), up_y[mid:], down_y))
    elif variant == "two_cycles":
        x = np.concatenate((up, down, up[1:], down))
        y = np.concatenate((up_y, down_y, up_y[1:], down_y))
    else:
        x = np.concatenate((up, down))
        y = np.concatenate((up_y, down_y))
        if variant == "noisy":
            x = _sfns_add_turn_chatter(x)

    return SfnsLikeSeries(x=np.asarray(x, dtype=np.float64), y=np.asarray(y, dtype=np.float64), variant=variant)


def no_display_source(path=None, *, title: str = "no-display") -> Path | bytes:
    """Zeit + channel record with no DatenFenste2 window / proposal."""
    n = CHANNEL_N
    source_filename = Path(path).name if path is not None else "no_display.wwt"
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", CHAN_Y, CHAN_Y_UNIT, n=n,
            values=_linspace(CHAN_Y_LO, CHAN_Y_HI, n),
        ),
    )
    return _emit(
        write_wwt_bytes(
            records, title=title, comment="no-display",
            source_filename=source_filename,
        ),
        path,
    )


def batch_choice_set(
    directory,
    *,
    n_display: int = 3,
    include_no_display: bool = True,
    no_display_at: int = 0,
) -> WwtBatchChoiceSet:
    """Write N distinct display-bearing WWTs plus one optional no-display WWT.

    Display files reuse the one-window channel XY profile so
    ``offer_layout`` actually asks. The no-display file still loads a
    Navigator source/record but must not consume a batch decision.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if n_display < 1:
        raise ValueError("n_display must be at least 1")
    display_paths = []
    for index in range(int(n_display)):
        name = f"batch_display_{index + 1:02d}.wwt"
        display_paths.append(channel_xy_with_auxiliaries(directory / name))
    no_display_path = None
    ordered: list[Path] = list(display_paths)
    if include_no_display:
        no_display_path = no_display_source(directory / "batch_no_display.wwt")
        insert_at = max(0, min(int(no_display_at), len(ordered)))
        ordered.insert(insert_at, no_display_path)
    return WwtBatchChoiceSet(
        display_paths=tuple(display_paths),
        no_display_path=no_display_path,
        ordered_paths=tuple(ordered),
    )


def sfns_like_custom_x_native_viewport(
    path=None,
    *,
    variant: str = "cycle",
    y_offset: float = 0.0,
    source_filename: str | None = None,
    title: str = "sfns-like",
) -> Path | bytes:
    """Custom X ``Rack Travel`` with native window X range ``-100..100``.

    Data union is about ``-83..83``; Y ``Rack Force`` has a deterministic
    hysteresis so the same X has two distinct Y values on the up vs down
    stroke. Does not depend on ``testdoc/``.
    """
    series = sfns_like_hysteresis_arrays(variant, y_offset=y_offset)
    n = int(series.x.size)
    if n < _MIN_TIMESERIES_SAMPLES:
        raise ValueError(
            f"SFNS-like series n={n} is below {_MIN_TIMESERIES_SAMPLES}; "
            "Zeit group would not become a Navigator source"
        )
    filename = source_filename
    if filename is None:
        filename = Path(path).name if path is not None else "sfns_like.wwt"
    records = (
        WwtRecordSpec("Zeit", TIME_NAME, "s", n=n, dt=DT, t0=T0),
        WwtRecordSpec(
            "Real", SFNS_RACK_TRAVEL, SFNS_RACK_TRAVEL_UNIT, n=n, values=series.x,
        ),
        WwtRecordSpec(
            "Real", SFNS_RACK_FORCE, SFNS_RACK_FORCE_UNIT, n=n, values=series.y,
        ),
    )
    windows = (
        WwtWindowSpec(
            rect_mm=RECT_WIN_A,
            global_x=1,
            x_axis=_axis_curve(
                f"{SFNS_RACK_TRAVEL} [{SFNS_RACK_TRAVEL_UNIT}]",
                SFNS_NATIVE_X_LO, SFNS_NATIVE_X_HI,
                x_record_index=1,
                tick=SFNS_NATIVE_X_TICK, grid=SFNS_NATIVE_X_GRID,
            ),
            curves=(
                _y_curve(
                    2,
                    f"{SFNS_RACK_FORCE} [{SFNS_RACK_FORCE_UNIT}]",
                    SFNS_Y_LO, SFNS_Y_HI,
                    x_record_index=1,
                    tick=SFNS_Y_TICK, grid=SFNS_Y_GRID,
                    color=CHAN_Y_COLOR,
                ),
            ),
        ),
    )
    return _emit(
        write_wwt_bytes(
            records, windows, title=title, comment=f"sfns-{variant}",
            source_filename=filename,
        ),
        path,
    )


def sfns_like_same_display_names(directory) -> tuple[Path, Path]:
    """Two WWTs with identical channel labels and distinct source identity."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    first = sfns_like_custom_x_native_viewport(
        directory / "sfns_src_a.wwt",
        variant="cycle",
        y_offset=0.0,
        source_filename="sfns_src_a.wwt",
        title="sfns-src-a",
    )
    second = sfns_like_custom_x_native_viewport(
        directory / "sfns_src_b.wwt",
        variant="cycle",
        y_offset=8.0,
        source_filename="sfns_src_b.wwt",
        title="sfns-src-b",
    )
    return first, second
