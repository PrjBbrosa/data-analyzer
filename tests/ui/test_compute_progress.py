from mf4_analyzer.ui.compute_progress import ComputeProgressWidget
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window import window as window_mod


def test_progress_widget_is_hidden_when_idle(qapp, qtbot):
    widget = ComputeProgressWidget()
    qtbot.addWidget(widget)

    assert not widget.isVisible()
    assert widget.objectName() == "computeProgressWidget"
    assert widget.label.objectName() == "computeProgressLabel"
    assert widget.bar.objectName() == "computeProgressBar"


def test_begin_indeterminate_shows_busy_bar(qapp, qtbot):
    widget = ComputeProgressWidget()
    qtbot.addWidget(widget)

    widget.begin("时间域绘制中")

    assert widget.isVisible()
    assert widget.label.text() == "时间域绘制中"
    assert widget.bar.minimum() == 0
    assert widget.bar.maximum() == 0


def test_update_determinate_sets_value_and_total(qapp, qtbot):
    widget = ComputeProgressWidget()
    qtbot.addWidget(widget)

    widget.begin("FFT-时间", total=100)
    widget.set_progress(25, 100)

    assert widget.isVisible()
    assert widget.bar.minimum() == 0
    assert widget.bar.maximum() == 100
    assert widget.bar.value() == 25


def test_finish_hides_widget(qapp, qtbot):
    widget = ComputeProgressWidget()
    qtbot.addWidget(widget)

    widget.begin("阶次", total=10)
    widget.finish()

    assert not widget.isVisible()


def test_set_progress_clamps_value(qapp, qtbot):
    widget = ComputeProgressWidget()
    qtbot.addWidget(widget)

    widget.begin("FFT-时间", total=100)
    widget.set_progress(-5, 100)
    assert widget.bar.value() == 0

    widget.set_progress(120, 100)
    assert widget.bar.value() == 100


def test_main_window_compute_progress_token_guards_stale_updates(qapp, qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    qapp.processEvents()

    active = window._begin_compute_progress("FFT-时间", total=100)

    window._update_compute_progress(50, 100, token=object())
    assert window._compute_progress.bar.value() == 0

    window._update_compute_progress(60, 100, token=active)
    assert window._compute_progress.bar.value() == 60

    window._finish_compute_progress(token=object())
    assert window._compute_progress.isVisible()

    window._finish_compute_progress(token=active)
    assert not window._compute_progress.isVisible()

    window._update_compute_progress(80, 100)
    assert not window._compute_progress.isVisible()


def test_begin_compute_progress_can_skip_process_events(qapp, qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    calls = []

    monkeypatch.setattr(
        window_mod.QApplication,
        "processEvents",
        lambda *args, **kwargs: calls.append("process"),
    )

    token = window._begin_compute_progress(
        "FFT-时间 1/1",
        total=1000,
        process_events=False,
    )

    assert calls == []
    assert window._active_compute_progress_token is token

    window._finish_compute_progress(token=token)
    window._begin_compute_progress("时间域绘制中")

    assert calls == ["process"]
