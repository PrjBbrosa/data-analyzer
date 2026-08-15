# UltraView 适配 / 缩放 / 浮层消隐探针（2026-08-15）

服务于 [`specs/2026-08-15-ultraview-fit-zoom-and-dismiss-fixes-spec.md`](../../specs/2026-08-15-ultraview-fit-zoom-and-dismiss-fixes-spec.md)。

本批是几何与事件路由的逻辑缺陷，**离屏证据充分**。唯一真机项是 300% 下位图预览的软化程度（spec §4 已知副作用）。

| 文件 | 说明 |
|---|---|
| `probe_current.py` | 三段：contain-fit 四起点、空白点击命中链、4 卡适应几何 |
| `baseline.txt` | 改前读数 |
| `after.txt` | 改后读数（2026-08-15 Task 5） |

改后对照：

| 项 | 改前 | 改后 |
|---|---|---|
| 4×6 / 10×3 / 6×4 / 2×2 ← 图 1000×800 | 全部 → 7×8 | 4×5 / 2×3 / 3×4 / 2×2（互不相同，逐维只减） |
| 自由网格内部空白点击（库已开） | `library after inner blank=True` | `False` |
| 4 卡适应 | zoom 0.7608，停 (90,76)，宽占 ~57% | zoom 0.8131，盒 (196,211) 1274×482，宽占安全区 84%，中心对齐 |

300% 预览软化：本机未做 Cocoa 真机目视，标 **UNVERIFIED**；未改 `MAX_PREVIEW_RAW_EDGE`。

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python docs/analyzer/verify/2026-08-15-ultraview-fit-zoom-probes/probe_current.py
```
