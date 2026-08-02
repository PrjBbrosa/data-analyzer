"""Classification of optional batch-renderer import failures."""
from __future__ import annotations


def is_optional_renderer_import_error(exc: ImportError) -> bool:
    """Return whether ``exc`` identifies an absent optional renderer stack."""
    name = str(getattr(exc, "name", "") or "")
    return (
        name == "PyQt5"
        or name.startswith("PyQt5.")
        or name == "pyqtgraph"
        or name.startswith("pyqtgraph.")
        or name == "mf4_analyzer.batch_render"
        or name.startswith("mf4_analyzer.batch_render_qt")
    )


__all__ = ["is_optional_renderer_import_error"]
