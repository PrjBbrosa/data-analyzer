"""Guideline-hardening Task 9 — scattered defaults convergence (C6/C7/C10/C11/P3)."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_c6_tick_density_uses_shared_default_symbol():
    """C6: canvas default must reference DEFAULT_CHART_TICK_DENSITY, not (20, 15)."""
    from mf4_analyzer.ui.chart_defaults import DEFAULT_CHART_TICK_DENSITY
    from mf4_analyzer.ui.chart_stack.toolbar import (
        DEFAULT_CHART_TICK_DENSITY as toolbar_default,
    )
    from mf4_analyzer.ui.pg_canvas import tick_density as td_mod

    assert DEFAULT_CHART_TICK_DENSITY == (20, 15)
    assert toolbar_default is DEFAULT_CHART_TICK_DENSITY
    source = Path(td_mod.__file__).read_text(encoding="utf-8")
    assert "DEFAULT_CHART_TICK_DENSITY" in source
    assert "self.density = (20, 15)" not in source
    assert "self.density = DEFAULT_CHART_TICK_DENSITY" in source


def test_c7_chart_font_pt_shared_by_defaults_and_measure_sites():
    """C7: render defaults and the three measure sites share CHART_FONT_PT."""
    from mf4_analyzer.qt_chart_fonts import (
        CHART_FONT_PT,
        apply_axis_font,
        apply_text_item_font,
        chart_font,
    )

    assert CHART_FONT_PT == pytest.approx(9.0)
    assert inspect.signature(chart_font).parameters["point_size"].default is CHART_FONT_PT
    assert (
        inspect.signature(apply_axis_font).parameters["point_size"].default
        is CHART_FONT_PT
    )
    assert (
        inspect.signature(apply_text_item_font).parameters["point_size"].default
        is CHART_FONT_PT
    )

    measure_files = (
        ROOT / "mf4_analyzer" / "ui" / "pg_canvas" / "tick_density.py",
        ROOT / "mf4_analyzer" / "ui" / "pg_canvas" / "overlay_axes.py",
        ROOT / "mf4_analyzer" / "ui" / "pg_canvas" / "analysis_axes.py",
    )
    for path in measure_files:
        source = path.read_text(encoding="utf-8")
        assert "_pg_chart_font(CHART_FONT_PT)" in source
        assert "_pg_chart_font(9)" not in source


def test_c10_overlap_normalization_is_shared():
    """C10: percent/fraction coercion + clamp lives in one helper."""
    from mf4_analyzer.batch_compute import avg_overlap_fraction
    from mf4_analyzer.signal.analysis_defaults import normalize_overlap_fraction

    assert normalize_overlap_fraction(75) == pytest.approx(0.75)
    assert normalize_overlap_fraction(0.5) == pytest.approx(0.5)
    assert normalize_overlap_fraction(120) == pytest.approx(0.95)
    assert normalize_overlap_fraction(-10) == pytest.approx(0.0)
    assert avg_overlap_fraction({"avg_overlap": 80}) == pytest.approx(0.8)
    assert avg_overlap_fraction({"avg_overlap": 0.25}) == pytest.approx(0.25)

    fft_mixin = (
        ROOT / "mf4_analyzer" / "ui" / "main_window" / "_fft_mixin.py"
    ).read_text(encoding="utf-8")
    method_buttons = (
        ROOT / "mf4_analyzer" / "ui" / "drawers" / "batch" / "method_buttons.py"
    ).read_text(encoding="utf-8")
    assert "normalize_overlap_fraction" in fft_mixin
    assert "normalize_overlap_fraction" in method_buttons
    assert "overlap_pct / 100.0" not in fft_mixin


def test_c11_coherence_and_window_candidates_share_defaults():
    """C11: coherence threshold and window order converge on analysis_defaults."""
    from mf4_analyzer.signal.analysis_defaults import (
        ANALYSIS_WINDOW_CANDIDATES,
        DEFAULT_ANALYSIS_WINDOW,
        DEFAULT_COHERENCE_THRESHOLD,
    )
    from mf4_analyzer.batch_render_models import BatchFrfFigureSpec
    from mf4_analyzer.ui.pg_canvas.frf_canvas import _DEFAULT_DISPLAY

    assert DEFAULT_COHERENCE_THRESHOLD == pytest.approx(0.8)
    assert DEFAULT_ANALYSIS_WINDOW == "hanning"
    assert ANALYSIS_WINDOW_CANDIDATES.index("flattop") == 5
    assert _DEFAULT_DISPLAY["coherence_threshold"] == DEFAULT_COHERENCE_THRESHOLD
    assert BatchFrfFigureSpec.__dataclass_fields__[
        "coherence_threshold"
    ].default == DEFAULT_COHERENCE_THRESHOLD

    sources = [
        ROOT / "mf4_analyzer" / "ui" / "inspector_sections" / "contextual_fft.py",
        ROOT / "mf4_analyzer" / "ui" / "inspector_sections" / "contextual_fft_time.py",
        ROOT / "mf4_analyzer" / "ui" / "inspector_sections" / "contextual_order.py",
        ROOT / "mf4_analyzer" / "ui" / "inspector_sections" / "contextual_frf.py",
        ROOT / "mf4_analyzer" / "ui" / "drawers" / "batch" / "method_buttons.py",
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "ANALYSIS_WINDOW_CANDIDATES" in text
        assert "hanning', 'flattop'" not in text

    # Five product default sites must reference the shared coherence symbol.
    coherence_sites = [
        ROOT / "mf4_analyzer" / "ui" / "pg_canvas" / "frf_canvas.py",
        ROOT / "mf4_analyzer" / "ui" / "inspector_sections" / "contextual_frf.py",
        ROOT / "mf4_analyzer" / "ui" / "drawers" / "batch" / "method_buttons.py",
        ROOT / "mf4_analyzer" / "batch_render_models.py",
        ROOT / "mf4_analyzer" / "batch.py",
    ]
    for path in coherence_sites:
        assert "DEFAULT_COHERENCE_THRESHOLD" in path.read_text(encoding="utf-8")


def test_c11_db_reference_degraded_helper_is_shared():
    from mf4_analyzer import db_reference
    from mf4_analyzer.ui.main_window import _fft_time_mixin, _order_mixin

    resolution = db_reference.degraded_numeric_resolution({"db_reference": 2.5})
    assert resolution.value == pytest.approx(2.5)
    assert resolution.source == "generic"
    bad = db_reference.degraded_numeric_resolution({"db_reference": 0.0})
    assert bad.value == pytest.approx(1.0)

    for mod in (_fft_time_mixin, _order_mixin):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "degraded_numeric_resolution" in source
        assert "source='generic')" not in source


def test_p3_format_range_value_branches_on_rounded_form():
    """P3: branch like _fmt_rate — round first, then choose format path."""
    from mf4_analyzer.ui.pg_canvas.context_menu import _format_range_value

    assert _format_range_value(999.6) == "999.6"
    # Rounds into the scientific branch rather than printing "1000" via .3f.
    assert _format_range_value(999.9996) == f"{999.9996:.3g}"
    assert _format_range_value(0.0099996) == f"{0.0099996:.3g}"
    assert _format_range_value(12.5) == "12.5"


def test_analysis_defaults_module_has_no_gui_imports():
    path = ROOT / "mf4_analyzer" / "signal" / "analysis_defaults.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = ("PyQt5", "matplotlib", "mf4_analyzer.ui", "pyqtgraph")
    for name in imported:
        assert not any(
            name == item or name.startswith(item + ".") for item in forbidden
        ), name
