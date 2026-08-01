"""Exact-pixel QImage rendering and PNG encoding."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtGui import QImage, QPainter

from ._builder import BuiltBatchScene


def render_scene_image(
    scene: BuiltBatchScene, *, metadata: dict[str, str] | None = None
) -> QImage:
    """Render one settled scene at the option's authoritative pixel size."""

    scene.show_and_settle()
    image = QImage(
        scene.options.width_px,
        scene.options.height_px,
        QImage.Format_ARGB32_Premultiplied,
    )
    image.fill(scene.theme.background)
    image.setDotsPerMeterX(round(scene.options.dpi / 0.0254))
    image.setDotsPerMeterY(round(scene.options.dpi / 0.0254))
    for key, value in dict(metadata or {}).items():
        image.setText(str(key), str(value))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    scene.widget.render(painter)
    painter.end()
    return image


def save_png(image: QImage, path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(target), "PNG"):
        raise RuntimeError(f"failed to write batch PNG: {target}")
    return target


__all__ = ["render_scene_image", "save_png"]
