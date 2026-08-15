#!/usr/bin/env python3
"""回切时 ink 在 Y 恢复前测量的三个后果（画布级复现）。

顺序照产品 _view_mixin._render_view_to_canvas：
    plot_channels(defer_first_frame=True)   # Y 还是占位区间 [0, 1]
    restore_visible_xlim(state.xlim)        # 内部同步 flush -> 在这里测 ink
    restore_visible_ylims(state.ylims)      # Y 到这一步才被恢复
后果：ink 放大 -> (1) 超 _INK_OFF_BUDGET 时 envelope 分桶被砍（曲线变粗糙）；
(2) AA 拒绝、质量点红；(3) 线被误收进光栅准入集。且不自愈——事件循环空转
500 ms 仍不恢复，只有用户再动一下画布（range key 变化）才重算。

offscreen 也能复现（这是逻辑缺陷不是 paint 成本），但本目录基线用真机。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/donghang/Downloads/data analyzer")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main():
    import numpy as np
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    app = QApplication.instance() or QApplication([])
    c = TimeDomainCanvasPG(); c.resize(1600, 950); c.show(); c.raise_()
    for _ in range(60):
        app.processEvents(); time.sleep(0.01)
    t = np.arange(1_000_000) / 20000.0
    rows = [(f"CH{i}", True, t, 100 * np.sin(2 * np.pi * (0.5 + 0.1 * i) * t),
             "#1769e0", "Nm", "fileA") for i in range(2)]

    def dump(tag):
        parts = []
        for ck, n, (ax, line) in c._channel_lines.composite_items():
            xd, _ = line.plot_data_item.getData(); st = c._line_ink_state.get(ck)
            parts.append(f"{n}: 绘点={0 if xd is None else len(xd)} "
                         f"ink={round(st[0]) if st else None} 超预算={st[1] if st else None} "
                         f"光栅收编={c._raster_backend_eligible(ck)}")
        q = c._quality
        print(f"{tag:<26} " + " | ".join(parts)
              + f" | AA判定={q._idle_aa_density_ok()} 点={q.quality_status()['state']}")

    print(f"platform={app.platformName()} dpr={c._glw.devicePixelRatioF()}")
    c.plot_channels(rows, mode="overlay", defer_first_frame=False,
                    render_context_key=("cap", "A"))
    c.restore_visible_xlim((10.0, 25.0)); c._flush_pending_refresh(); app.processEvents()
    ylims = c.get_visible_ylims()
    dump("首次进 View（bind envelope）")

    c.plot_channels(rows, mode="overlay", defer_first_frame=True,
                    render_context_key=("p", "A"))
    c.restore_visible_xlim((10.0, 25.0))
    c.restore_visible_ylims(ylims)
    app.processEvents()
    dump("回切后（当前顺序）")
    for _ in range(10):
        app.processEvents(); time.sleep(0.05)
    dump("回切后再空转 500 ms")
    c._last_range_key.clear(); c._flush_pending_refresh(); app.processEvents()
    dump("强制按真实 Y 重刷（=用户动一下）")
    c.close(); app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
