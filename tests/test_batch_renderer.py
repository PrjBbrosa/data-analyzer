"""Public-contract tests for the Qt batch-render facade.

Detailed scene, parity, heatmap, font, and pixel assertions live in the
``test_batch_render_qt*`` suites.  This file deliberately tests only the thin
product boundary that callers are allowed to import.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtGui import QImage, QImageReader


def test_facade_exports_only_supported_qt_renderer_contract():
    import mf4_analyzer.batch_render as facade
    import mf4_analyzer.batch_render_qt as implementation

    assert facade.__all__ == [
        "BatchRenderContext",
        "BatchRenderOptions",
        "BatchSeries",
        "BatchTimeFigureSpec",
        "render_batch_image",
    ]
    assert facade.render_batch_image is implementation.render_batch_image
    assert facade.BatchRenderContext is implementation.BatchRenderContext
    assert not hasattr(facade, "_build_batch_figure")


def test_facade_preserves_render_batch_image_call_signature():
    from mf4_analyzer.batch_render import render_batch_image

    assert tuple(inspect.signature(render_batch_image).parameters) == (
        "payload",
        "path",
        "params",
        "options",
        "context",
        "warnings_out",
    )


def test_facade_source_has_no_matplotlib_runtime_dependency():
    import mf4_analyzer.batch_render as facade

    source = inspect.getsource(facade)
    assert "matplotlib" not in source.lower()
    assert "batch_render_qt" in source


def test_product_package_has_no_matplotlib_runtime_imports():
    """Development comparison tools may use mpl; product modules may not."""
    package = Path(__file__).resolve().parents[1] / "mf4_analyzer"
    matches = []
    for source_path in package.rglob("*.py"):
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
        for node in ast.walk(tree):
            modules = ()
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = (node.module,)
            if any(
                module == "matplotlib" or module.startswith("matplotlib.")
                for module in modules
            ):
                matches.append(
                    f"{source_path.relative_to(package)}:{node.lineno}"
                )

    assert matches == []


def test_importing_batch_does_not_import_qt_runtime(tmp_path):
    code = (
        "import json, sys; import mf4_analyzer.batch; "
        "print(json.dumps(sorted(name for name in sys.modules "
        "if name == 'PyQt5' or name.startswith('PyQt5.') "
        "or name == 'pyqtgraph' or name.startswith('pyqtgraph.'))))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    assert completed.stdout.strip() == "[]"


def test_facade_renders_exact_size_png_offscreen(tmp_path):
    from mf4_analyzer.batch_render import (
        BatchRenderContext,
        BatchRenderOptions,
        render_batch_image,
    )

    target = tmp_path / "fft.png"
    payload = (
        "fft",
        pd.DataFrame({
            "frequency_hz": np.array([0.0, 10.0, 20.0]),
            "amplitude": np.array([0.0, 1.0, 0.25]),
        }),
    )
    result = render_batch_image(
        payload,
        target,
        options=BatchRenderOptions(width_px=640, height_px=360, dpi=72),
        context=BatchRenderContext(
            source_display_name="single-file.mf4",
            channel="acc",
            unit="m/s²",
            method="fft",
        ),
    )

    assert result == target
    image = QImage(str(target))
    assert not image.isNull()
    assert bytes(QImageReader.imageFormat(str(target))).lower() == b"png"
    assert (image.width(), image.height()) == (640, 360)
    sampled_colors = {
        image.pixel(x, y)
        for x in range(0, image.width(), 16)
        for y in range(0, image.height(), 16)
    }
    assert len(sampled_colors) > 1


def test_report_facts_use_runner_nfft_effective_not_requested_auto(tmp_path):
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.batch_render_qt._page import effective_fact_items
    from mf4_analyzer.io import FileData
    from mf4_analyzer.signal import resolve_auto_nfft

    fs = 1000.0
    n = 60000
    t = np.arange(n, dtype=float) / fs
    df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 40.0 * t)})
    path = tmp_path / "runner-facts.csv"
    df.to_csv(path, index=False)
    fd = FileData(path, df, list(df.columns), {}, idx=0, fs=fs)
    preset = AnalysisPreset.from_current_single(
        name="auto facts render",
        method="fft",
        signal=(0, "sig"),
        params={
            "fs": fs,
            "nfft": None,
            "nfft_mode": "auto",
            "avg_mode": "线性平均",
            "avg_overlap": 50,
            "t_win_s": 1.5,
            "window": "hanning",
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    facts = result.items[0].effective_params
    expected = resolve_auto_nfft(fs, n, 1.5, 0.5, purpose="fft_segmented")
    assert facts["nfft"] is None
    assert facts["nfft_effective"] == expected.effective_nfft
    assert "effective_nfft" not in facts
    items = effective_fact_items(facts, facts)
    text = " ".join(items)
    assert f"NFFT={expected.effective_nfft}" in text
    assert "NFFT=auto" not in text.lower()
    assert "NFFT=None" not in text


@pytest.mark.parametrize("illegal_format", ("pdf", "svg"))
def test_facade_rejects_retired_vector_formats(illegal_format):
    from mf4_analyzer.batch_render import BatchRenderOptions

    with pytest.raises(ValueError, match="format must be one of: png"):
        BatchRenderOptions(format=illegal_format)
