"""Runtime DAQ list / ODT mapping for the Stage 8 XCP backend."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import IfDataXcp
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


@dataclass(frozen=True)
class OdtEntry:
    measurement_name: str
    offset: int
    size: int
    datatype: str
    address: int
    address_extension: int = 0
    scale_a: float = 1.0
    scale_b: float = 0.0


@dataclass(frozen=True)
class DaqMap:
    pid_to_odt: Mapping[int, tuple[int, int]]
    entries: Mapping[tuple[int, int], tuple[OdtEntry, ...]]
    event_for_daq: Mapping[int, int]


_DATATYPE_SIZE = {
    "UBYTE": 1,
    "SBYTE": 1,
    "UWORD": 2,
    "SWORD": 2,
    "ULONG": 4,
    "SLONG": 4,
    "A_UINT64": 8,
    "A_INT64": 8,
    "FLOAT32_IEEE": 4,
    "FLOAT64_IEEE": 8,
    "u8": 1,
    "s8": 1,
    "u16": 2,
    "s16": 2,
    "u32": 4,
    "s32": 4,
    "f32": 4,
    "u64": 8,
    "s64": 8,
    "f64": 8,
}


def _size_from_datatype(datatype: str, payload_bytes_fallback: int) -> int:
    return _DATATYPE_SIZE.get(datatype, payload_bytes_fallback)


def build_daq_map(
    selected: Sequence[SelectedMeasurement],
    ifdata: IfDataXcp,
    measurements: Mapping[str, MeasurementSummary],
) -> DaqMap:
    """Group selected measurements by DAQ event and pack entries into ODTs."""

    overhead = 1 + ifdata.daq_timestamp_size
    payload_budget = ifdata.max_dto - overhead
    if payload_budget <= 0:
        raise ValueError(
            f"MAX_DTO={ifdata.max_dto} too small for PID + timestamp "
            f"({overhead} bytes overhead)"
        )

    by_event: dict[str, list[SelectedMeasurement]] = {}
    for sel in selected:
        if sel.name not in measurements:
            raise ValueError(
                f"measurement {sel.name!r} not in A2L summary; cannot build DAQ map"
            )
        if not sel.event:
            raise ValueError(
                f"measurement {sel.name!r} has no event assigned; "
                "A2L per-MEASUREMENT IF_DATA likely missing"
            )
        by_event.setdefault(sel.event, []).append(sel)

    event_number_by_name = {event.name: event.number for event in ifdata.available_events}
    # PID values are assigned by the ECU only after SELECT.  Keep the packing
    # map intentionally unbound here; decoding is impossible until
    # ``bind_first_pids`` receives each real response.
    pid_to_odt: dict[int, tuple[int, int]] = {}
    entries: dict[tuple[int, int], tuple[OdtEntry, ...]] = {}
    event_for_daq: dict[int, int] = {}

    for daq_list, (event_name, event_selected) in enumerate(by_event.items()):
        if event_name not in event_number_by_name:
            raise ValueError(f"selected event {event_name!r} not in A2L IF_DATA")
        event_for_daq[daq_list] = event_number_by_name[event_name]

        odt_index = 0
        offset = overhead
        current: list[OdtEntry] = []

        def flush() -> None:
            nonlocal current, odt_index, offset
            if not current:
                return
            entries[(daq_list, odt_index)] = tuple(current)
            odt_index += 1
            offset = overhead
            current = []

        for sel in event_selected:
            measurement = measurements[sel.name]
            if not measurement.conversion_supported:
                raise ValueError(
                    f"unsupported conversion {measurement.conversion!r} for "
                    f"measurement {sel.name!r}; cannot decode physical values"
                )
            datatype = measurement.datatype or ""
            size = _size_from_datatype(datatype, sel.payload_bytes)
            if size > payload_budget:
                raise ValueError(
                    f"measurement {sel.name!r} size {size} exceeds ODT payload "
                    f"budget {payload_budget}"
                )
            if current and offset + size - overhead > payload_budget:
                flush()
            address = int(sel.address_hex, 16) if sel.address_hex else measurement.address
            address_extension = int(measurement.address_extension)
            if not 0 <= address_extension <= 0xFF:
                raise ValueError(
                    f"measurement {sel.name!r} address extension out of byte "
                    f"range: {address_extension}"
                )
            scale_a = float(measurement.scale_a)
            scale_b = float(measurement.scale_b)
            if not (math.isfinite(scale_a) and math.isfinite(scale_b)):
                raise ValueError(
                    f"measurement {sel.name!r} has non-finite linear conversion"
                )
            current.append(
                OdtEntry(
                    measurement_name=sel.name,
                    offset=offset,
                    size=size,
                    datatype=datatype,
                    address=address,
                    address_extension=address_extension,
                    scale_a=scale_a,
                    scale_b=scale_b,
                )
            )
            offset += size
        flush()

    return DaqMap(
        pid_to_odt=pid_to_odt,
        entries=entries,
        event_for_daq=event_for_daq,
    )


def bind_first_pids(layout: DaqMap, first_pid_by_daq: Mapping[int, int]) -> DaqMap:
    """Bind ECU-returned ``firstPid`` values to the pre-programmed ODT layout."""

    pid_to_odt: dict[int, tuple[int, int]] = {}
    for daq_list in sorted(layout.event_for_daq):
        if daq_list not in first_pid_by_daq:
            raise ValueError(f"DAQ list {daq_list} has no ECU firstPid response")
        first_pid = int(first_pid_by_daq[daq_list])
        if not 0 <= first_pid <= 0xFB:
            raise ValueError(f"DAQ list {daq_list} firstPid out of DTO range: {first_pid}")
        odts = sorted(odt for daq, odt in layout.entries if daq == daq_list)
        for offset, odt in enumerate(odts):
            pid = first_pid + offset
            if pid > 0xFB:
                raise ValueError(f"DAQ list {daq_list} PID range exceeds DTO range")
            if pid in pid_to_odt:
                raise ValueError(f"overlapping ECU PID assignment: {pid}")
            pid_to_odt[pid] = (daq_list, odt)
    return DaqMap(
        pid_to_odt=pid_to_odt,
        entries=layout.entries,
        event_for_daq=layout.event_for_daq,
    )
