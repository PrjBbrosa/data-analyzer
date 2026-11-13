# UltraView 加固 Task 0 盘点

- 日期：2026-11-13。
- 计划：`docs/analyzer/plans/2026-11-13-ultraview-window-and-markup-interaction-hardening-plan.md` §4 Task 0、§2.3。
- 设计：`docs/analyzer/specs/2026-11-13-ultraview-window-and-markup-interaction-hardening-spec.md` §3.3 D-W3、§3.9、§5。
- 报告：`docs/analyzer/reviews/2026-11-13-ultraview-and-markup-interaction-review.md` §2.2、§5、§6。
- 读码基线：`HEAD` `9d8d924feebea49ff5c18c9de9ce1a5d5081f829`（计划编写基线是 `0614559a`，行号以盘点当时的工作区为准）。
- `mf4_analyzer/ui/chart_stack/ultraview/page.py` 在盘点时相对该 `HEAD` 已有未提交改动（失焦清理路径，不是本 Task 写入的）。下文 `page.py` 行号是工作区行号，对不上干净的 `9d8d924f`。其余列出的产品文件在盘点时与该 `HEAD` 一致。

本文件只盘点。没有改产品代码，没有把 offscreen 尺寸写成基线。

## 1. 本机没有做的测量

以下四项在这台机器上**没有做**。offscreen 自检不能代替它们。

| 项 | 计划出处 | 本机状态 |
|---|---|---|
| mini 窗口在 Windows 上的触发条件（报告 §2.2 的 5 个假设） | §2.3 第 1 条 | **没有做** |
| Windows 隐藏窗口的真实窗框，供 D-W2 平台估算 | §2.3 第 2 条 | **没有做** |
| Windows 上 24 卡缩放、平移、卡片拖动、画笔的帧时间 | §2.3 第 3 条 | **没有做** |
| 在真实 Snipaste 上核对报告 §5 里涉及手感的条目 | §2.3 第 5 条 | **没有做**。报告没有回写 |

报告 §2.2 的五个假设都仍是未验证：打开瞬间 `availableGeometry()` 退化或过期；多屏混合缩放；隐藏窗口估算窗框 `(1, 28, 1, 1)` 小于 Windows 实际窗框；最小化还原后再显示；`SM_CXMINIMIZED == 160` 的巧合排除。本机没有 Windows，也没有跑这五条。

`DISPLAY=:1` 且本机有 `xdotool`，但 Task 0 要求的自检带 `QT_QPA_PLATFORM=offscreen`。两条交互探针因此打印 `skipped: no display` 并退出，没有对真实 `MainWindow` 或标注编辑器做失焦、滚轮、手柄、拖动、按下、Esc、平移。那些 X11 场景留在有显示、且不把平台设成 offscreen 时再跑。

## 2. 产品决策

Q-1 … Q-6 **UNCONFIRMED**。截图 2 里白色画布对应的源图也 **UNCONFIRMED**。没有用户答复。实施按 spec §5 的默认方案，不按备选：

| 编号 | 未确认的决策 | 实施使用的 spec §5 默认 |
|---|---|---|
| Q-1 | 标注编辑器里滚轮的含义 | 保持缩放，线宽用 `[` / `]` |
| Q-2 | 「完成复制」的键盘入口 | Ctrl+Enter |
| Q-3 | 卡片拖动的跟手层 | 幽灵逐像素跟手，落点轮廓吸附 |
| Q-4 | 自由对象松手是否吸附 | 保持 0.25 单位吸附，拖动中连续 |
| Q-5 | 有吸附端点的连线拖主体 | 不移动并提示 |
| Q-6 | 第二阶段新工具的范围 | 椭圆、马克笔、马赛克 / 模糊 |

## 3. `camera_settled` 的连接、发出与消费者

运行时只有一条消费者链。信号本身不带相机参数。`persist()` 在恢复视口中、或没有 board id 时直接返回，那种情况下不发信号（`viewport_controller.py:298-303`）。

