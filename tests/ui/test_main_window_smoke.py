from mf4_analyzer.ui.main_window import MainWindow


def test_main_window_constructs(qapp):
    w = MainWindow()
    assert w.toolbar is not None
    assert w.navigator is not None
    assert w.chart_stack is not None
    assert w.inspector is not None


def test_fft_time_effective_auto_nfft_resolves_before_cache_key(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)

    p = {
        "fid": "f1",
        "channel": "speed",
        "time_range": (0.0, 52.1),
        "fs": 96.0,
        "nfft": None,
        "nfft_mode": "auto",
        "t_win_s": 1.5,
        "overlap": 0.75,
        "window": "hanning",
        "remove_mean": True,
        "db_reference": 1.0,
    }
    effective = w._resolve_fft_time_effective_params(p, 5002)

    assert effective["nfft"] == 256
    assert effective["nfft_effective"] == 256
    assert effective["nfft_mode"] == "auto"
    key = w._fft_time_cache_key(effective)
    assert isinstance(key[4], int)
    assert key[4] == 256

    fixed = w._resolve_fft_time_effective_params(
        dict(p, nfft=1024, nfft_mode="fixed"), 5002
    )
    assert fixed["nfft"] == 1024
    assert fixed["nfft_effective"] == 1024
    assert fixed["nfft_mode"] == "fixed"


def test_fft_time_analysis_cache_key_auto_uses_effective_nfft(
    qapp, qtbot, monkeypatch
):
    import json
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    w = MainWindow()
    qtbot.addWidget(w)
    t = np.arange(5002, dtype=float) / 96.0
    sig = np.sin(2.0 * np.pi * 3.0 * t)
    w.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"speed": sig}),
        time_array=t,
        channel_units={"speed": "rpm"},
    )
    params = {
        "fs": 96.0,
        "nfft": None,
        "nfft_mode": "auto",
        "t_win_s": 1.5,
        "nfft_preview": 256,
        "overlap": 0.75,
        "window": "hanning",
        "remove_mean": True,
        "db_reference": 1.0,
    }
    monkeypatch.setattr(w.inspector.fft_time_ctx, "get_params", lambda: params)

    generic_key = w._analysis_cache_key("fft_time", "f1", "speed", pane_idx=0)
    effective = w._resolve_fft_time_effective_params(params, len(sig))
    effective_key = w._fft_time_analysis_cache_key("f1", "speed", effective, 0)
    key_params = json.loads(generic_key[2])

    assert generic_key == effective_key
    assert key_params["nfft"] == 256


def test_fft_time_dispatch_uses_effective_auto_nfft(qapp, qtbot, monkeypatch):
    import numpy as np
    import pandas as pd
    from types import SimpleNamespace

    w = MainWindow()
    qtbot.addWidget(w)
    t = np.arange(5002, dtype=float) / 96.0
    sig = np.sin(2.0 * np.pi * 3.0 * t)
    w.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"speed": sig}),
        time_array=t,
        channel_units={"speed": "rpm"},
    )
    monkeypatch.setattr(w, "_check_uniform_or_prompt", lambda *_args: True)
    monkeypatch.setattr(
        w.inspector.fft_time_ctx,
        "get_params",
        lambda: {
            "fs": 96.0,
            "nfft": None,
            "nfft_mode": "auto",
            "t_win_s": 1.5,
            "overlap": 0.75,
            "window": "hanning",
            "remove_mean": True,
            "db_reference": 1.0,
            "amplitude_mode": "amplitude_db",
            "cmap": "turbo",
        },
    )

    seen = {}

    from mf4_analyzer.signal import spectrogram as spectrogram_mod

    def fake_compute(
        _sig,
        _time,
        params,
        channel_name="",
        unit="",
        progress_callback=None,
        cancel_token=None,
    ):
        seen["nfft"] = params.nfft
        seen["pending_nfft"] = w._fft_time_pending["render_params"]["nfft"]
        seen["cache_key_nfft"] = w._fft_time_pending["cache_key"][4]
        return object()

    class DummyProgress:
        def emit(self, *args):
            pass

    class DummyWorker:
        progress = DummyProgress()
        cancelled = False

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        "compute",
        staticmethod(fake_compute),
    )
    monkeypatch.setattr(
        w, "_start_fft_time_worker", lambda job: job(DummyWorker())
    )

    assert w._dispatch_fft_time_job(0, "f1", "speed", time_range=None)
    assert seen == {
        "nfft": 256,
        "pending_nfft": 256,
        "cache_key_nfft": 256,
    }


def test_fft_time_render_auto_frequency_range_uses_energy_band(qapp, qtbot):
    from types import SimpleNamespace

    import numpy as np

    w = MainWindow()
    qtbot.addWidget(w)

    class Canvas:
        def __init__(self):
            self.kwargs = None

        def plot_result(self, result, **kwargs):
            self.kwargs = kwargs

        def set_tick_density(self, xt, yt):
            pass

    freq = np.arange(0.0, 51.0, 1.0)
    amp = np.zeros((freq.size, 4), dtype=float)
    amp[1, :] = [0.2, 1.0, 0.5, 0.1]
    result = SimpleNamespace(
        times=np.arange(4, dtype=float),
        frequencies=freq,
        amplitude=amp,
        params=SimpleNamespace(db_reference=1.0),
        channel_name="speed",
        unit="rpm",
    )
    p = {
        "amplitude_mode": "amplitude",
        "cmap": "turbo",
        "freq_auto": True,
        "x_auto": True,
        "y_auto": True,
        "z_auto": True,
    }
    canvas = Canvas()

    w._render_fft_time_on(canvas, result, p)

    assert canvas.kwargs["freq_range"] == (0.0, 5.0)


def test_fft_time_render_manual_frequency_range_is_preserved(qapp, qtbot):
    from types import SimpleNamespace

    import numpy as np

    w = MainWindow()
    qtbot.addWidget(w)

    class Canvas:
        def __init__(self):
            self.kwargs = None

        def plot_result(self, result, **kwargs):
            self.kwargs = kwargs

        def set_tick_density(self, xt, yt):
            pass

    freq = np.arange(0.0, 51.0, 1.0)
    amp = np.zeros((freq.size, 2), dtype=float)
    amp[1, :] = 1.0
    result = SimpleNamespace(
        times=np.arange(2, dtype=float),
        frequencies=freq,
        amplitude=amp,
        params=SimpleNamespace(db_reference=1.0),
        channel_name="speed",
        unit="rpm",
    )
    p = {
        "amplitude_mode": "amplitude",
        "cmap": "turbo",
        "freq_auto": False,
        "freq_min": 2.0,
        "freq_max": 12.0,
        "x_auto": True,
        "y_auto": False,
        "z_auto": True,
    }
    canvas = Canvas()

    w._render_fft_time_on(canvas, result, p)

    assert canvas.kwargs["freq_range"] == (2.0, 12.0)


def test_fft_effective_auto_nfft_resolves_for_average_modes(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)

    base = {
        "window": "hanning",
        "nfft": None,
        "nfft_mode": "auto",
        "t_win_s": 1.5,
        "avg_mode": "线性平均",
        "avg_overlap": 75,
    }

    linear = w._resolve_fft_effective_params(base, 5002, 96.0)
    assert linear["nfft"] == 256
    assert linear["nfft_effective"] == 256
    assert linear["nfft_mode"] == "auto"

    peak_hold = w._resolve_fft_effective_params(
        dict(base, avg_mode="峰值保持"), 5002, 96.0
    )
    assert peak_hold["nfft"] == 256
    assert peak_hold["nfft_effective"] == 256

    high_fs = w._resolve_fft_effective_params(base, 60000, 1000.0)
    assert high_fs["nfft"] == 2048
    assert high_fs["nfft_effective"] == 2048

    single_frame = w._resolve_fft_effective_params(
        dict(base, avg_mode="单帧"), 5002, 96.0
    )
    assert single_frame["nfft"] is None
    assert single_frame["nfft_effective"] is None
    assert single_frame["nfft_mode"] == "auto"


def test_fft_compute_arrays_uses_effective_nfft_for_auto_average(
    qapp, qtbot, monkeypatch
):
    import numpy as np

    from mf4_analyzer.ui import main_window as main_window_mod

    w = MainWindow()
    qtbot.addWidget(w)
    sig = np.ones(5002, dtype=float)
    seen = {}

    def fake_averaged(_sig, _fs, _win, nfft, _overlap):
        seen["averaged"] = nfft
        freq = np.arange(4, dtype=float)
        amp = np.ones(4, dtype=float)
        return freq, amp, amp ** 2

    def fake_peak_hold(_sig, _fs, win, nfft, overlap):
        seen["peak"] = nfft
        return np.arange(4, dtype=float), np.ones(4, dtype=float)

    monkeypatch.setattr(
        main_window_mod.FFTAnalyzer,
        "compute_averaged_fft",
        staticmethod(fake_averaged),
    )
    monkeypatch.setattr(
        main_window_mod.FFTAnalyzer,
        "compute_peak_hold_fft",
        staticmethod(fake_peak_hold),
    )

    params = {
        "window": "hanning",
        "nfft": None,
        "nfft_effective": 256,
        "avg_mode": "线性平均",
        "avg_overlap": 75,
    }
    w._fft_compute_arrays(sig, 96.0, params)
    w._fft_compute_arrays(sig, 96.0, dict(params, avg_mode="峰值保持"))

    assert seen == {"averaged": 256, "peak": 256}


def test_plot_fft_entries_auto_xlim_uses_energy_band_and_manual_stays_fixed(
    qapp, qtbot, monkeypatch
):
    import numpy as np

    from mf4_analyzer.signal import energy_band_fmax

    class _Canvas:
        def __init__(self):
            self.plot_kwargs = None

        def plot_spectra(self, entries, **kwargs):
            self.plot_kwargs = kwargs

        def set_tick_density(self, _xt, _yt):
            pass

    w = MainWindow()
    qtbot.addWidget(w)
    freq = np.linspace(0.0, 50.0, 501)
    amp = np.zeros_like(freq)
    amp[np.argmin(np.abs(freq - 1.0))] = 10.0
    amp[np.argmin(np.abs(freq - 1.6))] = 4.0
    entry = {
        "label": "narrow",
        "color": "#2563eb",
        "freq": freq,
        "amp": amp,
        "time": [],
        "signal": [],
    }

    auto_canvas = _Canvas()
    w._plot_fft_entries([entry], auto_canvas)

    auto_xmax = auto_canvas.plot_kwargs["xlim"][1]
    assert auto_xmax == energy_band_fmax(freq, amp)
    assert 2.0 <= auto_xmax < freq[-1] * 0.25

    params = w.inspector.fft_ctx.current_params()
    monkeypatch.setattr(
        w.inspector.fft_ctx,
        "current_params",
        lambda: dict(params, x_auto=False, autoscale=False, x_min=0.0, x_max=80.0),
    )
    manual_canvas = _Canvas()
    w._plot_fft_entries([entry], manual_canvas)

    assert manual_canvas.plot_kwargs["xlim"] == (0.0, 80.0)


