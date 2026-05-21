"""T3-3 regression: vector_probe layered exit codes.

The action board's failure-triage row references these exit codes by
number, so they must stay stable. Each test fixes one stage's
behavior via patching and asserts the resolved code.

Real-hardware verification lives in the PR-4 bench runbook.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from can_logger.p0 import vector_probe


def _fake_vector_module(*, xldriver):
    can_module = types.ModuleType("can")
    interfaces_module = types.ModuleType("can.interfaces")
    vector_module = types.ModuleType("can.interfaces.vector")
    vector_module.canlib = types.SimpleNamespace(xldriver=xldriver)
    interfaces_module.vector = vector_module
    can_module.interfaces = interfaces_module
    return {
        "can": can_module,
        "can.interfaces": interfaces_module,
        "can.interfaces.vector": vector_module,
    }


class _FakeVectorInitializationError(Exception):
    """Stand-in for ``can.interfaces.vector.exceptions.VectorInitializationError``.

    Cross-platform: python-can is a Windows-only dependency in
    requirements.txt, so non-Windows CI cannot import the real class.
    """


def _fake_vector_with_bus(get_application_config):
    """Inject a fake ``can.interfaces.vector`` package exposing
    ``VectorBus.get_application_config`` — the real API surface
    ``_stage_app`` depends on.
    """

    impl = get_application_config  # capture before class body shadows the name

    can_module = types.ModuleType("can")
    interfaces_module = types.ModuleType("can.interfaces")
    vector_module = types.ModuleType("can.interfaces.vector")
    exceptions_module = types.ModuleType("can.interfaces.vector.exceptions")

    class FakeVectorBus:
        get_application_config = staticmethod(impl)

    exceptions_module.VectorInitializationError = _FakeVectorInitializationError
    vector_module.VectorBus = FakeVectorBus
    vector_module.exceptions = exceptions_module
    interfaces_module.vector = vector_module
    can_module.interfaces = interfaces_module
    return {
        "can": can_module,
        "can.interfaces": interfaces_module,
        "can.interfaces.vector": vector_module,
        "can.interfaces.vector.exceptions": exceptions_module,
    }


def test_non_windows_returns_exit_10(capsys):
    with patch.object(sys, "platform", "darwin"):
        rc = vector_probe.main(["--channel", "0", "--app-name", "Python"])
    captured = capsys.readouterr()
    assert rc == vector_probe.EXIT_NOT_WINDOWS
    assert "windows=false" in captured.err
    assert "darwin" in captured.err


def test_driver_failure_returns_exit_1(monkeypatch, capsys):
    def boom_driver() -> vector_probe.StageResult:
        return vector_probe.StageResult(
            label="[stage1/driver]",
            ok=False,
            detail="loadable=false",
            error="vxlapi DLL not loadable: DLL load failed",
        )

    monkeypatch.setattr(vector_probe, "_stage_driver", boom_driver)
    monkeypatch.setattr(
        vector_probe,
        "_stage_app",
        lambda *a, **k: vector_probe.StageResult(
            label="[stage2/app]", ok=True, detail="ok"
        ),
    )
    monkeypatch.setattr(
        vector_probe,
        "_stage_channel",
        lambda *a, **k: vector_probe.StageResult(
            label="[stage3/channel]", ok=True, detail="ok"
        ),
    )

    with patch.object(sys, "platform", "win32"):
        rc = vector_probe.main(["--channel", "0", "--app-name", "Python"])

    out = capsys.readouterr().out
    assert rc == vector_probe.EXIT_DRIVER
    assert "[stage1/driver]" in out
    assert "loadable=false" in out
    assert "stage_failed=[stage1/driver]" in out


def test_driver_api_unavailable_returns_stage1_exit_1(capsys):
    with (
        patch.object(sys, "platform", "win32"),
        patch.dict(sys.modules, _fake_vector_module(xldriver=None)),
    ):
        rc = vector_probe.main(["--channel", "0", "--app-name", "Python"])

    out = capsys.readouterr().out
    assert rc == vector_probe.EXIT_DRIVER
    assert "[stage1/driver]" in out
    assert "loadable=false" in out
    assert "Vector API has not been loaded" in out
    assert "stage_failed=[stage1/driver]" in out


def test_channel_list_failure_stays_stage3_when_driver_loads(monkeypatch):
    xldriver = types.SimpleNamespace(
        xlOpenDriver=MagicMock(), xlCloseDriver=MagicMock()
    )
    monkeypatch.setattr(
        vector_probe,
        "_stage_app",
        lambda *a, **k: vector_probe.StageResult(
            label="[stage2/app]", ok=True, detail="ok"
        ),
    )
    monkeypatch.setattr(
        vector_probe,
        "list_vector_channels",
        lambda: (_ for _ in ()).throw(RuntimeError("driver config unavailable")),
    )

    with patch.dict(sys.modules, _fake_vector_module(xldriver=xldriver)):
        report = vector_probe.probe_stages(
            channel=0, bitrate=500000, app_name="Python", open_bus=False
        )

    assert report.exit_code == vector_probe.EXIT_CHANNEL
    assert report.failed_stage == "[stage3/channel]"
    assert report.stages[0].ok is True
    assert report.stages[2].error == "list channels failed: driver config unavailable"
    xldriver.xlOpenDriver.assert_called_once_with()
    xldriver.xlCloseDriver.assert_called_once_with()


def test_app_failure_returns_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(
        vector_probe,
        "_stage_driver",
        lambda: vector_probe.StageResult(
            label="[stage1/driver]", ok=True, detail="loadable=true"
        ),
    )

    def bad_app(app_name: str, app_channel: int) -> vector_probe.StageResult:
        return vector_probe.StageResult(
            label="[stage2/app]",
            ok=False,
            detail=f'name="{app_name}"  configured=false',
            error=f"application {app_name!r} not configured",
        )

    monkeypatch.setattr(vector_probe, "_stage_app", bad_app)
    monkeypatch.setattr(
        vector_probe,
        "_stage_channel",
        lambda *a, **k: vector_probe.StageResult(
            label="[stage3/channel]", ok=True, detail="ok"
        ),
    )

    with patch.object(sys, "platform", "win32"):
        rc = vector_probe.main(["--app-name", "Python"])

    out = capsys.readouterr().out
    assert rc == vector_probe.EXIT_APP
    assert "configured=false" in out
    assert "stage_failed=[stage2/app]" in out


def test_channel_failure_returns_exit_3(monkeypatch, capsys):
    monkeypatch.setattr(
        vector_probe,
        "_stage_driver",
        lambda: vector_probe.StageResult(
            label="[stage1/driver]", ok=True, detail="loadable=true"
        ),
    )
    monkeypatch.setattr(
        vector_probe,
        "_stage_app",
        lambda *a, **k: vector_probe.StageResult(
            label="[stage2/app]", ok=True, detail="ok"
        ),
    )

    def bad_channel(idx: int) -> vector_probe.StageResult:
        return vector_probe.StageResult(
            label="[stage3/channel]",
            ok=False,
            detail=f"index={idx}  present=false  count=2",
            error=f"channel {idx} not present (count=2)",
        )

    monkeypatch.setattr(vector_probe, "_stage_channel", bad_channel)

    with patch.object(sys, "platform", "win32"):
        rc = vector_probe.main(["--channel", "5", "--app-name", "Python"])

    out = capsys.readouterr().out
    assert rc == vector_probe.EXIT_CHANNEL
    assert "index=5" in out
    assert "present=false" in out
    assert "stage_failed=[stage3/channel]" in out


def test_bus_failure_returns_exit_4(monkeypatch, capsys):
    for name, label in [
        ("_stage_driver", "[stage1/driver]"),
        ("_stage_app", "[stage2/app]"),
        ("_stage_channel", "[stage3/channel]"),
    ]:
        monkeypatch.setattr(
            vector_probe,
            name,
            lambda *a, _label=label, **k: vector_probe.StageResult(
                label=_label, ok=True, detail="ok"
            ),
        )

    def bad_bus(**_kwargs):
        return vector_probe.StageResult(
            label="[stage4/bus]",
            ok=False,
            detail="open=false  bitrate=500000",
            error="bus open failed: hardware busy",
        )

    monkeypatch.setattr(vector_probe, "_stage_bus", bad_bus)

    with patch.object(sys, "platform", "win32"):
        rc = vector_probe.main(["--app-name", "Python", "--open"])

    out = capsys.readouterr().out
    assert rc == vector_probe.EXIT_BUS
    assert "open=false" in out
    assert "stage_failed=[stage4/bus]" in out


def test_all_green_returns_exit_0(monkeypatch, capsys):
    """Happy path: every stage OK + --open invoked → exit 0."""

    for name, label in [
        ("_stage_driver", "[stage1/driver]"),
        ("_stage_app", "[stage2/app]"),
        ("_stage_channel", "[stage3/channel]"),
    ]:
        monkeypatch.setattr(
            vector_probe,
            name,
            lambda *a, _label=label, **k: vector_probe.StageResult(
                label=_label, ok=True, detail="ok"
            ),
        )
    monkeypatch.setattr(
        vector_probe,
        "_stage_bus",
        lambda **k: vector_probe.StageResult(
            label="[stage4/bus]", ok=True, detail="open=true  bitrate=500000"
        ),
    )

    with patch.object(sys, "platform", "win32"):
        rc = vector_probe.main(["--app-name", "Python", "--open"])

    out = capsys.readouterr().out
    assert rc == vector_probe.EXIT_OK
    assert "result: all_green" in out


def test_dry_run_skips_bus_stage(monkeypatch, capsys):
    """Without --open, stage 4 is not invoked at all."""

    for name, label in [
        ("_stage_driver", "[stage1/driver]"),
        ("_stage_app", "[stage2/app]"),
        ("_stage_channel", "[stage3/channel]"),
    ]:
        monkeypatch.setattr(
            vector_probe,
            name,
            lambda *a, _label=label, **k: vector_probe.StageResult(
                label=_label, ok=True, detail="ok"
            ),
        )
    invoked = MagicMock()
    monkeypatch.setattr(vector_probe, "_stage_bus", invoked)

    with patch.object(sys, "platform", "win32"):
        rc = vector_probe.main(["--app-name", "Python"])  # no --open

    invoked.assert_not_called()
    assert rc == vector_probe.EXIT_OK


def test_probe_stages_records_first_failure_only(monkeypatch):
    """When multiple stages fail, the resolved exit code is the
    first stage's. (Other stage results still appear in the report
    so the operator sees the full picture.)"""

    monkeypatch.setattr(
        vector_probe,
        "_stage_driver",
        lambda: vector_probe.StageResult(
            label="[stage1/driver]",
            ok=False,
            detail="loadable=false",
            error="dll missing",
        ),
    )
    monkeypatch.setattr(
        vector_probe,
        "_stage_app",
        lambda app, ch: vector_probe.StageResult(
            label="[stage2/app]",
            ok=False,
            detail="configured=false",
            error="app missing",
        ),
    )
    monkeypatch.setattr(
        vector_probe,
        "_stage_channel",
        lambda idx: vector_probe.StageResult(
            label="[stage3/channel]", ok=True, detail="ok"
        ),
    )

    report = vector_probe.probe_stages(
        channel=0, bitrate=500000, app_name="Python", open_bus=False
    )

    assert report.exit_code == vector_probe.EXIT_DRIVER
    assert report.failed_stage == "[stage1/driver]"
    assert len(report.stages) == 3
    assert report.stages[0].ok is False
    assert report.stages[1].ok is False
    assert report.stages[2].ok is True


def test_stage_app_green_when_get_application_config_succeeds():
    """Real-body test: _stage_app must reach for VectorBus.get_application_config
    with both (app_name, app_channel) arguments and surface the returned
    (hw_type, hw_index, hw_channel) tuple in the detail string.
    """

    calls = []

    def fake_get(app, ch):
        calls.append((app, ch))
        return (57, 0, 0)  # VN1630 hw_type=57, first device, channel 1

    with patch.dict(sys.modules, _fake_vector_with_bus(fake_get)):
        result = vector_probe._stage_app("Python", 0)

    assert calls == [("Python", 0)], (
        "_stage_app must call VectorBus.get_application_config(app, channel) "
        "with both arguments — passing only app_name regresses to the "
        "phantom canlib API"
    )
    assert result.ok is True
    assert result.label == "[stage2/app]"
    assert "configured=true" in result.detail
    assert "hw_type=57" in result.detail
    assert "hw_index=0" in result.detail
    assert "hw_channel=0" in result.detail
    assert "channel=0" in result.detail


def test_stage_app_red_when_application_not_mapped():
    def fake_get(app, ch):
        raise _FakeVectorInitializationError(
            f"Vector HW Config: Channel '{ch}' of application '{app}' is not "
            "assigned to any interface"
        )

    with patch.dict(sys.modules, _fake_vector_with_bus(fake_get)):
        result = vector_probe._stage_app("Python", 0)

    assert result.ok is False
    assert "configured=false" in result.detail
    assert "channel=0" in result.detail
    assert "not assigned" in (result.error or "")


def test_stage_app_red_on_unexpected_exception():
    def fake_get(app, ch):
        raise RuntimeError("driver surface in flux")

    with patch.dict(sys.modules, _fake_vector_with_bus(fake_get)):
        result = vector_probe._stage_app("Python", 0)

    assert result.ok is False
    assert "configured=unknown" in result.detail
    assert "VectorBus.get_application_config failed" in (result.error or "")
    assert "driver surface in flux" in (result.error or "")


def test_probe_stages_passes_channel_through_to_stage_app(monkeypatch):
    """probe_stages must forward ``channel`` into _stage_app so stage 2
    checks the same app+channel mapping stage 4 will use.
    """

    captured = {}

    def spy_app(app_name, app_channel):
        captured["app"] = app_name
        captured["channel"] = app_channel
        return vector_probe.StageResult(
            label="[stage2/app]", ok=True, detail="ok"
        )

    monkeypatch.setattr(
        vector_probe,
        "_stage_driver",
        lambda: vector_probe.StageResult(
            label="[stage1/driver]", ok=True, detail="ok"
        ),
    )
    monkeypatch.setattr(vector_probe, "_stage_app", spy_app)
    monkeypatch.setattr(
        vector_probe,
        "_stage_channel",
        lambda *a, **k: vector_probe.StageResult(
            label="[stage3/channel]", ok=True, detail="ok"
        ),
    )

    vector_probe.probe_stages(
        channel=3, bitrate=500000, app_name="MyApp", open_bus=False
    )

    assert captured == {"app": "MyApp", "channel": 3}


def test_uncategorized_exception_returns_exit_9(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("totally unexpected")

    monkeypatch.setattr(vector_probe, "probe_stages", boom)

    with patch.object(sys, "platform", "win32"):
        rc = vector_probe.main(["--app-name", "Python"])

    err = capsys.readouterr().err
    assert rc == vector_probe.EXIT_UNCATEGORIZED
    assert "uncategorized" in err
    assert "totally unexpected" in err
