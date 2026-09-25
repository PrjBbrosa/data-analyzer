"""Chart-options button capability: FRF stays disabled, line/time stay enabled."""

from mf4_analyzer.ui.chart_stack.cards import _ChartCard
from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


_FRF_REASON = "FRF 的幅值、相位和相干是三种量纲，当前图表选项还不能同时编辑这三张图。"
_UNSUPPORTED = "当前图表不支持图表选项"


def test_frf_chart_options_availability_explains_three_axes():
    canvas = PgFrfCanvas()
    try:
        assert canvas.chart_options_availability() == (False, _FRF_REASON)
    finally:
        canvas.deleteLater()


def test_frf_chart_options_button_is_disabled_with_reason(qapp):
    canvas = PgFrfCanvas()
    card = _ChartCard(canvas, chart_mode="fft")
    opened = []

    def _open():
        opened.append("frf")
        return True

    canvas.open_chart_options_dialog = _open
    try:
        assert card._options_btn.isEnabled() is False
        assert _FRF_REASON in card._options_btn.toolTip()
        card._options_btn.click()
        assert card.open_chart_options() is False
        assert opened == []
    finally:
        card.deleteLater()
        canvas.deleteLater()


def test_line_and_time_chart_options_buttons_stay_enabled(qapp):
    line = PgLineCanvas()
    time_canvas = TimeDomainCanvasPG()
    line_card = _ChartCard(line, chart_mode="frf")
    time_card = _ChartCard(time_canvas, chart_mode="time")
    try:
        assert not hasattr(line, "chart_options_availability")
        assert not hasattr(time_canvas, "chart_options_availability")
        assert line_card._options_btn.isEnabled() is True
        assert time_card._options_btn.isEnabled() is True
        assert line_card._options_btn.toolTip() == "图表选项"
        assert time_card._options_btn.toolTip() == "图表选项"
    finally:
        line_card.deleteLater()
        time_card.deleteLater()
        line.deleteLater()
        time_canvas.deleteLater()


def test_chart_options_button_follows_focus_canvas_capability(qapp):
    time_canvas = TimeDomainCanvasPG()
    frf = PgFrfCanvas()
    line = PgLineCanvas()
    card = _ChartCard(time_canvas)
    opened = []

    def _open_line():
        opened.append("line")
        return True

    try:
        assert card._options_btn.isEnabled() is True
        assert card._options_btn.toolTip() == "图表选项"

        card._options_canvas_provider = lambda: frf
        card.set_focus_marker(None)
        assert card._options_btn.isEnabled() is False
        assert _FRF_REASON in card._options_btn.toolTip()

        card.set_focus_marker("#2d7ff9")
        assert card._options_btn.isEnabled() is False

        line.open_chart_options_dialog = _open_line
        card._options_canvas_provider = lambda: line
        assert card._options_btn.isEnabled() is True
        assert card._options_btn.toolTip() == "图表选项"
        assert card.open_chart_options() is True
        assert opened == ["line"]

        line.open_chart_options_dialog = None
        card._options_canvas_provider = lambda: line
        assert card._options_btn.isEnabled() is False
        assert card._options_btn.toolTip() == _UNSUPPORTED
        assert card.open_chart_options() is False
        assert opened == ["line"]
    finally:
        card.deleteLater()
        time_canvas.deleteLater()
        frf.deleteLater()
        line.deleteLater()


def test_disabled_chart_options_button_does_not_open_dialog(qapp):
    canvas = PgFrfCanvas()
    card = _ChartCard(canvas)
    opened = []

    def _open():
        opened.append("frf")
        return True

    canvas.open_chart_options_dialog = _open
    try:
        assert card._options_btn.isEnabled() is False
        card._options_btn.click()
        assert card.open_chart_options() is False
        assert opened == []
    finally:
        card.deleteLater()
        canvas.deleteLater()
