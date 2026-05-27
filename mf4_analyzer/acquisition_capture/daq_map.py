"""Runtime DAQ list / ODT mapping for the Stage 8 XCP backend."""

from __future__ import annotations

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
    pid_to_odt: dict[int, tuple[int, int]] = {}
    entries: dict[tuple[int, int], tuple[OdtEntry, ...]] = {}
    event_for_daq: dict[int, int] = {}
    next_pid = 0

    for daq_list, (event_name, event_selected) in enumerate(by_event.items()):
        if event_name not in event_number_by_name:
            raise ValueError(f"selected event {event_name!r} not in A2L IF_DATA")
        event_for_daq[daq_list] = event_number_by_name[event_name]

        odt_index = 0
        offset = overhead
        current: list[OdtEntry] = []

        def flush() -> None:
            nonlocal current, odt_index, offset, next_pid
            if not current:
                return
            entries[(daq_list, odt_index)] = tuple(current)
            pid_to_odt[next_pid] = (daq_list, odt_index)
            next_pid += 1
            odt_index += 1
            offset = overhead
            current = []

        for sel in event_selected:
            measurement = measurements[sel.name]
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
            current.append(
                OdtEntry(
                    measurement_name=sel.name,
                    offset=offset,
                    size=size,
                    datatype=datatype,
                    address=address,
                )
            )
            offset += size
        flush()

    return DaqMap(
        pid_to_odt=pid_to_odt,
        entries=entries,
        event_for_daq=event_for_daq,
    )
