# UltraView View 库几何探针（2026-08-15）

服务于 [`plans/2026-08-15-ultraview-view-library-geometry-and-material-plan.md`](../../plans/2026-08-15-ultraview-view-library-geometry-and-material-plan.md)。

| 文件 | 说明 |
|---|---|
| `probe_current.py` | 六组探针，一次跑完复现 plan §1 的整张实测表，并在离屏上验证 §5 三条修法与 §3.2 定高效果 |
| `baseline.txt` | `main@380e5ac2` 上的**改前**读数（Darwin 27.0.0 / Fusion / offscreen） |

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python docs/analyzer/verify/2026-08-15-ultraview-library-probes/probe_current.py
```

改动落地后再跑一次，预期变化：

- §1.1 七行 rect **逐字段相同**（现状是高度在 356–656 之间跳、顶边在 64–147 之间挪）
- §1.2 `time` 分组从 `CLIPPED (-51)` 变 `OK`
- §1.3 概览卡从 `[81, 80, 81, 80, 81]` 变 `[40, 40, 40, 40, 40]`
- §1.4 行外框 42→46、圆点内缩 7→14、＋/− 20×20→23×23、搜索框 32→34、tab 53→222

§5 / §3.2 两组是**修法预演**（在未改动的产品对象上临时打补丁测的），
落地后它们会与产品实际行为重合，可作为回归的第二道确认。

offscreen 只证明结构与几何。材质、配色、字重的验收走 Cocoa 真机
`tools/verify_ultraview_visuals.py`（见 plan §7.4）。
