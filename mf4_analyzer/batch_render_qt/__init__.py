"""Qt/pyqtgraph batch image renderer for all four analysis kinds."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from mf4_analyzer.batch_image_options import BatchRenderOptions

from ._builder import build_batch_scene
from ._dispatch import render_on_gui_thread
from ._export import render_scene_image, save_png
from ._models import (
    BatchChartDiagnostic, BatchRenderContext, BatchSeries, BatchStatisticRow,
    BatchTimeFigureSpec,
)
from ._page import render_metadata


def render_batch_image(
    payload,
    path,
    params: Mapping[str, Any] | None = None,
    options: BatchRenderOptions | None = None,
    context: BatchRenderContext | None = None,
    warnings_out: list[str] | None = None,
) -> Path:
    """Render one prepared batch payload to an exact-pixel PNG."""

    render_options = options or BatchRenderOptions()
    render_context = context or BatchRenderContext()
    if render_options.format != "png":
        raise ValueError("Qt batch renderer supports PNG output only")

    def render():
        scene = build_batch_scene(
            payload,
            params=params,
            options=render_options,
            context=render_context,
            warnings_out=warnings_out,
        )
        try:
            image = render_scene_image(
                scene, metadata=render_metadata(render_context)
            )
            return image
        finally:
            scene.close()

    # QWidget construction/layout/painting must stay on QApplication's
    # thread. QImage is an implicitly shared, reentrant value type, so the
    # caller can perform the lossless PNG encode/write after the GUI work is
    # complete. Batch workers therefore do not block the GUI during encoding;
    # direct GUI-thread callers retain the same synchronous API.
    image = render_on_gui_thread(render)
    return save_png(image, path)


__all__ = [
    "BatchRenderContext",
    "BatchChartDiagnostic",
    "BatchRenderOptions",
    "BatchSeries",
    "BatchStatisticRow",
    "BatchTimeFigureSpec",
    "render_batch_image",
]
