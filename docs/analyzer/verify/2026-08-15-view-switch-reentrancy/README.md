# View 切换重入 — 真机渲染验收（2026-08-15）

用户报障：「切 view 切来切去突然图没了，点绘图都没反应，然后右键全图，图闪了一下又
出来了」＋「view2 还变成 view3 的内容了，通道都换了」。

根因、修法与规则见
`docs/lessons-learned/pyqt-ui/2026-08-15-progress-pump-makes-the-render-reentrant.md`；
回归用例 `tests/ui/test_view_switch_reentrancy.py`。offscreen 只能当排版草稿，
所以这里的验收跑**真实 Cocoa 窗口**。

## 复现

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python \
  docs/analyzer/verify/2026-08-15-view-switch-reentrancy/probe_view_switch_render.py <输出目录>
```

不要带 `QT_QPA_PLATFORM=offscreen`——离屏量不出真实 paint，也不算视觉验收。
探针在同一进程内跑两侧：`guard-off` 把三处修复前行为原样还原
（`_restore_view_xlim` 逐字恢复 · `_time_render_gate` 返回 None 关掉闸门 ·
`_capture_focused_view` 去掉在途守卫），`guard-on` 是当前实现。两侧数据、窗口尺寸、
手势完全相同：View1 = 260 s 文件缩放到 118.41–125.03 s，View2 = 49.5 s 宽带
L/R，View3 = 260 s 文件；然后在 View2 的渲染途中投递 View3 / View2 两次切换。

## 实测读数（本机 macOS，dpr 2.0，画布 1500×860）

| 侧 | 三个 View 的 xlim | 可见曲线点数 | 画布墨迹占比 | 抓图 md5 |
| --- | --- | --- | --- | --- |
| guard-off（修复前） | 全部塌成 `(118.41, 125.03)` | L=1 · R=1 | **0.2170 %** | `648c1b2e335c` |
| guard-on（修复后） | `(118.41,125.03)` / `(0,49.5)` / `(0,260)` | L=1736 · R=1736 | **61.0384 %** | `d0ceefd031cc` |

`guard-off-shipped-bug.png` 与用户截图 #1 一致：两栏空图、横轴停在 118.8–124.8 s、
只剩图例。0.217 % 是坐标框和刻度文字，曲线一个点都没画。
`guard-on-fixed.png` 是同一手势下的正确结果。

判据（探针退出码 0 才算过）：修复前必须**全部曲线 < 2 点**（空图），修复后必须
**全部曲线 ≥ 2 点**且墨迹占比高于修复前。