def test_fft_auto_xlim_keeps_broadband_spectrum_near_nyquist(qapp, qtbot):
    import numpy as np

    from mf4_analyzer.signal import energy_band_fmax

    w = MainWindow()
    qtbot.addWidget(w)
    freq = np.linspace(0.0, 50.0, 501)
    amp = np.ones_like(freq)

    assert w._fft_auto_xlim(freq, amp) == energy_band_fmax(freq, amp)
    assert w._fft_auto_xlim(freq, amp) == freq[-1]


def test_fft_analysis_cache_key_auto_uses_effective_nfft(qapp, qtbot, monkeypatch):
    import json
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    w = MainWindow()
    qtbot.addWidget(w)
    t_96 = np.arange(5002, dtype=float) / 96.0
    t_1000 = np.arange(60000, dtype=float) / 1000.0
    w.files["f96"] = SimpleNamespace(
        data=pd.DataFrame({"sig": np.sin(2.0 * np.pi * 3.0 * t_96)}),
        time_array=t_96,
        fs=96.0,
    )
    w.files["f1000"] = SimpleNamespace(
        data=pd.DataFrame({"sig": np.sin(2.0 * np.pi * 3.0 * t_1000)}),
        time_array=t_1000,
        fs=1000.0,
    )
    params = {
        "window": "hanning",
        "nfft": None,
        "nfft_mode": "auto",
        "t_win_s": 1.5,
        "avg_mode": "线性平均",
        "avg_overlap": 75,
    }
    monkeypatch.setattr(w.inspector.fft_ctx, "get_params", lambda: params)
    monkeypatch.setattr(w.inspector.fft_ctx, "current_params", lambda: params)

    key_96 = w._analysis_cache_key("fft", "f96", "sig", pane_idx=0)
    key_1000 = w._analysis_cache_key("fft", "f1000", "sig", pane_idx=0)

    params_96 = json.loads(key_96[2])
    params_1000 = json.loads(key_1000[2])
    assert params_96["nfft"] == 256
    assert params_1000["nfft"] == 2048
    assert key_96 != key_1000


def test_order_effective_auto_nfft_resolves_from_angle_domain(qapp, qtbot):
    import numpy as np

    from mf4_analyzer.signal import resolve_order_nfft

    w = MainWindow()
    qtbot.addWidget(w)
    t = np.arange(1000, dtype=float) / 100.0
    rpm = np.full_like(t, 1200.0)
    p = {
        "nfft": None,
        "nfft_mode": "auto",
        "samples_per_rev": 256,
        "order_res": 0.05,
    }

    effective = w._resolve_order_effective_params(p, rpm, t)
    n_angle = int(round(256 * np.trapezoid(np.abs(rpm) / 60.0, t)))
    expected = resolve_order_nfft(256, 0.05, n_angle)

    assert effective["nfft"] == expected
    assert effective["nfft_effective"] == expected
    assert effective["nfft_mode"] == "auto"
    assert effective["n_angle_samples"] == n_angle

    reverse = w._resolve_order_effective_params(p, -rpm, t)
    assert reverse["nfft"] == expected

    fixed = w._resolve_order_effective_params(
        dict(p, nfft=2048, nfft_mode="fixed"), rpm, t
    )
    assert fixed["nfft"] == 2048
    assert fixed["nfft_effective"] == 2048
    assert fixed["nfft_mode"] == "fixed"


def test_order_analysis_cache_key_auto_uses_effective_nfft(
    qapp, qtbot, monkeypatch
):
    import json
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    w = MainWindow()
    qtbot.addWidget(w)
    t = np.arange(1000, dtype=float) / 100.0
    sig = np.sin(2.0 * np.pi * 12.0 * t)
    rpm = np.full_like(t, 1200.0)
    w.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"sig": sig, "rpm": rpm}),
        time_array=t,
        fs=100.0,
        channel_units={"sig": "g", "rpm": "rpm"},
    )
    params = {
        "nfft": None,
        "nfft_mode": "auto",
        "nfft_preview": 8192,
        "window": "hanning",
        "max_order": 20.0,
        "order_res": 0.05,
        "time_res": 0.05,
    }
    current = dict(params, samples_per_rev=256)
    monkeypatch.setattr(w, "_pane_time_range_for", lambda *_args, **_kw: None)
    monkeypatch.setattr(w.inspector.order_ctx, "rpm_factor", lambda: 1.0)
    monkeypatch.setattr(w.inspector.order_ctx, "get_params", lambda: params)
    monkeypatch.setattr(w.inspector.order_ctx, "current_params", lambda: current)

    generic_key = w._analysis_cache_key(
        "order", "f1", "sig", rpm_source=("f1", "rpm"), pane_idx=0
    )
    effective = w._resolve_order_effective_params(current, rpm, t)
    key_params = json.loads(generic_key[2])

    assert key_params["nfft"] == effective["nfft_effective"]
    assert key_params["nfft_mode"] == "auto"
    assert key_params["rpm_source"] == ["f1", "rpm"]


def test_order_dispatch_uses_effective_auto_nfft(qtbot, monkeypatch):
    import numpy as np
    import pandas as pd
    from types import SimpleNamespace

    from PyQt5.QtCore import QThread

    from mf4_analyzer.signal import order_cot
    from mf4_analyzer.ui import main_window as mw_mod

    win = MainWindow()
    qtbot.addWidget(win)

    t = np.arange(1000, dtype=float) / 100.0
    sig = np.sin(2.0 * np.pi * 12.0 * t)
    rpm = np.full_like(t, 1200.0)
    win.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"sig": sig, "rpm": rpm}),
        time_array=t,
        fs=100.0,
        channel_units={"sig": "g", "rpm": "rpm"},
    )

    params = {
        "nfft": None,
        "nfft_mode": "auto",
        "nfft_preview": 8192,
        "window": "hanning",
        "max_order": 20.0,
        "order_res": 0.05,
        "time_res": 0.05,
    }
    current = dict(params, samples_per_rev=256, amplitude_mode="Amplitude dB")
    monkeypatch.setattr(win, "_pane_time_range_for", lambda *_args, **_kw: None)
    monkeypatch.setattr(win.inspector.order_ctx, "rpm_factor", lambda: 1.0)
    monkeypatch.setattr(win.inspector.order_ctx, "fs", lambda: 100.0)
    monkeypatch.setattr(win.inspector.order_ctx, "current_params", lambda: current)
    monkeypatch.setattr(win.inspector.order_ctx, "get_params", lambda: params)

    real_cot_params = order_cot.COTParams
    seen = {}

    def recording_cot_params(**kwargs):
        seen["nfft"] = kwargs["nfft"]
        return real_cot_params(**kwargs)

    monkeypatch.setattr(order_cot, "COTParams", recording_cot_params)

    started_threads = []
    QThreadBase = QThread

    class RecordingThread(QThreadBase):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.started_called = False
            started_threads.append(self)

        def start(self, priority=QThreadBase.InheritPriority):
            self.started_called = True

    monkeypatch.setattr(mw_mod, "QThread", RecordingThread)

    assert win._dispatch_order_job(0, "f1", "sig", ("f1", "rpm")) is True
    expected = win._resolve_order_effective_params(current, rpm, t)["nfft_effective"]
    assert seen["nfft"] == expected
    assert started_threads and started_threads[0].started_called is True


def test_main_window_moves_time_hints_to_status_line(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)

    hint_bar = w.chart_stack._time_hint_bar
    dock_layout = w.chart_stack._time_bottom_dock.layout()

    assert getattr(w, "_status_hint_bar") is hint_bar
    assert hint_bar.parentWidget() is w.statusBar
    assert dock_layout.indexOf(hint_bar) == -1
    assert dock_layout.indexOf(w.view_tabbar) >= 0
    assert dock_layout.count() == 1


def test_main_window_keeps_single_active_hint_bar_in_status_line(qapp, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QFrame, QToolButton

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qapp.processEvents()

    cards = {
        "time": w.chart_stack._time_card,
        "fft": w.chart_stack._fft_card,
        "fft_time": w.chart_stack._fft_time_card,
        "order": w.chart_stack._order_card,
    }
    for mode, card in cards.items():
        w.chart_stack.set_mode(mode)
        qapp.processEvents()

        active_bar = card._hint_bar
        assert getattr(w, "_status_hint_bar") is active_bar
        assert active_bar.parentWidget() is w.statusBar
        assert card.layout().indexOf(active_bar) == -1

        status_bars = [
            child
            for child in w.statusBar.findChildren(
                QFrame, "chartHintBar", Qt.FindDirectChildrenOnly
            )
            if not child.isHidden()
        ]
        assert status_bars == [active_bar]

        help_buttons = active_bar.findChildren(
            QToolButton, "chartHintQuickrefButton", Qt.FindDirectChildrenOnly
        )
        assert len(help_buttons) == 1
        assert active_bar.layout().indexOf(help_buttons[0]) == 0
        assert active_bar.layout().indexOf(card._hint_context) > 0

    active_bar = getattr(w, "_status_hint_bar")
    button = active_bar.findChild(
        QToolButton, "chartHintQuickrefButton", Qt.FindDirectChildrenOnly
    )
    qtbot.mouseClick(button, Qt.LeftButton)
    qapp.processEvents()
    assert w._quickref_panel is not None
    assert w._quickref_panel.isVisible()


def test_status_hint_quickref_button_stays_inside_bar_under_qss(qapp, qtbot):
    from pathlib import Path

    from PyQt5.QtWidgets import QToolButton

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        w = MainWindow()
        qtbot.addWidget(w)
        w.resize(1920, 1080)
        w.show()
        qtbot.waitExposed(w)
        qapp.processEvents()

        bar = w._status_hint_bar
        button = bar.findChild(QToolButton, "chartHintQuickrefButton")
        assert button is not None

        button_rect = button.geometry()
        bar_rect = bar.rect()
        assert button_rect.top() >= bar_rect.top()
        assert button_rect.bottom() <= bar_rect.bottom(), (
            f"quickref button {button_rect.getRect()} must fit inside "
            f"hint bar {bar_rect.getRect()} so its rounded bottom is not clipped"
        )
    finally:
        qapp.setStyleSheet(old_sheet)


def test_fft_quality_indicator_repositions_after_first_mode_layout(qapp, qtbot):
    """First FFT entry moves its hint bar to the status line, changing the
    child canvas height after the card has already shown.

    The quality indicator is card chrome positioned from the current canvas
    geometry, so it must follow that late child-layout pass.
    """
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1450, 850)
    w.show()
    qtbot.waitExposed(w)
    qapp.processEvents()

    w._on_mode_changed("fft")
    qapp.processEvents()
    qapp.processEvents()

    card = w.chart_stack._fft_card
    canvas_rect = card.canvas.geometry()
    dot_rect = card._quality_indicator.geometry()

    assert canvas_rect.contains(dot_rect.center())
    assert canvas_rect.right() - dot_rect.right() <= 12
    assert canvas_rect.bottom() - dot_rect.bottom() <= 12


