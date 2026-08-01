"""Qt/pyqtgraph batch image renderer (Batch 2: time + FFT)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from mf4_analyzer.batch_image_options import BatchRenderOptions

from ._builder import build_batch_scene
from ._dispatch import render_on_gui_thread
from ._export import render_scene_image, save_png
from ._models import BatchRenderContext, BatchSeries, BatchTimeFigureSpec
from ._page import render_metadata


def render_batch_image(
    payload,
    path,
    params: Mapping[str, Any] | None = None,
    options: BatchRenderOptions | None = None,
    context: BatchRenderContext | None = None,
    warnings_out: list[str] | None = None,
) -> Path:
    """Render one prepared time/FFT payload to an exact-pixel PNG."""

    render_options = options or BatchRenderOptions()
    render_context = context or BatchRenderContext()
    if render_options.format != "png":
        raise ValueError("Qt batch renderer supports PNG output only")

    def render() -> Path:
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
            return save_png(image, path)
        finally:
            scene.close()

    return render_on_gui_thread(render)


__all__ = [
    "BatchRenderContext",
    "BatchRenderOptions",
    "BatchSeries",
    "BatchTimeFigureSpec",
    "render_batch_image",
]
