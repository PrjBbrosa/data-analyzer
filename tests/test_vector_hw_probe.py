import sys
import time
import types
from unittest.mock import MagicMock, patch

from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


class _FakeVectorInitializationError(Exception):
    """Cross-platform stand-in. python-can is Windows-only per
    requirements.txt, so non-Windows CI can't import the real class."""


def _fake_vector_pkg(
    *,
    channel_count: int = 0,
    dll_version_packed: int = 0,
    get_application_config=None,
    channel_configs_exc: Exception | None = None,
):
    """Build a fake ``can.interfaces.vector`` package + register it on
    ``sys.modules`` so the ``from can.interfaces.vector import VectorBus``
    inside ``vector_hw_probe`` resolves to the fake.

    Returns ``(vector_pkg, sys_modules_patch_dict)``.
    """

    impl = get_application_config or (lambda app, ch: (57, 0, 0))

    can_module = types.ModuleType("can")
    interfaces_module = types.ModuleType("can.interfaces")
    vector_module = types.ModuleType("can.interfaces.vector")
    exceptions_module = types.ModuleType("can.interfaces.vector.exceptions")

    class FakeVectorBus:
        get_application_config = staticmethod(impl)

    exceptions_module.VectorInitializationError = _FakeVectorInitializationError

    def get_channel_configs():
        if channel_configs_exc is not None:
            raise channel_configs_exc
        return [object()] * channel_count

    def _get_xl_driver_config():
        return types.SimpleNamespace(dllVersion=dll_version_packed)

    vector_module.VectorBus = FakeVectorBus
    vector_module.get_channel_configs = get_channel_configs
    vector_module.canlib = types.SimpleNamespace(
        _get_xl_driver_config=_get_xl_driver_config
    )
    vector_module.exceptions = exceptions_module
    interfaces_module.vector = vector_module
    can_module.interfaces = interfaces_module

    sys_modules = {
        "can": can_module,
        "can.interfaces": interfaces_module,
        "can.interfaces.vector": vector_module,
        "can.interfaces.vector.exceptions": exceptions_module,
    }
    return vector_module, sys_modules


def _ifdata():
    from can_logger.p0.ifdata_xcp import IfDataXcp, DaqProcessorInfo

    return IfDataXcp(
        cmd_id=0x500,
        resp_id=0x501,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=0,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(),
        daq_processor=DaqProcessorInfo(
            min_daq=0,
            max_event_channel=0,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )


def test_probe_returns_red_on_non_windows():
    from mf4_analyzer.acquisition_capture.health import level_hw
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    with patch.object(sys, "platform", "darwin"):
        result = vector_hw_probe(TransportConfig())

    assert result.ok is False
    assert "Windows" in (result.error or "")
    assert isinstance(result.channel_count, int)
    assert isinstance(result.last_probe_ts, float)
    assert level_hw(result) == "red"


def test_probe_returns_green_on_windows_when_app_known():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    calls = []

    def fake_get_app_cfg(app, ch):
        calls.append((app, ch))
        return (57, 0, 0)  # (hw_type=VN1630, hw_index=0, hw_channel=0)

    vector_pkg, sys_modules = _fake_vector_pkg(
        channel_count=4,
        dll_version_packed=(22 << 24),  # 22.0.0
        get_application_config=fake_get_app_cfg,
    )

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
        return_value=vector_pkg,
    ), patch.dict(sys.modules, sys_modules):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=0))

    assert calls == [("Python", 0)], (
        "vector_hw_probe must call VectorBus.get_application_config with both "
        "(app_name, channel) — the phantom canlib.get_application_config(app_name) "
        "one-arg call is the bug we're guarding against"
    )
    assert result.ok is True
    assert result.error is None
    assert result.channel_count == 4
    assert result.driver_version == "22.0.0"


def test_probe_reports_missing_app():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    def fake_get_app_cfg(app, ch):
        raise _FakeVectorInitializationError(
            f"Vector HW Config: Channel '{ch}' of application '{app}' is not "
            "assigned to any interface"
        )

    vector_pkg, sys_modules = _fake_vector_pkg(
        channel_count=4,
        dll_version_packed=(22 << 24),
        get_application_config=fake_get_app_cfg,
    )

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
        return_value=vector_pkg,
    ), patch.dict(sys.modules, sys_modules):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=0))

    assert result.ok is False
    assert "Python" in (result.error or "")
    assert "not mapped" in (result.error or "")
    # Channel count and driver version should still report — they're
    # gathered before the app-config check.
    assert result.channel_count == 4
    assert result.driver_version == "22.0.0"
    assert isinstance(result.last_probe_ts, float)


