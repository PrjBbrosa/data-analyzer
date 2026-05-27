"""Tests for IF_DATA XCP parser and dataclasses."""

from pathlib import Path

import pytest

from can_logger.p0.ifdata_xcp import (
    DaqEventInfo,
    DaqProcessorInfo,
    IfDataXcp,
    parse_measurement_events,
    parse_ifdata_xcp_file,
    parse_ifdata_xcp_text,
)


FIXTURES = Path(__file__).parent / "fixtures" / "ifdata_xcp"


def test_dataclasses_are_frozen():
    info = DaqEventInfo(
        number=0,
        name="10ms",
        cycle_time_ms=10.0,
        max_odt_entries=8,
        properties=("DAQ",),
    )

    with pytest.raises(Exception, match="frozen|cannot assign"):
        info.number = 1  # type: ignore[misc]


def test_if_data_xcp_carries_all_required_fields():
    proc = DaqProcessorInfo(
        min_daq=0,
        max_event_channel=8,
        granularity_odt_entry_size_daq=1,
        overload_indication="EVENT",
    )
    ifd = IfDataXcp(
        cmd_id=0x500,
        resp_id=0x501,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=2,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(),
        daq_processor=proc,
    )

    assert ifd.cmd_id == 0x500
    assert ifd.daq_processor.min_daq == 0


def test_parse_classic_can_single_event():
    blocks = parse_ifdata_xcp_file(FIXTURES / "classic_can.a2l_snippet")

    assert len(blocks) == 1
    ifd = blocks[0]
    assert ifd.cmd_id == 0x500
    assert ifd.resp_id == 0x501
    assert ifd.cmd_id_extended is False
    assert ifd.resp_id_extended is False
    assert ifd.can_fd is False
    assert ifd.max_cto == 8
    assert ifd.max_dto == 8
    assert ifd.byte_order == "MSB_LAST"
    assert ifd.address_granularity == "BYTE"
    assert ifd.daq_timestamp_size == 2
    assert ifd.daq_timestamp_unit == "1US"
    assert ifd.daq_timestamp_fixed is True
    assert ifd.daq_processor == DaqProcessorInfo(
        min_daq=0,
        max_event_channel=1,
        granularity_odt_entry_size_daq=1,
        overload_indication="EVENT",
    )
    assert ifd.available_events == (
        DaqEventInfo(
            number=0,
            name="10ms",
            cycle_time_ms=10.0,
            max_odt_entries=8,
            properties=("DAQ",),
        ),
    )


def test_parse_file_accepts_latin1_a2l_comments(tmp_path: Path):
    path = tmp_path / "latin1.a2l"
    path.write_bytes(
        b"/* supplier note: caf\xe9 */\n"
        + (FIXTURES / "classic_can.a2l_snippet").read_bytes()
    )

    blocks = parse_ifdata_xcp_file(path)

    assert len(blocks) == 1
    assert blocks[0].cmd_id == 0x500
    assert blocks[0].available_events[0].name == "10ms"


def test_parse_can_fd_extended_ids():
    text = (FIXTURES / "can_fd.a2l_snippet").read_text()
    ifd = parse_ifdata_xcp_text(text)[0]

    assert ifd.can_fd is True
    assert ifd.max_cto == 64
    assert ifd.max_dto == 64
    assert ifd.cmd_id == 0x18FF0500
    assert ifd.cmd_id_extended is True
    assert ifd.resp_id == 0x18FF0501
    assert ifd.resp_id_extended is True
    assert ifd.daq_timestamp_size == 4
    assert ifd.daq_timestamp_unit == "1NS"


def test_parse_multi_event():
    text = (FIXTURES / "multi_event.a2l_snippet").read_text()
    ifd = parse_ifdata_xcp_text(text)[0]

    assert len(ifd.available_events) == 3
    assert [event.name for event in ifd.available_events] == [
        "10ms",
        "100ms",
        "1s",
    ]
    assert [event.cycle_time_ms for event in ifd.available_events] == [
        10.0,
        100.0,
        1000.0,
    ]


def test_parse_no_timestamp_big_endian():
    text = (FIXTURES / "no_timestamp.a2l_snippet").read_text()
    ifd = parse_ifdata_xcp_text(text)[0]

    assert ifd.daq_timestamp_size == 0
    assert ifd.byte_order == "MSB_FIRST"
    assert ifd.daq_processor.overload_indication == "NONE"
    assert ifd.available_events[0].cycle_time_ms == 1.0


def test_parse_vector_dialect_aliases():
    text = (FIXTURES / "vector_dialect.a2l_snippet").read_text()
    ifd = parse_ifdata_xcp_text(text)[0]

    assert ifd.daq_timestamp_fixed is True
    assert ifd.cmd_id == 0x650
    assert ifd.resp_id == 0x651
    assert ifd.available_events[0].name == "5ms"


def test_parse_measurement_events_handles_quoted_and_unquoted_names():
    text = (FIXTURES / "measurement_events.a2l_snippet").read_text()
    events = parse_measurement_events(text)

    assert events["EngineSpeed"] == ("10ms",)
    assert events["Quoted Load"] == ("100ms",)


def test_parse_measurement_events_handles_multiple_events():
    text = (FIXTURES / "measurement_events.a2l_snippet").read_text()

    assert parse_measurement_events(text)["WheelSpeed"] == ("10ms", "1s")


def test_parse_measurement_events_returns_empty_without_per_measurement_ifdata():
    text = (FIXTURES / "classic_can.a2l_snippet").read_text()

    assert parse_measurement_events(text) == {}


def test_parses_real_canape14_xcp_block():
    text = (FIXTURES / "canape14_real_aside.a2l_snippet").read_text(encoding="latin-1")
    blocks = parse_ifdata_xcp_text(text)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.cmd_id == 0x6C7
    assert block.resp_id == 0x6C6
    assert block.cmd_id_extended is False
    assert block.resp_id_extended is False
    assert block.can_fd is False
    assert (block.max_cto, block.max_dto) == (8, 8)
    assert block.byte_order == "MSB_LAST"
    assert block.address_granularity == "BYTE"
    assert block.daq_timestamp_size == 0
    assert {event.name for event in block.available_events} == {
        "Rte_Appl_OS_Task_100ms",
        "Rte_OsTask_BSW_10ms",
        "Rte_OsTask_BSW_1ms",
        "Rte_OsTask_BSW_5ms",
        "BSW_2ms",
    }


def test_parser_filters_segment_only_canape_companion_block():
    transport = (FIXTURES / "canape14_real_aside.a2l_snippet").read_text(encoding="latin-1")
    segment_only = (
        FIXTURES / "canape14_real_aside_segment_only.a2l_snippet"
    ).read_text(encoding="latin-1")

    blocks_in_natural_order = parse_ifdata_xcp_text(transport + "\n" + segment_only)
    blocks_in_inverted_order = parse_ifdata_xcp_text(segment_only + "\n" + transport)

    # the SEGMENT-only fragment has no CAN IDs / no events and must be dropped
    # regardless of source order, so neither position survives as ``blocks[0]``.
    assert len(blocks_in_natural_order) == 1
    assert len(blocks_in_inverted_order) == 1
    assert blocks_in_natural_order[0].cmd_id == 0x6C7
    assert blocks_in_inverted_order[0].cmd_id == 0x6C7
