# TraceLab 四项交互优化验证报告

日期：2026-09-11 · Plan：`docs/analyzer/plans/2026-09-11-four-interaction-refinements-plan.md`。

交付：**T5 文案 + Cocoa 原生检查完成**。不是发版。冻结包：`NOT_IN_SCOPE`。未跑全量、`tests/ui` 整包或 `tests/acquisition_ui`。未 commit / push。

## 环境

| 项 | 值 |
| --- | --- |
| HEAD | `a8d4b231c96f1a2f25f85c2aeee2e9a7cbf47f46`（与 T0 / 计划调查基线一致） |
| OS | macOS 27.0 arm64 |
| Qt / PyQt / pyqtgraph | 5.15.14 / 5.15.11 / 0.14.0 |
| Cocoa 平台插件 | `cocoa`（探针未设 `QT_QPA_PLATFORM=offscreen`） |
| DPR / 刷新率 | 2.0 / 60 Hz |
| QSettings | 临时 INI：`/tmp/t5-cocoa-*/qsettings/qsettings.ini` |
| 原始截图 / 几何 / 录屏 | `.state/four-interaction-refinements/cocoa/`（不入库） |
| 探针 | `.state/four-interaction-refinements/probe_t5_cocoa.py` |

Dirty 范围（T1–T5 产品与测试，未提交）：通道树 / PillSwitch / ViewTabBar / BatchSheet 详情、hints/quickref、对应测试；无关未跟踪 `ssh-keygen` 未动。计划文件仍为未跟踪原稿，未改写成已完成。

## 门禁总表

| Gate | 结论 | 证据 |
| --- | --- | --- |
| T1 S owner | **PASS**（执行时记录） | `test_channel_filter_context.py` + `test_channel_widget.py` + `test_channel_widget_setters.py`：**76 passed** |
| T2 P owner | **PASS**（执行时记录；协调者复验含 BatchSheet） | `test_pill_switch.py` + `test_batch_switch_motion.py` + slice/stats/motion_demo：**93 passed**。协调者复验 T2 BatchSheet + T4 + lambda：**162 passed** |
| T3 V owner | **PASS**（执行时记录） | `test_view_marker_activation.py` + tabbar/mount/view_state：**177 passed** |
| T4 B owner | **PASS**（执行时记录；协调者复验） | `test_batch_result_details.py` + smoke + task_list + qss：**117 passed** |
| T5 H owner | **PASS**（T5 文案）+ 一条 **HEAD 既有红** | 见下方命令。T5 新增/改写行均 ≤160 字且 hints ≤18 全宽 |
| T5 边界 | **PASS** | 指定 5 个文件：**26 passed** / 4.83s |
| G3 Cocoa | **PASS**（1080×760 与 1440×900 @ DPR 2.0） | 真实暴露窗口 + 合成数据；不是 HTML / offscreen |
| G4 Windows 100%/150% | **UNVERIFIED** | `sys.platform=darwin`，无 Windows 项目 Python |
| DPR1 | **UNVERIFIED** | 本机 `devicePixelRatio=2.0` |
| 桌面 avfoundation 录屏 | **UNVERIFIED** | ffmpeg `Input/output error`（无屏幕录制权限）。P/V 动效用暴露窗口 `widget.grab` 帧序列合成 mp4 |
| `git diff --check` | **PASS** | 无空白/冲突标记 |
| lessons | 不新增 | `scripts/lessons/check.py --status` → `lesson_required: False` |

未跑：全量、`tests/ui` 整包、`tests/acquisition_ui`、冻结 Windows Full/Lite、macOS 前台主窗口走完整打开文件路径（本报告用生产控件 + 生产 QSS + 暴露的 Cocoa 窗口）。

## T5 帮助文案

两份同时补了「清除筛选恢复展开/滚动」和「批处理查看详情 / Esc 收起 / 检查入口」。不声称恢复勾选或眼睛显隐，不声称重试、恢复任务或新导出规则。现有 View / switch 名称未改。

| 面 | id / 行 | 文案要点 |
| --- | --- | --- |
| hints discovery | `channel.filter_restore` | `清除筛选恢复展开滚动，不改勾选显隐`（全宽 17 ≤ 18） |
| hints discovery | `batch.result_details` | `底栏查看详情 · Esc收起 · 可检查`（全宽 11；`retire_on=batch_open`） |
| quickref 通道树 | `搜索通道` | 交集、「清除筛选」清关键词和已选、恢复展开与滚动；不恢复勾选或显隐 |
| quickref 批处理 | `查看详情` + 更新 `运行警告` | Esc 先收起并交还入口；可检查输出目录或频响配对；不自动重试 |

## Owner 命令

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_hints.py tests/ui/test_quickref.py tests/ui/test_quickref_status_hints.py
```

**86 passed, 1 failed** / 2.73s。失败项：

`tests/ui/test_quickref.py::test_secondary_copy_stays_scannable` — `预设 / 切换时保留坐标` 的 `sub` 长度 170 > 160。该行在 HEAD `a8d4b231` 已是 170 字，T5 未改。T5 新增行长度为 66 / 64 / 28。不以缩短无关预设文案来消这条既有红。

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py \
  tests/ui_kit/test_qss_border_shorthand.py
```

**26 passed** / 4.83s。只跑一次。

