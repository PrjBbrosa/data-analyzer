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

    def bad_app(app_name: str) -> vector_probe.StageResult:
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
        lambda app: vector_probe.StageResult(
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