def test_main_window_has_splitter_with_three_panes(qapp):
    w = MainWindow()
    # The central widget contains a QSplitter with 3 widgets
    from PyQt5.QtWidgets import QSplitter
    splitter = w.findChild(QSplitter)
    assert splitter is not None
    assert splitter.count() == 3


def test_main_window_splitter_default_sizes_align_with_inspector_cap(qapp, qtbot):
    """fix-5 — the inspector's default splitter slot must match the
    Inspector's content max-width (~288) so the user does not see a
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
    # Inspector pane is the third slot (narrowed 360 → 288 to match the left
    # file column). >= 270 keeps content within cap; > 320 would mean the
    # splitter assigned more space than the content can ever fill.
    assert 270 <= sizes[2] <= 320, (
        f"inspector default splitter size {sizes[2]} should be ~288 to "
        "match Inspector._scroll_body.maximumWidth (R3 紧凑化 fix-5)."
    )
    # Inspector minimumWidth must remain <= the default sized slot.
    assert w.inspector.minimumWidth() <= sizes[2], (
        f"inspector.minimumWidth {w.inspector.minimumWidth()} > splitter "
        f"default sizes[2] {sizes[2]} (mismatch)."
    )


def test_main_window_inspector_slot_fixed_at_288_under_qss(qapp, qtbot):
    """Default app styling keeps the right Inspector slot at 288px.

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
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        w = MainWindow()
        qtbot.addWidget(w)
        w.resize(2048, 1228)
        w.show()
        qtbot.waitExposed(w)
        qtbot.wait(50)

        splitter = w.findChild(QSplitter)
        sizes = splitter.sizes()
        assert sizes[2] == 288, (
            f"Inspector splitter slot should stay fixed at 288px; got {sizes}"
        )
        assert w.inspector.width() == 288
        assert w.inspector.minimumWidth() == 288
        assert w.inspector.maximumWidth() == 288
    finally:
        qapp.setStyleSheet(old_sheet)


def test_main_window_collapsing_inspector_expands_chart_then_repin_restores(qtbot):
    from mf4_analyzer.ui.side_panels import Side, PanelState

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1500, 800)
    w.show()
    qtbot.waitExposed(w)
    qtbot.wait(50)

    splitter = w.splitter
    before = splitter.sizes()
    assert w.inspector.isVisible()
    assert w._strip_right.isVisible() is False
    assert w._panel_ctrl_right.state == PanelState.PINNED

    # Simulate dragging the inspector handle to the right edge (collapse).
    splitter.setSizes([before[0], before[1] + before[2], 0])
    w._panel_ctrl_right.on_splitter_moved()
    qtbot.wait(20)

    hidden = splitter.sizes()
    assert not w.inspector.isVisible()
    assert w._strip_right.isVisible() is True
    assert w._panel_ctrl_right.state == PanelState.HIDDEN
    assert hidden[2] == 0
    assert hidden[1] > before[1]

    # Click the strip to re-pin: inspector re-docks, chart shrinks back.
    w._strip_right.pin_requested.emit(Side.RIGHT)
    qtbot.wait(20)

    restored = splitter.sizes()
    assert w.inspector.isVisible()
    assert w._strip_right.isVisible() is False
    assert w._panel_ctrl_right.state == PanelState.PINNED
    assert 270 <= restored[2] <= 320
    assert restored[1] < hidden[1]


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


def test_signal_change_handlers_update_unit_recommendation(qapp, qtbot):
    from types import SimpleNamespace
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.files['f1'] = SimpleNamespace(
        fs=1000.0,
        channel_units={'torque': 'Nm', 'vib': 'g', 'empty': ''},
    )

    w._on_inspector_signal_changed('fft', ('f1', 'torque'))
    assert w.inspector.fft_ctx.preset_bar._load_btns[1].property(
        'recommended'
    ) == 'true'
    assert w.inspector.order_ctx.preset_bar._load_btns[1].property(
        'recommended'
    ) == 'true'

    w._on_inspector_signal_changed('order', ('f1', 'vib'))
    assert w.inspector.fft_ctx.preset_bar._load_btns[2].property(
        'recommended'
    ) == 'true'
    assert w.inspector.order_ctx.preset_bar._load_btns[2].property(
        'recommended'
    ) == 'true'

    w._on_inspector_signal_changed('fft', None)
    for ctx in (w.inspector.fft_ctx, w.inspector.order_ctx):
        for n in (1, 2, 3):
            assert ctx.preset_bar._load_btns[n].property('recommended') == 'false'

    w._on_fft_time_signal_changed(('f1', 'empty'))
    assert w.inspector.fft_time_ctx.preset_bar._load_btns[2].property(
        'recommended'
    ) == 'true'

    w._on_fft_time_signal_changed(None)
    for n in (1, 2, 3):
        assert w.inspector.fft_time_ctx.preset_bar._load_btns[n].property(
            'recommended'
        ) == 'false'


def _combo_texts(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_custom_xaxis_time_range_filters_by_file_time_axis(qapp, qtbot, tmp_path):
    """The persistent range controls are always a time-domain filter.

    When X is a custom channel, the displayed x values come from that
    channel, but the selected range must still slice by FileData.time_array.
    """
    import numpy as np
    import pandas as pd
    from PyQt5.QtCore import Qt
    from unittest.mock import patch

    p = tmp_path / "custom_x_range.csv"
    pd.DataFrame({
        "time": np.arange(10, dtype=float),
        "angle": np.arange(100, 110, dtype=float),
        "force": np.arange(10, 20, dtype=float),
    }).to_csv(p, index=False)

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        'mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
        return_value=([str(p)], ""),
    ):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    fi = w.channel_list._file_items[fid]
    force_idx = next(
        i for i in range(fi.childCount())
        if fi.child(i).data(0, Qt.UserRole) == ('channel', fid, 'force')
    )
    w.channel_list._updating = True
    fi.child(force_idx).setCheckState(0, Qt.Checked)
    w.channel_list._updating = False
    w.channel_list.channels_changed.emit()
    qapp.processEvents()

    w.inspector.top.set_xaxis_mode('channel')
    w._on_xaxis_mode_changed('channel')
    combo = w.inspector.top._combo_xaxis_ch
    angle_idx = next(
        i for i in range(combo.count())
        if combo.itemData(i) == (fid, 'angle')
    )
    combo.setCurrentIndex(angle_idx)
    w.inspector.top.set_range_from_span(2.0, 4.0)
    w._apply_xaxis()

    assert w.canvas_time.channel_data
    xdata, ydata, _color, _unit = next(iter(w.canvas_time.channel_data.values()))
    np.testing.assert_allclose(xdata, [102.0, 103.0, 104.0])
    np.testing.assert_allclose(ydata, [12.0, 13.0, 14.0])


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
    # User-request 2026-05-20: file load no longer auto-checks channel[0].
    # The validation path under test reads "every file whose channels are
    # currently checked"; explicitly check file 1's first channel so the
    # mismatch-vs-file-2 assertion has something to compare against.
    fid_first = next(iter(w.files))
    w.channel_list.check_first_channel(fid_first)
    qapp.processEvents()
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


def test_channel_edit_refreshes_custom_xaxis_candidates(qapp, qtbot, loaded_csv):
    """A channel created by the editor must be immediately selectable as X."""
    import numpy as np
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        'mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    w.inspector.top.set_xaxis_mode('channel')
    w._on_xaxis_mode_changed('channel')
    combo = w.inspector.top._combo_xaxis_ch
    before_data = combo.currentData()

    arr = np.arange(len(w.files[fid].data), dtype=float)
    w._apply_channel_edits(fid, {'d_dt_speed': (arr, 'unit/s')}, set())
    qapp.processEvents()

    texts = _combo_texts(combo)
    assert any(text.endswith('d_dt_speed') for text in texts)
    assert combo.currentData() == before_data


def test_file_load_refreshes_custom_xaxis_candidates_when_channel_mode(
    qapp, qtbot, loaded_csv, tmp_path
):
    """Loading another file while X source is channel mode must add it."""
    import numpy as np
    import pandas as pd
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    second = tmp_path / 'second.csv'
    pd.DataFrame({
        'time': np.linspace(0, 1, 128),
        'pressure': np.linspace(10, 20, 128),
    }).to_csv(second, index=False)

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        'mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()

    w.inspector.top.set_xaxis_mode('channel')
    w._on_xaxis_mode_changed('channel')

    with patch(
        'mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
        return_value=([str(second)], ""),
    ):
        w.load_files()
    qapp.processEvents()

    texts = _combo_texts(w.inspector.top._combo_xaxis_ch)
    assert any(text.endswith('pressure') for text in texts)


def test_channel_edit_removing_custom_xaxis_source_resets_to_time(
    qapp, qtbot, loaded_csv
):
    """Removing the applied X source must not leave stale custom-X state."""
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        'mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    w.inspector.top.set_xaxis_mode('channel')
    w._on_xaxis_mode_changed('channel')
    combo = w.inspector.top._combo_xaxis_ch
    idx = next(i for i in range(combo.count()) if combo.itemData(i) == (fid, 'speed'))
    combo.setCurrentIndex(idx)
    w._apply_xaxis()
    assert w._custom_xaxis_ch == 'speed'

    w._apply_channel_edits(fid, {}, {'speed'})
    qapp.processEvents()

    assert w._custom_xaxis_fid is None
    assert w._custom_xaxis_ch is None
    assert w.inspector.top.xaxis_mode() == 'time'


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


def test_order_speed_suitability_helper_stable_rpm_does_not_warn(qtbot, monkeypatch):
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    captured = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': captured.append((msg, level)),
    )
    win.statusBar.clearMessage()

    assert win._warn_if_order_speed_unsuitable(np.full(64, 1200.0)) is True
    assert captured == []
    assert "转速" not in win.statusBar.currentMessage()


