from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QSizePolicy

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
    assert widget.label.text() == "FFT-时间 · 25%"


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


def test_long_load_label_does_not_overlap_or_clip_bar(qapp, qtbot):
    """Load-phase copy is longer than FFT labels; keep label/bar disjoint."""
    widget = ComputeProgressWidget()
    qtbot.addWidget(widget)
    widget.resize(320, 28)
    widget.show()
    qtbot.waitExposed(widget)
    qapp.processEvents()

    widget.begin("加载文件 0/1", total=1000)
    widget.set_progress(
        150,
        1000,
        label="加载 1/1 · 读取 CAN 帧",
    )
    qapp.processEvents()

    assert widget.maximumWidth() >= 480
    assert widget.bar.width() == widget._BAR_WIDTH
    assert "读取 CAN 帧" in widget.label.toolTip()
    assert widget.label.text().endswith("%") or widget.label.text().endswith("…")

    label_rect = widget.label.geometry()
    bar_rect = widget.bar.geometry()
    assert label_rect.right() < bar_rect.left(), (
        f"label {label_rect.getRect()} overlaps bar {bar_rect.getRect()}"
    )
    assert bar_rect.right() <= widget.width() - widget._H_MARGIN, (
        f"bar {bar_rect.getRect()} clipped by widget width {widget.width()}"
    )
    # Even when the outer widget is forced narrower than the ideal hint, the
    # fixed bar must remain fully painted (not squeezed).
    widget.resize(280, 28)
    qapp.processEvents()
    assert widget.bar.width() == widget._BAR_WIDTH
    assert widget.label.geometry().right() < widget.bar.geometry().left()


def test_percent_ink_stays_clear_of_bar_without_resize(qapp, qtbot):
    """Regression: full label text must not overflow onto the bar when width is pinned.

    Previously ``_apply_label_text`` wrote the un-elided string and waited for
    ``resizeEvent`` to trim it.  If the status bar kept the same width,
    resize never fired and QLabel painted '%' into the progress chunk.
    """
    from PyQt5.QtWidgets import QHBoxLayout, QWidget

    host = QWidget()
    host_layout = QHBoxLayout(host)
    host_layout.setContentsMargins(0, 0, 0, 0)
    host_layout.setSpacing(0)

    widget = ComputeProgressWidget()
    narrow = widget._chrome_width() + widget._MIN_LABEL_WIDTH
    host.setFixedWidth(narrow)
    host_layout.addWidget(widget)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    qapp.processEvents()

    widget.begin("加载 1/1 · 解码信号", total=1000)
    # Same outer width as begin() — the bug path is "text changes, size does not".
    widget.set_progress(790, 1000, label="加载 1/1 · 解码信号")
    qapp.processEvents()

    assert widget.width() == narrow
    assert widget.layout().spacing() >= 12
    assert widget.sizePolicy().horizontalPolicy() == QSizePolicy.Preferred

    metrics = QFontMetrics(widget.label.font())
    painted = widget.label.text()
    ink_right = widget.label.geometry().left() + metrics.horizontalAdvance(painted)
    assert ink_right <= widget.bar.geometry().left(), (
        f"label ink ends at {ink_right}, bar starts at {widget.bar.geometry().left()} "
        f"(painted={painted!r}, full={widget._full_label!r})"
    )
    assert metrics.horizontalAdvance(painted) <= widget.label.width()
    # Full copy stays on the tooltip even when the visible label is elided.
    assert widget.label.toolTip() == "加载 1/1 · 解码信号 · 79%"


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


def test_restore_progress_token_blocks_nested_process_events(
    qapp, qtbot, monkeypatch
):
    """Project restore owns the status bar; nested begins must not drain Qt."""
    window = MainWindow()
    qtbot.addWidget(window)
    calls = []

    monkeypatch.setattr(
        window_mod.QApplication,
        "processEvents",
        lambda *args, **kwargs: calls.append("process"),
    )

    token = window._begin_compute_progress(
        "正在恢复分析 0/2",
        total=2,
        process_events=False,
    )
    window._analysis_jobs.set_progress_token("restore", token)

    nested = window._begin_compute_progress("时间域绘制中")
    assert nested is token
    assert calls == []

    window._update_compute_progress(1, 2, token=token, process_events=True)
    assert calls == []

    window._finish_compute_progress(token=token)
    assert window._active_compute_progress_token is token

    window._analysis_jobs.clear_progress_token("restore")
    window._finish_compute_progress(token=token)
    assert window._active_compute_progress_token is None


def test_analysis_restore_pump_survives_closed_window(qapp, qtbot, monkeypatch):
    """A pending restore timer must not paint a deleted status-bar bar."""
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        type(window),
        "_recompute_restored_analysis_view",
        lambda self, section, view_id: None,
    )
    window._analysis_restore_pending = {("fft", "view-1")}
    window._dispatch_pending_analysis_restore()
    assert window._analysis_jobs.progress_token("restore") is not None

    window.close()
    window.deleteLater()
    qapp.processEvents()
    qapp.processEvents()
