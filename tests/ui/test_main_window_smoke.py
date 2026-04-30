from mf4_analyzer.ui.main_window import MainWindow


def test_main_window_constructs(qapp):
    w = MainWindow()
    assert w.toolbar is not None
    assert w.navigator is not None
    assert w.chart_stack is not None
    assert w.inspector is not None


def test_main_window_has_splitter_with_three_panes(qapp):
    w = MainWindow()
    # The central widget contains a QSplitter with 3 widgets
    from PyQt5.QtWidgets import QSplitter
    splitter = w.findChild(QSplitter)
    assert splitter is not None
    assert splitter.count() == 3


def test_main_window_splitter_default_sizes_align_with_inspector_cap(qapp, qtbot):
    """fix-5 — the inspector's default splitter slot must match the
    Inspector's content max-width (~360) so the user does not see a
    visible empty band the moment the app opens.

    We resize the window before reading splitter sizes because QSplitter
    does not honor setSizes() until it has geometry to distribute.
    """
    from PyQt5.QtWidgets import QSplitter
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1500, 800)
    w.show()
    qtbot.waitExposed(w)
    splitter = w.findChild(QSplitter)
    sizes = splitter.sizes()
    assert len(sizes) == 3
    # Inspector pane is the third slot. >= 340 keeps content within cap;
    # > 400 would mean the splitter assigned the inspector more space
    # than its content can ever fill, leaving a hard empty gap.
    assert 340 <= sizes[2] <= 420, (
        f"inspector default splitter size {sizes[2]} should be ~360 to "
        "match Inspector._scroll_body.maximumWidth (R3 紧凑化 fix-5)."
    )
    # Inspector minimumWidth must remain <= the default sized slot.
    assert w.inspector.minimumWidth() <= sizes[2], (
        f"inspector.minimumWidth {w.inspector.minimumWidth()} > splitter "
        f"default sizes[2] {sizes[2]} (mismatch)."
    )


def test_main_window_inspector_slot_fixed_at_360_under_qss(qapp, qtbot):
    """Default app styling keeps the right Inspector slot at 360px.

    This covers the real startup path more closely than the smoke test
    above because it applies ``style.qss``. The bug report screenshots came
    from the styled app, where the Inspector body could shrink inside the
    splitter slot and leave an empty band.
    """
    from pathlib import Path
    from PyQt5.QtWidgets import QSplitter

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui/style.qss").read_text(encoding="utf-8")
        )
        w = MainWindow()
        qtbot.addWidget(w)
        w.resize(2048, 1228)
        w.show()
        qtbot.waitExposed(w)
        qtbot.wait(50)

        splitter = w.findChild(QSplitter)
        sizes = splitter.sizes()
        assert sizes[2] == 360, (
            f"Inspector splitter slot should stay fixed at 360px; got {sizes}"
        )
        assert w.inspector.width() == 360
        assert w.inspector.minimumWidth() == 360
        assert w.inspector.maximumWidth() == 360
    finally:
        qapp.setStyleSheet(old_sheet)


def test_load_csv_flows_through_navigator(qapp, qtbot, loaded_csv):
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    assert len(w.files) == 1
    assert w.navigator.channel_list.tree.topLevelItemCount() == 1


def test_mode_change_routes_to_chart_stack(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    w.toolbar.btn_mode_fft.click()
    assert w.chart_stack.current_mode() == 'fft'
    assert w.inspector.contextual_widget_name() == 'fft'


def test_custom_xaxis_length_mismatch_warns(qapp, qtbot, loaded_csv, tmp_path):
    """If user selects a custom X channel whose length != data, surface a
    non-blocking warning toast and abort."""
    import pandas as pd
    import numpy as np
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow
    # Second csv with different length
    df = pd.DataFrame({"time": np.linspace(0, 1, 500), "pressure": np.random.randn(500)})
    p2 = tmp_path / "shorter.csv"; df.to_csv(p2, index=False)

    w = MainWindow(); qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv, str(p2)], "")):
        w.load_files()
    # Pick custom X from file 2's channel while file 1 checked
    w.inspector.top.set_xaxis_mode('channel')
    w._on_xaxis_mode_changed('channel')
    w.inspector.top._combo_xaxis_ch.setCurrentIndex(
        w.inspector.top._combo_xaxis_ch.count() - 1  # last candidate (from file 2)
    )
    qapp.processEvents()
    # Validation feedback now goes through MainWindow.toast (non-blocking)
    # rather than QMessageBox.warning.
    with patch.object(MainWindow, 'toast') as toast:
        w._apply_xaxis()
    assert toast.called
    levels = [call.args[1] if len(call.args) > 1 else call.kwargs.get('level')
              for call in toast.call_args_list]
    assert 'warning' in levels


