# 8.4.8 MF4 导入与对话框回归 Review

日期：2026-11-17。结论：**needs revision**。本轮为源码审查、只读探针与后续设计，不实施产品修复。实施后的结果见 [执行报告](2026-11-17-import-budget-and-dialog-recovery-report.md)；本文结论不改写。

基线 `c126fcae24b73961eb798b989df1068a94327197`，`APP_VERSION=v8.4.8`。用户确认截图版本为 8.4.8；Windows Full/Lite、Qt/字体、缩放和包 hash 未知。起始工作区只有未跟踪的 `CSER TTR/`，保留不动。以下源码行号对应此基线。

配套：[Spec](../specs/2026-11-17-import-budget-and-dialog-recovery-spec.md) · [Plan](../plans/2026-11-17-import-budget-and-dialog-recovery-plan.md)。范围沿三个截图的实际 owner、共用 helper 与同类导入入口展开；不是全仓库审计或全部窗口视觉验收。

## 1. 按严重度排序的发现

### F1 · P1：支持的 MF4 在当前资源政策下被拒绝，错误框没有恢复闭环

位置：`mf4_analyzer/io/mdf_reader.py:169–184` 的 `_reserve_shared_output`；`io/import_limits.py:88–105`；`ui/main_window/_project_io_mixin.py:705–717`。

图1是**读取前资源拒绝**，不是导入成功后的提示。当前 admission 将记录缓存、目录、公共轴表与副本累计计费；默认内存预算为估计可用物理内存的四分之一、最多 2 GiB，无法探测时 512 MiB。只有超时有明确重试操作，resource_limit 直接弹 `QMessageBox.critical(..., str(exc))`，用户只能确认退出，没有可重查资源的恢复动作。

本轮用仍在本机的此前事故样本 `1-5.W04_180_10s_rt_11210854.mf4`，SHA256 `72d81a087e9816c7dca80633b20f5a899c0a484a6a80465b99a6d2f3c56cf5b3`，调用当前 `open_mdf` 的正式预检，得到与图1**逐字相同**的错误：

| 计费项 | 字节 |
| --- | ---: |
| 记录/解压临时预算 | 36,601,314 |
| 通道目录/数组展开 | 2,197,504 |
| 公共时间表 float64 × 3 | 599,941,344 |
| 累计请求 | **638,740,162（609.15 MiB）** |
| 注入截图相同上限 | **498,988,944（475.87 MiB）** |

这确认了可复现机制，并高度支持同一类负载归因；不能仅凭相同数字证明图1文件 hash。图2文件名是另一个 `2.W04_360_1s_rt_11201724.mf4`，本轮未取得并解析该文件，不能把旧样本成功当作它通过。

`599,941,344 = 471,652 × 53 × 8 × 3`；其来源是当前公共轴数据模型。请求数是累计估算，不是当前 RSS，也不是还需释放的字节数。默认策略下，该估算需要约 2.38 GiB 可用物理内存才通过四分之一门槛；这是公式推导，不是用户机器总内存诊断。禁止把“放开阈值”或“删掉 copies=3”作为未经测量的修复。

已有[原生采样 Spec](../specs/2026-11-17-mf4-native-sampling-spec.md)仍未实施。其历史 buffer 普查为公共表约 190.7 MiB、原生 raw/physical/time 约 23.9 MiB；这些不是进程峰值。之前[导入验收](../verify/2026-11-17-import-robustness-implementation.md)的成功是在另一资源条件下，且 Windows frozen 为 UNKNOWN，不能推翻本次现场失败。

### F2 · P2：工具窗保护被扩大到所有有标题窗口，拒绝短提示框的正确尺寸

位置：`mf4_analyzer/ui_kit/dialog_geometry.py:785–792, 872–876`；调用者 `ui_kit/message_dialog.py:680–705`。影响未保存项目等通过 `AppMessageDialog` 创建的短提示。

`decorated_plan_is_degenerate()` 对任意有标题顶层窗口使用宽或高小于 200 的拦截。未保存框按内容算出的 380×134 布局因此被丢弃，保留 QScrollArea 驱动的自然高度，正文顶部与底部按钮之间形成空白。`_shrink_unaccounted_frame:714–721` 还有第二处同样的无差别 floor；只改首次拦截并不完整。

本轮使用生产 `build_unsaved_project_dialog`、生产 QSS、Fusion、Qt offscreen，实际 show 后测量并看图：

| 场景 | 窗口客户区 | 正文 scroll | 按钮行 y |
| --- | --- | --- | ---: |
| 当前源码 | 346×307 | 234×221 | 255 |
| 同一诊断进程，仅临时绕过拒绝条件 | 380×134 | 268×48 | 82 |

两次原计划均为 380×134。诊断的 monkeypatch 未写入产品，后者只证明因果，不是最终修复方案，也没有验证所有原生框架补偿。截图已查看，第一张重现同类大空白，第二张恢复紧凑。Windows 精确客户区尺寸仍需实机测量；无需将本机截图冒充 Windows 复现。

### F3 · P2：新导入进度框没有同步进度/阶段，平台轨道几何未经验收

位置：`mf4_analyzer/ui/main_window/_project_io_mixin.py:593–624`；`io/import_process.py:385–387`。

导入窗口用 `QProgressDialog(..., 0, 0, self)`，整个生命周期没有更新其 range/value；`report()` 只更新底部 compute progress。图2绿色块是 busy 动画，不是“已完成到这里”的百分比。已知阶段/进度不能在弹窗中反映，用户容易把“加载 1/1”（当前文件序号）理解成完成。

