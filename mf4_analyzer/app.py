"""Application entry point."""
import importlib
import os
import sys
from pathlib import Path


if __package__ in (None, ""):
    package_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(package_dir.parent))
    package_name = package_dir.name
else:
    package_name = __package__


def _import_symbol(module_name: str, symbol_name: str):
    module = importlib.import_module(f"{package_name}.{module_name}")
    return getattr(module, symbol_name)


def _configure_high_dpi():
    """Enable Qt's per-monitor DPI scaling before QApplication is created."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    from PyQt5.QtCore import QCoreApplication, Qt
    from PyQt5.QtGui import QGuiApplication

    for attribute_name in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        attribute = getattr(Qt, attribute_name, None)
        if attribute is not None:
            QCoreApplication.setAttribute(attribute, True)

    policy_enum = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
    if policy_enum is not None and hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy_enum.PassThrough)


def _load_stylesheet(app):
    """Load style.qss with subcontrol-arrow icon-cache substitution.

    style.qss is a template containing ``{{ICON_*}}`` placeholders for
    QComboBox / QSpinBox arrow glyphs. ``ensure_icon_cache`` renders the
    PNGs into ~/.mf4-analyzer-cache/icons/ on first run (or after a
    qtawesome / palette change) and returns a placeholder→path map.
    ``render_qss_template`` substitutes them; placeholder-free QSS for
    older / external setStyleSheet callers continues to load fine since
    Qt silently drops unresolved ``image: url(...)`` rules.

    Must run AFTER QApplication construction — qtawesome lazy-loads its
    icon font lazily and the device-pixel-ratio that drives PNG
    resolution is read from the QApplication primary screen.
    """
    qss = Path(__file__).resolve().parent / "ui" / "style.qss"
    if not qss.exists():
        return
    template = qss.read_text(encoding="utf-8")
    try:
        ensure_icon_cache = _import_symbol("ui.icons", "ensure_icon_cache")
        render_qss_template = _import_symbol("ui.icons", "render_qss_template")
        icon_paths = ensure_icon_cache()
        stylesheet = render_qss_template(template, icon_paths)
    except Exception as exc:
        # Defensive: if qtawesome import or icon rendering fails (e.g. on
        # an unusual install), fall back to the raw template. Spinbox
        # arrows will be invisible (the original bug) but the rest of
        # the app remains styled. Log so it surfaces in the console.
        print(
            f"[mf4_analyzer.app] icon cache generation failed ({exc!r}); "
            "loading stylesheet without subcontrol arrow glyphs.",
        )
        stylesheet = template
    app.setStyleSheet(stylesheet)


def main():
    _configure_high_dpi()

    import matplotlib

    matplotlib.use("Qt5Agg", force=True)

    from PyQt5.QtWidgets import QApplication

    MainWindow = _import_symbol("ui", "MainWindow")
    setup_chinese_font = _import_symbol("_fonts", "setup_chinese_font")

    setup_chinese_font()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    _load_stylesheet(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
