"""Structured view of an A2L IF_DATA XCP transport block.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md
section 4.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
from collections.abc import Mapping
from typing import Literal


@dataclass(frozen=True)
class DaqProcessorInfo:
    min_daq: int
    max_event_channel: int
    granularity_odt_entry_size_daq: int
    overload_indication: str


@dataclass(frozen=True)
class DaqEventInfo:
    number: int
    name: str
    cycle_time_ms: float
    max_odt_entries: int
    properties: tuple[str, ...]


@dataclass(frozen=True)
class IfDataXcp:
    cmd_id: int
    resp_id: int
    cmd_id_extended: bool
    resp_id_extended: bool
    can_fd: bool
    max_cto: int
    max_dto: int
    byte_order: Literal["MSB_FIRST", "MSB_LAST"]
    address_granularity: Literal["BYTE", "WORD", "DWORD"]
    daq_timestamp_size: int
    daq_timestamp_unit: str
    daq_timestamp_fixed: bool
    available_events: tuple[DaqEventInfo, ...]
    daq_processor: DaqProcessorInfo


_IFDATA_RE = re.compile(
    r"/begin\s+IF_DATA\s+XCP\b(.*?)/end\s+IF_DATA",
    re.DOTALL,
)
_NAMED_BLOCK_RE = re.compile(
    r"/begin\s+{name}\b(.*?)/end\s+{name}",
    re.DOTALL,
)
_MEASUREMENT_RE = re.compile(
    r"/begin\s+MEASUREMENT\b(?P<header>[^\r\n]*)(?P<body>.*?)/end\s+MEASUREMENT",
    re.DOTALL,
)
_EVENT_REF_RE = re.compile(r"\bEVENT\s+([+-]?(?:0[xX][0-9a-fA-F]+|\d+))\b")

_BYTE_ORDER_TOKENS = {
    "BYTE_ORDER_MSB_LAST": "MSB_LAST",
    "BYTE_ORDER_MSB_FIRST": "MSB_FIRST",
}
_GRANULARITY_TOKENS = {
    "ADDRESS_GRANULARITY_BYTE": "BYTE",
    "ADDRESS_GRANULARITY_WORD": "WORD",
    "ADDRESS_GRANULARITY_DWORD": "DWORD",
}
_TIME_SIZE_TOKENS = {
    "NO_TIME_STAMP": 0,
    "SIZE_BYTE": 1,
    "SIZE_WORD": 2,
    "SIZE_DWORD": 4,
}
_TIME_UNIT_TOKENS = {
    "UNIT_1NS": "1NS",
    "UNIT_10NS": "10NS",
    "UNIT_100NS": "100NS",
    "UNIT_1US": "1US",
    "UNIT_10US": "10US",
    "UNIT_100US": "100US",
    "UNIT_1MS": "1MS",
}
_FIXED_TIMESTAMP_TOKENS = {
    "TIMESTAMP_FIXED",
    "DAQ_TIMESTAMP_FIXED",
    "DAQ_TIMESTAMP_FIXED_LENGTH",
}
_GRANULARITY_ODT_TOKENS = {
    "GRANULARITY_ODT_ENTRY_SIZE_DAQ_BYTE": 1,
    "GRANULARITY_ODT_ENTRY_SIZE_DAQ_WORD": 2,
    "GRANULARITY_ODT_ENTRY_SIZE_DAQ_DWORD": 4,
}
_CMD_ID_TOKENS = {"CAN_ID_MASTER", "CAN_ID_CMD", "CAN_ID_COMMAND"}
_RESP_ID_TOKENS = {"CAN_ID_SLAVE", "CAN_ID_RES", "CAN_ID_RESPONSE"}

# A2L EVENT time-cycle unit is an exponent over 1 ns: 0=1 ns, 6=1 ms, 9=1 s.
_TIME_CYCLE_EXPONENT_TO_MS = {
    0: 1e-6,
    1: 1e-5,
    2: 1e-4,
    3: 1e-3,
    4: 1e-2,
    5: 1e-1,
    6: 1.0,
    7: 10.0,
    8: 100.0,
    9: 1000.0,
}


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)


def _tokens(block: str) -> list[str]:
    lexer = shlex.shlex(_strip_comments(block), posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _find_block(block: str, name: str) -> str | None:
    pattern = re.compile(_NAMED_BLOCK_RE.pattern.format(name=re.escape(name)), re.DOTALL)
    match = pattern.search(block)
    return match.group(1) if match else None


def _find_blocks(block: str, name: str) -> list[str]:
    pattern = re.compile(_NAMED_BLOCK_RE.pattern.format(name=re.escape(name)), re.DOTALL)
    return [match.group(1) for match in pattern.finditer(block)]


def _event_cycle_ms(cycle: int, unit_exp: int) -> float:
    if cycle <= 0:
        return 0.0
    return cycle * _TIME_CYCLE_EXPONENT_TO_MS.get(unit_exp, 1.0)


def _parse_event(event_block: str) -> DaqEventInfo:
    toks = _tokens(event_block)
    if len(toks) < 7:
        raise ValueError("IF_DATA XCP EVENT block is incomplete")

    return DaqEventInfo(
        number=int(toks[2], 0),
        name=toks[0],
        cycle_time_ms=_event_cycle_ms(int(toks[5], 0), int(toks[6], 0)),
        max_odt_entries=int(toks[4], 0),
        properties=(toks[3],),
    )


def _parse_protocol_layer(block: str) -> tuple[int, int, str, str]:
    toks = _tokens(block)
    max_cto = int(toks[8], 0) if len(toks) > 8 else 8
    max_dto = int(toks[9], 0) if len(toks) > 9 else 8
    byte_order = "MSB_LAST"
    address_granularity = "BYTE"

    for tok in toks:
        if tok in _BYTE_ORDER_TOKENS:
            byte_order = _BYTE_ORDER_TOKENS[tok]
        elif tok in _GRANULARITY_TOKENS:
            address_granularity = _GRANULARITY_TOKENS[tok]

    return max_cto, max_dto, byte_order, address_granularity


def _parse_daq_processor(daq_block: str) -> DaqProcessorInfo:
    toks = _tokens(daq_block)
    min_daq = 0
    max_event_channel = 0
    granularity_odt = 1
    overload = "NONE"

    if len(toks) >= 4:
        try:
            max_event_channel = int(toks[2], 0)
            min_daq = int(toks[3], 0)
        except ValueError:
            pass

    for tok in toks:
        if tok in _GRANULARITY_ODT_TOKENS:
            granularity_odt = _GRANULARITY_ODT_TOKENS[tok]
        elif tok.startswith("OVERLOAD_INDICATION_"):
            overload = tok.removeprefix("OVERLOAD_INDICATION_")

    return DaqProcessorInfo(
        min_daq=min_daq,
        max_event_channel=max_event_channel,
        granularity_odt_entry_size_daq=granularity_odt,
        overload_indication=overload,
    )


def _parse_timestamp(daq_block: str) -> tuple[int, str, bool]:
    timestamp_block = _find_block(daq_block, "TIMESTAMP_SUPPORTED") or ""
    ts_size = 0
    ts_unit = "1US"
    ts_fixed = False

    for tok in _tokens(timestamp_block):
        if tok in _TIME_SIZE_TOKENS:
            ts_size = _TIME_SIZE_TOKENS[tok]
        elif tok in _TIME_UNIT_TOKENS:
            ts_unit = _TIME_UNIT_TOKENS[tok]
        elif tok in _FIXED_TIMESTAMP_TOKENS:
            ts_fixed = True

    return ts_size, ts_unit, ts_fixed


def _parse_transport(block: str) -> tuple[int, int, bool, bool, bool]:
    can_fd = _find_block(block, "XCP_ON_CAN_FD") is not None
    transport = (
        _find_block(block, "XCP_ON_CAN_FD")
        or _find_block(block, "XCP_ON_CAN")
        or ""
    )
    toks = _tokens(transport)
    cmd_id = 0
    resp_id = 0

    index = 0
    while index < len(toks):
        tok = toks[index]
        if tok in _CMD_ID_TOKENS and index + 1 < len(toks):
            cmd_id = int(toks[index + 1], 0)
            index += 2
            continue
        if tok in _RESP_ID_TOKENS and index + 1 < len(toks):
            resp_id = int(toks[index + 1], 0)
            index += 2
            continue
        index += 1

    return cmd_id, resp_id, cmd_id > 0x7FF, resp_id > 0x7FF, can_fd


def _parse_one_block(block: str) -> IfDataXcp:
    max_cto, max_dto, byte_order, address_granularity = _parse_protocol_layer(
        _find_block(block, "PROTOCOL_LAYER") or ""
    )
    daq_block = _find_block(block, "DAQ") or ""
    ts_size, ts_unit, ts_fixed = _parse_timestamp(daq_block)
    cmd_id, resp_id, cmd_ext, resp_ext, can_fd = _parse_transport(block)

    return IfDataXcp(
        cmd_id=cmd_id,
        resp_id=resp_id,
        cmd_id_extended=cmd_ext,
        resp_id_extended=resp_ext,
        can_fd=can_fd,
        max_cto=max_cto,
        max_dto=max_dto,
        byte_order=byte_order,  # type: ignore[arg-type]
        address_granularity=address_granularity,  # type: ignore[arg-type]
        daq_timestamp_size=ts_size,
        daq_timestamp_unit=ts_unit,
        daq_timestamp_fixed=ts_fixed,
        available_events=tuple(
            _parse_event(event) for event in _find_blocks(daq_block, "EVENT")
        ),
        daq_processor=_parse_daq_processor(daq_block),
    )


def _measurement_name(header: str) -> str | None:
    toks = _tokens(header)
    return toks[0] if toks else None


def _event_name_by_number(a2l_text: str) -> dict[int, str]:
    event_names: dict[int, str] = {}
    for block in parse_ifdata_xcp_text(a2l_text):
        for event in block.available_events:
            event_names.setdefault(event.number, event.name)
    return event_names


def _event_refs_in_measurement(measurement_body: str) -> list[int]:
    refs: list[int] = []
    for ifdata_match in _IFDATA_RE.finditer(measurement_body):
        ifdata_block = ifdata_match.group(1)
        toks = set(_tokens(ifdata_block))
        if "DAQ_EVENT" not in toks:
            continue
        if not {"FIXED_EVENT_LIST", "AVAILABLE_EVENT_LIST"} & toks:
            continue
        for event_match in _EVENT_REF_RE.finditer(_strip_comments(ifdata_block)):
            refs.append(int(event_match.group(1), 0))
    return refs


def parse_measurement_events(a2l_text: str) -> Mapping[str, tuple[str, ...]]:
    """Map MEASUREMENT names to compatible IF_DATA XCP DAQ event names."""

    event_names = _event_name_by_number(a2l_text)
    if not event_names:
        return {}

    measurement_events: dict[str, tuple[str, ...]] = {}
    for match in _MEASUREMENT_RE.finditer(a2l_text):
        measurement_name = _measurement_name(match.group("header"))
        if not measurement_name:
            continue
        names = tuple(
            event_names[event_number]
            for event_number in _event_refs_in_measurement(match.group("body"))
            if event_number in event_names
        )
        if names:
            measurement_events[measurement_name] = names
    return measurement_events


def parse_ifdata_xcp_text(a2l_text: str) -> list[IfDataXcp]:
    """Parse every transport-carrying ``/begin IF_DATA XCP`` block.

    CANape and similar tools emit additional ``IF_DATA XCP`` fragments
    next to the real transport block — typically SEGMENT/CHECKSUM-only
    blocks that describe calibration pages. They share the
    ``/begin IF_DATA XCP`` opener but contain no ``XCP_ON_CAN`` /
    ``XCP_ON_CAN_FD`` transport block and no DAQ events. We filter them
    out so callers like ``A2LSummary`` and ``MainWindow._cached_ifdata``
    receive only the active transport block(s).
    """

    parsed = [
        _parse_one_block(match.group(1)) for match in _IFDATA_RE.finditer(a2l_text)
    ]
    return [
        block
        for block in parsed
        if block.cmd_id or block.resp_id or block.available_events
    ]


def parse_ifdata_xcp_file(path: str | Path) -> list[IfDataXcp]:
    """Parse every ``/begin IF_DATA XCP`` block in an A2L file."""

    return parse_ifdata_xcp_text(
        Path(path).read_text(encoding="latin-1", errors="replace")
    )


def parse_ifdata_xcp(a2l_text: str) -> list[IfDataXcp]:
    """Backward-compatible alias for the Stage 8 plan's draft name."""

    return parse_ifdata_xcp_text(a2l_text)