Cocoa（不要设 offscreen）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. \
  .venv/bin/python .state/four-interaction-refinements/probe_t5_cocoa.py
```

窗口 `isExposed()` = true，平台 `cocoa`。

## 逐项 S / P / V / B

| ID | 实现 | Owner | Cocoa 1080×760 DPR2 | Cocoa 1440×900 DPR2 | Windows | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| S | 筛选快照恢复展开/滚动；三类空态 | PASS | **PASS** | **PASS** | UNVERIFIED | 清除前后 scroll/展开一致；空态「没有匹配的通道」+「清除筛选」。不恢复勾选 |
| P | 三只 Batch PillSwitch Light 160 ms | PASS | **PASS** | **PASS** | UNVERIFIED | 中间帧旋钮在轨上移动；静止后 driver inactive；锁定 ArrowCursor + 灰轨；`setChecked` 不播 |
| V | 生产 ViewTabBar 2 px / 140 ms | PASS | **PASS** | **PASS** | UNVERIFIED | 中间帧底标离开起点；切换后关闭叉不可用，离开再进入才可用。hit rect 96×27 / close 20×20 |
| B | 底栏「查看详情」只读 overlay | PASS | **PASS** | **PASS** | UNVERIFIED | 长诊断换行；操作按钮高 32 未裁；Esc 收起且焦点回入口；sheet 仍开。footer 始终 50 px，三栏宽度不跳 |

### S

生产 `MultiFileChannelWidget` + 合成通道（方向盘扭矩 / 电机转速 / 电机扭矩 + aux）。筛选前折叠 file-a、展开 file-b 并滚到底；搜「扭矩」后两组都展开；无匹配显示「没有匹配的通道」；「清除筛选」后折叠/滚动回到筛选前。1080：scroll 8→0→8。截图：`.state/four-interaction-refinements/cocoa/S/`。

### P

生产 `BatchSheet` 三只 Light 开关。用户点击滤波：`1080x760-filter_00.png` 旋钮在左，`filter_06.png` 在右；11 帧合成 `P/recordings/*.mp4`。结束后 driver inactive。`lock_editing`：`isEnabled=False`，cursor 13→0（PointingHand→Arrow），锁定轨为浅灰。程序 `setChecked` 后 driver 仍 inactive。

### V

`ChartStack.attach_view_tabbar` 与 `AnalysisSectionPage` 均为 `POLICY_LIGHT`。点击 View 2：中间帧底标仍在 View 1 与 View 2 之间（`V/1080x760-marker_03.png`），静止后 inactive。切换后 `_close_slot_actionable(1)=False`；HoverLeave + 再进入后为 True（`V/1440x900-after.png` 可见 ×）。分析栏 `V/1080x760-analysis.png`。

### B

注入合成 `BatchRunResult`（失败长文 / 跳过 / 完成），不跑 DSP。1080 overlay `y=470,h=240`；1440 `y=610,h=240`（`min(240, 45% work)`）。footer 50 px，input 宽 313/418 在打开/Esc 前后不变。Esc 后 `focusWidget` 为「查看详情」，sheet 仍可见。可见入口：查看输出目录设置、检查信号配对、复制诊断、收起。无重试。

## 指纹（T5 结束时）

| 文件 | sha256 |
| --- | --- |
| `mf4_analyzer/ui/hints.py` | `9e86836a3b744901576eec11c9a2532ca7ccc35823e51ce7c286d10bc932b3b0` |
| `mf4_analyzer/ui/quickref.py` | `6de6af3f2085de4e68b5ee755e578eb6d00c17d4f6f19c54bf244d4b6b01d960` |
| `tests/ui/test_hints.py` | `bece6a136ea88a1455b0e20c89995ebd49f68adf4062692136986a25a6a1b0fb` |
| `tests/ui/test_quickref.py` | `9c80504fd73769e7318714b045cd09d325d335de3bb952e7ed7f317889508e85` |
| `mf4_analyzer/ui/widgets/channel_tree.py` | `7fcdcb015556991cde5a1e1b0591f43211df268665f4bfe401a77ca0f5284d6a` |
| `mf4_analyzer/ui/widgets/pill_switch.py` | `9ca1854bc309b3a919375141c827afd8190e38d75290c26b2942bc1682c931ee` |
| `mf4_analyzer/ui/view_tabbar.py` | `e564bb410b345c013a9c45488c1f115c91bd2b91df010569ec06de6ad682d66e` |
| `mf4_analyzer/ui/drawers/batch/sheet.py` | `ea1616edd6024f88717f14f9af84b8969307cabf5b525c11cfdeba56da1daff5` |
| `mf4_analyzer/ui/drawers/batch/result_details.py` | `68becca98c046a67eca5e176a4c34777071858eb0dd13a8291fd233f573192d6` |

完整任务文件指纹见 `.state/four-interaction-refinements/cocoa/report.json`。Cocoa 运行期间未改产品源。

## 明确未验证

- Windows 100% / 150% 源码运行与冻结包
- DPR 1.0 显示器
- 系统屏幕录制权限下的桌面 avfoundation
- 全量 pytest 与 `tests/acquisition_ui`
- 以完整 MainWindow 打开真实用户文件的走查（本报告为生产控件 + 合成数据）
