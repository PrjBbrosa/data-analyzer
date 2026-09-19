"""Demo entry smoke (Stage 4).

Pins:

- ``python -m mf4_analyzer.acquisition_ui --self-test`` exits with code 0.
- Child processes resolve temp config/cache/home and never the real store.
- ``RingBuffer.watermark_changed`` is bridged to the Qt slot
  ``MainWindow.set_target_fps`` — emitting the signal directly toggles
  the live timer interval between the 30 fps and 10 fps constants.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from tests._helpers.acq_owned_objects import isolated_user_env

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SELF_TEST_WRAPPER = r"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

print("HOME=" + str(Path.home()), flush=True)

from PyQt5.QtWidgets import QApplication

from mf4_analyzer.acquisition_capture import thresholds

settings = thresholds.default_user_settings_path()
print("SETTINGS=" + str(settings), flush=True)
print("SETTINGS_EXISTS=" + str(settings.exists()), flush=True)

app = QApplication.instance() or QApplication([])
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.__main__ import main

window = CockpitMainWindow()
print("TIMEOUT=" + str(thresholds.CONNECTION_TIMEOUT_S), flush=True)
print("LOAD_ERROR=" + json.dumps(window._settings_load_error), flush=True)
window.close()
app.processEvents()

sys.exit(main(["--demo", "--self-test"]))
"""


def _write_settings(home: Path, kind: str) -> Path:
    settings_dir = home / ".acquisition-cockpit"
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / "settings.json"
    if kind == "empty":
        return path
    if kind == "valid":
        path.write_text(
            json.dumps(
                {
                    "version": thresholds.SETTINGS_VERSION,
                    "thresholds": {"CONNECTION_TIMEOUT_S": 99},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path
    path.write_text("{this is not: json", encoding="utf-8")
    return path


@pytest.mark.parametrize("config_kind", ("empty", "valid", "corrupt"))
def test_self_test_exits_zero(tmp_path, config_kind):
    """Run the self-test entrypoint as a subprocess so we exercise the
    real argv parser + headless launch path, isolated from the user store.
    """
    home = tmp_path / "home"
    home.mkdir()
    settings_path = _write_settings(home, config_kind)
    env = isolated_user_env(home)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", _SELF_TEST_WRAPPER],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"self-test exit {result.returncode} kind={config_kind}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    lines = dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line and line.split("=", 1)[0]
        in {"HOME", "SETTINGS", "SETTINGS_EXISTS", "TIMEOUT", "LOAD_ERROR"}
    )
    assert Path(lines["HOME"]) == home
    assert Path(lines["SETTINGS"]) == settings_path
    assert str(home) in lines["SETTINGS"]
    if config_kind == "empty":
        assert lines["SETTINGS_EXISTS"] == "False"
        assert float(lines["TIMEOUT"]) == 3.0
        assert lines["LOAD_ERROR"] == "null"
    elif config_kind == "valid":
        assert lines["SETTINGS_EXISTS"] == "True"
        assert float(lines["TIMEOUT"]) == 99.0
        assert lines["LOAD_ERROR"] == "null"
    else:
        assert lines["SETTINGS_EXISTS"] == "True"
        assert float(lines["TIMEOUT"]) == 3.0
        assert lines["LOAD_ERROR"] != "null"


def test_ring_buffer_watermark_bridge_to_fps(qapp):
    """Emit the watermark signal directly and assert the slot fires.

    No recorder required — the test pokes the shim's ``emit`` API.
    """
    window = CockpitMainWindow()
    # Start in green / 30 fps.
    assert window._target_fps == thresholds.LIVE_FPS_NORMAL

    # Emit a red watermark → 10 fps.
    window._ring.watermark_changed.emit("red")
    assert window._target_fps == thresholds.LIVE_FPS_DEGRADED
    # Interval reflects fps.
    assert window._live_timer.interval() == int(
        1000 / thresholds.LIVE_FPS_DEGRADED
    )

    # Back to green → 30 fps.
    window._ring.watermark_changed.emit("green")
    assert window._target_fps == thresholds.LIVE_FPS_NORMAL
    assert window._live_timer.interval() == int(
        1000 / thresholds.LIVE_FPS_NORMAL
    )

    window.close()


def test_red_drop_sustained_only_degrades_fps(qapp):
    """Instant watermark only degrades FPS; controller owns auto-stop."""
    window = CockpitMainWindow()
    fired = []
    window.auto_stop_requested.connect(lambda reason: fired.append(reason))
    window._ring.watermark_changed.emit("red_drop_sustained")
    assert window._target_fps == thresholds.LIVE_FPS_DEGRADED
    assert fired == []
    assert window._review_modal is None
    window.close()
