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


def _load_app_icon():
    """Build a multi-resolution QIcon from assets/icons/tracelab_*.png.

    Uses pre-rendered PNGs (not .ico/.icns) so the icon shows correctly on every
    platform regardless of which Qt image-format plugins are installed.
    """
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QIcon

    # PyInstaller --onedir/--onefile expose the bundle root via sys._MEIPASS.
    # In dev, fall back to the repo root (parent of the mf4_analyzer package).
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        icon_dir = Path(base) / "assets" / "icons"
    else:
        icon_dir = Path(__file__).resolve().parent.parent / "assets" / "icons"
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256, 512):
        png = icon_dir / f"tracelab_{size}.png"
        if png.exists():
            icon.addFile(str(png), QSize(size, size))
    return icon if not icon.isNull() else None


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


def main():
    _configure_high_dpi()

    from PyQt5.QtWidgets import QApplication

    MainWindow = _import_symbol("ui", "MainWindow")
    setup_chinese_font = _import_symbol("ui_kit", "setup_chinese_font")
    load_stylesheet = _import_symbol("ui_kit", "load_stylesheet")
    install_glass_tooltips = _import_symbol("ui_kit", "install_glass_tooltips")

    setup_chinese_font()
    app = QApplication(sys.argv)
    from mf4_analyzer.ui.pg_canvas.fonts import apply_global_chart_font
    apply_global_chart_font(app)
    app.setStyle('Fusion')
    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    load_stylesheet(app)
    install_glass_tooltips(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