def test_order_speed_suitability_helper_warns_for_bad_rpm(qtbot, monkeypatch):
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    cases = [
        np.array([1000.0, -1000.0, 1000.0, -1000.0, 1000.0, -1000.0]),
        np.array([900.0, 0.0, 10.0, 20.0, 30.0, 900.0]),
    ]

    for rpm in cases:
        captured = []
        monkeypatch.setattr(
            win, 'toast',
            lambda msg, level='info', bucket=captured: bucket.append((msg, level)),
        )
        win.statusBar.clearMessage()

        assert win._warn_if_order_speed_unsuitable(rpm) is False
        assert any(level == 'warning' and "转速" in msg for msg, level in captured)
        assert "转速" in win.statusBar.currentMessage()


def test_order_dispatch_unsuitable_rpm_warns_but_starts_worker(
    qtbot, monkeypatch
):
    import numpy as np
    import pandas as pd
    from types import SimpleNamespace
    from PyQt5.QtCore import QThread
    from mf4_analyzer.ui import main_window as mw_mod
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    n = 512
    t = np.arange(n, dtype=float) / 1000.0
    sig = np.sin(2.0 * np.pi * 12.0 * t)
    rpm = np.tile([1000.0, -1000.0], n // 2)
    win.files['f1'] = SimpleNamespace(
        data=pd.DataFrame({'sig': sig, 'rpm': rpm}),
        time_array=t,
        channel_units={'sig': 'g', 'rpm': 'rpm'},
    )

    monkeypatch.setattr(win, '_pane_time_range_for', lambda *_args, **_kw: None)
    monkeypatch.setattr(win.inspector.order_ctx, 'rpm_factor', lambda: 1.0)
    monkeypatch.setattr(win.inspector.order_ctx, 'fs', lambda: 1000.0)
    monkeypatch.setattr(
        win.inspector.order_ctx,
        'current_params',
        lambda: {'samples_per_rev': 256, 'amplitude_mode': 'Amplitude dB'},
    )
    monkeypatch.setattr(
        win.inspector.order_ctx,
        'get_params',
        lambda: {
            'nfft': 256,
            'window': 'hanning',
            'max_order': 20.0,
            'order_res': 0.05,
            'time_res': 0.05,
        },
    )

    captured = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': captured.append((msg, level)),
    )

    started_threads = []
    QThreadBase = QThread

    class RecordingThread(QThreadBase):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.started_called = False
            started_threads.append(self)

        def start(self, priority=QThreadBase.InheritPriority):
            self.started_called = True

    monkeypatch.setattr(mw_mod, 'QThread', RecordingThread)

    assert win._dispatch_order_job(0, 'f1', 'sig', ('f1', 'rpm')) is True
    assert started_threads and started_threads[0].started_called is True
    assert any(level == 'warning' and "转速" in msg for msg, level in captured)
    assert "转速" in win.statusBar.currentMessage()
    btn_ot = getattr(win.inspector.order_ctx, 'btn_ot', None)
    if btn_ot is not None:
        assert btn_ot.isEnabled()


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


def test_file_load_does_not_autoplot_first_channel(qapp, qtbot, loaded_csv):
    """User-request 2026-05-20 (fix 1): loading a file must NOT
    auto-check channel[0] or call plot_time. The canvas opens empty
    and the channel list shows all channels unchecked until the user
    explicitly picks one.
    """
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    qapp.processEvents()

    # File loaded.
    assert len(w.files) == 1
    # No channels checked.
    assert w.channel_list.get_checked_channels() == []
    # Canvas has nothing to draw — no axes (plot_time was not called,
    # or was called with no checks and cleared).
    assert w.canvas_time.axes_list == []
    assert w.canvas_time._channel_lines == {}


def test_file_load_reload_with_prior_checks_still_opens_empty(qapp, qtbot, loaded_csv):
    """fix 1 edge (a): re-loading the same file (a fresh fid) does not
    inherit any auto-check, even if a previous load had a channel
    selected by the user."""
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)

    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    fid_first = next(iter(w.files))
    # Simulate user checking a channel manually.
    w.channel_list.check_first_channel(fid_first)
    qapp.processEvents()
    assert len(w.channel_list.get_checked_channels()) == 1

    # Close that file and reload — the fresh fid must come up unchecked.
    w._close(fid_first)
    qapp.processEvents()
    assert w.channel_list.get_checked_channels() == []
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    qapp.processEvents()
    assert w.channel_list.get_checked_channels() == []


def test_file_load_multi_file_no_autocheck_per_file(qapp, qtbot, loaded_csv, tmp_path):
    """fix 1 edge (b): drag-drop / multi-file load: NONE of the loaded
    files auto-checks channel[0]."""
    import pandas as pd
    import numpy as np
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    df2 = pd.DataFrame({
        "time": np.linspace(0, 1, 256),
        "extra": np.cos(np.linspace(0, 6.28, 256)),
    })
    p2 = tmp_path / "second.csv"
    df2.to_csv(p2, index=False)

    w = MainWindow()
    qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv, str(p2)], "")):
        w.load_files()
    qapp.processEvents()
    assert len(w.files) == 2
    assert w.channel_list.get_checked_channels() == []


