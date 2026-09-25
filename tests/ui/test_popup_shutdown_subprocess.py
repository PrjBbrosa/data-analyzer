"""Process exit is part of the popup lifetime contract, beyond widget tests."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("popup_kind", ["preset", "tooltip"])
@pytest.mark.parametrize("exit_kind", ["close", "quit"])
def test_popup_shutdown_exits_cleanly(tmp_path, popup_kind, exit_kind):
    script = tmp_path / "popup_exit.py"
    script.write_text(textwrap.dedent('''
        import sys
        import weakref
        from PyQt5 import sip
        from PyQt5.QtCore import QPoint, QSettings, QTimer
        from PyQt5.QtWidgets import QApplication, QWidget

        app = QApplication([])
        window = QWidget()
        window.resize(320, 200)
        window.show()
        kind, exit_kind, settings_path = sys.argv[1:]
        if kind == "preset":
            from mf4_analyzer.ui.inspector_sections import presets
            presets._preset_settings = lambda: QSettings(settings_path, QSettings.IniFormat)
            bar = presets.PresetBar("exit_probe", dict, lambda _: None, parent=window)
            popup_ref = weakref.ref(bar._hover_card)
            # Qt must own this tooltip even though it remains a top-level window.
            assert not sip.ispyowned(bar._hover_card)
            bar._hover_card.show()
        else:
            from mf4_analyzer.ui_kit.glass_tooltip import _GlassTooltipPopup
            _GlassTooltipPopup.instance().show_for("退出前的提示", QPoint(100, 100))
            popup_ref = weakref.ref(_GlassTooltipPopup.existing())
        QTimer.singleShot(30, window.close if exit_kind == "close" else app.quit)
        assert app.exec_() == 0
        if kind == "tooltip":
            # aboutToQuit must dispose it before SIP's interpreter-exit traversal.
            assert _GlassTooltipPopup.existing() is None
            assert popup_ref() is None or sip.isdeleted(popup_ref())
        print("popup-exit-ok", flush=True)
    '''), encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONMALLOC="debug")
    env["PYTHONPATH"] = str(root)
    result = subprocess.run(
        [sys.executable, str(script), popup_kind, exit_kind, str(tmp_path / "settings.ini")],
        cwd=root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "popup-exit-ok" in result.stdout
