# 两波 UI 改动审查及 8.2.5 版本检查

日期：2026-09-16。结论：**needs revision**。确认 5 项问题，其中 1 项 P1、4 项 P2；已同步版本，问题修复留待执行优化计划。

## 发现（按严重程度）

### F1 · P1 · 过渡图像覆盖期间，输入直接作用于另一幅真实图

- 位置：`mf4_analyzer/ui/chart_stack/page_transition.py:47`、`:370`；生产启用点 `mf4_analyzer/ui/main_window/window.py:476`。
- 遮盖层始终设置 `WA_TransparentForMouseEvents=True`，controller 只处理部分宿主几何事件，没有 pending 图面输入保护，也没有 ready 后先撤层、再处理原事件的接线。
- 触发：单 Pane 时域 A→B 后，在仍显示 A 或 A/B 混合图时点击、拖动或取点。实际接收者是已恢复的 B；用户看到的曲线/坐标与命中对象不一致，可能把游标或标注放到错误的视觉位置。该问题不意味着数值算法改算了数据。
- 复现：生产 controller + 真实 QWidget，使用 `QApplication.widgetAt` 命中测试和完整 `QTest.mouseClick`。自然 paint 回执前，目标收到 1 次点击且旧图覆盖层仍可见；回执后点击，动画仍 active。offscreen 与 Cocoa 均复现。
- 建议：在现有呈现 owner 中明确 pending / ready / idle 输入状态；pending 仅限制图面，ready 撤层后让原事件自然处理一次，导航和关闭保持可用。不要建立输入回放队列。

### F2 · P2 · 字体加载失败绕过了随包图标兜底

- 位置：`mf4_analyzer/ui_kit/icons.py:1505`；上游 `mf4_analyzer/ui_kit/stylesheet.py:46`、`mf4_analyzer/app.py:91`。
- `qta.icon(...).pixmap(...)` 不在已知资源异常处理范围内。当前只处理导入失败、空 pixmap、缓存读写失败；qtawesome 实际字体加载失败会抛 `FontError`，字体文件读取失败还可能抛 `OSError`，都不会返回空 pixmap。
- 触发：首次生成缓存时，Qt 无法加载应用字体，例如 Windows 字体限制或字体资源损坏。即使 14 个随包 PNG 全部有效，样式安装仍抛异常；当前应用入口在创建主窗口之前直接调用它。
- 复现：隔离空缓存，仅把 `QFontDatabase.addApplicationFontFromData` 的返回值设为 Qt 的失败值 `-1`，调用真实 qtawesome 渲染路径。输出 `packaged_fallbacks_valid=14`、`error_type=FontError`、`fallback_returned=false`。
- 建议：仅针对已知字体/资源异常选择有效随包图标并节流记录；无效图标名等程序错误仍传播。另行验证其他直接使用 qtawesome 的控件，不能把此 helper 修复等同于整个程序已支持字体完全不可用。

### F3 · P2 · 快速重定向漏掉实时目标，图面会跳变

- 位置：`mf4_analyzer/ui/chart_stack/page_transition.py:88`、`:292`。
- 生产路径 `accept_target(token)` 不保存 B 的 pixmap，B 是下层实时画布。`composite_snapshot()` 却只把覆盖层绘到透明图片，得到带透明度的 A，未包含 B；`begin_departure()` 随后丢弃调用方已经抓到的完整可见端点，改用此残缺合成。
- 触发：A→B 淡化中再次切 C。残留 A 的透明部分立即透出 C，B 的贡献瞬间消失，没有从用户实际看到的 A/B 状态连续交接。
- 像素复现：A 红、B 蓝、进度 0.5，重定向前中心像素为 `#7f0080`；C 绿更新后，尚未开始下一段动画就变为 `#7f8000`。新 source 的 alpha 为 127。offscreen / Cocoa 一致。
- 现有快速切换测试给 `accept_target` 传了第二张图片，覆盖的是双图片路径，不能证明生产的单图片 + 实时背景路径正确。
- 建议：保留正确的完整可见合成，或在无法满足捕获成本时取消到真实终态。必须覆盖不传目标 pixmap 的生产路径，避免每帧抓图。

### F4 · P2 · 带 None 占位行的候选列表每次都被重建

- 位置：`mf4_analyzer/ui_kit/widgets/searchable_combo.py:378`、`:400`；实际调用 `mf4_analyzer/ui/inspector_sections/contextual_frf.py:554`、`contextual_order.py:692`。
- 期望 metadata 总包含 `Qt.UserRole: None`，但 Qt 的 `itemData()` 不保留无效 QVariant 对应的 role。两份语义相同的数据字典因此始终不相等。
- FRF 两个下拉都有“请选择通道 / None”占位行，Order RPM 有“None”行，故这些列表无法走 no-op。切换相同候选 View 时仍 clear/add，破坏预期的模型复用并增加界面工作量。
- 复现：连续两次 `replace_candidate_rows([('None', None), ('signal', ('fid', 'ch'))])`，第二次仍返回 `True`；offscreen / Cocoa 一致。
- 建议：按 Qt 实际角色存储语义规范化比较，保留完整顺序、身份与有效展示角色检查。不要通过忽略所有附加 role 来掩盖差异。