def test_time_plot_button_warns_when_no_file_loaded(qapp, qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    seen = []
    monkeypatch.setattr(w, "toast", lambda msg, level="info": seen.append((msg, level)))

    w.inspector.time_ctx.btn_plot.click()
    qapp.processEvents()

    assert seen == [("请先打开数据文件", "warning")]


def test_explicit_time_plot_warns_when_no_channel_checked(
    qapp, qtbot, loaded_csv, monkeypatch
):
    from unittest.mock import patch

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()
    assert w.channel_list.get_checked_channels() == []

    seen = []
    monkeypatch.setattr(w, "toast", lambda msg, level="info": seen.append((msg, level)))

    w.plot_time(user_initiated=True)
    qapp.processEvents()

    assert seen == [("请在左侧勾选至少一个通道", "warning")]


def test_time_plot_warns_when_checked_data_is_empty(
    qapp, qtbot, loaded_csv, monkeypatch
):
    w, _fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    seen = []
    monkeypatch.setattr(w, "toast", lambda msg, level="info": seen.append((msg, level)))
    monkeypatch.setattr(w, "_build_time_plot_data", lambda *args, **kwargs: [])

    w.plot_time(user_initiated=True)
    qapp.processEvents()

    assert seen == [("当前时间范围内无可绘制数据，请调整时间范围或点最大", "warning")]


def test_automatic_time_replot_does_not_warn_for_empty_selection(
    qapp, qtbot, loaded_csv, monkeypatch
):
    from unittest.mock import patch

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()
    seen = []
    monkeypatch.setattr(w, "toast", lambda msg, level="info": seen.append((msg, level)))

    w.plot_time()
    qapp.processEvents()

    assert seen == []


def test_user_initiated_non_primary_time_plot_still_warns(
    qapp, qtbot, loaded_csv, monkeypatch
):
    from unittest.mock import patch

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        "mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames",
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()
    seen = []
    monkeypatch.setattr(w, "toast", lambda msg, level="info": seen.append((msg, level)))

    w._plot_time_on_canvas(
        w.canvas_time,
        update_primary_ui=False,
        user_initiated=True,
    )
    qapp.processEvents()

    assert seen == [("请在左侧勾选至少一个通道", "warning")]


def _load_time_window_with_checked(qapp, qtbot, loaded_csv, checked_names=("speed",)):
    from PyQt5.QtCore import Qt
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1500, 800)
    w.show()
    qtbot.waitExposed(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    fi = w.channel_list._file_items[fid]
    checked = set(checked_names)
    w.channel_list._updating = True
    for i in range(fi.childCount()):
        item = fi.child(i)
        _, _fid, ch = item.data(0, Qt.UserRole)
        item.setCheckState(0, Qt.Checked if ch in checked else Qt.Unchecked)
    w.channel_list._updating = False
    w.channel_list.channels_changed.emit()
    qapp.processEvents()
    assert w.canvas_time._primary_xaxis_ax is not None
    return w, fid


def test_plot_mode_toggle_preserves_xlim_overlay_to_subplot(qapp, qtbot, loaded_csv):
    """User-request 2026-05-20 (fix 2): toggling 分↔叠 must keep the
    user's current x-zoom window. Toolbar Back/Forward history need
    not be preserved; only the visible x-axis range."""
    import pytest
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1500, 800)
    w.show()
    qtbot.waitExposed(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    qapp.processEvents()

    # Check two channels so the overlay/subplot distinction is meaningful.
    fid = next(iter(w.files))
    w.channel_list._updating = True
    fi = w.channel_list._file_items[fid]
    for i in range(min(2, fi.childCount())):
        from PyQt5.QtCore import Qt
        fi.child(i).setCheckState(0, Qt.Checked)
    w.channel_list._updating = False
    w.channel_list.channels_changed.emit()
    qapp.processEvents()

    # Start in subplot mode, render once.
    w.chart_stack.set_plot_mode('subplot')
    qapp.processEvents()
    w.plot_time()
    qapp.processEvents()
    assert w.canvas_time.axes_list

    # Zoom in to a sub-range.
    t0, t1 = 0.2, 0.6
    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(t0, t1)
    qapp.processEvents()
    captured = primary.get_xlim()
    assert captured[0] == pytest.approx(t0, abs=1e-6)
    assert captured[1] == pytest.approx(t1, abs=1e-6)

    # Toggle 分→叠. Listener fires → _on_plot_mode_changed → plot_time
    # → axes rebuilt. The new primary axis must keep the captured window.
    w.chart_stack.set_plot_mode('overlay')
    qapp.processEvents()
    new_primary = w.canvas_time._primary_xaxis_ax
    assert new_primary is not None
    nlo, nhi = new_primary.get_xlim()
    assert nlo == pytest.approx(t0, abs=1e-6)
    assert nhi == pytest.approx(t1, abs=1e-6)

    # Toggle 叠→分. Window is again preserved.
    w.chart_stack.set_plot_mode('subplot')
    qapp.processEvents()
    final_primary = w.canvas_time._primary_xaxis_ax
    assert final_primary is not None
    flo, fhi = final_primary.get_xlim()
    assert flo == pytest.approx(t0, abs=1e-6)
    assert fhi == pytest.approx(t1, abs=1e-6)


def test_channel_selection_change_preserves_xlim(qapp, qtbot, loaded_csv):
    import pytest
    from PyQt5.QtCore import Qt

    w, fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    t0, t1 = 0.2, 0.6
    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(t0, t1)
    qapp.processEvents()

    fi = w.channel_list._file_items[fid]
    torque_item = next(
        fi.child(i) for i in range(fi.childCount())
        if fi.child(i).data(0, Qt.UserRole) == ('channel', fid, 'torque')
    )
    torque_item.setCheckState(0, Qt.Checked)
    qapp.processEvents()

    new_primary = w.canvas_time._primary_xaxis_ax
    assert new_primary is not None
    nlo, nhi = new_primary.get_xlim()
    assert nlo == pytest.approx(t0, abs=1e-6)
    assert nhi == pytest.approx(t1, abs=1e-6)


def test_max_range_button_sets_full_extent_and_replots_time_mode(
    qapp, qtbot, loaded_csv
):
    """「最大」 in time mode: emitting ``max_range_requested`` with a file loaded
    and a channel checked stages the full [0, 全程] extent, enables the range
    filter, and triggers a replot without error."""
    import pytest

    w, fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    w.chart_stack.set_mode('time')
    w.inspector.set_mode('time')
    qapp.processEvents()

    top = w.inspector.top
    # Start from a partial, unchecked selection inside the data extent.
    top.set_range_values(0.2, 0.6)
    top.chk_range.setChecked(False)
    qapp.processEvents()
    assert top.range_enabled() is False

    data_lo = 0.0
    data_hi = float(w.files[fid].time_array[-1])
    assert data_hi > data_lo  # data extent is available after load

    # Simulate stale/narrow spinbox limits. The Max button must fill the data
    # extent directly, not merely echo whatever limits happen to be installed.
    stale_hi = data_hi / 2.0
    top.set_range_limits(data_lo, stale_hi)
    top.set_range_values(0.1, stale_hi)
    assert top.spin_end.maximum() == pytest.approx(stale_hi, abs=1e-6)

    # Drive the live signal path the button uses.
    top.max_range_requested.emit()
    qapp.processEvents()

    rlo, rhi = top.range_values()
    assert rlo == pytest.approx(data_lo, abs=1e-6)
    assert rhi == pytest.approx(data_hi, abs=1e-6)
    assert top.spin_end.maximum() == pytest.approx(data_hi, abs=1e-6)
    assert top.range_enabled() is True
    # A replot must have produced a live primary axis (no exception raised).
    assert w.canvas_time._primary_xaxis_ax is not None


def test_max_range_button_noops_without_data_extent(qapp, qtbot):
    """With no file loaded, the spinbox extent is degenerate; emitting
    ``max_range_requested`` must be a safe no-op (no replot, no exception)."""
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.chart_stack.set_mode('time')
    w.inspector.set_mode('time')

    top = w.inspector.top
    top.set_range_limits(0, 0)  # degenerate extent (mirrors close-file reset)
    top.chk_range.setChecked(False)
    # Should not raise and should not enable the range filter.
    top.max_range_requested.emit()
    assert top.range_enabled() is False


def test_time_range_fields_track_current_visible_xlim_when_unchecked(
    qapp, qtbot, loaded_csv
):
    import pytest

    w, _fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    w.inspector.top.chk_range.setChecked(False)

    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(0.2, 0.6)
    w.canvas_time._flush_pending_refresh()
    qapp.processEvents()

    lo, hi = w.inspector.top.range_values()
    assert lo == pytest.approx(0.2, abs=1e-6)
    assert hi == pytest.approx(0.6, abs=1e-6)


def test_checking_time_range_uses_current_visible_xlim_without_manual_entry(
    qapp, qtbot, loaded_csv
):
    import pytest

    w, _fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    w.inspector.top.chk_range.setChecked(False)

    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(0.2, 0.6)
    w.canvas_time._flush_pending_refresh()
    qapp.processEvents()

    w.inspector.top.chk_range.setChecked(True)
    qapp.processEvents()

    name = next(name for name in w.canvas_time.channel_data if name.endswith("speed"))
    t, _sig, _color, _unit = w.canvas_time.channel_data[name]
    assert float(t.min()) >= 0.2 - 1e-6
    assert float(t.max()) <= 0.6 + 1e-6

    nlo, nhi = w.canvas_time._primary_xaxis_ax.get_xlim()
    assert nlo == pytest.approx(0.2, abs=1e-6)
    assert nhi == pytest.approx(0.6, abs=1e-6)

    w.inspector.top.chk_range.setChecked(False)
    qapp.processEvents()

    t, _sig, _color, _unit = w.canvas_time.channel_data[name]
    assert len(t) == len(w.files[next(iter(w.files))].time_array)


def test_time_range_toggle_preserves_unapplied_xaxis_channel_draft(
    qapp, qtbot, loaded_csv
):
    w, fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    top = w.inspector.top

    top.set_xaxis_mode("channel")
    w._on_xaxis_mode_changed("channel")
    combo = top._combo_xaxis_ch
    target = next(
        i for i in range(combo.count())
        if combo.itemData(i) == (fid, "torque")
    )
    combo.setCurrentIndex(target)

    assert top.xaxis_mode() == "channel"
    assert combo.currentData() == (fid, "torque")
    assert w._custom_xaxis_fid is None
    assert w._custom_xaxis_ch is None

    top.chk_range.setChecked(True)
    qapp.processEvents()

    assert top.xaxis_mode() == "channel"
    assert combo.currentData() == (fid, "torque")
    assert w._custom_xaxis_fid is None
    assert w._custom_xaxis_ch is None
    assert w.view_manager.get(0).axis_opts["x_axis"]["mode"] == "time"


def test_channel_editor_apply_preserves_checked_xlim(qapp, qtbot, loaded_csv):
    import numpy as np
    import pytest

    w, fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    t0, t1 = 0.2, 0.6
    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(t0, t1)
    qapp.processEvents()

    arr = np.arange(len(w.files[fid].data), dtype=float)
    w._apply_channel_edits(fid, {'d_dt_speed': (arr, 'unit/s')}, set())
    qapp.processEvents()

    checked_names = {ch for _fid, ch, _color in w.channel_list.get_checked_channels()}
    assert "speed" in checked_names
    new_primary = w.canvas_time._primary_xaxis_ax
    assert new_primary is not None
    nlo, nhi = new_primary.get_xlim()
    assert nlo == pytest.approx(t0, abs=1e-6)
    assert nhi == pytest.approx(t1, abs=1e-6)


def test_returning_to_time_mode_preserves_xlim(qapp, qtbot, loaded_csv):
    import pytest

    w, _fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    t0, t1 = 0.2, 0.6
    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(t0, t1)
    qapp.processEvents()

    w._on_mode_changed('fft')
    qapp.processEvents()
    w._on_mode_changed('time')
    qapp.processEvents()

    new_primary = w.canvas_time._primary_xaxis_ax
    assert new_primary is not None
    nlo, nhi = new_primary.get_xlim()
    assert nlo == pytest.approx(t0, abs=1e-6)
    assert nhi == pytest.approx(t1, abs=1e-6)


def test_main_window_promotes_fft_time_canvas(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    win = MainWindow()
    qtbot.addWidget(win)

    # M9: FFT-vs-Time moved from the matplotlib SpectrogramCanvas to
    # PgHeatmapCanvas(with_slice=True). The slice row must be present.
    assert isinstance(win.canvas_fft_time, PgHeatmapCanvas)
    assert win.canvas_fft_time._with_slice is True
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


def test_render_fft_time_on_requests_smooth_heatmap_interpolation(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    class _CaptureCanvas:
        def __init__(self):
            self.kwargs = None
            self.tick_density = None

        def plot_result(self, result, **kwargs):
            self.kwargs = dict(kwargs)

        # Real FFT-time canvases (PgHeatmapCanvas) expose set_tick_density;
        # _render_fft_time_on calls it after plot_result, so the fake double
        # must carry it too (capture for an optional assertion).
        def set_tick_density(self, x, y):
            self.tick_density = (x, y)

    win = MainWindow()
    qtbot.addWidget(win)
    canvas = _CaptureCanvas()

    win._render_fft_time_on(canvas, result=object(), p=_fft_time_base_params())

    assert canvas.kwargs["interp"] == "bilinear"


def test_render_order_on_uses_time_coverage_extent(qtbot):
    from types import SimpleNamespace

    import numpy as np

    from mf4_analyzer.ui.main_window import MainWindow

    class _CaptureCanvas:
        def __init__(self):
            self.kwargs = None
            self.tick_density = None
            self._slice_curve = None

        def plot_or_update_heatmap(self, **kwargs):
            self.kwargs = dict(kwargs)

        def set_tick_density(self, x, y):
            self.tick_density = (x, y)

    win = MainWindow()
    qtbot.addWidget(win)
    canvas = _CaptureCanvas()
    result = SimpleNamespace(
        times=np.array([5.0, 7.0]),
        orders=np.array([1.0, 2.0, 3.0]),
        amplitude=np.ones((2, 3), dtype=float),
        params=SimpleNamespace(order_res=0.1),
        metadata={'coverage_start': 0.0, 'coverage_end': 12.0},
    )

    win._render_order_on(canvas, result)

    assert canvas.kwargs["x_extent"] == (0.0, 12.0)


def test_render_fft_time_on_auto_freq_range_uses_energy_band(qtbot):
    import numpy as np

    from mf4_analyzer.signal import energy_band_fmax
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    class _CaptureCanvas:
        def __init__(self):
            self.kwargs = None

        def plot_result(self, result, **kwargs):
            self.kwargs = dict(kwargs)

        def set_tick_density(self, _x, _y):
            pass

    win = MainWindow()
    qtbot.addWidget(win)
    freq = np.linspace(0.0, 50.0, 501)
    amp = np.zeros((freq.size, 3), dtype=np.float32)
    amp[np.argmin(np.abs(freq - 1.0)), :] = (2.0, 8.0, 3.0)
    amp[np.argmin(np.abs(freq - 1.8)), :] = (1.0, 4.0, 0.5)
    result = SpectrogramResult(
        times=np.array([0.0, 0.5, 1.0]),
        frequencies=freq,
        amplitude=amp,
        params=SpectrogramParams(fs=100.0, nfft=100),
        channel_name="narrow",
        metadata={"frames": 3, "freq_bins": freq.size},
    )

    canvas = _CaptureCanvas()
    win._render_fft_time_on(canvas, result, _fft_time_base_params())

    representative_amp = np.nanmax(amp, axis=1)
    expected = energy_band_fmax(freq, representative_amp)
    assert canvas.kwargs["freq_range"] == (0.0, expected)
    assert 2.0 <= expected < freq[-1] * 0.25


def test_render_fft_time_on_manual_freq_range_is_preserved(qtbot):
    import numpy as np

    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    class _CaptureCanvas:
        def __init__(self):
            self.kwargs = None

        def plot_result(self, result, **kwargs):
            self.kwargs = dict(kwargs)

        def set_tick_density(self, _x, _y):
            pass

    win = MainWindow()
    qtbot.addWidget(win)
    freq = np.linspace(0.0, 50.0, 51)
    result = SpectrogramResult(
        times=np.array([0.0, 1.0]),
        frequencies=freq,
        amplitude=np.ones((freq.size, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=100),
        channel_name="manual",
    )
    p = dict(
        _fft_time_base_params(),
        freq_auto=False,
        freq_min=3.0,
        freq_max=17.0,
    )

    canvas = _CaptureCanvas()
    win._render_fft_time_on(canvas, result, p)

    assert canvas.kwargs["freq_range"] == (3.0, 17.0)


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
    # M9: pg canvas exposes has_result() + _result instead of mpl
    # ``_ax_spec.images`` — the behaviour under test is "a failed recompute
    # leaves the previously rendered result on screen".
    assert win.canvas_fft_time.has_result()

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

    # The old chart is still on the canvas (no clear() on failure).
    assert win.canvas_fft_time.has_result()
    # The original SpectrogramResult object is still the canvas's
    # ``_result`` (clear() would have set it to None).
    assert win.canvas_fft_time._result is seed
    # Status bar reports the error.
    assert "FFT vs Time 错误" in win.statusBar.currentMessage()
    # An error toast was emitted.
    assert any(level == 'error' for _msg, level in captured)


def test_fft_time_cursor_info_does_not_propagate_to_status_bar(qtbot):
    """Passive FFT-vs-Time hover XYZ readout is retired."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    win.statusBar.showMessage("ready")
    win.canvas_fft_time.cursor_info.emit("t=0.123 s · f=50.0 Hz · 1.234 (V)")
    assert win.statusBar.currentMessage() == "ready"


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


def _fft_time_spectrogram_job(sig, t, params, ch='ch', unit='V'):
    """Build the same spectrogram closure ``do_fft_time`` now hands to
    ``AnalysisComputeWorker`` (M9). The job receives the worker so it can
    relay progress and poll ``worker.cancelled`` as its cancel token —
    identical wiring to production.
    """
    def job(worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit):
        from mf4_analyzer.signal import SpectrogramAnalyzer
        return SpectrogramAnalyzer.compute(
            _sig, _t, _params, channel_name=_ch, unit=_unit,
            progress_callback=worker.progress.emit,
            cancel_token=worker.cancelled,
        )
    return job


def test_fft_time_worker_emits_finished(qtbot):
    """Happy-path smoke: the M9 FFT-vs-Time spectrogram job, run on an
    ``AnalysisComputeWorker`` + QThread, must emit ``finished`` with a
    SpectrogramResult payload.

    ``thread.quit`` is thread-safe (per Qt docs); we wire it with a
    DirectConnection so it fires on the worker thread without going
    through the main event loop. Without that, ``thread.wait(5000)``
    blocks the main thread, the queued ``finished -> thread.quit`` slot
    cannot drain, and the wait deadlocks (see
    pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit).
    """
    import numpy as np
    from PyQt5.QtCore import Qt, QThread
    from mf4_analyzer.signal.spectrogram import SpectrogramParams
    from mf4_analyzer.ui.analysis_worker import AnalysisComputeWorker

    fs = 1000.0
    nfft = 256
    t = np.arange(2048) / fs
    sig = np.sin(2 * np.pi * 100 * t)
    worker = AnalysisComputeWorker(
        _fft_time_spectrogram_job(sig, t, SpectrogramParams(fs=fs, nfft=nfft))
    )
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    results = []
    worker.finished.connect(lambda r: results.append(r), Qt.DirectConnection)
    worker.finished.connect(thread.quit, Qt.DirectConnection)

    thread.start()
    assert thread.wait(5000)

    assert len(results) == 1
    # SpectrogramResult.amplitude is (freq_bins, frames); at least one
    # frame must be present.
    assert results[0].amplitude.shape[1] > 0


def test_fft_time_worker_cancels(qtbot):
    """``worker.cancel()`` flips the cancel token the spectrogram job
    polls via ``worker.cancelled``; the analyzer raises
    ``RuntimeError('spectrogram computation cancelled')`` mid-loop and
    the worker re-emits the message via ``failed``.

    overlap=0.9 + 200k samples gives ~thousands of frames so cancel
    has time to fire before the loop finishes.
    """
    import numpy as np
    from PyQt5.QtCore import Qt, QThread
    from mf4_analyzer.signal.spectrogram import SpectrogramParams
    from mf4_analyzer.ui.analysis_worker import AnalysisComputeWorker

    fs = 1000.0
    nfft = 64
    n = 200_000  # many frames so cancel has time to fire
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 100 * t)
    worker = AnalysisComputeWorker(
        _fft_time_spectrogram_job(
            sig, t, SpectrogramParams(fs=fs, nfft=nfft, overlap=0.9)
        )
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


def test_publish_copied_pixmap_sets_clipboard_toast_and_thumbnail(qtbot, monkeypatch):
    """Chart-card publish path writes the plain pixmap immediately, shows the
    mandatory success toast, and presents the optional thumbnail."""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    pix = QPixmap(40, 24)
    pix.fill()

    pushed = []
    monkeypatch.setattr(QApplication.clipboard(), 'setPixmap', lambda p: pushed.append(p))
    toasts = []
    monkeypatch.setattr(win, 'toast', lambda msg, level='info': toasts.append((msg, level)))

    class ThumbSpy:
        def __init__(self):
            self.presented = []

        def present(self, pixmap):
            self.presented.append(pixmap)

    thumb = ThumbSpy()
    win._copy_thumbnail = thumb

    win._publish_copied_pixmap(pix)

    assert pushed == [pix]
    assert toasts == [("已复制到剪贴板 · 可直接粘贴", "success")]
    assert thumb.presented == [pix]
    assert "已复制到剪贴板" in win.statusBar.currentMessage()


def test_publish_copied_pixmap_ignores_null_pixmap(qtbot, monkeypatch):
    """Null captures should not mutate clipboard, toast, or thumbnail."""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    pushed = []
    monkeypatch.setattr(QApplication.clipboard(), 'setPixmap', lambda p: pushed.append(p))
    toasts = []
    monkeypatch.setattr(win, 'toast', lambda msg, level='info': toasts.append((msg, level)))

    class ThumbSpy:
        def __init__(self):
            self.presented = []

        def present(self, pixmap):
            self.presented.append(pixmap)

    thumb = ThumbSpy()
    win._copy_thumbnail = thumb

    win._publish_copied_pixmap(QPixmap())

    assert pushed == []
    assert toasts == []
    assert thumb.presented == []


def test_chart_stack_image_captured_routes_to_publish_pipeline(qtbot, monkeypatch):
    """MainWindow wiring routes the four chart-card copy captures into the
    publish pipeline, not the legacy status-string signal."""
    from PyQt5.QtGui import QPixmap
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    routed = []
    monkeypatch.setattr(win, '_publish_copied_pixmap', lambda pix: routed.append(pix))
    pix = QPixmap(12, 12)
    pix.fill()

    win.chart_stack.image_captured.emit(pix)

    assert len(routed) == 1
    assert routed[0].size() == pix.size()
    assert routed[0].cacheKey() == pix.cacheKey()


def test_thumbnail_click_opens_markup_editor_with_full_pixmap(qtbot, monkeypatch):
    """Thumbnail click opens a non-modal editor with the full-resolution pixmap."""
    from PyQt5.QtGui import QPixmap
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    pix = QPixmap(80, 40)
    pix.fill()
    created = []

    class FakeEditor:
        def __init__(self, source, on_done=None, parent=None):
            self.source = source
            self.on_done = on_done
            self.parent = parent
            self.shown = False

        def show(self):
            self.shown = True

        def raise_(self):
            pass

        def activateWindow(self):
            pass

    monkeypatch.setattr(win, '_create_markup_editor', lambda source, on_done: created.append(FakeEditor(source, on_done, win)) or created[-1])

    win._open_markup_editor(pix)

    assert created and created[0].source is pix
    assert created[0].shown
    assert win._markup_editor is created[0]


def test_editor_done_republishes_annotated_pixmap_without_thumbnail_loop(qtbot, monkeypatch):
    """Completing the editor overwrites the clipboard and toast but does not
    re-present the optional thumbnail."""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    pix = QPixmap(32, 20)
    pix.fill()
    pushed = []
    monkeypatch.setattr(QApplication.clipboard(), 'setPixmap', lambda p: pushed.append(p))
    toasts = []
    monkeypatch.setattr(win, 'toast', lambda msg, level='info': toasts.append((msg, level)))

    class ThumbSpy:
        def __init__(self):
            self.presented = []

        def present(self, pixmap):
            self.presented.append(pixmap)

    thumb = ThumbSpy()
    win._copy_thumbnail = thumb

    win._publish_annotated_pixmap(pix)

    assert pushed == [pix]
    assert toasts == [("已复制(含标注)", "success")]
    assert thumb.presented == []
    assert "已复制(含标注)" in win.statusBar.currentMessage()


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


def test_fft_panel_keeps_signal_selection_across_channel_edit(
    qapp, qtbot, loaded_csv, tmp_path
):
    """B1: editing channels on one file must NOT reset the FFT panel's
    currently-selected signal back to index 0 (regression from
    commit 0132253 which patched xaxis + fft_time but missed FFT/Order)."""
    import numpy as np
    import pandas as pd
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    t2 = np.linspace(0, 1, 128)
    second = tmp_path / 'second.csv'
    pd.DataFrame({
        'time': t2,
        'pressure': 12.0 + 3.0 * np.sin(2 * np.pi * 4 * t2),
    }).to_csv(second, index=False)

    w = MainWindow()
    qtbot.addWidget(w)
    with patch(
        'mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
        return_value=([loaded_csv], ""),
    ):
        w.load_files()
    qapp.processEvents()
    with patch(
        'mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
        return_value=([str(second)], ""),
    ):
        w.load_files()
    qapp.processEvents()

    # Resolve targets from the actual combo content — different builds
    # may apply different "signal vs metadata" filters; what matters is
    # that whatever the user picked from file B is preserved when an
    # unrelated file A is edited.
    fid_first = next(iter(w.files))
    fid_second = list(w.files.keys())[1]
    fft_combo = w.inspector.fft_ctx.combo_sig
    order_combo = w.inspector.order_ctx.combo_sig

    def _first_data_for_fid(combo, fid):
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data is not None and data[0] == fid:
                return i, data
        return -1, None

    idx_fft, target_fft = _first_data_for_fid(fft_combo, fid_second)
    idx_order, target_order = _first_data_for_fid(order_combo, fid_second)
    assert idx_fft >= 0, "file B has no FFT signal candidate"
    assert idx_order >= 0, "file B has no Order signal candidate"
    fft_combo.setCurrentIndex(idx_fft)
    order_combo.setCurrentIndex(idx_order)

    # Edit channels on file 1 — would have reset the dropdowns prior to fix.
    arr = np.arange(len(w.files[fid_first].data), dtype=float)
    w._apply_channel_edits(fid_first, {'derived': (arr, 'unit')}, set())
    qapp.processEvents()

    assert fft_combo.currentData() == target_fft, (
        "FFT panel signal selection was reset after editing an unrelated file"
    )
    assert order_combo.currentData() == target_order, (
        "Order panel signal selection was reset after editing an unrelated file"
    )


def test_safe_restore_primary_xlim_skips_when_only_tangent_overlap(qapp, qtbot):
    """B2: a captured window that only touches the new ax extent at a
    single point must fall back to autoscale, not lock onto a one-pixel
    slice. Strict ``<`` would let (5, 10) restore against an ax with
    autoscale extent (0, 5); ``<=`` correctly drops it."""
    from mf4_analyzer.ui.main_window import MainWindow

    class _FakeAx:
        def __init__(self, lo, hi):
            self._lo, self._hi = lo, hi
            self.applied = None

        def get_xlim(self):
            return (self._lo, self._hi)

        def set_xlim(self, lo, hi):
            self.applied = (lo, hi)

    w = MainWindow()
    qtbot.addWidget(w)

    ax = _FakeAx(0.0, 5.0)
    w.canvas_time._primary_xaxis_ax = ax  # type: ignore[attr-defined]
    # Captured window touches ax extent only at (5.0, 5.0) — zero
    # measure intersection; must skip restoration.
    w._safe_restore_primary_xlim((5.0, 10.0))
    assert ax.applied is None
    # Sanity: a real overlap still restores.
    ax.applied = None
    w._safe_restore_primary_xlim((1.0, 3.0))
    assert ax.applied == (1.0, 3.0)


def _left_axis_channel_name(canvas):
    """Return the channel NAME currently bound to the overlay left axis,
    i.e. the channel whose axis handle is axes_list[0]."""
    if not canvas.axes_list:
        return None
    left_handle = canvas.axes_list[0]
    for name, (handle, _line) in canvas._channel_lines.items():
        if handle is left_handle:
            return name
    return None


def test_overlay_set_primary_left_axis_reorders_and_preserves_xlim(
    qapp, qtbot, tmp_path
):
    """Task 3: right-click 设为左轴 on a channel makes it the overlay LEFT-axis
    channel. The chosen channel must end up bound to axes_list[0] and the
    current x-zoom window must be preserved across the rebuild."""
    import pytest
    import numpy as np
    import pandas as pd
    from PyQt5.QtCore import Qt
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    t = np.linspace(0.0, 1.0, 500)
    p = tmp_path / "three_ch.csv"
    pd.DataFrame({
        "time": t,
        "speed": 1000.0 * np.sin(2 * np.pi * 5 * t),
        "torque": 50.0 + 5.0 * np.cos(2 * np.pi * 3 * t),
        "pressure": 0.2 + 0.1 * np.sin(2 * np.pi * 7 * t),
    }).to_csv(p, index=False)

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1500, 800)
    w.show()
    qtbot.waitExposed(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([str(p)], "")):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    fi = w.channel_list._file_items[fid]
    w.channel_list._updating = True
    for i in range(fi.childCount()):
        fi.child(i).setCheckState(0, Qt.Checked)
    w.channel_list._updating = False
    w.channel_list.channels_changed.emit()
    qapp.processEvents()

    w.chart_stack.set_plot_mode('overlay')
    qapp.processEvents()
    w.plot_time()
    qapp.processEvents()
    assert w.canvas_time._overlay_mode is True

    # Default: the FIRST checked channel (speed) holds the left axis.
    assert _left_axis_channel_name(w.canvas_time).endswith("speed")

    # Zoom to a sub-window so we can assert it survives the reorder rebuild.
    t0, t1 = 0.2, 0.6
    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(t0, t1)
    qapp.processEvents()

    # User right-clicks 'pressure' and picks 设为左轴. The navigator emits
    # primary_channel_requested(fid, 'pressure'); main_window reorders and
    # replots preserving xlim.
    w.navigator.primary_channel_requested.emit(fid, 'pressure')
    qapp.processEvents()

    # pressure now owns the left axis.
    left_name = _left_axis_channel_name(w.canvas_time)
    assert left_name is not None and left_name.endswith("pressure"), (
        f"expected pressure on the left axis, got {left_name!r}"
    )
    # X window preserved across the reorder rebuild.
    new_primary = w.canvas_time._primary_xaxis_ax
    nlo, nhi = new_primary.get_xlim()
    assert nlo == pytest.approx(t0, abs=1e-6)
    assert nhi == pytest.approx(t1, abs=1e-6)


def test_overlay_primary_cleared_when_channel_unchecked(qapp, qtbot, tmp_path):
    """Task 3: an _overlay_primary that is no longer checked must be ignored
    so it does not force a hidden channel onto the left axis."""
    import numpy as np
    import pandas as pd
    from PyQt5.QtCore import Qt
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow

    t = np.linspace(0.0, 1.0, 400)
    p = tmp_path / "three_ch2.csv"
    pd.DataFrame({
        "time": t,
        "speed": np.sin(2 * np.pi * 5 * t),
        "torque": np.cos(2 * np.pi * 3 * t),
        "pressure": 0.5 * t,
    }).to_csv(p, index=False)

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1500, 800)
    w.show()
    qtbot.waitExposed(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([str(p)], "")):
        w.load_files()
    qapp.processEvents()

    fid = next(iter(w.files))
    fi = w.channel_list._file_items[fid]

    def _set_checked(names):
        w.channel_list._updating = True
        for i in range(fi.childCount()):
            _, _fid, ch = fi.child(i).data(0, Qt.UserRole)
            fi.child(i).setCheckState(0, Qt.Checked if ch in names else Qt.Unchecked)
        w.channel_list._updating = False
        w.channel_list.channels_changed.emit()
        qapp.processEvents()

    _set_checked({"speed", "torque", "pressure"})
    w.chart_stack.set_plot_mode('overlay')
    qapp.processEvents()
    w.plot_time()
    qapp.processEvents()

    w.navigator.primary_channel_requested.emit(fid, 'pressure')
    qapp.processEvents()
    assert _left_axis_channel_name(w.canvas_time).endswith("pressure")

    # Uncheck pressure → it must not be forced onto the left axis. The
    # left axis falls back to the first remaining checked channel.
    _set_checked({"speed", "torque"})
    left_name = _left_axis_channel_name(w.canvas_time)
    assert left_name is not None and not left_name.endswith("pressure"), (
        f"unchecked primary must be ignored; got {left_name!r}"
    )


def test_alt_view_shortcut_switches_active_section(qapp, qtbot):
    """Alt+i view switching must drive the CURRENTLY shown section's view
    manager (fft/fft_time/order), not only the time section."""
    from mf4_analyzer.ui_kit import load_stylesheet
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 850)
    w.show()
    qtbot.waitExposed(w)
    qapp.processEvents()

    w._on_mode_changed("fft")
    qapp.processEvents()
    mgr = w.analysis_managers['fft']
    while len(mgr.views) < 2:
        mgr.new_view()
    mgr.set_active(0)
    qapp.processEvents()

    captured = []
    orig = w._on_analysis_switch

    def _spy(section, idx):
        captured.append((section, idx))
        return orig(section, idx)

    w._on_analysis_switch = _spy
    w._switch_view_for_active_section(1)   # what Alt+2 invokes
    assert ('fft', 1) in captured
    assert mgr.active == 1


# ---- Task 4: FFT dB reference render tests ----

def test_fft_amplitude_to_db_uses_reference():
    import numpy as np
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin

    out = FFTMixin._amplitude_to_db(np.array([1.0, 10.0]), 1.0)
    np.testing.assert_allclose(out, np.array([0.0, 20.0]), atol=1e-6)


def test_fft_entry_from_cache_uses_db_reference(monkeypatch, qapp):
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    freq = np.array([10.0, 20.0])
    amp = np.array([1.0, 10.0])

    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "current_params",
        lambda: {"amp_y": "dB", "db_reference": 1.0},
    )
    monkeypatch.setattr(win, "_file_display_name", lambda fid: str(fid))
    monkeypatch.setattr(
        win,
        "_fft_trace_for_source",
        lambda fid, ch, time_range=None: (None, None),
    )

    entry = win._fft_entry_from_cache((freq, amp, None), "f1", "sig", "#2563eb")

    np.testing.assert_allclose(entry["amp"], np.array([0.0, 20.0]), atol=1e-6)
    np.testing.assert_allclose(entry["amp_for_xlim"], amp)


def test_fft_cache_key_excludes_db_reference_display_only():
    """db_reference is display-only and must NOT affect the FFT compute cache key."""
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin

    base = {
        "window": "hanning",
        "nfft_effective": 1024,
        "avg_mode": "单帧",
        "avg_overlap": 50,
        "weighting": "A",
    }
    k1 = FFTMixin._fft_compute_cache_params(dict(base, db_reference=1.0))
    k2 = FFTMixin._fft_compute_cache_params(dict(base, db_reference=2.0))
    assert k1 == k2


def test_fft_cache_key_includes_fs_single_frame():
    """Regression (问题①): the FFT line-chart compute key MUST include fs.

    In single-frame mode the resolved nfft is None (whole-segment), so a Fs
    change after a 重建时间轴 left every other keyed field identical and the
    key never changed → the chart hit the stale result computed at the OLD fs
    (wrong frequency axis + PSD scaling). fs is a real compute input
    (FFTAnalyzer.compute_fft(sig, fs, ...)), sourced from fd.fs, so it belongs
    in the key.
    """
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin

    base = {
        "window": "hanning",
        "nfft": None,          # single-frame / whole-segment auto
        "nfft_mode": "auto",
        "avg_mode": "单帧",
        "avg_overlap": 50,
        "weighting": "None",
    }
    # Resolve at two different sample rates (same n_samples, same nfft=None).
    p_lo = FFTMixin._resolve_fft_effective_params(dict(base), 4096, 1000.0)
    p_hi = FFTMixin._resolve_fft_effective_params(dict(base), 4096, 2000.0)
    assert p_lo.get("nfft_effective") is None
    assert p_hi.get("nfft_effective") is None
    k_lo = FFTMixin._fft_compute_cache_params(p_lo)
    k_hi = FFTMixin._fft_compute_cache_params(p_hi)
    assert k_lo != k_hi, "single-frame FFT key did not change with fs"
    assert k_lo["fs"] == 1000.0
    assert k_hi["fs"] == 2000.0


def test_fft_cache_key_includes_fs_fixed_nfft():
    """fs also distinguishes fixed-NFFT keys (defensive: a fixed nfft + new fs
    still changes the frequency axis)."""
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin

    base = {
        "window": "hanning",
        "nfft": 1024,
        "nfft_mode": "fixed",
        "avg_mode": "单帧",
        "avg_overlap": 50,
        "weighting": "None",
    }
    p_lo = FFTMixin._resolve_fft_effective_params(dict(base), 4096, 1000.0)
    p_hi = FFTMixin._resolve_fft_effective_params(dict(base), 4096, 2000.0)
    assert FFTMixin._fft_compute_cache_params(p_lo) != \
        FFTMixin._fft_compute_cache_params(p_hi)


# ---- Task 5: Order dB reference render tests ----

def test_order_db_display_uses_db_reference(monkeypatch, qapp):
    import numpy as np
    from types import SimpleNamespace
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    captured = {}

    class Canvas:
        _amplitude_mode = None

        def plot_or_update_heatmap(self, **kwargs):
            captured.update(kwargs)

        def set_tick_density(self, *_args):
            pass

    result = SimpleNamespace(
        amplitude=np.array([[1.0, 10.0]], dtype=float),  # frames x orders
        times=np.array([0.5]),
        orders=np.array([1.0, 2.0]),
        params=SimpleNamespace(order_res=0.1),
        metadata={"coverage_start": 0.0, "coverage_end": 1.0},
    )
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "current_params",
        lambda: {
            "amplitude_mode": "Amplitude dB",
            "db_reference": 1.0,
            "z_auto": False,
            "z_floor": -40.0,
            "z_ceiling": 20.0,
            "x_auto": True,
            "y_auto": True,
        },
    )
    monkeypatch.setattr(win.inspector.top, "tick_density", lambda: (10, 10))

    win._render_order_on(Canvas(), result)

    # Matrix should be pre-converted to dB: 20*log10([1,10]/1) = [0, 20]
    # The matrix is result.amplitude.T shape=(orders, frames)=(2, 1)
    np.testing.assert_allclose(
        captured["matrix"],
        np.array([[0.0], [20.0]]),
        atol=1e-6,
    )
    # Canvas receives amplitude_mode='amplitude' (canvas must NOT re-normalize)
    assert captured["amplitude_mode"] == "amplitude"
    # cbar_label must include dB reference
    assert "dB re 1" in captured["cbar_label"]


def test_order_cache_key_excludes_db_reference_display_only():
    """db_reference is display-only and must NOT affect the Order compute cache key."""
    from mf4_analyzer.ui.main_window._order_mixin import OrderMixin

    base = {
        "nfft": 1024,
        "max_order": 20,
        "order_res": 0.1,
        "time_res": 0.05,
        "samples_per_rev": 256,
        "rpm_factor": 1.0,
        "fs": 1000.0,
        "weighting": "A",
    }
    k1 = OrderMixin._order_compute_cache_params(dict(base, db_reference=1.0), ("f", "rpm"), None)
    k2 = OrderMixin._order_compute_cache_params(dict(base, db_reference=2.0), ("f", "rpm"), None)
    assert k1 == k2


def test_order_cache_key_includes_window():
    """问题⑨ (preventive): window IS a COTParams field consumed by compute
    (COTOrderAnalyzer builds the analysis window from it), so changing it must
    invalidate the Order compute cache key — otherwise a window change silently
    reuses a result built with the old window."""
    from mf4_analyzer.ui.main_window._order_mixin import OrderMixin

    base = {
        "nfft": 1024,
        "max_order": 20,
        "order_res": 0.1,
        "time_res": 0.05,
        "samples_per_rev": 256,
        "rpm_factor": 1.0,
        "fs": 1000.0,
        "weighting": "None",
    }
    k_hann = OrderMixin._order_compute_cache_params(
        dict(base, window="hanning"), ("f", "rpm"), None)
    k_flat = OrderMixin._order_compute_cache_params(
        dict(base, window="flattop"), ("f", "rpm"), None)
    assert k_hann != k_flat, "Order cache key did not change with window"
    assert k_hann["window"] == "hanning"
    assert k_flat["window"] == "flattop"


def test_fft_time_db_reference_change_triggers_cached_rerender(qapp, qtbot, monkeypatch):
    """FFT-vs-Time dB reference is display-only, but changing it must still
    re-render the current result from cache without forcing a recompute.

    The MainWindow wiring should mirror FFT/Order: valueChanged schedules
    ``do_fft_time(force=False)`` so the normal cache-hit path redraws with the
    new render-time ``db_reference``.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    calls = []

    def fake_do_fft_time(force=False):
        calls.append(force)

    monkeypatch.setattr(win, "do_fft_time", fake_do_fft_time)

    win.inspector.fft_time_ctx.spin_db_ref.setValue(2.0)

    qtbot.waitUntil(lambda: bool(calls), timeout=1000)
    assert calls == [False]


def test_fft_time_low_cache_key_excludes_db_reference_display_only():
    """db_reference is display-only and must NOT affect the FFT-vs-Time LRU key.

    ``_fft_time_cache_key`` reads only its ``params`` argument (no ``self``
    state), so we bind the unbound method against a bare object stub.
    """
    from mf4_analyzer.ui.main_window._fft_time_mixin import FFTTimeMixin

    base = {
        "fid": "f1",
        "channel": "sig",
        "time_range": (0.0, 1.0),
        "fs": 1000.0,
        "nfft_effective": 512,
        "window": "hanning",
        "overlap": 0.5,
        "remove_mean": True,
        "weighting": "A",
    }
    stub = object.__new__(type("S", (FFTTimeMixin,), {}))
    k1 = FFTTimeMixin._fft_time_cache_key(stub, dict(base, db_reference=1.0))
    k2 = FFTTimeMixin._fft_time_cache_key(stub, dict(base, db_reference=2.0))
    assert k1 == k2


def test_order_nfft_preview_wired_to_loaded_data(qapp, qtbot):
    """End-to-end: the order auto-NFFT header reflects loaded data, not 8192.

    Reproduces the reported trap — Fs=50 Hz, ~71 s, slow speed → only a few
    dozen revolutions. The naive blind preview shows 自动(8192); once the main
    window wires the revolution-count provider, the header (and the value COT
    actually computes) shrinks via the shared resolve_order_nfft.
    """
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    from mf4_analyzer.signal import resolve_order_nfft
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)

    fs = 50.0
    t = np.arange(3552, dtype=float) / fs        # ~71.0 s
    rpm = np.full(t.shape, 30.0)                  # 0.5 rev/s → ~35 revolutions
    sig = np.sin(2.0 * np.pi * 2.0 * t)
    w.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"torque": sig, "speed": rpm}),
        time_array=t,
        channel_units={"torque": "Nm", "speed": "rpm"},
        fs=fs,
    )
    octx = w.inspector.order_ctx
    octx.current_signal = lambda: ("f1", "torque")
    octx.current_rpm = lambda: ("f1", "speed")
    octx.set_fs(fs)
    octx.spin_samples_per_rev.setValue(512)
    octx.spin_order_res.setValue(0.10)

    # The main window must have installed a revolution-count provider.
    assert octx._auto_nfft_provider is not None

    revs = w._order_preview_revs()
    assert revs is not None
    assert 34.0 < revs < 36.0     # 0.5 rev/s over ~71 s

    n_angle = max(1, int(round(512 * revs)))
    expected = int(resolve_order_nfft(512, 0.10, n_angle, overlap=0.75))
    preview = octx._order_nfft_preview()
    assert preview == expected
    assert preview < 8192          # data-aware shrink vs the naive blind value
    assert f"{octx._AUTO_NFFT_LABEL}({expected})" in octx._order_summary_text()