| 角色 | 位置 | 做什么 |
|---|---|---|
| 信号定义 | `mf4_analyzer/ui/chart_stack/ultraview/page.py:353` | `camera_settled = pyqtSignal()` |
| 交给控制器的发出回调 | `page.py:476` | `camera_settled=self.camera_settled.emit` |
| 控制器保存回调 | `mf4_analyzer/ui/chart_stack/ultraview/viewport_controller.py:126`、`:161` | 构造参数与 `self._camera_settled` |
| 唯一发出点 | `viewport_controller.py:313` | `persist()` 末尾 `self._camera_settled()` |
| 唯一 `connect` | `mf4_analyzer/ui/main_window/ultraview_coordinator.py:754` | `_connect_page`（`:706`）的 pairs；`:756-757` 连上 |
| 协调器转发 | `ultraview_coordinator.py:473-474` | `_on_camera_settled` 转到 capture |
| 唯一运行时消费者 | `mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py:1170-1173` | 未停用时 `self._focus_timer.start()`，到期后走焦点层重新截图 |

Task 9 要改成「停手才发一次」时，这条焦点截图定时器是必须迁走或保留的消费者。当前没有第二个连接，也没有「每个滚轮事件都要相机状态」的其他槽。

`persist()` 的调用点（每一处在通过 `:298` 的早退之后都会发 `camera_settled`）：

| 调用 | 位置 |
|---|---|
| `_park_zoom` | `viewport_controller.py:676`（同函数 `:674` 先 `_apply_lod_chrome`） |
| `_apply_zoom_and_center` | `viewport_controller.py:763`（`:761` 先 `_apply_lod_chrome`） |
| `_zoom_at` | `viewport_controller.py:795`（`:793` 先 `_apply_lod_chrome`） |
| `_after_end_board_pan` | `viewport_controller.py:857` |
| `_persist_viewport_to_board` | `page.py:1798-1799`。全库没有别的调用点 |
| `_on_board_scrolled` | `page.py:2089-2093`。由 `page.py:890-891` 的横纵滚动条 `valueChanged` 连入 |

缩放三条路径在 `setValue` 之后还会再进滚动条的 `valueChanged`，所以一次滚轮除了 `_zoom_at` 里那一次 `persist()`，还可能从 `_on_board_scrolled` 再发。报告 U-10 记过「每个事件 `persist` 3 次」；那是当时的 offscreen 计数，本盘点没有重测次数。

测试里的名字，不是运行时消费者：

- `tests/ui/test_ultraview_placement_history.py:313` 直接调用 `uv._on_camera_settled()`。
- `tests/ui/test_ultraview_compatibility.py:251` 与 `:305` 把信号名冻在合同元组里。

## 4. `_apply_lod_chrome` 的调用点

定义在 `page.py:2124`。函数体从 `:2129` 起遍历栅格和自由网格的全部卡片，调用 `card.apply_lod(...)`。

| 种类 | 位置 | 所在函数 |
|---|---|---|
| 定义 | `page.py:2124` | `_apply_lod_chrome` |
| 绑到控制器 | `page.py:468` | `UltraViewPage.__init__` 构造 `ViewportController` |
| 控制器保存 | `viewport_controller.py:118`、`:153` | 构造参数与 `self._apply_lod_chrome` |
| 调用 | `page.py:2473` | `set_presentation_active`（`:2427`） |
| 调用 | `page.py:4082` | `_refresh_projection`（`:4044`） |
| 调用 | `page.py:4263` | `_refresh_free_grid_projection`（`:4227`） |
| 调用 | `viewport_controller.py:674` | `_park_zoom` |
| 调用 | `viewport_controller.py:761` | `_apply_zoom_and_center` |
| 调用 | `viewport_controller.py:793` | `_zoom_at` |

全库没有别的调用。缩放路径在每个滚轮事件上都会进 `_zoom_at`，从而遍历全部卡片。这是 spec §3.9「只在 LOD 档位变化时执行」要收的点。

## 5. 标注编辑器的打开入口

产品路径只有一条，终点是 `MainWindow._open_markup_editor`。没有菜单项、没有快捷键直接调用它。

