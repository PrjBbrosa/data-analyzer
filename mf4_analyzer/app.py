"""Application entry point."""
import importlib
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


def _load_stylesheet(app):
    qss = Path(__file__).resolve().parent / "ui" / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))


def main():
    bootstrap_pyqt5 = _import_symbol("_qt_bootstrap", "bootstrap_pyqt5")
    bootstrap_pyqt5()

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
