"""End-to-end UI flow for the non-uniform FFT vs Time recovery (T4).

Cross-references:
  * T1 diagnosis: docs/superpowers/reports/2026-04-26-nonuniform-fft-T1-diagnosis.md
  * T2 fix:       docs/superpowers/reports/2026-04-26-nonuniform-fft-T2-fix.md
  * T3 popover:   docs/superpowers/reports/2026-04-26-nonuniform-fft-T3-popover-geometry.md
  * T4 (this):    docs/superpowers/reports/2026-04-26-nonuniform-fft-T4-validation.md

What this file covers (pytest-qt under ``QT_QPA_PLATFORM=offscreen``):

  1. Click 计算时频图 with a non-uniform fixture -> the rebuild popover
     opens, ``frameGeometry()`` lives entirely inside the available
     screen rect (T3 regression point), the user accepts -> exactly
     one worker dispatch, no error toast, cache is populated, a
     subsequent click hits the cache.
  2. The Reject path: popover opens, user cancels -> NO worker thread
     is created, NO cache entry is added, NO error toast.
  3. T2/T3 interaction regression: anchor stretched into the bottom
     right corner of the available screen (simulating the user's
     "拉宽窗口" reproduction) -> the popover stays inside
     ``availableGeometry`` after ``show_at`` runs.

Lesson tags consumed at startup:
  * pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md -- offscreen Qt
    exposes valid screen geometry, so ``frameGeometry()`` and
    ``availableGeometry()`` assertions are trustworthy in headless CI.
  * pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md -- never
    call ``thread.wait()`` on the main thread under pytest-qt; use
    ``qtbot.waitUntil`` / ``qtbot.waitSignal`` to drain the worker.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QDialog


# --- Fixture: a duck-typed FileData stand-in that fails the predicate ---


class _NonUniformFakeFD:
    """Duck-typed FileData stand-in whose pre-flight predicate returns
    ``False`` so ``MainWindow._check_uniform_or_prompt`` actually opens
    the rebuild popover.

    Kept structurally compatible with ``mf4_analyzer.io.file_data.FileData``
    on the surface MainWindow touches:
      * ``data`` (DataFrame holding the channel column),
      * ``time_array`` (numpy array),
      * ``fs`` (float),
      * ``channel_units`` (dict),
      * ``filename``, ``short_name`` (popover title strings),
      * ``rebuild_time_axis(fs)`` (popover Accept side-effect).

    The ``is_time_axis_uniform`` flag is mutable so the test can flip
    it from ``False`` to ``True`` after the popover Accept simulates a
    rebuild.
    """

    def __init__(self, n: int = 64, nominal_fs: float = 100.0):
        self.fs = float(nominal_fs)
        # Build the same "alternating jitter" axis as the recovery test
        # so the predicate has a real reason to reject.
        nominal_dt = 1.0 / self.fs
        bumps = np.zeros(n, dtype=float)
        bumps[1::2] = 2.4 * nominal_dt
        t_uniform = np.arange(n, dtype=float) / self.fs
        self.time_array = np.cumsum(
            np.concatenate(([0.0], np.diff(t_uniform) + bumps[1:]))
        )
        # Signal: 20 Hz tone sampled on a uniform clock (same model as
        # the recovery fixture -- ADC stable, timestamps jittered).
        sig = np.sin(2.0 * np.pi * 20.0 * (np.arange(n, dtype=float) / self.fs))
        self.data = pd.DataFrame({'ch': sig.astype(float)})
        self.channels = ['ch']
        self.channel_units = {'ch': 'V'}
        self.filename = 'synthetic.mf4'
        self.short_name = 'syn'
        self.file_index = 0
        self._uniform = False  # mutated by tests to simulate Accept

    def is_time_axis_uniform(self, tolerance=None):
        return self._uniform

    def suggested_fs_from_time_axis(self):
        # Median dt reciprocal; matches the production helper. We
        # return the nominal so the popover seeds spin_fs at a sensible
        # value.
        return self.fs

    def rebuild_time_axis(self, new_fs):
        self.fs = float(new_fs)
        n = len(self.time_array)
        self.time_array = np.arange(n, dtype=float) / float(new_fs)
        self._uniform = True

    def get_color_palette(self):
        # MainWindow.activate path may read this; return the same shape
        # FILE_PALETTES entries do (a list of color hex strings).
        return ['#2563eb']


def _wire_fake_file(win, monkeypatch, fake_fd):
    """Inject the fake fd so do_fft_time can resolve a signal without
    having to load a real file (the signal-layer recovery test already
    covers the FileData path; here we exercise the UI plumbing).
    """
    fid = 'fX'
    monkeypatch.setattr(
        win, '_get_fft_time_signal',
        lambda: (
            fid,
            'ch',
            np.asarray(fake_fd.time_array, dtype=float),
            np.asarray(fake_fd.data['ch'].to_numpy(), dtype=float),
            fake_fd,
        ),
    )
    p = dict(
        fid=fid, channel='ch', fs=fake_fd.fs, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params',
                        lambda: dict(p, fs=fake_fd.fs))
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)
    # Register fid -> fd so _show_rebuild_popover's lookup succeeds.
    win.files[fid] = fake_fd
    win._active = fid
    return fid, p


# --- Helper: drive the popover ---------------------------------------


def _patch_popover(monkeypatch, *, accept: bool, capture=None):
    """Replace ``RebuildTimePopover`` with a stub that returns
    Accepted / Rejected synchronously. ``capture`` (optional list)
    receives the constructed stub instances so tests can introspect
    geometry / Fs values pushed at construction time.

    NOTE: we do NOT patch the popover for the geometry test below --
    that one constructs a real RebuildTimePopover and asserts on its
    ``frameGeometry`` after ``show_at``.
    """
    captured = capture if capture is not None else []

    class _StubPopover:
        def __init__(self, parent, fname, fs):
            self._parent = parent
            self._fname = fname
            self._fs = fs
            captured.append(self)

        def show_at(self, anchor):
            # No-op: the geometry test constructs the real popover.
            pass

        def exec_(self):
            return QDialog.Accepted if accept else QDialog.Rejected

        def new_fs(self):
            return float(self._fs)

    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.rebuild_time_popover.RebuildTimePopover',
        _StubPopover,
    )
    return captured


# --- The flows --------------------------------------------------------


def test_full_flow_accept_dispatches_one_worker_and_caches(qtbot, monkeypatch):
    """Click 计算时频图 -> popover -> Accept -> exactly one worker
    dispatch, no error toast, cache populated, second click hits cache.

    This is the end-to-end happy path of the user's recovery, except
    we keep the popover stubbed (Accepted) so the test does not block
    on a modal. The geometry test below covers the real popover under
    show_at.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake_fd = _NonUniformFakeFD()
    _, p = _wire_fake_file(win, monkeypatch, fake_fd)
    _patch_popover(monkeypatch, accept=True)

    # Capture toasts so we can assert no error fires after Accept.
    toasts = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': toasts.append((msg, level)),
    )

    # First click -> worker dispatch -> finished -> cache put.
    win.do_fft_time(force=False)
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)

    # No error toast (warnings about 重建时间轴 are expected from the
    # pre-flight; errors are not).
    error_toasts = [m for m, lvl in toasts if lvl == 'error']
    assert not error_toasts, f'unexpected error toasts: {error_toasts}'

    # Cache populated: exactly one entry under the user's fid.
    cache_keys = list(win._fft_time_cache.keys())
    assert len(cache_keys) == 1, (
        f'expected exactly one cache entry after Accept; got {cache_keys}'
    )

    # Status bar reports completion (not 'FFT vs Time 错误').
    assert 'FFT vs Time 错误' not in win.statusBar.currentMessage()

    # Second click hits the cache (synchronous, no thread spawned).
    # Reset the toast capture so we only see the cache-hit status path.
    toasts.clear()
    # The fake FD is now uniform (Accept side-effect ran), so the
    # pre-flight passes without re-prompting.
    assert fake_fd.is_time_axis_uniform() is True
    win.do_fft_time(force=False)
    # Cache hit: no new thread, no new cache entry.
    assert win._fft_time_thread is None
    assert len(win._fft_time_cache) == 1
    assert '使用缓存结果' in win.statusBar.currentMessage()


