"""Application entry point."""
import sys

import matplotlib
matplotlib.use('Qt5Agg')

from PyQt5.QtWidgets import QApplication

from .ui import MainWindow
from ._fonts import setup_chinese_font


def main():
    setup_chinese_font()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