def test_file_activation_updates_inspector_fs_and_range(qapp, qtbot, loaded_csv):
    from unittest.mock import patch
    import pytest
    from mf4_analyzer.ui.main_window import MainWindow
    w = MainWindow(); qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    fid = next(iter(w.files))
    fd = w.files[fid]
    # activation should have pushed fs + range-limit to inspector
    # (QDoubleSpinBox default decimals=2 rounds fs, so compare with tolerance)
    assert w.inspector.fft_ctx.fs() == pytest.approx(fd.fs, abs=0.01)
    assert w.inspector.order_ctx.fs() == pytest.approx(fd.fs, abs=0.01)
    # range limit upper bound should match time_array tail
    assert w.inspector.top.spin_end.maximum() >= fd.time_array[-1]


def test_close_file_resets_inspector(qapp, qtbot, loaded_csv):
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow
    w = MainWindow(); qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    assert w.files
    w._close(next(iter(w.files)))
    # No crash; stats strip shows placeholder
    assert '—' in w.chart_stack.stats_strip._lbl_summary.text()


def test_main_window_promotes_fft_time_canvas(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    win = MainWindow()
    qtbot.addWidget(win)

    assert isinstance(win.canvas_fft_time, SpectrogramCanvas)
    assert win.canvas_fft_time is win.chart_stack.canvas_fft_time


# ---------------------------------------------------------------------------
# FFT vs Time synchronous compute path (Plan Task 6)
# ---------------------------------------------------------------------------


def _fft_time_base_params():
    """Shared param dict for cache-key tests."""
    return dict(
        fid='f1', channel='ch', time_range=(0.0, 1.0),
        fs=1000.0, nfft=2048, window='hanning', overlap=0.75,
        remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude_db', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
    )


def test_fft_time_cache_key_ignores_display_only_options(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    base = _fft_time_base_params()
    changed = dict(
        base,
        amplitude_mode='amplitude',
        cmap='gray',
        dynamic='60 dB',
        freq_auto=False,
        freq_min=10.0,
        freq_max=2000.0,
    )

    assert win._fft_time_cache_key(base) == win._fft_time_cache_key(changed)


def test_fft_time_cache_hit_status(qtbot, monkeypatch):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake = SpectrogramResult(
        times=np.array([0.0, 0.1]),
        frequencies=np.array([0.0, 50.0]),
        amplitude=np.ones((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 2, 'hop': 4, 'freq_bins': 2},
    )
    p = dict(
        fid='f1', channel='ch', fs=100.0, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
        time_range=(0.0, 0.1),
    )
    key = win._fft_time_cache_key(p)
    win._fft_time_cache_put(key, fake)

    # Stub _get_fft_time_signal and inspector.get_params so do_fft_time
    # hits the cache branch.
    monkeypatch.setattr(
        win, '_get_fft_time_signal',
        lambda: ('f1', 'ch', np.linspace(0, 0.1, 2), np.ones(2), object()),
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params', lambda: p)
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)

    win.do_fft_time(force=False)

    # statusBar in this codebase is an attribute (a QStatusBar instance),
    # not the QMainWindow accessor method. The plan example used
    # ``statusBar()`` which is incorrect here; the codebase convention
    # (verified in T5 report) is attribute access.
    assert "使用缓存结果" in win.statusBar.currentMessage()


def test_fft_time_force_bypasses_cache(qtbot, monkeypatch):
    """force=True must skip the cache and call the analyzer.

    Plan Task 7 moved compute to a worker thread; we wait on
    ``thread.finished`` (via ``qtbot.waitUntil``) so the cache PUT and
    status-bar update fired by ``_on_fft_time_finished`` are visible
    to the asserts.
    """
    import numpy as np
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    cached = SpectrogramResult(
        times=np.array([0.0, 0.1]),
        frequencies=np.array([0.0, 50.0]),
        amplitude=np.zeros((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 2},
    )
    p = dict(
        fid='f1', channel='ch', fs=100.0, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
        time_range=(0.0, 0.1),
    )
    key = win._fft_time_cache_key(p)
    win._fft_time_cache_put(key, cached)

    fresh = SpectrogramResult(
        times=np.array([0.0, 0.1]),
        frequencies=np.array([0.0, 50.0]),
        amplitude=np.ones((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 2, 'hop': 4, 'freq_bins': 2},
    )
    calls = {'n': 0}

    def fake_compute(*a, **kw):
        calls['n'] += 1
        return fresh

    monkeypatch.setattr(spectrogram_mod.SpectrogramAnalyzer, 'compute', staticmethod(fake_compute))
    monkeypatch.setattr(
        win, '_get_fft_time_signal',
        lambda: ('f1', 'ch', np.linspace(0, 0.1, 2), np.ones(2), object()),
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params', lambda: p)
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)

    win.do_fft_time(force=True)
    # Worker dispatched — wait for the finished slot to drain on the
    # main thread (clears _fft_time_thread to None).
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=5000)
    assert calls['n'] == 1
    # Status bar should NOT mention cache when force-recomputing.
    assert "使用缓存结果" not in win.statusBar.currentMessage()


def test_fft_time_failed_compute_keeps_old_chart(qtbot, monkeypatch):
    """If SpectrogramAnalyzer.compute raises, the previously plotted
    image must remain visible — do_fft_time MUST NOT call canvas.clear()."""
    import numpy as np
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    # Plot a known result first so the canvas has an image.
    seed = SpectrogramResult(
        times=np.linspace(0.0, 1.0, 8),
        frequencies=np.linspace(0.0, 50.0, 4),
        amplitude=np.linspace(0, 1, 32, dtype=np.float32).reshape(4, 8),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 8, 'hop': 4, 'freq_bins': 4},
    )
    win.canvas_fft_time.plot_result(
        seed, amplitude_mode='amplitude', cmap='turbo', z_auto=True,
        freq_range=None,
    )
    assert win.canvas_fft_time._ax_spec is not None
    images_before = len(win.canvas_fft_time._ax_spec.images)
    assert images_before >= 1

    # Force the analyzer to fail. Use force=True to skip the cache.
    def boom(*a, **kw):
        raise ValueError("boom")

    monkeypatch.setattr(spectrogram_mod.SpectrogramAnalyzer, 'compute', staticmethod(boom))
    monkeypatch.setattr(
        win, '_get_fft_time_signal',
        lambda: ('f1', 'ch', np.linspace(0, 1, 32), np.ones(32), object()),
    )
    p = dict(
        fid='f1', channel='ch', fs=100.0, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params', lambda: p)
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)

    # Toasts should not raise; capture invocations.
    captured = []
    monkeypatch.setattr(win, 'toast', lambda msg, level='info': captured.append((msg, level)))

    win.do_fft_time(force=True)
    # Worker dispatched — wait for the failed slot to drain on the
    # main thread (clears _fft_time_thread to None).
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=5000)

    # The old chart is still on the canvas.
    assert win.canvas_fft_time._ax_spec is not None
    assert len(win.canvas_fft_time._ax_spec.images) == images_before
    # The original SpectrogramResult object is still the canvas's
    # ``_result`` (clear() would have set it to None).
    assert win.canvas_fft_time._result is seed
    # Status bar reports the error.
    assert "FFT vs Time 错误" in win.statusBar.currentMessage()
    # An error toast was emitted.
    assert any(level == 'error' for _msg, level in captured)


def test_fft_time_cursor_info_propagates_to_status_bar(qtbot):
    """canvas_fft_time.cursor_info must reach the MainWindow status bar."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    win.canvas_fft_time.cursor_info.emit("t=0.123 s · f=50.0 Hz · 1.234 (V)")
    assert "t=0.123" in win.statusBar.currentMessage()
    assert "f=50.0" in win.statusBar.currentMessage()


def test_fft_time_normalize_freq_range_clamps_inverted_pair(qtbot):
    """Reviewer Important #3: contradictory (lo>0, hi>0, hi<=lo) must
    fall back to auto rather than passing the silent inverted range
    down to the canvas."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    # auto path — None.
    assert win._normalize_freq_range({'freq_auto': True, 'freq_min': 0, 'freq_max': 0}) is None
    # manual + freq_max == 0 (Nyquist sentinel) — pass through.
    assert win._normalize_freq_range(
        {'freq_auto': False, 'freq_min': 10.0, 'freq_max': 0.0}
    ) == (10.0, 0.0)
    # manual + valid range — pass through.
    assert win._normalize_freq_range(
        {'freq_auto': False, 'freq_min': 10.0, 'freq_max': 2000.0}
    ) == (10.0, 2000.0)
    # manual + inverted (hi <= lo, hi > 0) — auto fallback.
    assert win._normalize_freq_range(
        {'freq_auto': False, 'freq_min': 100.0, 'freq_max': 50.0}
    ) is None
    assert win._normalize_freq_range(
        {'freq_auto': False, 'freq_min': 100.0, 'freq_max': 100.0}
    ) is None


def test_fft_time_cache_lru_eviction(qtbot):
    """Capacity is 12 — older entries should evict in insertion order."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    base = _fft_time_base_params()
    # Insert 13 distinct entries (vary nfft to make distinct keys).
    for i in range(13):
        p = dict(base, nfft=512 * (i + 1))
        win._fft_time_cache_put(win._fft_time_cache_key(p), object())

    assert len(win._fft_time_cache) == 12
    # The first inserted (nfft=512) should have evicted.
    first = dict(base, nfft=512)
    assert win._fft_time_cache_get(win._fft_time_cache_key(first)) is None
    # The second (nfft=1024) should still be present.
    second = dict(base, nfft=1024)
    assert win._fft_time_cache_get(win._fft_time_cache_key(second)) is not None


def test_fft_time_inspector_relays_signal_changed_and_rebuild(qtbot):
    """Reviewer Important #2: Inspector must relay fft_time_ctx
    rebuild_time_requested and signal_changed."""
    from mf4_analyzer.ui.inspector import Inspector

    insp = Inspector()
    qtbot.addWidget(insp)

    rebuild_seen = []
    sig_seen = []
    insp.rebuild_time_requested.connect(lambda anchor, mode: rebuild_seen.append(mode))
    insp.fft_time_signal_changed.connect(lambda d: sig_seen.append(d))

    insp.fft_time_ctx.btn_rebuild.click()
    assert rebuild_seen == ['fft_time']

    insp.fft_time_ctx.signal_changed.emit(('f1', 'ch'))
    assert sig_seen == [('f1', 'ch')]


# ---------------------------------------------------------------------------
# FFT vs Time cache invalidation hooks (Plan Task 8)
# ---------------------------------------------------------------------------


def test_fft_time_cache_clears_on_close_all(qtbot):
    """``close_all`` is the wholesale cache-wipe site (T5 flag site #2,
    close-all variant)."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._fft_time_cache[
        ('f1', 'ch', (0, 1), 1000.0, 8, 'hanning', 0.5, True, 1.0)
    ] = object()
    # close_all early-returns when self.files is empty, so prime a
    # placeholder file entry so the body actually runs and exercises
    # the new cache-clear line.
    win.files['f1'] = object()
    win.navigator.add_file = lambda *a, **kw: None  # silence side effects
    win.navigator.remove_file = lambda *a, **kw: None
    win.close_all()
    assert len(win._fft_time_cache) == 0


def test_fft_time_cache_clears_for_fid_on_rebuild(qtbot):
    """Per-fid targeted clear: rebuild_time_axis on file f1 must drop
    only f1's entries, leaving f2's entries intact."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._fft_time_cache[
        ('f1', 'ch', (0, 1), 1000.0, 8, 'hanning', 0.5, True, 1.0)
    ] = object()
    win._fft_time_cache[
        ('f2', 'ch', (0, 1), 1000.0, 8, 'hanning', 0.5, True, 1.0)
    ] = object()
    win._fft_time_cache_clear_for_fid('f1')
    assert all(k[0] != 'f1' for k in win._fft_time_cache)
    assert any(k[0] == 'f2' for k in win._fft_time_cache)


def test_fft_time_rebuild_popover_resolves_signal_via_fft_time_ctx(
    qtbot, monkeypatch
):
    """T5 flagged: ``_show_rebuild_popover(anchor, mode='fft_time')``
    must read the signal from ``inspector.fft_time_ctx.current_signal()``,
    not from ``order_ctx`` (the previous else-branch fallback). Confirm
    by spying on each ctx's ``current_signal`` and asserting only
    ``fft_time_ctx`` was queried for selection on a fft_time dispatch.
    """
    from PyQt5.QtWidgets import QDialog
    from mf4_analyzer.ui import main_window as mw_mod
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    # Wire one fake file so the post-accept branch can run.
    class _StubFD:
        filename = 'stub'
        short_name = 'stub'
        fs = 1000.0
        time_array = []
        def rebuild_time_axis(self, new_fs):
            self.fs = new_fs

    fd = _StubFD()
    win.files['fX'] = fd

    # Spy each ctx's current_signal.
    calls = {'fft': 0, 'fft_time': 0, 'order': 0}

    def make_spy(name, retval):
        def spy():
            calls[name] += 1
            return retval
        return spy

    win.inspector.fft_ctx.current_signal = make_spy('fft', None)
    win.inspector.fft_time_ctx.current_signal = make_spy(
        'fft_time', ('fX', 'ch_a')
    )
    win.inspector.order_ctx.current_signal = make_spy('order', None)

    # Stub the popover so exec_() returns Rejected — keeps the test
    # from blocking on a modal and lets the signal-resolution branch
    # be the only thing exercised.
    class _StubPopover:
        def __init__(self, parent, fname, fs):
            pass
            self._fs = fs
        def show_at(self, anchor):
            pass
        def exec_(self):
            return QDialog.Rejected
        def new_fs(self):
            return 500

    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.rebuild_time_popover.RebuildTimePopover',
        _StubPopover,
    )

    # Suppress toast so a missing-signal fallthrough surfaces as an
    # assertion failure rather than a UI side effect.
    win.toast = lambda *a, **kw: None

    win._show_rebuild_popover(anchor=None, mode='fft_time')

    # fft_time_ctx must have been the source. Other ctxs must not be
    # queried for the fft_time mode dispatch.
    assert calls['fft_time'] >= 1
    assert calls['fft'] == 0
    assert calls['order'] == 0


# ---------------------------------------------------------------------------
# FFT vs Time worker thread (Plan Task 7)
# ---------------------------------------------------------------------------


def test_fft_time_worker_emits_finished(qtbot):
    """Happy-path smoke: a small spectrogram run on a worker QThread
    must emit ``finished`` with a SpectrogramResult-like payload.

    ``thread.quit`` is thread-safe (per Qt docs); we wire it with a
    DirectConnection so it fires on the worker thread without going
    through the main event loop. Without that, ``thread.wait(5000)``
    blocks the main thread, the queued ``finished -> thread.quit`` slot
    cannot drain, and the wait deadlocks.
    """
    import numpy as np
    from PyQt5.QtCore import Qt, QThread
    from mf4_analyzer.signal.spectrogram import SpectrogramParams
    from mf4_analyzer.ui.main_window import FFTTimeWorker

    fs = 1000.0
    nfft = 256
    t = np.arange(2048) / fs
    sig = np.sin(2 * np.pi * 100 * t)
    worker = FFTTimeWorker(sig, t, SpectrogramParams(fs=fs, nfft=nfft), 'ch', 'V')
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    results = []
    # ``finished -> results.append`` is allowed to be queued (we read
    # the list after thread.wait returns, so we just need the emission
    # itself to have happened — Qt buffers queued emissions on the
    # receiver thread's queue once the connection fires the post).
    # But to actually USE that buffer here we must let the main loop
    # run; simpler: store via a DirectConnection lambda.
    worker.finished.connect(lambda r: results.append(r), Qt.DirectConnection)
    worker.finished.connect(thread.quit, Qt.DirectConnection)

    thread.start()
    assert thread.wait(5000)

    assert len(results) == 1
    # SpectrogramResult.amplitude is (freq_bins, frames); at least one
    # frame must be present.
    assert results[0].amplitude.shape[1] > 0


def test_fft_time_worker_cancels(qtbot):
    """``worker.cancel()`` flips the cancel token; the analyzer raises
    ``RuntimeError('spectrogram computation cancelled')`` mid-loop and
    the worker re-emits the message via ``failed``.

    overlap=0.9 + 200k samples gives ~thousands of frames so cancel
    has time to fire before the loop finishes.
    """
    import numpy as np
    from PyQt5.QtCore import Qt, QThread
    from mf4_analyzer.signal.spectrogram import SpectrogramParams
    from mf4_analyzer.ui.main_window import FFTTimeWorker

    fs = 1000.0
    nfft = 64
    n = 200_000  # many frames so cancel has time to fire
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 100 * t)
    worker = FFTTimeWorker(
        sig, t, SpectrogramParams(fs=fs, nfft=nfft, overlap=0.9), 'ch', 'V'
    )
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    failures = []
    # DirectConnection (thread-safe slots) so thread.wait(5000) does not
    # deadlock waiting on a queued main-thread event drain.
    worker.failed.connect(lambda m: failures.append(m), Qt.DirectConnection)
    worker.failed.connect(thread.quit, Qt.DirectConnection)

    thread.start()
    worker.cancel()
    assert thread.wait(5000)

    assert any('cancel' in f.lower() for f in failures)


# ---------------------------------------------------------------------------
# FFT vs Time export to clipboard (Plan Task 9)
# ---------------------------------------------------------------------------


def test_copy_fft_time_image_warns_when_no_result(qtbot, monkeypatch):
    """No SpectrogramResult on the canvas → warning toast and the
    clipboard MUST NOT receive a pixmap. Guards against pushing a
    blank/garbage image to the system clipboard."""
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    # Sanity: the canvas starts with no result.
    assert not win.canvas_fft_time.has_result()

    captured = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': captured.append((msg, level)),
    )

    # Spy on clipboard.setPixmap so we can assert it was NOT called.
    cb = QApplication.clipboard()
    set_calls = []
    orig_set = cb.setPixmap
    monkeypatch.setattr(cb, 'setPixmap', lambda pix: set_calls.append(pix))

    win._copy_fft_time_image(mode='full')
    win._copy_fft_time_image(mode='main')

    # Two warning toasts (one per call); no clipboard mutation.
    assert any(level == 'warning' for _msg, level in captured)
    assert set_calls == []
    # Restore (defensive — qtbot teardown also handles this).
    monkeypatch.setattr(cb, 'setPixmap', orig_set)


def test_copy_fft_time_image_pushes_pixmap_when_has_result(qtbot, monkeypatch):
    """With a SpectrogramResult plotted, both modes must succeed:
    clipboard receives a non-null QPixmap, status bar shows the
    Chinese success message, and a success toast fires."""
    import numpy as np
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    result = SpectrogramResult(
        times=np.array([0.0, 0.1, 0.2]),
        frequencies=np.array([0.0, 50.0, 100.0]),
        amplitude=np.ones((3, 3), dtype=np.float32),
        params=SpectrogramParams(fs=200.0, nfft=8),
        channel_name='demo',
    )
    win.canvas_fft_time.plot_result(result, amplitude_mode='amplitude')
    assert win.canvas_fft_time.has_result()

    captured = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': captured.append((msg, level)),
    )

    cb = QApplication.clipboard()
    pushed = []
    monkeypatch.setattr(cb, 'setPixmap', lambda pix: pushed.append(pix))

    # Mode='full' first.
    win._copy_fft_time_image(mode='full')
    assert pushed, "clipboard.setPixmap should have been called"
    assert not pushed[-1].isNull()
    assert "完整视图" in win.statusBar.currentMessage()
    assert any(level == 'success' and '完整视图' in msg for msg, level in captured)

    # Mode='main' next — clipboard receives a fresh pixmap.
    win._copy_fft_time_image(mode='main')
    assert len(pushed) == 2
    assert not pushed[-1].isNull()
    assert "主图" in win.statusBar.currentMessage()
    assert any(level == 'success' and '主图' in msg for msg, level in captured)


# ---------------------------------------------------------------------------
# FFT vs Time non-uniform UX (Plan Task 11)
# ---------------------------------------------------------------------------


def _stub_fft_time_signal(win, monkeypatch):
    """Wire ``_get_fft_time_signal`` + inspector params so do_fft_time
    can dispatch a worker without a real loaded file. Mirrors the
    pattern used by ``test_fft_time_failed_compute_keeps_old_chart``.
    """
    import numpy as np
    monkeypatch.setattr(
        win, '_get_fft_time_signal',
        lambda: ('f1', 'ch', np.linspace(0, 1, 32), np.ones(32), object()),
    )
    p = dict(
        fid='f1', channel='ch', fs=100.0, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params', lambda: p)
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)
    return p


class _NonUniformFakeFD:
    """Duck-typed FileData stand-in whose pre-flight predicate returns
    False until ``rebuild_time_axis`` is called.

    The 2026-04-30 UX contract auto-rebuilds the time axis with the
    median-dt Fs estimate instead of opening a blocking rebuild popover.
    """

    def __init__(self):
        import numpy as _np
        self.fs = 100.0
        nominal_dt = 1.0 / self.fs
        dts = _np.resize(_np.array([1.2 * nominal_dt, 0.8 * nominal_dt]), 31)
        self.time_array = _np.concatenate(([0.0], _np.cumsum(dts)))
        self.channel_units = {'ch': ''}
        self._uniform = False
        self.rebuilt_with = None

    def is_time_axis_uniform(self, tolerance=None):
        return self._uniform

    def suggested_fs_from_time_axis(self):
        return 100.0

    def rebuild_time_axis(self, new_fs):
        import numpy as _np
        self.fs = float(new_fs)
        self.rebuilt_with = float(new_fs)
        self.time_array = _np.arange(len(self.time_array), dtype=float) / self.fs
        self._uniform = True


def _stub_fft_time_signal_nonuniform(win, monkeypatch):
    """Variant of ``_stub_fft_time_signal`` that swaps the opaque
    ``object()`` fd for a duck-typed fake whose
    ``is_time_axis_uniform()`` returns False, so the new pre-flight
    path actually fires."""
    import numpy as np
    fake_fd = _NonUniformFakeFD()
    monkeypatch.setattr(
        win, '_get_fft_time_signal',
        lambda: (
            'f1', 'ch',
            np.asarray(fake_fd.time_array, dtype=float),
            np.ones(32),
            fake_fd,
        ),
    )
    p = dict(
        fid='f1', channel='ch', fs=100.0, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params',
                        lambda: dict(p, fs=fake_fd.fs))
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)
    return p, fake_fd


def test_fft_time_non_uniform_auto_rebuilds_without_popover(qtbot, monkeypatch):
    """Non-uniform single-file FFT-vs-Time should auto-rebuild and compute."""
    import numpy as np
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    _, fake_fd = _stub_fft_time_signal_nonuniform(win, monkeypatch)
    monkeypatch.setattr(
        win,
        '_show_rebuild_popover',
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError('auto path must not open rebuild popover')
        ),
    )

    good = SpectrogramResult(
        times=np.linspace(0.0, 1.0, 4),
        frequencies=np.linspace(0.0, 50.0, 3),
        amplitude=np.ones((3, 4), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 4, 'hop': 4, 'freq_bins': 3},
    )
    compute_calls = {'n': 0}

    def fake_compute(*a, **kw):
        compute_calls['n'] += 1
        return good

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        'compute',
        staticmethod(fake_compute),
    )

    captured = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': captured.append((msg, level)),
    )

    win.do_fft_time(force=True)
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)

    assert fake_fd.rebuilt_with == 100.0
    assert fake_fd.is_time_axis_uniform() is True
    assert compute_calls['n'] == 1
    assert len(win._fft_time_cache) == 1
    assert not any(level == 'warning' and '请重建' in msg for msg, level in captured)
    assert 'FFT vs Time 错误' not in win.statusBar.currentMessage()


def test_fft_time_non_uniform_auto_dispatches_worker_once(qtbot, monkeypatch):
    """Auto rebuild proceeds inline; there is no retry round-trip."""
    import numpy as np
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _, fake_fd = _stub_fft_time_signal_nonuniform(win, monkeypatch)

    good = SpectrogramResult(
        times=np.linspace(0.0, 1.0, 4),
        frequencies=np.linspace(0.0, 50.0, 3),
        amplitude=np.ones((3, 4), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 4, 'hop': 4, 'freq_bins': 3},
    )
    call_state = {'compute_calls': 0}

    def fake_compute(*a, **kw):
        call_state['compute_calls'] += 1
        return good

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer, 'compute', staticmethod(fake_compute)
    )

    monkeypatch.setattr(
        win,
        '_show_rebuild_popover',
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError('auto path must not open rebuild popover')
        ),
    )
    monkeypatch.setattr(win, 'toast', lambda *a, **kw: None)

    invocations = {'count': 0}
    real_do = win.do_fft_time

    def counted_do(force=False):
        invocations['count'] += 1
        return real_do(force=force)

    monkeypatch.setattr(win, 'do_fft_time', counted_do)

    win.do_fft_time(force=False)
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)

    # Exactly one invocation (no retry in the T2 model).
    assert invocations['count'] == 1, \
        f'T2 contract: pre-flight proceeds in-line, no retry. got {invocations["count"]}'
    # Analyzer ran exactly once on the now-uniform axis.
    assert call_state['compute_calls'] == 1
    # Successful compute pushed exactly one result into the LRU.
    assert len(win._fft_time_cache) == 1
    assert fake_fd.rebuilt_with == 100.0


def test_fft_time_non_uniform_auto_rebuilds_with_suggested_fs(qtbot, monkeypatch):
    """The automatic path should use suggested_fs_from_time_axis()."""
    import numpy as np
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    _, fake_fd = _stub_fft_time_signal_nonuniform(win, monkeypatch)
    fake_fd.suggested_fs_from_time_axis = lambda: 250.0

    good = SpectrogramResult(
        times=np.linspace(0.0, 1.0, 4),
        frequencies=np.linspace(0.0, 50.0, 3),
        amplitude=np.ones((3, 4), dtype=np.float32),
        params=SpectrogramParams(fs=250.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 4, 'hop': 4, 'freq_bins': 3},
    )
    seen = {}

    def fake_compute(signal, time, params, **kw):
        seen['fs'] = params.fs
        seen['dt'] = float(np.median(np.diff(time)))
        return good

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        'compute',
        staticmethod(fake_compute),
    )
    monkeypatch.setattr(
        win,
        '_show_rebuild_popover',
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError('auto path must not open rebuild popover')
        ),
    )
    monkeypatch.setattr(win, 'toast', lambda *a, **kw: None)

    win.do_fft_time(force=True)
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)

    assert fake_fd.rebuilt_with == 250.0
    assert seen['fs'] == 250.0
    assert abs(seen['dt'] - (1.0 / 250.0)) < 1e-12