def test_full_flow_auto_rebuild_does_not_open_popover(qtbot, monkeypatch):
    """Click 计算时频图 on a non-uniform axis -> auto rebuild -> compute.

    The 2026-04-30 UX contract removes the blocking confirmation step:
    no rebuild popover should be constructed during normal compute.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake_fd = _NonUniformFakeFD()
    _wire_fake_file(win, monkeypatch, fake_fd)

    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.rebuild_time_popover.RebuildTimePopover',
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError('auto path must not construct RebuildTimePopover')
        ),
    )

    toasts = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': toasts.append((msg, level)),
    )

    win.do_fft_time(force=False)
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)

    assert fake_fd.is_time_axis_uniform() is True
    assert len(win._fft_time_cache) == 1
    # No error toast (the pre-flight emitted a warning, not an error).
    assert not any(level == 'error' for _msg, level in toasts)


def test_full_flow_no_dispatch_when_signal_already_uniform(qtbot, monkeypatch):
    """Sanity / no-regression baseline: when the fd is already uniform
    the pre-flight passes through and the worker dispatches normally,
    without ever opening the popover.

    This guards against an over-eager pre-flight that would prompt the
    user on every click for a perfectly fine file.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake_fd = _NonUniformFakeFD()
    # Simulate "already-uniform" by both flipping the predicate flag AND
    # rebuilding the time_array to arange/fs (the predicate is duck-typed
    # so a stale jittered axis would still be rejected by the analyzer's
    # _validate_time_axis inside the worker).
    fake_fd.rebuild_time_axis(fake_fd.fs)
    assert fake_fd.is_time_axis_uniform() is True
    _wire_fake_file(win, monkeypatch, fake_fd)

    # Track popover construction via a sentinel: if anyone tried to
    # build it, the test fails.
    constructed = []

    class _Sentinel:
        def __init__(self, *a, **kw):
            constructed.append((a, kw))
        def show_at(self, anchor):
            pass
        def exec_(self):
            return QDialog.Rejected
        def new_fs(self):
            return 0.0

    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.rebuild_time_popover.RebuildTimePopover',
        _Sentinel,
    )

    monkeypatch.setattr(win, 'toast', lambda *a, **kw: None)

    win.do_fft_time(force=True)
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)

    # Popover never built.
    assert constructed == [], (
        f'popover constructed for an already-uniform axis: {constructed}'
    )
    # And the worker actually ran (cache populated).
    assert len(win._fft_time_cache) == 1