def test_probe_reports_channel_enumeration_failure():
    """If get_channel_configs throws, that's a different class of failure
    than 'app not mapped' — surface it distinctly."""

    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    vector_pkg, sys_modules = _fake_vector_pkg(
        channel_configs_exc=RuntimeError("driver in transient state"),
    )

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
        return_value=vector_pkg,
    ), patch.dict(sys.modules, sys_modules):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=0))

    assert result.ok is False
    assert "get_channel_configs failed" in (result.error or "")
    assert result.channel_count == 0
    assert result.driver_version is None


def test_probe_reports_channel_out_of_range():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    vector_pkg, sys_modules = _fake_vector_pkg(
        channel_count=2,
        dll_version_packed=(22 << 24),
        get_application_config=lambda app, ch: (57, 0, 0),
    )

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
        return_value=vector_pkg,
    ), patch.dict(sys.modules, sys_modules):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=5))

    assert result.ok is False
    assert "channel 5 not present" in (result.error or "")
    assert "count=2" in (result.error or "")


class _ProbeRuntime:
    def __init__(self, master):
        self.master = master
        self.closed = False

    def connect(self):
        return self.master.connect()

    def close(self):
        self.closed = True


class _ProbeMaster:
    def __init__(self, *, connect_error: Exception | None = None):
        self.connect_error = connect_error
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self.connect_error:
            raise self.connect_error
        return types.SimpleNamespace(resource=0x05)


def test_test_xcp_connection_uses_shared_runtime_and_closes_it(monkeypatch):
    from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    runtime = _ProbeRuntime(_ProbeMaster())
    monkeypatch.setattr(PyXcpRuntime, "open", lambda *_args: runtime)
    result = test_xcp_connection(TransportConfig(), _ifdata())

    assert result.ok is True
    assert result.resource_byte == 0x05
    assert result.latency_ms is not None
    assert runtime.master.connect_calls == 1
    assert runtime.closed is True


def test_test_xcp_connection_reports_connect_timeout_and_closes_runtime(monkeypatch):
    from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    runtime = _ProbeRuntime(_ProbeMaster(connect_error=TimeoutError("no response")))
    monkeypatch.setattr(PyXcpRuntime, "open", lambda *_args: runtime)
    result = test_xcp_connection(TransportConfig(), _ifdata())
    assert result.ok is False
    assert "0x500" in (result.error or "")
    assert runtime.closed is True


def test_test_xcp_connection_reports_runtime_construction_failure(monkeypatch):
    from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    def fail(*_args):
        raise RuntimeError("pyxcp import failed")

    monkeypatch.setattr(PyXcpRuntime, "open", fail)
    result = test_xcp_connection(TransportConfig(), _ifdata())
    assert result.ok is False
    assert "pyxcp" in (result.error or "").lower()


def test_test_xcp_connection_surfaces_seed_key_failure_and_closes_runtime(monkeypatch):
    from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime
    from mf4_analyzer.acquisition_capture.xcp_auth import XcpAuthError
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    runtime = _ProbeRuntime(_ProbeMaster())
    monkeypatch.setattr(PyXcpRuntime, "open", lambda *_args: runtime)
    monkeypatch.setattr(
        "mf4_analyzer.acquisition_capture.vector_hw_probe.unlock_resources_if_needed",
        lambda **_kwargs: (_ for _ in ()).throw(XcpAuthError("bad key")),
    )
    result = test_xcp_connection(TransportConfig(seed_and_key_dll="seedkey.dll"), _ifdata())
    assert result.ok is False
    assert "Seed&Key" in (result.error or "")
    assert runtime.closed is True


def test_default_health_aggregator_can_bind_transport_probe():
    from mf4_analyzer.acquisition_capture.health import HealthAggregator, HwHealth

    transport = TransportConfig(app_name="CANalyzer", channel=2)

    def probe(candidate: TransportConfig):
        assert candidate == transport
        return HwHealth(
            ok=True,
            driver_version="22.0",
            channel_count=4,
            last_probe_ts=time.monotonic(),
        )

    agg = HealthAggregator(transport=transport, hw_probe=probe)
    assert agg.poll_once().hw.ok is True
