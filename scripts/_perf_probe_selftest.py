"""离屏自测 TRACELAB_PERF 探针：加载 6×129.5kHz 通道 + 低通 + subplot plot_time。

仅用于验证探针字段齐全/能跑通；离屏 paint 数字不代表真机。运行：
  TRACELAB_PERF=1 QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/_perf_probe_selftest.py
诊断后可删除本脚本。
"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TRACELAB_PERF", "1")

from PyQt5.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from mf4_analyzer.ui.main_window.window import MainWindow

HDF = str(Path("testdoc/260417-ripple-PK2C-电机加热-1.hdf").resolve())

w = MainWindow()
w.resize(1600, 900)
w.show()
app.processEvents()

w.load_file(HDF)
app.processEvents()

# 选取一个 fid，挑出采样率最高(≈129.5kHz)的前 6 个通道。
fid = next(iter(w.files))
fd = w.files[fid]
# 按 fs 选 wideband 通道：用 channel 列表 + per-channel fs（回退 fd.fs）。
cols = [c for c in fd.data.columns]
# 估各通道点数最多的（同 fid 下 wideband 列点数=最长）。HEAD 多速率分组后，
# 同一 FileData 通常已是同速率；直接取前 6 列即可触发 dense-stack。
chosen = cols[:6]
print("chosen channels:", chosen, "fid fs=", getattr(fd, "fs", None),
      "len=", len(fd.data))

palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
checked = [(fid, ch, palette[i % len(palette)]) for i, ch in enumerate(chosen)]
w.navigator.set_checked_channels(checked)
app.processEvents()

# 启用低通滤波。
fp = w.inspector.filter_panel
fp.set_enabled(True)
# 低通默认即 combo_kind[0]；确保 cutoff>0。
try:
    if fp.spin_cut.value() <= 0:
        fp.spin_cut.setValue(1000.0)
except Exception:
    pass
print("filter enabled:", fp.is_enabled(), "spec:", fp.filter_spec())
app.processEvents()

# subplot 模式（卡片默认即 subplot）。触发一次绘图。
w.plot_time()
app.processEvents()

log = Path.home() / "tracelab_perf.log"
print("==== LOG TAIL ====")
print(log.read_text(encoding="utf-8"))