### F5 · P2 · 新增 lambda 信号连接使必需边界门失败

- 位置：`mf4_analyzer/ui/chart_stack/stack.py:121`。
- 新的取消信号连接用 lambda 捕获 `self`，该文件计数由 12 增到 13。`test_no_lambda_signal_connections.py` 两项失败，总量由允许的 111 增到 112。
- 当前可以确认的是边界检查失败和新增生命周期闭包，**没有复现由它导致的崩溃**。
- 建议：连接已接受 `*_args` 的 `_clear_page_transition_ready_fence` 绑定方法；不扩大白名单。

## 审查范围与快照

- 第一波：`db29cdf92752c6b27fbfd4f2de7fc61ec81fd8c6`，Windows 通道树绘制、图标兜底与打包资源。
- 第二波：`b0b3fcf76271d380cab42c93ac3f2bbc2e277410`，通道树/候选/facts 更新、页面过渡、paint 回执及 UltraView 捕获协调。开始时尚未提交，用户确认范围后它已提交，本报告按该固定提交审查。
- 相邻修复：`f28f5820`，刻度显示精度；包含源码检查和相关刻度测试。
- 阅读了两份 2026-09-15 计划及流畅性调查，历史测量仅用于理解范围。最终 HEAD 保持 `b0b3fcf7`，本轮产品修改仅为版本同步；上述 5 个问题未修改。
- 未触碰原有未跟踪 Windows 计划、流畅性调查及 `ssh-keygen`。

## 验证与证据

| 证据类别 | 本次结果 | 边界 |
| --- | --- | --- |
| owner 聚焦测试 | **1126 passed, 1 deselected**，退出 0，165.91 秒 | 通道树/筛选/颜色、View 投影/分屏、候选/分析恢复、FRF、过渡、UltraView、时域/频谱画布、图标和 QSS；日志 `.state/review-825/focused.log` |
| 版本、刻度与边界测试 | **323 passed, 2 skipped, 2 failed**，退出 1，34.93 秒 | 失败仅 F5；版本/帮助、Windows 脚本、打包导入、项目版本、状态归属/backref、依赖边界、刻度与 QSS 检查包含在此组；日志 `.state/review-825/boundary-release.log` |
| 输入/合成/候选探针 | F1/F3/F4 在 offscreen 和 Cocoa 均复现，退出 0 | `.state/review-825/probe.py` 与 `probe-{offscreen,cocoa}.json`；独立真实控件探针，非客户文件或完整前台应用验收 |
| 字体故障注入 | F2 复现，probe 正常退出 0 | `.state/review-825/font_probe.py`、`font-probe.json`；Qt 字体注册失败的受控注入，未修改本机字体 |
| 通道树生产控件渲染 | Cocoa、DPR 2，40 状态，`public_contract_failures=0`，退出 0 | 生产 QSS 与真实控件抓图；`.state/windows-ui-visual-consistency/review-825-cocoa/evidence.json`；不代表 Windows |
| 版本/文档卫生 | `git diff --check` 通过 | 历史 8.2.4 更新记录保留 |

owner 组启动时版本还是 8.2.4；期间只修改版本/文档/版本断言，受审 UI 源码保持不变。第二组在 8.2.5 同步完成后启动。没有把并发期间的结果当作全套稳定快照验收。

可重放的测试文件清单和命令存 `.state/review-825/commands.md`。warnings 主要是 pyqtgraph 对 NumPy shape 赋值的弃用提示；没有据此认定新的产品故障。本轮没有运行全量 suite，因为 owner 与边界范围已覆盖此次改动，且已存在明确待修项。

## 未完成的验收与风险

- Windows 源码、Full/Lite frozen、125%/150% 缩放及跨屏未验收；本机 Cocoa 结果不能替代。第一波计划中的依赖约束基线也没有因此完成。
- 完整 TraceLab 前台、客户大文件、百万点滤波与全屏高 DPI 的交互性能/峰值内存没有重新测量。启动代码无平台/负载准入判断就启用单图时域动效，历史的小数据 Cocoa 结果不足以覆盖这些场景。
- controller 对分区切换、来源/目标被替换、窗口失活和 DPR 改变的取消接线不完整。探针确认切到 FFT 后仍保留 time 目标，失活事件也没有释放图像；尚未完成这些路径的用户可见故障矩阵，作为 T1 必补边界，不重复计作一个已确认图像错误。
- 未发现本次改动直接改变 DSP 算法或持久化 schema；这不构成全产品无 bug 的证明。

## 交付

- [优化计划](../plans/2026-09-16-two-wave-review-optimization-plan.md)：按 F1–F5 给出 owner、回归门与完成标准。
- 8.2.5 已同步应用版本、README/current baseline、主帮助及各带版本指南、用户指南、Windows Full/Lite 构建/启动脚本与版本断言；主帮助和 README 已补具体更新内容，历史记录未改写。
- 没有执行上述问题的产品修复，也没有 commit、push 或构建/发布安装包。
