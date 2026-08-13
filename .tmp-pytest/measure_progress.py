# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QFontMetrics
import sys

app = QApplication(sys.argv)
from mf4_analyzer.ui_kit import stylesheet
stylesheet.load_stylesheet(app)
from mf4_analyzer.ui.compute_progress import ComputeProgressWidget
from mf4_analyzer.ui.main_window import MainWindow

out = []
w = ComputeProgressWidget()
w.begin("加载 1/1 · 解码信号", total=1000)
w.set_progress(790, 1000)
w.show()
app.processEvents()
w.resize(w.sizeHint())
app.processEvents()
fm = QFontMetrics(w.label.font())
tw = fm.horizontalAdvance(w.label.text())
out.append(f"standalone text={w.label.text()!r}")
out.append(
    f"adv={tw} label_w={w.label.width()} "
    f"gap={w.bar.geometry().left() - w.label.geometry().right()} "
    f"ink_over={w.label.geometry().left() + tw - w.bar.geometry().left()}"
)

mw = MainWindow()
mw.resize(1280, 800)
mw.show()
app.processEvents()
tok = mw._begin_compute_progress("加载 1/1 · 解码信号", total=1000)
mw._update_compute_progress(790, 1000, token=tok, process_events=True)
cp = mw._compute_progress
app.processEvents()
fm2 = QFontMetrics(cp.label.font())
tw2 = fm2.horizontalAdvance(cp.label.text())
out.append(f"mainwin text={cp.label.text()!r}")
out.append(
    f"cp={cp.geometry().getRect()} label={cp.label.geometry().getRect()} "
    f"bar={cp.bar.geometry().getRect()}"
)
out.append(
    f"gap={cp.bar.geometry().left() - cp.label.geometry().right()} "
    f"adv={tw2} label_w={cp.label.width()} "
    f"ink_over={cp.label.geometry().left() + tw2 - cp.bar.geometry().left()}"
)
out.append(
    f"font={cp.label.font().family()!r} px={cp.label.font().pixelSize()} "
    f"pt={cp.label.font().pointSize()} weight={cp.label.font().weight()}"
)
sb = mw.statusBar
out.append(f"sb={sb.width()}x{sb.height()}")
for child in sb.children():
    if isinstance(child, QWidget) and child.isVisible():
        t = child.text() if hasattr(child, "text") else ""
        out.append(
            f"child {child.objectName()} {child.__class__.__name__} "
            f"{child.geometry().getRect()} text={t!r}"
        )
pix = cp.grab()
pix.save(r"D:\Coding project\data analyzer\.tmp-pytest\progress_79.png")
sp = sb.grab()
sp.save(r"D:\Coding project\data analyzer\.tmp-pytest\statusbar_79.png")
out.append(
    f"saved progress={pix.width()}x{pix.height()} "
    f"statusbar={sp.width()}x{sp.height()}"
)
path = r"D:\Coding project\data analyzer\.tmp-pytest\progress_measure.txt"
open(path, "w", encoding="utf-8").write("\n".join(out))
print("wrote", path)
