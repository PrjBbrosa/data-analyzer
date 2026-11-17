"""Real broker recovery and production tool windows on Cocoa.

Run explicitly with QT_QPA_PLATFORM=cocoa. Optional evidence goes to
IMPORT_RECOVERY_EVIDENCE; screenshots are local verification artifacts.
"""
import json
import os
from pathlib import Path

import pytest
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

pytestmark = pytest.mark.skipif(os.environ.get('QT_QPA_PLATFORM') != 'cocoa', reason='Cocoa acceptance')


def capture(widget, name, facts):
    directory = os.environ.get('IMPORT_RECOVERY_EVIDENCE')
    facts[name] = {'width': widget.width(), 'height': widget.height(),
                   'dpr': widget.devicePixelRatioF(), 'visible': widget.isVisible()}
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        widget.grab().save(str(target / f'{name}.png'))
        prior = json.loads((target / 'geometry.json').read_text()) if (target / 'geometry.json').exists() else {}
        prior.update(facts)
        (target / 'geometry.json').write_text(json.dumps(prior, indent=2))


def test_cocoa_production_tool_windows(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    from mf4_analyzer.ui.drawers.ultraview.sheet import UltraViewSheet
    from mf4_analyzer.ui_kit import load_stylesheet
    from tests.ui_kit.test_message_dialog import _checkbox_dialog
    load_stylesheet(qapp)
    host = MainWindow()
    qtbot.addWidget(host)
    host.show()
    facts = {}
    message = _checkbox_dialog(parent=host, text='操作已完成')
    qtbot.addWidget(message)
    message.show()
    qtbot.waitExposed(message)
    capture(message, 'short-message', facts)
    assert message.height() < 250
    message.close()
    batch = BatchSheet(host, files={})
    qtbot.addWidget(batch)
    batch.present()
    qtbot.waitExposed(batch)
    capture(batch, 'batch', facts)
    assert batch.width() >= 640 and batch.height() >= 480
    batch.close()
    ultra = UltraViewSheet(host, host.chart_stack.page_ultraview, host.chart_stack.stack)
    qtbot.addWidget(ultra)
    ultra.present()
    qtbot.waitExposed(ultra)
    capture(ultra, 'ultraview', facts)
    assert ultra.width() >= 640 and ultra.height() >= 480
    ultra.close()


@pytest.mark.allow_blocking_modal
def test_cocoa_real_resource_recheck_reaps_and_retries(qapp, qtbot, monkeypatch, tmp_path):
    from dataclasses import replace
    from mf4_analyzer.io.import_limits import default_limits
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui_kit.message_dialog import AppMessageDialog
    from tests.test_mdf_native_reader import _write_bulky
    from tests.ui.test_mf4_native_product_path import _track_workers

    from mf4_analyzer.ui_kit import load_stylesheet
    load_stylesheet(qapp)
    path = _write_bulky(tmp_path / 'retry.mf4')
    fresh = default_limits()
    calls = []
    def fresh_default():
        calls.append('fresh')
        return fresh
    monkeypatch.setattr('mf4_analyzer.io.import_limits.default_limits', fresh_default)
    pids = _track_workers(monkeypatch)
    host = MainWindow()
    qtbot.addWidget(host)
    monkeypatch.setattr(host, 'toast', lambda *a: None)
    host.show()
    seen, terminals, facts = [], [], {}
    host._imports.finished.connect(lambda request, status, value: terminals.append(status))
    timer = QTimer(host)
    timer.setInterval(25)
    def retry_visible():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, AppMessageDialog) or id(dialog) in seen:
            return
        seen.append(id(dialog))
        def settled():
            capture(dialog, 'resource-recheck', facts)
            capture(host._imports.progress_dialog, 'waiting-progress', facts)
            assert host._imports._thread is None
            assert host._imports.current_progress.kind == 'waiting_user'
            height = dialog.height()
            button = dialog.button('recheck_retry')
            assert button is not None
            button.click()
            assert height < 400
        QTimer.singleShot(250, settled)
    timer.timeout.connect(retry_visible)
    timer.start()
    try:
        host.request_explicit_native_import(path, limits=replace(fresh,
            max_memory_bytes=240*1024*1024, max_output_bytes=120*1024*1024))
        qtbot.waitUntil(lambda: not host._imports.busy, timeout=30000)
        assert len(seen) == 1 and calls == ['fresh']
        assert terminals == ['success']
        assert len(host.files) == 1
        assert next(iter(host.files.values())).is_native
        assert len(pids) == 2 and pids[0] != pids[1]
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        assert host._imports._last_call is None
        assert host._imports.progress_dialog is None
        if os.environ.get('IMPORT_RECOVERY_EVIDENCE'):
            (Path(os.environ['IMPORT_RECOVERY_EVIDENCE']) / 'retry.json').write_text(json.dumps({
                'pids': pids, 'reaped': True, 'terminals': terminals, 'fresh_default_calls': len(calls),
                'fresh_memory': fresh.max_memory_bytes, 'initial_memory': 240*1024*1024,
            }, indent=2))
    finally:
        timer.stop()
        host._imports.cancel()
        qtbot.waitUntil(lambda: not host._imports.busy, timeout=5000)
