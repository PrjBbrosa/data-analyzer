# 2026-08-16 当日评审跟进 · Cocoa 走查

- 日期：2026-08-16
- 全量快照：`HEAD 23d0a1b7`（跑前跑后相同；工作区干净）
- 状态：**UNVERIFIED（本机无前台 Cocoa 会话：`DISPLAY` 空，前台探测挂起；未启动 TraceLab，无截图）**

offscreen 全量不能替代本清单。解锁后应在同一提交（或其后仅文档补录的提交）用
`QT_QPA_PLATFORM=cocoa` 打开 TraceLab，按下列项目操作并补截图。

## 已完成的自动证据（offscreen，不是 Cocoa）

B8 全量（协调者独占，两条串行、前台）：

| 门禁 | 命令 | 结果 | HEAD / 脏文件 |
|---|---|---|---|
| 主体 | `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q --ignore=tests/acquisition_ui` | **7402 passed**, 14 skipped, 3 deselected, 0 failed（1154.19s / 0:19:14） | 跑前跑后 `23d0a1b7`，porcelain 空 |
| `tests/acquisition_ui` | 同上解释器，单独进程 | **359 passed**, 4 warnings（9.12s） | 同上 |

`test_gen_help_screenshots` 未落入失败集。主体 **0 failed**，无剩余红需要在 plan 里另起 Task 名。

相关聚焦护栏（Task 1–13 已在各自提交验证）覆盖：pill section 门禁、标注意图层、落点单一真相、QSS 几何、harness hover 契约、router 生命周期、DPR 背景、会话相机、结构护栏泛化、edge-pan 滚动条位移。这些证明的是 offscreen 契约，不是钛金琥珀锐度或触控板 pinch。

## 未执行的 Cocoa 清单

### 1. 手势路由五起点（接缝加固 Task 7 / C5）

指针经过下列五处时，中键平移与空格+左键平移必须连续，不得在边界丢掉 grab：

- 模板卡片
- 模板空白
- 自由网格卡片
- 自由网格空白
- 滚动视口（含滚过卡片边缘）

另验：Ctrl+滚轮、Cmd+滚轮、触控板 pinch 锚点停在指针下；普通左键不进平移；文本输入焦点时手势不抢；CanvasHost 外控件与 hide/show 后过滤器卸载重装。

### 2. 钛金琥珀 + C1 背景锐度

Retina（dpr 2）截图对比点阵 / 网格 / 虚线像素。Task 11 之后 `CanvasHost` 背景应按
`QPixmap(size * dpr) + setDevicePixelRatio(dpr)` 栅格化，`paintEvent` 按逻辑 rect 画、不拉伸。
本文件**没有** Task 11 前后对比图。

### 3. edge-pan 手感

把卡片拖到视口边：滚动条应朝拖动方向让路，ghost 跟随，松手后卡片落在目标格。offscreen 已钉
`horizontalScrollBar().value()` 位移；真机还要看加速度是否可跟手。

### 4. hover 操作条（8d57ab0e）

选中卡片后，操作条默认不常驻；悬停或键盘聚焦时出现。工程级「卡片操作常驻」打开后四键常显。

### 5. A1–A3 手验（阻塞真机验收的三条）

建议工程：`testdoc/1.tlproj`（评审 §1 复现过）。

- **A1**：时域 View 有 dual + A/B 落点，工程里另有 FRF View。重开后 pill 仍可见、A/B 竖线仍在；切到 FRF 再切回时域，pill 不被空 `cursor_info` 清掉。
- **A2**：时域 overlay / subplot 标注点。取消勾选另一通道触发重绘后，点还在；隐藏该点所在通道则点暂时不画，再显示回来点还在；用户删除后才从意图列表消失。
- **A3**：非法 / 半截 restore 时 `cursor_info` 回到「Click A」，落点不看 `_dual` 模式位。

### 6. 原持久化 plan Wave 3 两条

见 `docs/analyzer/plans/2026-08-16-view-markup-and-cursor-persistence-plan.md`：

- 多通道时域放 A/B → 勾一个新通道 → 读数面板跟着变。
- dual 关掉再打开：A/B 落点还在。

## 解锁后怎么补

1. 确认锁屏已开、本机前台可操作。
2. `QT_QPA_PLATFORM=cocoa python "MF4 Data Analyzer V1.py"`，版本栏为 v8.0.0。
3. 按上面 1–6 操作，截图放同目录（文件名自拟，本清单补路径）。
4. 把本文状态从 UNVERIFIED 改为通过或逐条记失败；不要用 offscreen 结果改写本节。