1. 复制图请求接到 `ChartStack._copy_card_image`（`mf4_analyzer/ui/chart_stack/stack.py:2423`），`:2437` `image_captured.emit(pix)`。信号定义在 `stack.py:84`。三条上游：
   - `stack.py:323` 时域卡 `copy_image_requested` → `_copy_focused_card_image`（`:748`）
   - `stack.py:518` 分析卡 `copy_image_requested` → `_copy_card_image`（`_connect_analysis_card_signals`，`:512`）
   - `stack.py:1203` 分屏第二张时域卡 → `_copy_secondary_card_image`（`:751`）
2. `mf4_analyzer/ui/main_window/window.py:1258-1259` 把 `image_captured` 连到 `_publish_copied_pixmap`（`:1136`）。
3. `_publish_copied_pixmap` 在 `:1148` 调用 `CopyThumbnail.present`。`present` 在 `mf4_analyzer/ui/markup/thumbnail.py:145`。
4. 左键按下缩略图：`thumbnail.py:176-178`，`clicked.emit`。信号定义在 `thumbnail.py:26`。
5. `window.py:670`：`self._copy_thumbnail.clicked.connect(self._open_markup_editor)`。这是 `_open_markup_editor` 的唯一产品调用方。
6. `window.py:1163` `_open_markup_editor`：空图直接返回；否则 `:1166` 经 `_create_markup_editor`（`:1159-1161`，`MarkupEditor(pix, on_done=..., parent=self)`）构造，`:1167-1170` `show` / `raise_` / `activateWindow`。

测试直接调用，不是产品入口：`tests/ui/test_main_window_smoke.py:3891`。各 `tests/ui/test_markup_*.py` 里的 `MarkupEditor(...)` 不经过 `MainWindow._open_markup_editor`。

## 6. 入库的探针

三个脚本都不是产品代码。stdout 是 JSON 或跳过行。它们不往 `docs/` 或 git 树写文件。Batch 偏好和标注提示的 `QSettings` 放在 `TMPDIR` 下的临时 INI。

| 脚本 | 作用 | 证据等级 |
|---|---|---|
| `scripts/probe_tool_window_geometry.py` | 打开 UltraView sheet、Batch sheet（空文件列表、隔离 INI，不需要工程）、标注编辑器。每个窗口打印屏幕 `geometry` / `availableGeometry` / DPR、窗框、客户区，时刻为构造结束、`showEvent` 进入、`showEvent` 返回、返回后的一个 0 ms 事件循环 tick。`--self-check` 只构造 `UltraViewSheet(None, QWidget())`，不构造 `MainWindow` | offscreen 数字**不是** Windows 证据。本机也不是 Windows 窗框测量 |
| `scripts/probe_ultraview_interaction.py` | 场景 `deactivation`、`wheel`、`handle-cursor`、`card-drag`、`author-select`。有 `DISPLAY`、有 `xdotool`、且平台不是 offscreen 时，对真实 `MainWindow.open_ultraview()` 做失焦和滚轮，并做手柄、拖动、自由对象框选。结束时关掉窗口、松开按键 | 跳过时不是 X11 证据，也不是 Windows 证据。offscreen 不合成输入来冒充真输入 |
| `scripts/probe_markup_interaction.py` | 场景 `press-on-existing`、`esc-dirty`、`pan`。真输入时直接构造 `MarkupEditor`（手势在编辑器上，不经缩略图入口）。同样的跳过规则 | 同上 |

本机自检（`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python`）：

| 命令 | 退出码 |
|---|---|
| 三个探针的 `--help` | 0。`--help` 不 import PyQt5 |
| `scripts/probe_tool_window_geometry.py --self-check` | 0。只构造了 UltraView sheet，四个时刻都有记录 |
| `scripts/probe_ultraview_interaction.py --self-check` | 0。stdout 为 `skipped: no display` |
| `scripts/probe_markup_interaction.py --self-check` | 0。stdout 为 `skipped: no display` |

另一次不带 `--self-check` 的几何探针在同一 offscreen 进程里把 Batch sheet 和标注编辑器也构造出来了，四个时刻都有记录。那些尺寸没有写入本文，不能当 Windows 窗框或帧时间。