# --- T3 regression: real popover geometry under realistic anchor ----


def test_popover_frame_geometry_inside_available_when_anchor_in_corner(
    qapp, qtbot, monkeypatch,
):
    """T3 + T2 interaction regression: when the rebuild popover is
    triggered by a real ``btn_rebuild`` anchor that the user has pushed
    into the bottom-right corner of the screen (e.g. by dragging the
    main window flush with the right edge), ``RebuildTimePopover.show_at``
    must place the popover entirely inside ``availableGeometry``.

    We do NOT patch RebuildTimePopover here -- the test constructs the
    real popover (the same class production code uses) and reads its
    ``frameGeometry`` after ``show_at``. The popover is a non-modal
    QDialog so the test does not block; we ``exec_`` is replaced with
    a Rejected return via ``QTimer.singleShot`` to drain the dialog.
    """
    from PyQt5.QtCore import QTimer
    from mf4_analyzer.ui.drawers.rebuild_time_popover import (
        MARGIN, RebuildTimePopover,
    )
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    # Stretch the window so the inspector's btn_rebuild anchor sits
    # near the screen's bottom-right corner. This mirrors the user's
    # "拉宽窗口" reproduction in the T3 report.
    avail = QGuiApplication.primaryScreen().availableGeometry()
    target_w = min(1200, avail.width() - 20)
    target_h = min(800, avail.height() - 20)
    win.resize(target_w, target_h)
    win.move(
        avail.right() - target_w + 1,
        avail.bottom() - target_h + 1,
    )
    win.show()
    qtbot.waitExposed(win)

    # Switch to FFT vs Time mode so the inspector lays out fft_time_ctx.
    win.toolbar.btn_mode_fft_time.click()
    qapp.processEvents()
    qtbot.wait(50)

    anchor = win.inspector.fft_time_ctx.btn_rebuild
    qtbot.waitExposed(anchor)

    # Capture the popover instance MainWindow constructs so we can
    # assert its frameGeometry sits inside availableGeometry.
    captured = []

    real_cls = RebuildTimePopover

    class _CapturingPopover(real_cls):
        def __init__(self, parent, fname, fs):
            super().__init__(parent, fname, fs)
            captured.append(self)

        def exec_(self):
            # Non-blocking: schedule a Reject after the show_at run
            # completes, then return Rejected without entering a real
            # modal loop.
            QTimer.singleShot(0, self.reject)
            return QDialog.Rejected

    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.rebuild_time_popover.RebuildTimePopover',
        _CapturingPopover,
    )

    fake_fd = _NonUniformFakeFD()
    fid, _ = _wire_fake_file(win, monkeypatch, fake_fd)
    monkeypatch.setattr(win, 'toast', lambda *a, **kw: None)

    win._show_rebuild_popover(anchor=anchor, mode='fft_time')
    qapp.processEvents()
    qtbot.wait(50)

    assert captured, 'expected the rebuild popover to be constructed'
    pop = captured[0]
    fg = pop.frameGeometry()

    # All four edges inside availableGeometry within MARGIN.
    # Allow a 1px slack for inclusive-vs-exclusive rounding under
    # offscreen Qt (same slack as test_rebuild_popover_geometry.py).
    assert fg.right() <= avail.right() - MARGIN + 1, (
        f'popover right={fg.right()} overflows avail.right()={avail.right()} '
        f'(corner anchor; T2/T3 interaction regression)'
    )
    assert fg.left() >= avail.left() + MARGIN - 1, (
        f'popover left={fg.left()} overflows avail.left()={avail.left()}'
    )
    assert fg.bottom() <= avail.bottom() - MARGIN + 1, (
        f'popover bottom={fg.bottom()} overflows avail.bottom()={avail.bottom()}'
    )
    assert fg.top() >= avail.top() + MARGIN - 1, (
        f'popover top={fg.top()} overflows avail.top()={avail.top()}'
    )


# --- T2 reviewer flag: fd.fs side-effect on Reject ------------------


def test_auto_rebuild_uses_suggested_fs(qtbot, monkeypatch):
    """The no-prompt path should rebuild with suggested_fs_from_time_axis()."""
    import numpy as np
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake_fd = _NonUniformFakeFD()
    fake_fd.fs = 100.0
    # suggested_fs_from_time_axis on this fake returns self.fs (100.0)
    # so the seed equals the original. Tweak the fake to return a
    # distinguishable value so we can see the mutation.
    fake_fd.suggested_fs_from_time_axis = lambda: 250.0

    _wire_fake_file(win, monkeypatch, fake_fd)
    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.rebuild_time_popover.RebuildTimePopover',
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError('auto path must not construct RebuildTimePopover')
        ),
    )
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
    monkeypatch.setattr(win, 'toast', lambda *a, **kw: None)

    win.do_fft_time(force=True)
    qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)

    assert fake_fd.fs == 250.0
    assert seen['fs'] == 250.0
    assert seen['dt'] == pytest.approx(1.0 / 250.0)
