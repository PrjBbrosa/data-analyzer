# Qt gate 与跨平台发布验收 — 2026-08-07

## 判定

| Gate | 状态 | 结论 |
| --- | --- | --- |
| SOURCE | GO | `9b01a66` 上两次默认全量 pytest 都正常退出。 |
| macOS Cocoa 自动矩阵 | PASS | Batch heartbeat、focus routing、per-pane controls 都在真实 `cocoa` 平台通过。 |
| macOS 主应用完整人工矩阵 | PARTIAL | 正式入口可见启动、Time/FFT 切换、窄窗口适配、正常关闭已观察；完整 CSV+MF4/所有分析/Batch/popup 覆盖未完成。 |
| MACOS RELEASE | NO-GO | 不能把部分主应用前台覆盖称为完整 Gate C。 |
| Windows 源码/打包合同 | PASS (source-level) | 静态依赖合同和 89 条定向测试通过；不替代 Windows。 |
| Windows Full / Lite frozen + foreground | UNVERIFIED | macOS 锁屏后无法打开真实交互式 Windows 11 桌面，未构建或复用任何 `dist/`。 |
| RELEASE | NO-GO | 缺 Windows fresh windowed Full/Lite、冻结 smoke 与前台矩阵；macOS 人工矩阵也未完成。 |

本轮明确未修改 `mf4_analyzer/io/head_hdf.py` 或任何旧 HDF 名称恢复合同。

## 固定源码与 SOURCE 门

- 实施提交：`9b01a66 fix(test): harden Qt gate and release checks`
- 两次独立默认全量（`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q -p no:randomly`）：
  - `.state/qt-gate-evidence/source-full-9b01a66-run1.log`：`5556 passed, 9 skipped, 3 deselected, 131 warnings in 339.64s`。
  - `.state/qt-gate-evidence/source-full-9b01a66-run2.log`：`5556 passed, 9 skipped, 3 deselected, 131 warnings in 336.81s`。
- `git diff --check b886a30e338514df31da5fe4874e992f5be110eb` 与 `git diff --check`：均无输出、exit 0。

### 已修复的实际 Qt 生命周期问题

默认全量曾在约 56–57% 的
`tests/ui/test_db_reference_controls.py::test_dialog_cancel_and_escape_leave_store_and_view_unchanged`
后以 exit 139 退出。macOS crash report 的 native stack 指向
`QAbstractItemView::updateEditorGeometries()` / `QTableWidget::timerEvent()`：两个无 parent、已
`reject()` 的测试 dialog 留到 pytest-qt 的 post-call `processEvents()` 才清理，表格的延迟 layout
计时器跨越了测试调用边界。

回归修复在测试的行为断言后显式投递各 dialog 的 `DeferredDelete`；并保留 `qtbot` 所有权。两次完整
新进程全量通过证明该路径不再以顺序偶然性掩盖 crash。

另外修正了 `SearchableComboBox.clear()`：Cocoa 下 QComboBox 内部 reset 与 completer
`QSortFilterProxyModel` 同时连接会报告 “inconsistent changes reported by source model”。clear 的单次
reset 期间现在暂时解绑 proxy，再重连同一个 live model；定向 18 条 UI 测试与后述 Cocoa 探针均无该告警。

## macOS Cocoa 证据

环境记录：`.state/release-acceptance/macos/environment.txt`（macOS 27.0、arm64、PyQt 5.15.11、Qt
5.15.14、pyqtgraph 0.14.0；输入 `testdoc/X04C_Ripple.mf4` SHA-256 已记录）。

在 `9b01a66` 上执行：

```text
QT_QPA_PLATFORM=cocoa scripts/batch_qt_foreground_heartbeat.py ...
QT_QPA_PLATFORM=cocoa scripts/focus_routing_cocoa_smoke.py
QT_QPA_PLATFORM=cocoa scripts/per_pane_controls_cocoa_smoke.py
```

- 日志：`.state/release-acceptance/macos/c1-batch-9b01a66.log`、`c1-focus-9b01a66.log`、`c1-per-pane-9b01a66.log`。
- Batch JSON：`.state/release-acceptance/macos/gate45/gate45-heartbeat-20260807-235154-24377/gate45-heartbeat.json`。
  真实 `cocoa`、20 个有效 PNG、无 worker residual/error、所有 20 次 scene build 在 GUI thread；50 ms
  heartbeat 最大间隔 67.079 ms（预算 200 ms）。
- split focus：primary → secondary → primary 的焦点标记均正确。
- per-pane：主 marker `(45, 127, 249)`、次 marker `(232, 89, 12)`；共享双游标同步到两块 canvas；次
  View 切为 overlay 时主 View 保持原模式。截图在
  `.state/release-acceptance/macos/focus-tmp/`。

正式入口 `PYTHONPATH=. .venv/bin/python "MF4 Data Analyzer V1.py"` 曾在已解锁桌面可见运行并正常关闭；
Time↔FFT 和窄窗口 View 标签适配已验证。产品默认宽窗口是 `1450x850`；边框拖拽覆盖了约
`1080x760` 窄窗口。`1440x900` 精确高度和 C2 所列全部人工交互尚无完整证据，因此本节不升级为
`MACOS GO`。

## Windows

在 macOS 上仅完成可移植的前置检查：

```text
PYTHONPATH=. .venv/bin/python tools/windows_runtime_dependencies.py --verify ...
QT_QPA_PLATFORM=offscreen pytest -q [D1 八个测试文件]
```

结果为 `Windows packaging contract: OK` 与 `89 passed, 1 skipped`。这只是源码/打包合同检查。

随后尝试连接 Windows 11 的真实交互桌面时，Computer Use 返回“Mac is locked”；因此没有可证明的
Windows build、DPI、同 SHA checkout、fresh EXE、frozen JSON、Event Viewer 或前台截图。不得以本机
offscreen 或历史 `dist/` 代替，D2–D5 全部保持 `UNVERIFIED`。

## 恢复后的剩余步骤

1. 解锁 macOS，完成 C2 未覆盖的真实主应用 CSV+MF4、四种分析、Batch、popup/tooltip 与精确宽窗口尺寸。
2. 在真实 Windows 10/11 x64 桌面检出 `9b01a66`，按计划 D0–D5 新建 Full/Lite windowed onedir；记录 EXE SHA、fresh smoke JSON、100%/150% DPI 截图和 Event Viewer。
3. 仅当 Full 与 Lite 均完成 fresh frozen + foreground，才把 RELEASE 改为 GO。
