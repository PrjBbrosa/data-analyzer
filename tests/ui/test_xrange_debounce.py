import numpy as np

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _subplot_canvas():
    c = TimeDomainCanvasPG()
    c.resize(800, 600)
    t = np.linspace(0, 10, 5000)
    rows = [
        (f"ch{i}", True, t, np.sin(t + i), "#1769e0", "u", "fid")
        for i in range(3)
    ]
    c.plot_channels(rows, mode="subplot")
    return c


def test_tick_recompute_is_debounced_not_per_drag_tick(qapp):
    c = _subplot_canvas()
    calls = {"n": 0}
    tick_density = c._tick_density_controller
    orig = tick_density._apply_target_x_ticks_to_all_axes

    def wrapped():
        calls["n"] += 1
        return orig()

    tick_density._apply_target_x_ticks_to_all_axes = wrapped

    src = c._primary_xaxis_ax
    for _ in range(20):
        c._on_xrange_changed(src)
    assert calls["n"] == 0, "刻度重算不得在每个拖动 tick 同步执行"

    c._flush_pending_refresh()
    assert calls["n"] >= 1, "刻度重算必须在松手/去抖刷新时执行"


def test_emit_xrange_is_debounced_not_per_drag_tick(qapp):
    c = _subplot_canvas()
    emitted = {"n": 0}
    c.xrange_changed.connect(lambda lo, hi: emitted.__setitem__("n", emitted["n"] + 1))

    src = c._primary_xaxis_ax
    for _ in range(20):
        c._on_xrange_changed(src)
    assert emitted["n"] == 0, "xrange_changed 不得每个拖动 tick 发一次"

    c._flush_pending_refresh()
    assert emitted["n"] >= 1, "松手时必须发一次 xrange_changed"


def test_sibling_propagation_stays_per_tick(qapp):
    c = _subplot_canvas()
    cnt = {"n": 0}
    orig = c._propagate_xlim_to_siblings

    def wrapped(source=None):
        cnt["n"] += 1
        return orig(source=source)

    c._propagate_xlim_to_siblings = wrapped

    src = c._primary_xaxis_ax
    for _ in range(10):
        c._on_xrange_changed(src)
    assert cnt["n"] == 10, "子图 x 范围同步必须保持每 tick"
