"""Structured, hardware-free tests for the pinned pyxcp runtime adapter."""

from __future__ import annotations

from types import SimpleNamespace

from can_logger.p0.ifdata_xcp import DaqProcessorInfo, IfDataXcp
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


def _ifdata(*, extended: bool = False) -> IfDataXcp:
    return IfDataXcp(
        cmd_id=0x18DAF110 if extended else 0x6C7,
        resp_id=0x18DA10F1 if extended else 0x6C6,
        cmd_id_extended=extended,
        resp_id_extended=extended,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=0,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(),
        daq_processor=DaqProcessorInfo(0, 0, 1, "EVENT"),
    )


class _StructuredPolicy:
    def __init__(self) -> None:
        self.xcp_master = None
        self.finalized = False

    def feed(self, category, counter, timestamp, payload) -> None:
        return

    def finalize(self) -> None:
        self.finalized = True


def test_runtime_maps_vector_and_a2l_facts_without_caller_owned_bus(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture import pyxcp_runtime

    created = {}

    def factory(config):
        created["input"] = config
        return SimpleNamespace(
            general=SimpleNamespace(seed_n_key_dll=None),
            transport=SimpleNamespace(
                layer=None,
                timeout=None,
                can=SimpleNamespace(
                    interface=None,
                    channel=None,
                    bitrate=None,
                    fd=None,
                    data_bitrate=None,
                    can_id_master=None,
                    can_id_slave=None,
                    vector=SimpleNamespace(app_name=None),
                ),
            ),
        )

    class Master:
        def __init__(self, transport_name, config, policy):
            self.transport_name = transport_name
            self.config = config
            self.policy = policy
            self.transport = SimpleNamespace(close_calls=0, close=self._close)
            self.disconnect_calls = 0

        def _close(self) -> None:
            self.transport.close_calls += 1

        def connect(self):
            return SimpleNamespace(resource=0)

        def disconnect(self) -> None:
            self.disconnect_calls += 1

    monkeypatch.setattr(
        pyxcp_runtime,
        "_load_pyxcp_surface",
        lambda: pyxcp_runtime._PyXcpSurface(Master=Master, create_application_from_config=factory),
    )
    policy = _StructuredPolicy()
    runtime = pyxcp_runtime.PyXcpRuntime.open(TransportConfig(app_name="Python", channel=2), _ifdata(), policy)

    assert runtime.master.transport_name == "can"
    assert runtime.application.transport.layer == "CAN"
    assert runtime.application.transport.can.interface == "vector"
    assert runtime.application.transport.can.vector.app_name == "Python"
    assert runtime.application.transport.can.channel == "2"
    assert runtime.application.transport.can.can_id_master == 0x6C7
    assert runtime.application.transport.can.can_id_slave == 0x6C6
    assert "bus" not in created["input"]

    runtime.connect()
    runtime.close()
    assert runtime.master.disconnect_calls == 1
    assert runtime.master.transport.close_calls == 1
    assert policy.finalized is True


def test_runtime_encodes_extended_a2l_ids(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture import pyxcp_runtime

    app = SimpleNamespace(
        general=SimpleNamespace(seed_n_key_dll=None),
        transport=SimpleNamespace(
            layer=None,
            timeout=None,
            can=SimpleNamespace(
                interface=None,
                channel=None,
                bitrate=None,
                fd=None,
                data_bitrate=None,
                can_id_master=None,
                can_id_slave=None,
                vector=SimpleNamespace(app_name=None),
            ),
        ),
    )
    monkeypatch.setattr(pyxcp_runtime, "_load_pyxcp_surface", lambda: None)
    pyxcp_runtime._build_application(lambda _config: app, TransportConfig(), _ifdata(extended=True))
    assert app.transport.can.can_id_master == 0x98DAF110
    assert app.transport.can.can_id_slave == 0x98DA10F1