截图另显示轨道右端和按钮/内容右端不齐；这是独立的布局验收问题，不能用 busy 模式解释掉。当前实现依赖 QProgressDialog 平台布局，没有自有网格或范围内的进度条样式。本机 offscreen 测得客户区 256×108，bar `[11,34,234,25]`、取消按钮 `[175,65,70,32]`，二者右端相齐，**未复现 Windows 的轨道短缺**。Windows 精确诱因（style、DPI、包内版本）为 UNKNOWN，不能指认某条 QSS padding。

即使将 broker 的 1.0 直接写入弹窗也不完整：它只表示读取/交接完成，后续 GUI 注册、View attach、项目恢复仍可能失败。应明确“当前阶段”和“整个导入成功”的不同终点。

### F4 · P2：测试覆盖允许上述回归通过，平台未验收仍留下交付缺口

位置：`tests/ui_kit/test_message_dialog.py:110–127` 只核对按钮语义/同高；`tests/ui_kit/test_dialog_geometry.py:601–616` 把所有短有标题 QDialog 的拒绝写成预期，没有内容型提示框反例。

本轮原样运行两个 owner 文件：**75 passed in 0.74s**。这与实际空白同时成立，证明需要补跨 owner 的内容高度合同，而不是重复运行全套。历史跨平台提示框 spec 的 G3/G4/G5 未闭环，导入鲁棒性验收也明确 Windows 未验证。现有证据不能宣称 8.4.8 所有窗口正常。

### F5 · P2：资源错误被扁平化，无法可靠区分内存、磁盘与通道数的建议

位置：`mf4_analyzer/io/import_worker.py:188–200`、`io/import_process.py:363–371`、`io/import_limits.py:125–131`。

内存预估、传输超限、MemoryError、ENOSPC/EDQUOT 都可成为 resource_limit；worker 仅传字符串，不保留结构化 requested/limit/resource kind。`check_channels()` 又复用字节字段承载数量。若只在 UI 对所有 resource_limit 建议“释放内存”或用正则抓数字，就会误导磁盘/通道上限失败。后续可行动文案需要在现有异常与协议 owner 内保留资源类型和单位，而不是解析中文错误字符串。

## 2. UI 是什么时候变化的

以下为 Git 中可追溯的提交时间，统一北京时间；不是用户安装时间，也不是未经确认的首次发行版本。

| 时间 | 提交 | 可确认变化 |
| --- | --- | --- |
| 2026-06-28 14:27 | `0f5cfbff` | QMessageBox 按钮语义颜色；橙/红按钮不是今天才出现 |
| 2026-09-05 09:45 | `6b3105a5` | 引入 AppMessageDialog 与共享屏幕几何；未保存项目开始使用新布局 |
| **2026-11-13 13:25** | **`f4bd9eb5`** | 为工具窗增加防退化保护，但全局拒绝有标题窗口任一维小于 200；图3空白的可复现回归点 |
| **2026-11-17 14:05** | **`161e5387`** | 引入导入资源预检与异步 QProgressDialog；图1拦截、图2新进度窗口路径来自这一批 |
| 2026-11-17 17:49 | `77ceade6` | 版本面同步到 8.4.8 |

随后 `febfc01d`、`c64caaba` 修 Windows 构建；当前 `c126fcae` 补记其他本地修复，均不是以上两个 UI 行为的最初引入点。`git log -S` 已核对进度框和未保存项目的入口历史。

## 3. 相邻路径与系统性边界

| 路径 | 当前 owner | 处置 |
| --- | --- | --- |
| 普通打开/拖入/最近文件 | `_start_import_paths` | 同一进度/错误修复必须覆盖这三个入口 |
| 项目恢复 | `_project_io_mixin.py:2967` | 同类 busy QProgressDialog；成功必须晚于恢复事务 |
| Batch DBC 预读 | `_project_io_mixin.py:1655` | 同类 busy 框；保留 sheet 自己的 coordinator/关闭回收 |
| Replay | `acquisition_ui/replay_tab.py:203` | 同类 busy 框；仅 Full，不能让 Lite 导入 acquisition UI |
| 超时选择 | `import_coordinator.py:283` | 已有“延长并重试”；不要与资源预算重试混淆 |
| 几何 helper 调用者 | 消息框、Batch/UltraView、表单、帮助与弹层 | 按内容型/工作窗/无边框分类；不能一刀切取消工具窗保护 |
| MDF API/Batch/Replay | `source_adapters.py:864` 仍为 `load_mf4` | 仍是公共轴路径；完整低内存根治依赖原生采样迁移，而不是仅更换弹窗 |

未发现证据支持全局字体变化或所有界面一起改版。没有将其他表单/弹层全部判为有 bug，也不启动历史计划中全量 QMessageBox 迁移。

## 4. 本轮证据与剩余项

本地证据目录 `.state/import-dialog-review-20261117/`：`geometry_probe.py`、`geometry.json`、`geometry.log`、当前/对照/进度 PNG；`budget_probe.py`、`budget.json`；`owner-tests.log`。所有图使用真实生产组件，但证据等级为 **offscreen**。预算探针只走元数据预检，不为复现错误实际分配 609 MiB。

仍待：Windows 8.4.8 包身份/缩放/真实 track geometry、图2原文件的独立验证、候选修复后的 Cocoa 与新鲜 Full/Lite。当前没有产品修复、没有发布，也没有全套通过结论。
