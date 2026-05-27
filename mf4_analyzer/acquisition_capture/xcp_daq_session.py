"""XCP master orchestration for the Stage 8 Vector backend."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import IfDataXcp
from mf4_analyzer.acquisition_capture.daq_map import DaqMap, build_daq_map
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.xcp_auth import unlock_resources_if_needed


class XcpConnectError(RuntimeError):
    """Raised when XCP CONNECT fails."""


class DaqAllocError(RuntimeError):
    """Raised when DAQ list allocation/programming fails."""


_TS_UNIT_TO_NS = {
    "1NS": 1,
    "10NS": 10,
    "100NS": 100,
    "1US": 1_000,
    "10US": 10_000,
    "100US": 100_000,
    "1MS": 1_000_000,
}


class XcpDaqSession:
    def __init__(
        self,
        *,
        master: Any,
        ifdata: IfDataXcp,
        measurements: Mapping[str, MeasurementSummary],
        seed_and_key_dll: str | None = None,
    ) -> None:
        self._master = master
        self._ifdata = ifdata
        self._measurements = measurements
        self._daq_map: DaqMap | None = None
        self._started = False
        self._seed_and_key_dll = seed_and_key_dll

    @property
    def daq_map(self) -> DaqMap | None:
        return self._daq_map

    @property
    def timestamp_unit_ns(self) -> int:
        return _TS_UNIT_TO_NS.get(self._ifdata.daq_timestamp_unit, 1_000)

    def is_running(self) -> bool:
        return self._started

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        try:
            connect_response = self._master.connect()
        except Exception as exc:
            raise XcpConnectError(f"XCP CONNECT failed: {exc}") from exc

        unlock_resources_if_needed(
            master=self._master,
            connect_response=connect_response,
            seed_and_key_dll=self._seed_and_key_dll,
        )
        self._check_daq_processor_info()
        self._daq_map = build_daq_map(selected, self._ifdata, self._measurements)

        try:
            daq_lists = sorted({daq for daq, _odt in self._daq_map.entries})
            for daq_list in daq_lists:
                odts = sorted(
                    odt for daq, odt in self._daq_map.entries if daq == daq_list
                )
                self._master.allocDaq(daq_list)
                self._master.allocOdt(daq_list, len(odts))
                for odt in odts:
                    entries = self._daq_map.entries[(daq_list, odt)]
                    self._master.allocOdtEntry(daq_list, odt, len(entries))
                    for entry_index, entry in enumerate(entries):
                        self._master.setDaqPtr(daq_list, odt, entry_index)
                        self._master.writeDaq(0xFF, entry.size, 0, entry.address)
                self._master.setDaqListMode(
                    mode=0x10,
                    daq=daq_list,
                    event=self._daq_map.event_for_daq[daq_list],
                    prescaler=1,
                    priority=0,
                )
        except Exception as exc:
            raise DaqAllocError(f"DAQ allocation failed: {exc}") from exc

        self._master.startStopSynch(0x01)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self._master.startStopSynch(0x00)
        finally:
            self._master.disconnect()
            self._started = False

    def _check_daq_processor_info(self) -> None:
        # Spec §5.2 step 5: cross-check ECU DAQ capability against the A2L
        # IF_DATA before allocating, so a too-small ECU surfaces here with a
        # clear message instead of a cryptic allocDaq() rejection later.
        try:
            info = self._master.getDaqProcessorInfo()
        except Exception as exc:
            raise DaqAllocError(f"getDaqProcessorInfo failed: {exc}") from exc

        declared = self._ifdata.daq_processor
        ecu_max_daq = (
            getattr(info, "maxDaq", None)
            or getattr(info, "max_daq", None)
            or getattr(info, "min_daq", None)
        )
        # ``isinstance(int)`` guard: pyxcp's response struct differs by
        # version, so unknown attribute shapes (e.g. MagicMock in tests
        # or a future namedtuple field rename) skip the check rather
        # than false-positive.
        if isinstance(ecu_max_daq, int) and ecu_max_daq < declared.min_daq:
            raise DaqAllocError(
                f"ECU reports max_daq={ecu_max_daq} but A2L IF_DATA declares "
                f"min_daq={declared.min_daq}"
            )
