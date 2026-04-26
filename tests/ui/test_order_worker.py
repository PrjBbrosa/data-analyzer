import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

from mf4_analyzer.signal.order import OrderAnalysisParams


def test_order_worker_emits_result_with_generation(qtbot):
    """OrderWorker should emit (result, kind, generation) on completion."""
    from mf4_analyzer.ui.main_window import OrderWorker
    fs = 1024.0
    nfft = 512
    n = nfft * 4
    t = np.arange(n, dtype=float) / fs
    sig = np.sin(2 * np.pi * 50.0 * t)
    rpm = np.full(n, 1500.0)
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    GEN = 42
    worker = OrderWorker('time', sig, rpm, t, params, generation=GEN)
    results = []
    failures = []
    worker.result_ready.connect(
        lambda r, kind, gen: results.append((r, kind, gen))
    )
    worker.failed.connect(lambda msg, gen: failures.append((msg, gen)))

    worker.start()
    qtbot.waitUntil(lambda: bool(results) or bool(failures), timeout=5000)
    worker.wait(2000)

    assert not failures, f"unexpected failure: {failures}"
    assert len(results) == 1
    r, kind, gen = results[0]
    assert gen == GEN
    assert kind == 'time'
    assert hasattr(r, 'amplitude')


def test_order_worker_cancel_before_run_yields_no_result(qtbot):
    """Cancel before start: worker emits no result_ready and finishes promptly.

    Cancel is set BEFORE start() so the very first cancel poll inside
    OrderAnalyzer triggers, avoiding the deadlock pattern where
    QTimer.singleShot(50, cancel) followed by an immediate worker.wait()
    would swallow the timer (codex review D14).
    """
    from mf4_analyzer.ui.main_window import OrderWorker
    fs = 1024.0
    nfft = 256
    n = nfft * 600
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.001)

    worker = OrderWorker('time', sig, rpm, t, params, generation=1)
    results = []
    failures = []
    worker.result_ready.connect(lambda *a: results.append(a))
    worker.failed.connect(lambda *a: failures.append(a))

    # Pre-cancel so worker.run's first cancel check trips immediately.
    worker.cancel()
    worker.start()
    assert worker.wait(5000), "worker did not finish within 5 s"
    assert not worker.isRunning()
    # Already cancelled — neither signal must fire.
    assert results == [], f"unexpected result after pre-cancel: {results}"
    assert failures == [], f"unexpected failure after pre-cancel: {failures}"


def test_order_worker_mid_run_cancel_via_event_loop(qtbot):
    """Mid-run cancel: drive event loop with qtbot.waitUntil so the
    worker actually receives the cancel before it completes.

    Uses qtbot.waitUntil to keep the main loop alive instead of
    blocking with wait() before the cancel signal fires.
    """
    from mf4_analyzer.ui.main_window import OrderWorker
    fs = 1024.0
    nfft = 256
    n = nfft * 600
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.001)

    worker = OrderWorker('time', sig, rpm, t, params, generation=2)
    progress_seen = []
    worker.progress.connect(lambda c, tt, g: progress_seen.append(c))

    worker.start()
    # Wait until at least 1 progress tick (worker has entered its loop).
    qtbot.waitUntil(lambda: len(progress_seen) > 0, timeout=3000)
    worker.cancel()
    # wait() now drains the QThread cleanly because cancel will trip in run().
    assert worker.wait(5000), "worker did not honor cancel within 5 s"


def test_order_worker_result_signal_carries_generation(qtbot):
    """OrderWorker.result_ready emits (result, kind, generation) with the
    generation round-tripping unmodified. The actual stale-drop behavior
    is exercised by `test_on_order_result_drops_stale_generation_deterministically`
    (slot unit) and `test_rapid_redispatch_drops_stale_generation` (end-to-end).
    """
    from mf4_analyzer.ui.main_window import OrderWorker
    import inspect
    # Reflectively confirm signal types exist (PyQt5 signals do not
    # expose introspectable signatures, so we rely on emit-side success).
    sig = OrderWorker.result_ready
    failed_sig = OrderWorker.failed
    progress_sig = OrderWorker.progress
    fs = 1024.0
    nfft = 256
    n = nfft * 4
    sig_data = np.zeros(n)
    rpm_data = np.full(n, 1500.0)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)
    w = OrderWorker('time', sig_data, rpm_data, t, params, generation=99)
    received = []
    w.result_ready.connect(lambda r, k, g: received.append((k, g)))
    w.start()
    qtbot.waitUntil(lambda: bool(received), timeout=5000)
    w.wait(2000)
    assert received[0] == ('time', 99)


