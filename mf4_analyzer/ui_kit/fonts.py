"""Font setup helpers for Qt/PyQt entry points."""


def setup_chinese_font():
    """Stable no-op after matplotlib retirement.

    Qt/pyqtgraph chart fonts are configured through the QApplication path.
    """
    return None


__all__ = ["setup_chinese_font"]
