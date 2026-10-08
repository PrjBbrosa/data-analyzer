"""A new data-only palette reaches fresh GUI/Batch consumers without wiring."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_second_style_is_discovered_by_gui_and_batch_in_fresh_process(tmp_path):
    root = Path(__file__).resolve().parents[1]
    package = tmp_path / "colormaps"
    shutil.copytree(root / "mf4_analyzer/colormaps/resources", package / "resources")
    resources = package / "resources"
    data = json.loads((resources / "luts/head-style-v1.json").read_text())
    ident = "tracelab.extension-probe.v1"
    data.update(id=ident, rgb=list(reversed(data["rgb"])), source_note="Synthetic extension probe")
    digest = hashlib.sha256(bytes(v for row in data["rgb"] for v in row)).hexdigest()
    (resources / "luts/extension-probe-v1.json").write_text(json.dumps(data))
    catalog = json.loads((resources / "catalog.json").read_text())
    catalog["entries"].append(dict(id=ident, label="Extension probe", provider="rgb_lut",
                                   file="luts/extension-probe-v1.json", rgb_sha256=digest))
    (resources / "catalog.json").write_text(json.dumps(catalog))
    # Redirect resource discovery BEFORE the first registry import. This models
    # shipping the new files, not hot-loading or changing production constants.
    script = r'''
import importlib.resources
from pathlib import Path
import sys
original = importlib.resources.files
importlib.resources.files = lambda anchor: Path(sys.argv[1]) if anchor == "mf4_analyzer.colormaps" else original(anchor)
from mf4_analyzer.colormaps import validate_colormap_resources, load_rgb_lut
assert len(validate_colormap_resources()) == 9
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication, QEvent
import numpy as np
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas, _HeatmapAxisHandle
from mf4_analyzer.ui.dialogs import ChartOptionsDialog
from mf4_analyzer.batch_render_qt._builder import _resolve_heatmap_colormap
app = QApplication([])
app.setOrganizationName("ColormapExtensionTest")
app.setApplicationName("Isolated")
ident = "tracelab.extension-probe.v1"
canvas = PgHeatmapCanvas(with_slice=False)
canvas.plot_or_update_heatmap(np.arange(9.).reshape(3,3), (0,2), (0,2), cmap=ident)
dialog = ChartOptionsDialog(canvas, _HeatmapAxisHandle(canvas))
assert dialog.combo_cmap.currentData() == ident
assert dialog.combo_cmap.currentText() == "Extension probe"
warnings = []
cm, lut = _resolve_heatmap_colormap({"cmap":ident}, warnings)
assert not warnings
np.testing.assert_array_equal(lut[:,:3], load_rgb_lut(ident))
np.testing.assert_array_equal(canvas._img.getColorMap().getLookupTable(0,1,256,alpha=False), lut[:,:3])
dialog.close()
canvas.close()
dialog.deleteLater()
canvas.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
print("second style discovered by GUI and Batch")
'''
    env = dict(os.environ, PYTHONPATH=str(root), QT_QPA_PLATFORM="offscreen",
               XDG_CONFIG_HOME=str(tmp_path / "settings"))
    result = subprocess.run([sys.executable, "-c", script, str(package)], env=env,
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
