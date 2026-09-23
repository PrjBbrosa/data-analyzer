# 启动面板与操作速查面板：原生玻璃质感修正

日期：2026-09-24。基于 HEAD `0186a58ffa6f2bb5bfbb760aa91442bcf0f639a3` 的局部修改。

## 问题与修改

用户的 macOS 截图中，背景终端文字清晰透过面板，波形区域还有明显的蓝色矩形底。代码确认此前只有 Windows 原生磨砂后端；`FROST_REFERENCE_PX = 25` 是 HTML 参考值，没有为 macOS 提供模糊处理。提高透明涂层浓度不能补上缺失的背景模糊。

- 保留 75% 涂层不透明度、原有波形几何、布局、文字与启动交接时序。
- 背景改为白色到冰蓝渐变，角部使用局部椭圆淡彩；移除波形区额外蓝色底；提示区从平涂青色改为青到淡蓝渐变。
- 为 macOS Cocoa 增加公开 `NSVisualEffectView` 后端，位于 Qt 内容视图后面，前景文字与交互仍由 Qt 负责。操作速查面板通过现有共享入口获得同一原生后端与白到冰蓝底色。
- 尊重系统“减少透明度”设置；没有原生模糊能力时使用完全不透明的浅色底，避免清晰的背景文字重影。
- 原生视图在隐藏、重新应用、销毁时释放；主动释放时断开销毁回调，避免重复打开累积连接。Win32 DWM 调用补充指针宽度正确的参数声明。

AppKit 与 Windows Acrylic 的模糊由系统材质决定，25px 不代表可设定或已验证的原生高斯半径。Apple 的 [behindWindow 文档](https://developer.apple.com/documentation/appkit/nsvisualeffectview/blendingmode-swift.enum/behindwindow) 描述了窗口后方内容的模糊与混合。

## 验证

先新增两个真实绘制像素回归：波形背景不得额外出现蓝色矩形、面板左上中性色区域应接近白色。修改前均失败，修改后通过。

```sh
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_startup_splash.py tests/ui/test_qt_panel_style.py tests/ui/test_quickref_panel.py tests/ui/test_import_boundaries.py tests/ui/test_no_lambda_signal_connections.py tests/ui_kit/test_qss_border_shorthand.py tests/test_startup_splash_child.py tests/test_packaging_imports.py -q
```

结果：**88 passed, 1 skipped in 8.13s**。含导入边界、子进程启动协议、QSS、平台能力回退、原生资源释放与速查面板行为；未运行全量测试。打包检查保留既有环境条件跳过。

原生适配器测试开发过程中，失败断言留下的假视图句柄在 monkeypatch 撤销后触发真实 native release，导致一次测试进程异常退出；该次结果无效。测试随后以 `finally` 保护资源释放、排空 Qt 延迟销毁，最终上述整组测试正常退出。

本机 Cocoa 前台使用真实 `StartupSplash` / `QuickRefPanel`，背后放置带文字和彩色区块的测试窗口：

- 启动面板背景文字不可辨认，淡彩过渡连续；前景文字、圆角与波形清晰，无波形矩形底。截图探针为便于捕获，仅在测试窗口中解除启动面板的无焦点标志；产品窗口标志未改。
- 操作速查真实执行 5 轮显示、置顶、取消置顶、隐藏，再搜索 Home 并清空；各轮原生后端成功，隐藏后资源释放，进程正常退出。
- 本地截图：`.state/panel-material/splash-cocoa.png`、`.state/panel-material/quickref-cocoa.png`；探针同目录。它们是临时本机证据，不是 Windows 或完整主程序运行证据。

**未验证**：Windows Full/Lite 冻结包实际桌面材质效果、Intel macOS 原生 ABI、多显示器切换。未宣称与浏览器 CSS 模糊逐像素一致。本轮没有改变启动面板关闭/主窗口显示协议，也没有重新评估真实冷启动耗时。

既有 `collapsible.py` 与 `test_collapsible_motion.py` 工作区修改不属于本任务，未改动。
