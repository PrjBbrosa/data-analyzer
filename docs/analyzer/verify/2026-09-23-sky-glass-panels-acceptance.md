# 晴空蓝白面板与启动交接验收

日期：2026-09-24。代码基线：工作区相对 `e35aae9d2b7c5273e54393e2c3d079c91d27dd6e` 的未提交改动。环境：macOS，项目 `.venv`，`QT_QPA_PLATFORM=offscreen`。

本文件只记录源码与 offscreen 测试。Windows 合成顺序、原生磨砂、DPI 和 frozen 包均为 **UNKNOWN**。offscreen 通过不能写成 Windows 视觉完成。

## 代码结果

| 项 | 状态 |
| --- | --- |
| 主窗在 splash `hidden` 之后才 `show` 一次 | 已实现。`StartupHandover` 是唯一 reveal owner |
| child 用 GUI `QObject` + `Qt.QueuedConnection` 接收 finish/stage/EOF | 已实现 |
| `hidden` 在视图 hide 之后发送，原因 `finish_close` / `user_close` / `never_shown` | 已实现 |
| 250ms 无 ACK 只终止本次 `Popen`；1.5s 仍无确认则 `handover_failed` 后降级显示 | 已实现 |
| 迟到 spawn 的回收在锁外 `wait` | 已补上，避免主线程卡在回收锁上 |
| 启动面板与 QuickRef 去掉自绘外阴影 | 已实现 |
| 玻璃填充 `#f4faff`、alpha 191/255（75% 不透明）；磨砂参考 25px；文字不走整窗 opacity | 已实现 |
| 非 Windows 表面回退原因 `unsupported_platform` | 本机按此回退。回退可用不等于磨砂通过 |
| 交接文案：启动面板先关闭，再显示主窗口 | `hints.py` 与 `quickref.py` 已同步 |

## 本机测试

运行环境：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`。

- 面板与 child/timing：`tests/ui/test_startup_splash.py`、`test_quickref_panel.py`、`test_quickref.py`、`test_quickref_status_hints.py`、`test_hints.py`、`test_qt_panel_style.py`、`tests/test_startup_splash_child.py`、`tests/test_startup_timing.py` — **156 passed**。
- 父控制器与入口：`tests/test_startup_feedback.py`、`tests/test_startup_entrypoints.py::test_app_module_main_marks_python_entry_when_launched_directly` — **19 passed**。入口测试补了 disabled snapshot，并接受第 4 个观察者参数。
- 边界（同一次运行，当时入口用例仍因假 `QApplication` 失败，其余通过）：`tests/test_startup_splash_integration.py`、`tests/test_startup_import_boundary.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui_kit/test_qss_border_shorthand.py`、`tests/ui/test_startup_preload.py`、`tests/ui/test_main_window_smoke.py::test_main_window_constructs`、`tests/test_packaging_imports.py`，以及上述 feedback/entrypoints 文件 — **94 passed, 1 skipped, 1 failed**。失败项已在下一行单独复跑通过。未跑全套，也未跑整个 `tests/ui` 或整个 `test_main_window_smoke.py`。

## Windows 与外观（未签）

以下全部 **UNKNOWN**，不能用本机 offscreen 代替：

- 热启动 ≥10 次、重启后首启 ≥3 次的连续帧；splash 消失是否早于或同于主窗首个可见帧
- `finish_requested` → `hidden_received` → `main_show_called` → `main_first_frame` → `child_exited` 的同一单调时钟现场样本
- 隐藏到主窗首显的空白间隔，以及相对禁用 splash 基线的可交互耗时
- Full / Lite / Modular frozen 正常链路
- 100/125/150/200% 缩放下的中英数混排字形
- 面板外侧是否还有灰色偏移块；频谱在真机上的峰顶
- `DWMWA_SYSTEMBACKDROP_TYPE` / `DWMSBT_TRANSIENTWINDOW` 的 HRESULT、系统透明开关、高对比度，以及与 25px HTML 参考的实际差异
- QuickRef 在 pin 改 HWND 之后材质是否仍在

原生磨砂没有 CSS `blur(25px)` 半径参数。25px 仍是视觉参考，不是已达成的 Win32 高斯半径。