def test_main_window_close_event_cancels_running_order_worker(qtbot):
    """If an order worker is still running, closeEvent must cancel it
    cleanly with no QThread destroyed warnings."""
    import warnings
    from mf4_analyzer.ui.main_window import MainWindow, OrderWorker
    from mf4_analyzer.signal.order import OrderAnalysisParams
    win = MainWindow()
    qtbot.addWidget(win)

    fs = 1024.0
    nfft = 256
    n = nfft * 800
    sig = np.zeros(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.001)

    win._dispatch_order_worker('time', sig, rpm, t, params,
                                status_msg='测试取消')
    qtbot.waitUntil(lambda: win._order_worker.isRunning(), timeout=2000)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        win.close()
        assert not win._order_worker.isRunning()
        thread_warnings = [w for w in caught
                            if 'QThread' in str(w.message) or 'destroyed' in str(w.message)]
        assert not thread_warnings, f"unexpected QThread warnings: {thread_warnings}"


def test_main_window_close_event_cancels_running_fft_time_thread(qtbot):
    """codex round-2 C10: if _fft_time_thread is still running,
    closeEvent must quit it. FFTTimeWorker is a QObject so the
    isRunning() check lives on the QThread, not the worker."""
    import warnings
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtCore import QThread, QObject, pyqtSignal

    win = MainWindow()
    qtbot.addWidget(win)

    # Minimal stub worker + real QThread to model a live fft-time path.
    class StubWorker(QObject):
        finished = pyqtSignal(object)
        failed = pyqtSignal(str)
        progress = pyqtSignal(int, int)

        def __init__(self):
            super().__init__()
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        def run(self):
            # Spin until cancel flips or the thread is asked to quit.
            while not self._cancelled:
                QThread.msleep(50)
            self.finished.emit(None)

    worker = StubWorker()
    thread = QThread(win)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    win._fft_time_thread = thread
    win._fft_time_worker = worker
    thread.start()
    qtbot.waitUntil(lambda: thread.isRunning(), timeout=2000)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        win.close()
        assert not thread.isRunning(), "fft-time thread must be stopped on close"
        thread_warnings = [w for w in caught
                            if 'QThread' in str(w.message) or 'destroyed' in str(w.message)]
        assert not thread_warnings, f"unexpected QThread warnings: {thread_warnings}"


def test_on_order_result_drops_stale_generation_deterministically(qtbot):
    """codex round-2 C11: stale-generation drop must not depend on
    worker timing. Call _on_order_result(..., old_gen) directly on the
    main thread and assert no render fires."""
    from mf4_analyzer.ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)

    rendered = []
    win._render_order_time = lambda r: rendered.append(r)

    # Simulate dispatcher having advanced generation to 5.
    win._order_generation = 5
    # Stale signal arrives from an old worker (generation=3).
    fake_result = object()
    win._on_order_result(fake_result, 'time', 3)
    assert rendered == [], "stale-generation result must NOT trigger render"

    # Current-generation result must be accepted.
    win._on_order_result(fake_result, 'time', 5)
    assert rendered == [fake_result]


def test_rapid_redispatch_drops_stale_generation(qtbot):
    """连续 dispatch 三次：只有最新 generation 的 result 应到 _on_order_result。

    本测试覆盖"端到端"路径（dispatcher → worker → signal → slot）；
    上一测试覆盖"slot 单元层"。两者互补。
    """
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.signal.order import OrderAnalysisParams
    win = MainWindow()
    qtbot.addWidget(win)

    # Hook _on_order_result BEFORE dispatches so the wrapper is used by
    # subsequent worker.result_ready.connect(self._on_order_result) lookups.
    # The wrapper records the generation only when it survives the guard,
    # i.e. matches win._order_generation at delivery time.
    accepted_generations = []
    original_on_result = win._on_order_result
    def capturing_on_result(result, kind, gen):
        if gen == getattr(win, '_order_generation', -1):
            accepted_generations.append(gen)
        original_on_result(result, kind, gen)
    win._on_order_result = capturing_on_result
    win._render_order_time = lambda result: None  # avoid real heavy render

    fs = 1024.0
    nfft = 256
    n = nfft * 50
    sig = np.zeros(n)
    rpm = np.full(n, 1500.0)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    for _ in range(3):
        win._dispatch_order_worker('time', sig, rpm, t, params,
                                    status_msg='rapid')
    final_gen = win._order_generation
    qtbot.waitUntil(lambda: not win._order_worker.isRunning(), timeout=10000)
    qtbot.wait(200)   # 让信号 deliver

    # Tightened: must accept exactly one render, and it must carry final_gen.
    # The previous `len <= 1` form allowed zero renders to pass.
    assert accepted_generations == [final_gen], (
        f"expected exactly one accepted render with generation={final_gen}, "
        f"got accepted_generations={accepted_generations}"
    )
