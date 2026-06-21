"""Task 6 TDD: preset guard for weighting in _apply_preset_values + Order invariant.

TDD flow:
- Problem ⑤ tests: RED before guard added, GREEN after.
- Order display-only invariant: RED before (or immediately GREEN if
  _render_order_on already doesn't bake window into _matrix_disp), GREEN after.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Problem ⑤ — _apply_preset_values must NOT reset weighting when key absent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('factory_spec', [
    ('FFTContextual', 'fft'),
    ('FFTTimeContextual', 'fft_time'),
    ('OrderContextual', 'order'),
])
def test_apply_preset_values_preserves_weighting_when_key_absent(
        qapp, factory_spec):
    """_apply_preset_values with a dict lacking 'weighting' must leave
    the current weighting unchanged (not reset it to 'None').

    TDD-RED before guard: d.get('weighting', 'None') resets A → None.
    TDD-GREEN after guard: if 'weighting' in d: branch skips the call.
    """
    class_name, _id = factory_spec
    mod = __import__(
        'mf4_analyzer.ui.inspector_sections',
        fromlist=[class_name],
    )
    ctx = getattr(mod, class_name)()

    # Set weighting to 'A' explicitly.
    ctx._apply_weighting_value('A')
    assert ctx.get_params()['weighting'] == 'A', "pre-condition: weighting must be A"

    # Build a preset dict WITHOUT the 'weighting' key (old-flat preset).
    full_preset = ctx._collect_preset()
    legacy_preset = {k: v for k, v in full_preset.items() if k != 'weighting'}
    assert 'weighting' not in legacy_preset, "key must be absent to test the guard"

    # Load the legacy preset. After the fix, weighting must stay 'A'.
    ctx._apply_preset_values(legacy_preset)

    assert ctx.get_params()['weighting'] == 'A', (
        f"[{class_name}] _apply_preset_values reset weighting to "
        f"'{ctx.get_params()['weighting']}' even though 'weighting' key was absent "
        f"in the preset dict. Add 'if weighting in d:' guard (mirror apply_params)."
    )


@pytest.mark.parametrize('factory_spec', [
    ('FFTContextual', 'fft'),
    ('FFTTimeContextual', 'fft_time'),
    ('OrderContextual', 'order'),
])
def test_apply_preset_values_does_update_weighting_when_key_present(
        qapp, factory_spec):
    """When 'weighting' IS in the preset dict, _apply_preset_values must
    apply it (so full presets that include weighting still work).

    This is the non-regression counterpart to the guard test above.
    """
    class_name, _id = factory_spec
    mod = __import__(
        'mf4_analyzer.ui.inspector_sections',
        fromlist=[class_name],
    )
    ctx = getattr(mod, class_name)()

    # Set weighting to 'A' first.
    ctx._apply_weighting_value('A')
    assert ctx.get_params()['weighting'] == 'A'

    # A preset that explicitly contains weighting='None' must reset it.
    preset_with_key = dict(ctx._collect_preset())
    preset_with_key['weighting'] = 'None'
    ctx._apply_preset_values(preset_with_key)

    assert ctx.get_params()['weighting'] == 'None', (
        f"[{class_name}] _apply_preset_values failed to apply weighting "
        f"when the key is present."
    )


# ---------------------------------------------------------------------------
# Order display-only invariant: _render_order_on must NOT bake z_floor/z_ceiling
# into _matrix_disp (manual mode).
# ---------------------------------------------------------------------------

def _make_cot_result():
    """Minimal COTResult fixture for render tests."""
    from mf4_analyzer.signal.order_cot import COTResult, COTParams
    rng = np.random.default_rng(7)
    n_frames = 16
    n_orders = 24
    amp = rng.uniform(1e-4, 0.5, (n_frames, n_orders)).astype(np.float32)
    return COTResult(
        times=np.linspace(0.0, 1.5, n_frames),
        orders=np.linspace(0.5, 12.0, n_orders),
        amplitude=amp,
        params=COTParams(
            samples_per_rev=64,
            nfft=128,
            max_order=12.0,
            order_res=0.5,
        ),
        metadata={},
    )


def _make_canvas():
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)
    return c


def _direct_render(canvas, result, z_floor, z_ceiling):
    """Call _render_order_on logic directly without needing a full MainWindow.

    Mirrors the actual _render_order_on dB path:
      matrix = amplitude.T
      dB-convert with reference=1.0
      plot_or_update_heatmap with amplitude_mode='amplitude', z_auto=False
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _AUTO_CEILING_PCT, _AUTO_SPAN_DB, _robust_db_ceiling,
    )
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

    matrix = result.amplitude.T
    db_ref = 1.0
    matrix_db = SpectrogramAnalyzer.amplitude_to_db(matrix, reference=db_ref)

    canvas._amplitude_mode = 'amplitude_db'
    canvas.plot_or_update_heatmap(
        matrix=matrix_db,
        x_extent=(float(result.times[0]), float(result.times[-1])),
        y_extent=(float(result.orders[0]), float(result.orders[-1])),
        x_label='Time (s)',
        y_label='Order',
        title='Test',
        cmap='turbo',
        interp='bilinear',
        cbar_label='Amplitude (dB re 1)',
        amplitude_mode='amplitude',
        z_auto=False,
        z_floor=z_floor,
        z_ceiling=z_ceiling,
        vmin=None,
        vmax=None,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
        x_coords=result.times, y_coords=result.orders,
    )


def test_render_order_matrix_invariant_across_manual_window_change(qapp):
    """Invariant: _matrix_disp is byte-identical across two renders with
    different z_floor/z_ceiling (manual mode, same COTResult).

    The display LEVELS must differ; only the colour mapping changes.
    Mirrors test_plot_result_matrix_invariant_across_window_rerenders but
    for the Order path (plot_or_update_heatmap with pre-converted dB matrix).

    TDD-RED if plot_or_update_heatmap clips _matrix_disp to [z_floor, z_ceiling].
    TDD-GREEN because plot_or_update_heatmap's amplitude='amplitude' path
    does NOT clip the matrix.
    """
    result = _make_cot_result()
    c = _make_canvas()

    # First render: tight high window.
    _direct_render(c, result, z_floor=-10.0, z_ceiling=0.0)
    matrix_first = c._matrix_disp.copy()
    levels_first = c._img.getLevels()

    # Second render: wide low window (very different colours).
    _direct_render(c, result, z_floor=-80.0, z_ceiling=-20.0)
    matrix_second = c._matrix_disp.copy()
    levels_second = c._img.getLevels()

    # The stored matrix must be byte-identical.
    assert np.array_equal(matrix_first, matrix_second), (
        "_render_order_on path baked the color window into _matrix_disp: "
        f"first_min={matrix_first.min():.2f}, second_min={matrix_second.min():.2f}"
    )

    # Sanity: levels must differ (otherwise the test is trivial).
    lf0, lf1 = float(levels_first[0]), float(levels_first[1])
    ls0, ls1 = float(levels_second[0]), float(levels_second[1])
    assert (lf0, lf1) != (ls0, ls1), (
        "Levels should differ between the two manual windows but were equal"
    )

    c.deleteLater()