def test_fft_time_nfft_preview_wired_to_loaded_data(qapp, qtbot):
    """End-to-end: FFT-vs-Time auto header tracks the loaded sample count."""
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    from mf4_analyzer.signal import resolve_nfft
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)

    fs = 1000.0
    t = np.arange(3000, dtype=float) / fs
    sig = np.sin(2.0 * np.pi * 50.0 * t)
    w.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"sig": sig}),
        time_array=t,
        channel_units={"sig": ""},
        fs=fs,
    )
    ftx = w.inspector.fft_time_ctx
    ftx.current_signal = lambda: ("f1", "sig")
    ftx.combo_nfft.setCurrentText(ftx._AUTO_NFFT_LABEL)
    ftx.set_fs(fs)
    ftx._t_win_s = 1.5
    ftx.spin_overlap.setValue(50)

    assert ftx._auto_nfft_provider is not None
    assert w._fft_time_preview_n_samples() == 3000

    expected = int(resolve_nfft(1000.0, 3000, 1.5, 0.5))
    assert expected == 128
    assert ftx._nfft_preview() == expected
    assert ftx._nfft_preview() != 2048  # not the data-blind ceil_pow2(Fs*t_win)
    assert f"{ftx._AUTO_NFFT_LABEL}({expected})" in ftx._tf_summary_text()


def test_fft_nfft_preview_wired_to_loaded_data(qapp, qtbot):
    """End-to-end: FFT single-frame auto header shows the whole-signal length."""
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)

    fs = 1000.0
    t = np.arange(3552, dtype=float) / fs
    sig = np.sin(2.0 * np.pi * 50.0 * t)
    w.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"sig": sig}),
        time_array=t,
        channel_units={"sig": ""},
        fs=fs,
    )
    fx = w.inspector.fft_ctx
    fx.current_signal = lambda: ("f1", "sig")
    fx.combo_nfft.setCurrentText(fx._AUTO_NFFT_LABEL)
    fx.combo_avg_mode.setCurrentText('单帧')
    fx.set_fs(fs)

    assert fx._auto_nfft_provider is not None
    assert w._fft_preview_n_samples() == 3552
    # 单帧 auto = whole-signal FFT → effective length is the data length.
    assert fx._fft_nfft_preview() == 3552
    assert f"{fx._AUTO_NFFT_LABEL}(3552)" in fx._fft_summary_text()
